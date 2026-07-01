"""日志查询 MCP Server(Mock 版,对标腾讯云 CLS 思路)

把"翻日志"封装成独立 HTTP 服务,通过 MCP 暴露给运维 Agent。两层结构:
  1) search_topic_by_service_name: 服务名 → 找到日志主题(topic)
  2) search_log: 拿着 topic_id 进去搜具体日志
这正是真人排障的动作:先定位"哪个日志库",再进去搜关键词。

埋点:mock 日志故意全是 INFO、没有 ERROR —— 让"查日志查不出异常"成为
逼 Agent 重新规划(Replan)的触发器,是 Plan-Execute-Replan 的演示素材。

独立进程运行: python mcp_servers/cls_server.py  (默认 127.0.0.1:8103)
"""

import functools
import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from fastmcp import FastMCP

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("CLS_MCP_Server")

mcp = FastMCP("CLS")

# 每条 mock 日志之间间隔 1 分钟(毫秒),单一事实来源
LOG_STEP_MS = 60 * 1000


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


# Mock 主题表:服务名 → 日志主题。单一数据源,search_topic 和 search_log 共用语义。
_MOCK_TOPICS = [
    {"topic_id": "topic-001", "topic_name": "数据同步服务日志",
     "service_name": "data-sync-service", "description": "应用运行日志"},
    {"topic_id": "topic-002", "topic_name": "数据同步服务错误日志",
     "service_name": "data-sync-service", "description": "错误日志"},
    {"topic_id": "topic-003", "topic_name": "API网关服务日志",
     "service_name": "api-gateway-service", "description": "网关访问日志"},
]


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
    """根据服务名查找对应的日志主题(topic),支持模糊匹配。排障链路第一层。

    Args:
        service_name: 服务名,如 "data-sync-service",或片段 "sync"(必填)
        fuzzy: True=部分匹配("sync" 命中 "data-sync-service");False=精确匹配(默认 True)

    Returns:
        含 total(命中数)、topics(每个含 topic_id/topic_name/service_name/description)、query。
        拿到 topics[0]["topic_id"] 后,喂给 search_log 查具体日志。
    """
    matched = []
    for topic in _MOCK_TOPICS:
        name = topic["service_name"].lower()
        target = service_name.lower()
        hit = (target in name or name in target) if fuzzy else (name == target)
        if hit:
            matched.append(topic)
    return {"total": len(matched), "topics": matched,
            "query": {"service_name": service_name, "fuzzy": fuzzy},
            "message": f"找到 {len(matched)} 个日志主题" if matched else f"未找到服务 '{service_name}' 的日志主题"}


@mcp.tool()
@log_tool_call
def search_log(topic_id: str, start_time: int, end_time: int,
               query: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
    """在指定日志主题里搜索一段时间内的日志。排障链路第二层。

    Args:
        topic_id: 主题ID,如 "topic-001"(必填,来自 search_topic_by_service_name)
        start_time: 开始时间戳(毫秒,int)。如 get_current_timestamp() - 15*60*1000
        end_time: 结束时间戳(毫秒,int)。通常用 get_current_timestamp()
        query: 查询语句,如 "level:ERROR"(可选)
        limit: 返回条数上限(默认 100)

    Returns:
        含 topic_id、total(实际条数)、logs(每条含 timestamp/level/message)、took_ms。
        注意:mock 日志全是 INFO,查不到 ERROR —— 这会让 Agent 判断"日志无异常",从而转向查别的。
    """
    # topic-001 才有日志;其它 topic_id 一律当作不存在,返回空+错误信息
    if topic_id != "topic-001":
        return {"topic_id": topic_id, "total": 0, "logs": [], "took_ms": 0,
                "error": f"主题不存在: {topic_id}",
                "message": f"错误: 未找到主题 {topic_id},请检查 topic_id"}

    logs = []
    current = start_time
    while current <= end_time and len(logs) < limit:
        time_str = datetime.fromtimestamp(current / 1000).strftime("%Y-%m-%d %H:%M:%S")

        logs.append({"timestamp": time_str, "level": "INFO", "message": "正在同步元数据……"})
        current += LOG_STEP_MS

    return {"topic_id": topic_id, "start_time": start_time, "end_time": end_time,
            "query": query, "limit": limit, "total": len(logs), "logs": logs,
            "took_ms": 50, "message": f"成功查询 {len(logs)} 条日志"}


if __name__ == "__main__":
    # streamable-http 模式: Agent 通过 http://127.0.0.1:8103/mcp 连接调用
    # 端口 8103 避开 Windows 保留段 7911-8010(否则 winerror 10013)
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8103, path="/mcp")
