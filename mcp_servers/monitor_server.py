"""监控数据 MCP Server(Mock 版,多剧本)

把"查监控指标"封装成一个独立的 HTTP 服务,通过 MCP 协议暴露给运维 Agent。
数据按 service_name 决定剧本(见 mock_scenario.py):
  - data-sync-service: CPU/内存从低到高爬升(指标必然冲高,触发告警,诊断结论可复现);
  - api-gateway/auth/payment: 指标正常(供网络/配置/依赖剧本,由日志侧定位根因);
  - order-service: 内存缓涨不上告警 + 日志侧 OOM(应用剧本,鉴别证据在日志堆栈)。
同时保留盲测动态场景:run_blind_eval 写入 runtime/blind_scenario.json 后,
blind-svc 按场景指标形态生成曲线(盲测专用,不重启 MCP 即可切换场景)。

后续把内部数据生成逻辑换成真实 Prometheus 查询即可,Agent 侧代码无需改动
——这就是"先 Mock 后真实"策略的技术地基。

独立进程运行: python mcp_servers/monitor_server.py  (默认 127.0.0.1:8104)
"""

import functools
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from fastmcp import FastMCP

# 确保独立进程直接运行时能 import 同目录下的 mcp_servers 包
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from mcp_servers.mock_scenario import build_points, scenario_for_service
from mcp_servers.prometheus_client import (
    PrometheusClient,
    _summarize,
    use_prometheus_backend,
)
from src.settings import settings

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("Monitor_MCP_Server")

mcp = FastMCP("Monitor")

# CPU/内存的告警阈值(超过即视为异常,单一事实来源,勿散落在各处)
CPU_ALERT_THRESHOLD = 80.0
MEMORY_ALERT_THRESHOLD = 70.0

# Prometheus 客户端单例(生产化后端,Mock→真实双轨,见 docs/MCP生产化改造方案.md)
_prom_client: "PrometheusClient | None" = None


def _get_prom_client() -> PrometheusClient:
    global _prom_client
    if _prom_client is None:
        _prom_client = PrometheusClient()
    return _prom_client

# 盲测动态指标:读取 run_blind_eval 写入的当前场景,按 metrics 形态生成曲线
BLIND_SCENARIO_PATH = os.path.join("runtime", "blind_scenario.json")


