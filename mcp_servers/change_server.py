"""变更/发布事件 MCP Server —— 真实 Elasticsearch 后端(独立证据源)

把"查变更"封装成独立 HTTP 服务,通过 MCP 暴露给运维 Agent。价值在于**时间对齐**:
指标/日志说"现在异常",变更说"刚发过版" —— 两条正交证据一撞,才能把根因从
"资源耗尽"这类症状层,推进到"某次变更引入"的触发层(矛盾触发/再规划的关键输入)。

数据来自真实 Elasticsearch(CHANGE_ES_URL 留空则回退 CLS_ES_URL,同集群不同索引)。
本服务不设 mock 分支: 后端不可达时一律如实返回"数据不可用"声明,绝不编造变更记录
(与日志侧同纪律: 变更是指标/日志之外的独立证据,造假同样会污染根因结论)。

两个工具(对齐"先定位、再下钻"的排障动作):
  1) search_changes:       服务名 + 时间窗 → 该服务窗口内的变更列表
  2) get_change_detail:    change_id → 单条变更的完整详情

独立进程运行: python mcp_servers/change_server.py  (默认 127.0.0.1:8106)
"""

import functools
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastmcp import FastMCP

# 确保独立进程直接运行时能 import 同目录下的 mcp_servers 包
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from mcp_servers.change_client import ChangeClient, use_es_backend
from src.settings import settings

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("Change_MCP_Server")

mcp = FastMCP("Change")

# Elasticsearch 客户端单例(真实变更事件后端)
_change_client: "ChangeClient | None" = None


def _get_change_client() -> ChangeClient:
    global _change_client
    if _change_client is None:
        _change_client = ChangeClient()
    return _change_client


def _unavailable(reason: str, **base: Any) -> Dict[str, Any]:
    """真实变更数据不可用时返回的"如实声明":无变更记录、明确标注不可用。"""
    note = (f"[数据来源: 真实变更数据不可用 —— {reason}; 本次未取得真实变更记录, "
            f"不得据此推断'无变更'或'变更是根因']")
    return {**base, "total": 0, "changes": [],
            "data_source": "unavailable", "data_source_note": note,
            "message": f"真实变更数据不可用({reason})"}


def log_tool_call(func):
    """装饰器:统一打印工具被调用时的方法名/参数/成败(与 monitor/cls 同款)。"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        logger.info("=" * 60)
        logger.info("调用工具: %s", func.__name__)
        logger.info("参数: %s", json.dumps(kwargs, ensure_ascii=False) if kwargs else "无")
        try:
            result = func(*args, **kwargs)
            logger.info("返回: SUCCESS")
            return result
        except Exception as e:
            logger.error("返回: ERROR - %s", e)
            raise
    return wrapper


def _summarize_types(changes: list) -> str:
    """按变更类型统计条数,给裁判一个可读的变更概览。"""
    counts: Dict[str, int] = {}
    for c in changes:
        t = str(c.get("change_type") or "unknown")
        counts[t] = counts.get(t, 0) + 1
    return ", ".join(f"{k} x{v}" for k, v in counts.items())


@mcp.tool()
@log_tool_call
def search_changes(service_name: str, start_time: int = 0, end_time: int = 0,
                   change_type: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
    """查询某服务在指定时间窗内的变更/发布事件(发布、配置、扩缩容、回滚等),按时间倒序。

    排障用途: 把"故障发生时间"与"变更发生时间"对齐 —— 若窗口内存在变更,
    说明故障很可能由该变更引入(变更相关性的核心证据)。

    Args:
        service_name: 服务名,如 "order-service" 或口头名 "订单服务"(必填,经别名表归一化)
        start_time: 开始时间戳(毫秒,int)。传 0 或不传则默认"最近 1 小时"
        end_time: 结束时间戳(毫秒,int)。传 0 或不传则默认"当前时间"
        change_type: 变更类型过滤,如 "deploy"/"config"/"scale"/"rollback"(可选)
        limit: 返回条数上限(默认 50)

    Returns:
        含 service_name、total(命中数)、changes(每条含 change_id/timestamp/service/
        change_type/operator/version/description/status)、summary(类型概览)、
        data_source("elasticsearch"真实 / "unavailable"不可用)。
    """
    now_ms = int(datetime.now().timestamp() * 1000)
    end = end_time if end_time and end_time > 0 else now_ms
    start = start_time if start_time and start_time > 0 else end - 3600 * 1000
    base = {"service_name": service_name, "start_time": start, "end_time": end,
            "change_type": change_type, "limit": limit}

    if not use_es_backend():
        return _unavailable("CHANGE_ES_URL / CLS_ES_URL 未配置", **base)

    client = _get_change_client()
    if not client.available:
        logger.warning("ES 不可达(%s)", settings.RESOLVED_CHANGE_ES_URL)
        return _unavailable(f"Elasticsearch({settings.RESOLVED_CHANGE_ES_URL}) 不可达", **base)

    result = client.search_changes(service_name, start, end, change_type, limit)
    if result.get("data_source") == "elasticsearch":
        changes = result.get("changes", [])
        if changes:
            result["summary"] = _summarize_types(changes)
            result["message"] = (f"查到 {len(changes)} 条变更记录(变更事件); "
                                 f"类型概览: {result['summary']}")
        else:
            result["message"] = ("窗口内无变更记录(变更事件): 该服务在指定时间窗内"
                                 "未发生发布/配置/扩缩容等变更")
    return result


@mcp.tool()
@log_tool_call
def get_change_detail(change_id: str) -> Dict[str, Any]:
    """按 change_id 获取单条变更的完整详情(用于确认变更内容与影响范围)。

    Args:
        change_id: 变更唯一标识(来自 search_changes 返回的 change_id)

    Returns:
        含 found(是否找到)、change(变更详情)、data_source 标记。
    """
    if not use_es_backend():
        return {"change_id": change_id, "found": False, "change": None,
                "data_source": "unavailable",
                "data_source_note": "[数据来源: 真实变更数据不可用 —— ES 未配置]",
                "message": "真实变更数据不可用"}

    client = _get_change_client()
    if not client.available:
        return {"change_id": change_id, "found": False, "change": None,
                "data_source": "unavailable",
                "data_source_note": (f"[数据来源: 真实变更数据不可用 —— Elasticsearch"
                                     f"({settings.RESOLVED_CHANGE_ES_URL}) 不可达]"),
                "message": "真实变更数据不可用"}
    return client.get_change_detail(change_id)


if __name__ == "__main__":
    # streamable-http 模式: Agent 通过 http://<host>:8106/mcp 连接调用
    # 端口 8106 避开 Windows 保留段 7911-8010(否则 winerror 10013)
    # MCP_HOST 环境变量: 容器内生产部署设 0.0.0.0,本机默认 127.0.0.1 不变
    mcp.run(transport="streamable-http",
            host=os.environ.get("MCP_HOST", "127.0.0.1"), port=8106, path="/mcp")