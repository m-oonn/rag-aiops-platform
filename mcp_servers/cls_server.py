"""日志查询 MCP Server —— 真实 Elasticsearch 后端(已移除运行时 Mock)

把"翻日志"封装成独立 HTTP 服务,通过 MCP 暴露给运维 Agent。两层结构:
  1) search_topic_by_service_name: 服务名 → 找到日志主题(topic,即 ES 索引)
  2) search_log: 拿着 topic_id 进去搜具体日志
这正是真人排障的动作:先定位"哪个日志库",再进去搜关键词。

数据来自真实 Elasticsearch(CLS_BACKEND=elasticsearch + CLS_ES_URL)。本服务已移除
运行时 Mock 回退: 未启用真实后端或后端不可达时, 一律如实返回"数据不可用"声明,
绝不返回编造日志。日志是根因鉴别的**主证据**, 造假会直接污染结论 —— 实测中 Mock 日志
的 OOM 堆栈曾让 Agent 编出自信但错误的根因"内存溢出"。

独立进程运行: python mcp_servers/cls_server.py  (默认 127.0.0.1:8103)
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

from mcp_servers.cls_client import ClsClient, use_es_backend
from src.settings import settings

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("CLS_MCP_Server")

mcp = FastMCP("CLS")

# Elasticsearch 客户端单例(真实日志后端)
_cls_client: "ClsClient | None" = None


def _get_cls_client() -> ClsClient:
    global _cls_client
    if _cls_client is None:
        _cls_client = ClsClient()
    return _cls_client


# ── 数据来源标记(2026-10-10): 与 monitor_server 同一纪律 ─────────────────
# 背景: 实测中 Agent 把 Mock 演示日志(order-service 的 OutOfMemoryError 堆栈)
# 当成真实证据, 编出了一个自信但错误的根因"内存溢出"。日志是根因鉴别的**主证据**,
# 比指标更必须标明来源: 每个日志返回都带 data_source;运行时 Mock 回退已彻底移除,
# 日志只可能来自 Elasticsearch 或"不可用"。


def _unavailable_logs(topic_id: str, start_time: Any, end_time: Any,
                      query: Any, limit: int, reason: str) -> Dict[str, Any]:
    """真实日志不可用时返回的"如实声明":无日志、明确标注不可用。"""
    note = (f"[数据来源: 真实日志不可用 —— {reason}; 本次未取得真实日志, "
            f"不得据此推断根因, 尤其不得编造异常堆栈或错误信息]")
    return {"topic_id": topic_id, "start_time": start_time, "end_time": end_time,
            "query": query, "limit": limit, "total": 0, "logs": [],
            "data_source": "unavailable", "data_source_note": note,
            "took_ms": 0, "message": f"真实日志不可用({reason})"}


def _real_logs(topic_id: str, start_time: Any, end_time: Any,
               query: Any, limit: int) -> Dict[str, Any]:
    """真实日志后端(ES)取数 —— 真实链路唯一路径。

    已移除运行时 Mock 回退: 未启用真实后端或后端不可达时, 一律返回"不可用"声明,
    绝不返回编造日志。
    """
    if settings.CLS_BACKEND.strip().lower() != "elasticsearch":
        return _unavailable_logs(topic_id, start_time, end_time, query, limit,
                                 "CLS_BACKEND 未设为 elasticsearch")
    if not use_es_backend():
        return _unavailable_logs(topic_id, start_time, end_time, query, limit,
                                 "CLS_ES_URL 未配置")
    client = _get_cls_client()
    if not client.available:
        logger.warning("ES 不可达(%s)", settings.CLS_ES_URL)
        return _unavailable_logs(topic_id, start_time, end_time, query, limit,
                                 f"Elasticsearch({settings.CLS_ES_URL}) 不可达")
    return client.search_logs(topic_id, start_time or 0,
                              end_time or int(datetime.now().timestamp() * 1000),
                              query, limit)


def log_tool_call(func):
    """装饰器:统一打印工具被调用时的方法名/参数/成败(与 monitor_server 同款)。"""
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


# 本地日志缓存目录:模拟真实系统"日志有本地磁盘副本",供 executor 在 cls 服务不可达时
# 降级读取(MCP 优先 + 本地兜底,消除日志查询的单点依赖)。只缓存**真实**日志查询结果,
# 不含任何 Mock 数据。
LOG_CACHE_DIR = os.path.join("runtime", "log_cache")


def _cache_logs(topic_id: str, logs: list) -> None:
    """把一次成功的真实 search_log 结果落盘,供服务不可达时本地兜底读取。"""
    try:
        os.makedirs(LOG_CACHE_DIR, exist_ok=True)
        with open(os.path.join(LOG_CACHE_DIR, f"{topic_id}.json"), "w", encoding="utf-8") as f:
            json.dump({"topic_id": topic_id, "logs": logs}, f, ensure_ascii=False)
    except Exception:
        pass


@mcp.tool()
@log_tool_call
def get_current_timestamp() -> int:
    """获取当前时间戳(毫秒)。

    Agent 排障第一步常用它来锚定时间窗:拿到"现在",再减去 N 分钟得到查询起点。

    Returns:
        int: 当前毫秒时间戳,例如 1708012345000。
        用法: 最近15分钟 = [get_current_timestamp() - 15*60*1000, get_current_timestamp()]
    """
    return int(datetime.now().timestamp() * 1000)


@mcp.tool()
@log_tool_call
def search_topic_by_service_name(service_name: str, fuzzy: bool = True) -> Dict[str, Any]:
    """根据服务名查找对应的日志主题(topic,即 ES 索引),支持模糊匹配。排障链路第一层。

    Args:
        service_name: 服务名,如 "data-sync-service",或片段 "sync"(必填)
        fuzzy: True=部分匹配("sync" 命中 "data-sync-service");False=精确匹配(默认 True)

    Returns:
        含 total(命中数)、topics(每个含 topic_id/topic_name/service_name/description)、query。
        拿到 topics[0]["topic_id"] 后,喂给 search_log 查具体日志。
    """
    if not use_es_backend():
        return {"total": 0, "topics": [],
                "query": {"service_name": service_name, "fuzzy": fuzzy},
                "data_source": "unavailable",
                "data_source_note": ("[数据来源: 真实日志平台未启用 —— CLS_BACKEND/CLS_ES_URL "
                                     "未正确配置; 未取得真实日志主题]"),
                "message": "真实日志平台未启用, 无法查询日志主题"}
    client = _get_cls_client()
    if not client.available:
        logger.warning("ES 不可达(%s)", settings.CLS_ES_URL)
        return {"total": 0, "topics": [],
                "query": {"service_name": service_name, "fuzzy": fuzzy},
                "data_source": "unavailable",
                "data_source_note": (f"[数据来源: 真实日志平台不可用 —— Elasticsearch"
                                     f"({settings.CLS_ES_URL}) 不可达; 未取得真实日志主题]"),
                "message": f"真实日志平台不可用, 未找到服务 '{service_name}' 的日志主题"}
    return client.search_topics(service_name, fuzzy)


@mcp.tool()
@log_tool_call
def search_log(topic_id: str, start_time: int, end_time: int,
               query: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
    """在指定日志主题(ES 索引)里搜索一段时间内的日志。排障链路第二层。

    Args:
        topic_id: 主题ID(即 ES 索引名),如 "data-sync-service-logs-2026.10.10"
            (必填,来自 search_topic_by_service_name)
        start_time: 开始时间戳(毫秒,int)。如 get_current_timestamp() - 15*60*1000
        end_time: 结束时间戳(毫秒,int)。通常用 get_current_timestamp()
        query: 查询语句,如 "level:ERROR"(可选)
        limit: 返回条数上限(默认 100)

    Returns:
        含 topic_id、total(实际条数)、logs(每条含 timestamp/level/message)、took_ms、
        data_source("elasticsearch"真实 / "unavailable"不可用)。
    """
    result = _real_logs(topic_id, start_time, end_time, query, limit)
    # 只缓存真实日志查询结果,供 cls 服务不可达时本地兜底(不含 Mock 数据)
    if result.get("data_source") == "elasticsearch" and result.get("logs"):
        _cache_logs(topic_id, result["logs"])
    return result


if __name__ == "__main__":
    # streamable-http 模式: Agent 通过 http://<host>:8103/mcp 连接调用
    # 端口 8103 避开 Windows 保留段 7911-8010(否则 winerror 10013)
    # MCP_HOST 环境变量: 容器内生产部署设 0.0.0.0,本机默认 127.0.0.1 不变
    mcp.run(transport="streamable-http",
            host=os.environ.get("MCP_HOST", "127.0.0.1"), port=8103, path="/mcp")