def _load_blind_metrics() -> Optional[Dict[str, Any]]:
    try:
        with open(BLIND_SCENARIO_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("scenario", {}).get("metrics", {})
    except Exception:
        return None


def log_tool_call(func):
    """装饰器:统一打印工具被调用时的方法名/参数/成败,方便观察 Agent 调了什么。"""
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


def _parse_time(time_str: Optional[str], default_offset_hours: int = 0) -> datetime:
    """把 "YYYY-MM-DD HH:MM:SS" 解析成 datetime;解析失败或为空则用 当前时间+偏移。"""
    if time_str:
        try:
            return datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return datetime.now() + timedelta(hours=default_offset_hours)


def _interval_minutes(interval: str) -> int:
    """把 "1m"/"5m"/"1h" 这种间隔字符串转成分钟数。"""
    if interval.endswith("h"):
        return int(interval[:-1]) * 60
    if interval.endswith("m"):
        return int(interval[:-1])
    return 1


def _blind_params(mode: str) -> dict:
    """盲测场景指标形态 → 曲线参数。normal=平稳不告警;moderate=偏高;rising=爬升触发告警。"""
    return {
        "normal": {"base": 12.0, "climb_per_step": 0.4, "ceiling": 30.0, "jitter": 1.5},
        "moderate": {"base": 45.0, "climb_per_step": 2.0, "ceiling": 72.0, "jitter": 1.5},
        "rising": {"base": 15.0, "climb_per_step": 8.5, "ceiling": 96.0, "jitter": 2.0},
    }.get(mode, {"base": 12.0, "climb_per_step": 0.4, "ceiling": 30.0, "jitter": 1.5})


def _blind_scenario_for(service_name: str) -> Optional[dict]:
    """盲测动态:服务名含 blind 且存在场景文件时,返回该场景的指标参数字典。"""
    if "blind" not in (service_name or "").lower():
        return None
    m = _load_blind_metrics()
    if not m:
        return None
    return {"cpu": _blind_params(m.get("cpu", "normal")),
            "mem": _blind_params(m.get("mem", "normal"))}


@mcp.tool()
@log_tool_call
def query_cpu_metrics(service_name: str, start_time: Optional[str] = None,
                      end_time: Optional[str] = None, interval: str = "1m") -> Dict[str, Any]:
    """查询某个服务在一段时间内的 CPU 使用率(百分比)。

    数据剧本由 service_name 决定(见 mock_scenario.py):
      - data-sync-service: CPU 爬升冲高,触发告警
      - 其余服务: 水平波动的正常指标
      - blind-svc: 读取盲测场景指标形态(盲测专用)

    Args:
        service_name: 服务名,如 "data-sync-service"(必填)
        start_time: 开始时间 "YYYY-MM-DD HH:MM:SS"(可选,默认 1 小时前)
        end_time: 结束时间 "YYYY-MM-DD HH:MM:SS"(可选,默认当前)
        interval: 采样间隔 "1m"/"5m"/"1h"(可选,默认 "1m")

    Returns:
        含 data_points(逐点 CPU%)、statistics(均值/峰值/p95)、alert_info(是否越过 80% 阈值)。
    """
    start = _parse_time(start_time, -1)
    end = _parse_time(end_time, 0)
    # 生产化双轨: Prometheus 后端启用且可达 → 真实查询(返回结构与 mock 一致)
    if use_prometheus_backend():
        client = _get_prom_client()
        if client.available:
            return client.query_cpu(service_name, start, end, _interval_minutes(interval))
        logger.warning("Prometheus 不可达(%s),回退 mock 剧本", settings.PROMETHEUS_URL)
    blind = _blind_scenario_for(service_name)
    if blind is not None:
        points = _build_from_params(start, end, _interval_minutes(interval), blind["cpu"])
        scenario = "blind"
    else:
        scenario = scenario_for_service(service_name)
        points = build_points(scenario, "cpu", start, end, _interval_minutes(interval))
    return {"service_name": service_name, "metric_name": "cpu_usage_percent",
            "scenario": scenario, "interval": interval, "data_points": points,
            **_summarize(points, CPU_ALERT_THRESHOLD)}


@mcp.tool()
@log_tool_call
def query_memory_metrics(service_name: str, start_time: Optional[str] = None,
                         end_time: Optional[str] = None, interval: str = "1m") -> Dict[str, Any]:
    """查询某个服务在一段时间内的内存使用率(百分比)。参数同 query_cpu_metrics。

    Returns:
        含 data_points(逐点内存%)、statistics、alert_info(是否越过 70% 阈值)。
    """
    start = _parse_time(start_time, -1)
    end = _parse_time(end_time, 0)
    # 生产化双轨: Prometheus 后端启用且可达 → 真实查询(返回结构与 mock 一致)
    if use_prometheus_backend():
        client = _get_prom_client()
        if client.available:
            return client.query_memory(service_name, start, end, _interval_minutes(interval))
        logger.warning("Prometheus 不可达(%s),回退 mock 剧本", settings.PROMETHEUS_URL)
    blind = _blind_scenario_for(service_name)
    if blind is not None:
        points = _build_from_params(start, end, _interval_minutes(interval), blind["mem"])
        scenario = "blind"
    else:
        scenario = scenario_for_service(service_name)
        points = build_points(scenario, "memory", start, end, _interval_minutes(interval))
    return {"service_name": service_name, "metric_name": "memory_usage_percent",
            "scenario": scenario, "interval": interval, "data_points": points,
            **_summarize(points, MEMORY_ALERT_THRESHOLD)}


def _build_from_params(start: datetime, end: datetime, interval_min: int, params: dict) -> list:
    """按参数字典生成先平稳后爬升的指标曲线(盲测场景专用)。"""
    points = []
    current, idx = start, 0
    while current <= end:
        if idx < 3:
            value = params["base"] + idx * 0.5
        else:
            value = min(params["base"] + (idx - 2) * params["climb_per_step"], params["ceiling"])
        value = max(0.0, min(100.0, round(value + __import__("random").uniform(-params["jitter"], params["jitter"]), 1)))
        points.append({"timestamp": current.strftime("%H:%M"), "value": value})
        current += timedelta(minutes=interval_min)
        idx += 1
    return points


if __name__ == "__main__":
    # streamable-http 模式: Agent 通过 http://<host>:8104/mcp 连接调用
    # 端口 8104 避开 Windows 保留段 7911-8010(否则 winerror 10013)
    # MCP_HOST 环境变量: 容器内生产部署设 0.0.0.0,本机默认 127.0.0.1 不变
    mcp.run(transport="streamable-http",
            host=os.environ.get("MCP_HOST", "127.0.0.1"), port=8104, path="/mcp")
