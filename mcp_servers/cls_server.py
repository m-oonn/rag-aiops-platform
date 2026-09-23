"""日志查询 MCP Server(Mock 版,多剧本,对标腾讯云 CLS 思路)

把"翻日志"封装成独立 HTTP 服务,通过 MCP 暴露给运维 Agent。两层结构:
  1) search_topic_by_service_name: 服务名 → 找到日志主题(topic)
  2) search_log: 拿着 topic_id 进去搜具体日志
这正是真人排障的动作:先定位"哪个日志库",再进去搜关键词。

日志内容按服务所属场景(见 mock_scenario.py)返回:
  - data-sync-service: 全 INFO 日志 —— "指标异常 + 日志查不出异常"是逼 Agent 重新规划
    (Replan)的触发器;
  - api-gateway/auth/order/payment: 对应网络/配置/应用/依赖根因的 ERROR 特征日志。
  - topic-003 保留混沌注入演示剧本(论文侧 e2e 特性:注入→超时→次生熔断→停止注入恢复);
  - topic-blind 为盲测动态主题,实时读取 run_blind_eval 写入的场景(不重启即切换)。

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

from mcp_servers.mock_scenario import log_lines, scenario_for_service
from mcp_servers.cls_client import ClsClient, use_es_backend
from src.settings import settings

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("CLS_MCP_Server")

mcp = FastMCP("CLS")

# Elasticsearch 客户端单例(生产化后端,Mock→真实双轨,见 docs/MCP生产化改造方案.md)
_cls_client: "ClsClient | None" = None


def _get_cls_client() -> ClsClient:
    global _cls_client
    if _cls_client is None:
        _cls_client = ClsClient()
    return _cls_client

# 盲测动态主题:由 run_blind_eval 写入 runtime/blind_scenario.json,本服务查询时实时读盘。
# 这样每个场景无需重启 MCP 即可切换(规避"cls 改动需重启 MCP 才生效"的问题)。
BLIND_TOPIC_ID = "topic-blind"
BLIND_SCENARIO_PATH = os.path.join("runtime", "blind_scenario.json")


def _load_blind_scenario() -> Optional[Dict[str, Any]]:
    """实时读取当前盲测场景(生成本服务服务 blind-svc 的日志)。"""
    try:
        with open(BLIND_SCENARIO_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


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
# 各服务对应 mock_scenario 的不同剧本(网络/配置/应用/依赖),供 demo 复现多根因。
_MOCK_TOPICS = [
    {"topic_id": "topic-001", "topic_name": "数据同步服务日志",
     "service_name": "data-sync-service", "description": "应用运行日志(指标剧本:全 INFO)"},
    {"topic_id": "topic-002", "topic_name": "数据同步服务错误日志",
     "service_name": "data-sync-service", "description": "错误日志"},
    {"topic_id": "topic-003", "topic_name": "API网关服务日志",
     "service_name": "api-gateway-service", "description": "网关访问/连接日志(网络剧本)"},
    {"topic_id": "topic-004", "topic_name": "认证服务配置日志",
     "service_name": "auth-service", "description": "配置与启动日志(配置剧本)"},
    {"topic_id": "topic-005", "topic_name": "订单服务应用日志",
     "service_name": "order-service", "description": "应用运行日志(应用 OOM 剧本)"},
    {"topic_id": "topic-006", "topic_name": "支付服务依赖日志",
     "service_name": "payment-service", "description": "中间件连接日志(外部依赖剧本)"},
    {"topic_id": "topic-007", "topic_name": "计费服务应用日志",
     "service_name": "billing-service", "description": "应用运行日志(多症状叠加剧本)"},
    {"topic_id": "topic-008", "topic_name": "库存服务依赖日志",
     "service_name": "inventory-service", "description": "上游依赖日志(级联故障剧本)"},
    {"topic_id": "topic-009", "topic_name": "容器平台服务日志",
     "service_name": "container-service", "description": "容器编排层日志(容器 OOM/驱逐剧本)"},
    {"topic_id": "topic-010", "topic_name": "订单接口服务日志",
     "service_name": "order-api-service", "description": "服务接口日志(接口超时/熔断剧本)"},
]
_TOPIC_BY_ID = {t["topic_id"]: t for t in _MOCK_TOPICS}

# 本地日志缓存目录:模拟真实系统"日志有本地磁盘副本",供 executor 在 cls 服务不可达时
# 降级读取(MCP 优先 + 本地兜底,消除日志查询的单点依赖)。
LOG_CACHE_DIR = os.path.join("runtime", "log_cache")


def _cache_logs(topic_id: str, logs: list) -> None:
    """把一次成功的 search_log 结果落盘,供服务不可达时本地兜底读取。"""
    try:
        os.makedirs(LOG_CACHE_DIR, exist_ok=True)
        with open(os.path.join(LOG_CACHE_DIR, f"{topic_id}.json"), "w", encoding="utf-8") as f:
            json.dump({"topic_id": topic_id, "logs": logs}, f, ensure_ascii=False)
    except Exception:
        pass

# topic-003 混沌注入演示剧本:复现"混沌注入→网络超时→次生熔断→停止注入恢复"。
# 让 Agent 能依据真实观测(而非空谈)锁定网络/连通性根因,并识别线程池积压为次生影响。
# 覆盖 evidence_judge 的混沌/故障注入根因锁定规则(prompt 第 8 条)。
_NETWORK_CHAOS_SCENARIO = [
    ("INFO",  "请求 http://svc-a/orders 正常响应 42ms"),
    ("INFO",  "请求 http://svc-b/pay 正常响应 55ms"),
    ("WARN",  "请求 http://svc-c/ 响应超时 read-timeout"),
    ("ERROR", "connect to 10.0.3.21:8080 timed out (Connection timed out)"),
    ("WARN",  "间歇性 connection reset by peer"),
    ("ERROR", "混沌工程平台向 api-gateway 注入网络延迟 200ms 与 5% 丢包"),
    ("ERROR", "大量请求 Connection timed out, Hystrix 熔断降级触发"),
    ("WARN",  "线程池队列积压(网络超时触发,非配置/应用根因)"),
    ("INFO",  "停止故障注入后, 延迟与超时恢复, 连接恢复正常"),
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
    # 生产化双轨: Elasticsearch 后端启用且可达 → 真实索引匹配(结构与 mock 一致)
    if use_es_backend():
        client = _get_cls_client()
        if client.available:
            return client.search_topics(service_name, fuzzy)
        logger.warning("ES 不可达(%s),回退 mock 剧本", settings.CLS_ES_URL)
    matched = []
    for topic in _MOCK_TOPICS:
        name = topic["service_name"].lower()
        target = service_name.lower()
        hit = (target in name or name in target) if fuzzy else (name == target)
        if hit:
            matched.append(topic)
    # 盲测动态主题:盲测服务名或存在场景文件时也暴露,便于 LLM 定位
    if "blind" in service_name.lower() or _load_blind_scenario() is not None:
        matched.append({"topic_id": BLIND_TOPIC_ID, "topic_name": "盲测服务日志",
                        "service_name": "blind-svc", "description": "盲测动态服务日志"})
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
        日志内容按主题所属服务的剧本返回(mock_scenario.py):
          - data-sync-service → 全 INFO(mock 日志查不出异常,逼 Agent 重新规划)
          - api-gateway/auth/order/payment → 对应根因的 ERROR 特征日志
    """
    # 生产化双轨: Elasticsearch 后端启用且可达 → 真实日志查询(结构与 mock 一致)
    if use_es_backend():
        client = _get_cls_client()
        if client.available:
            return client.search_logs(topic_id, start_time or 0, end_time or int(datetime.now().timestamp() * 1000),
                                      query, limit)
        logger.warning("ES 不可达(%s),回退 mock 剧本", settings.CLS_ES_URL)
    # topic-003:混沌注入演示剧本(论文侧 e2e 特性,不依赖时间窗,始终返回完整剧本)
    if topic_id == "topic-003":
        now = start_time if start_time else int(datetime.now().timestamp() * 1000)
        logs = []
        for level, msg in _NETWORK_CHAOS_SCENARIO:
            t = now - len(logs) * 60 * 1000
            time_str = datetime.fromtimestamp(t / 1000).strftime("%Y-%m-%d %H:%M:%S")
            logs.append({"timestamp": time_str, "level": level, "message": msg})
        _cache_logs(topic_id, logs)
        return {"topic_id": topic_id, "start_time": start_time, "end_time": end_time,
                "query": query, "limit": limit, "total": len(logs), "logs": logs,
                "took_ms": 50, "message": f"成功查询 {len(logs)} 条日志"}

    # 盲测动态主题:实时读取生成器写入的场景,返回其日志(不含送分词,根因需多证据推断)。
    if topic_id == BLIND_TOPIC_ID:
        scenario = _load_blind_scenario()
        if not scenario:
            return {"topic_id": topic_id, "total": 0, "logs": [], "took_ms": 0,
                    "error": "无盲测场景", "message": "尚未生成盲测场景，请先写入 runtime/blind_scenario.json"}
        logs = scenario.get("scenario", {}).get("logs", [])
        logs = logs[:limit] if limit else logs
        _cache_logs(topic_id, logs)
        return {"topic_id": topic_id, "start_time": start_time, "end_time": end_time,
                "query": query, "limit": limit, "total": len(logs), "logs": logs,
                "took_ms": 50, "message": f"成功查询 {len(logs)} 条日志"}

    topic = _TOPIC_BY_ID.get(topic_id)
    if topic is None:
        return {"topic_id": topic_id, "total": 0, "logs": [], "took_ms": 0,
                "error": f"主题不存在: {topic_id}",
                "message": f"错误: 未找到主题 {topic_id},请检查 topic_id"}

    scenario = scenario_for_service(topic["service_name"])
    logs = log_lines(scenario, start_time, end_time, limit)
    _cache_logs(topic_id, logs)

    return {"topic_id": topic_id, "start_time": start_time, "end_time": end_time,
            "query": query, "limit": limit, "total": len(logs), "logs": logs,
            "took_ms": 50, "message": f"成功查询 {len(logs)} 条日志"}


if __name__ == "__main__":
    # streamable-http 模式: Agent 通过 http://<host>:8103/mcp 连接调用
    # 端口 8103 避开 Windows 保留段 7911-8010(否则 winerror 10013)
    # MCP_HOST 环境变量: 容器内生产部署设 0.0.0.0,本机默认 127.0.0.1 不变
    mcp.run(transport="streamable-http",
            host=os.environ.get("MCP_HOST", "127.0.0.1"), port=8103, path="/mcp")
