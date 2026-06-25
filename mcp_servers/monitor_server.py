"""监控数据 MCP Server(Mock 版)

把"查监控指标"封装成一个独立的 HTTP 服务,通过 MCP 协议暴露给运维 Agent。
当前返回的是【精心编排的 mock 数据】(CPU 从低到高爬升),目的是先让 AI 诊断
链路跑通、演示可复现;后续把内部数据生成逻辑换成真实 Prometheus 查询即可,
Agent 侧代码无需改动 —— 这就是"先 Mock 后真实"策略的技术地基。

独立进程运行: python mcp_servers/monitor_server.py  (默认 127.0.0.1:8004)
"""

import functools
import json
import logging
import random
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from fastmcp import FastMCP

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("Monitor_MCP_Server")

mcp = FastMCP("Monitor")

# CPU/内存的告警阈值(超过即视为异常,单一事实来源,勿散落在各处)
CPU_ALERT_THRESHOLD = 80.0
MEMORY_ALERT_THRESHOLD = 70.0


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


def _build_rising_series(start: datetime, end: datetime, interval_min: int,
                         base: float, climb_per_step: float, ceiling: float,
                         jitter: float) -> list:
    """生成一条【先平稳后爬升】的指标曲线(CPU 和内存共用,避免重复实现)。

    剧本: 前 3 个点在 base 附近小幅波动,之后按 climb_per_step 线性爬升,封顶 ceiling。
    这样保证 demo 里指标必然冲高、触发告警,诊断结论稳定可复现。
    """
    points = []
    current, idx = start, 0
    while current <= end:
        if idx < 3:
            value = base + idx * 0.5
        else:
            value = min(base + (idx - 2) * climb_per_step, ceiling)
        value = max(0.0, min(100.0, round(value + random.uniform(-jitter, jitter), 1)))
        points.append({"timestamp": current.strftime("%H:%M"), "value": value})
        current += timedelta(minutes=interval_min)
        idx += 1
    return points


def _summarize(points: list, threshold: float) -> Dict[str, Any]:
    """对一条曲线算统计量(均值/峰值/p95)并判断是否越过告警阈值。"""
    values = [p["value"] for p in points]
    peak = max(values)
    p95 = sorted(values)[int(len(values) * 0.95)] if len(values) > 1 else peak
    triggered = peak > threshold
    return {
        "statistics": {"avg": round(sum(values) / len(values), 2),
                       "max": peak, "min": min(values), "p95": round(p95, 2)},
        "alert_info": {"triggered": triggered, "threshold": threshold,
                       "message": f"峰值 {peak}% 超过阈值 {threshold}%" if triggered else "指标正常"},
    }


@mcp.tool()
@log_tool_call
def query_cpu_metrics(service_name: str, start_time: Optional[str] = None,
                      end_time: Optional[str] = None, interval: str = "1m") -> Dict[str, Any]:
    """查询某个服务在一段时间内的 CPU 使用率(百分比)。

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
    points = _build_rising_series(start, end, _interval_minutes(interval),
                                  base=10.0, climb_per_step=8.5, ceiling=96.0, jitter=2.0)
    return {"service_name": service_name, "metric_name": "cpu_usage_percent",
            "interval": interval, "data_points": points,
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
    points = _build_rising_series(start, end, _interval_minutes(interval),
                                  base=30.0, climb_per_step=5.5, ceiling=85.0, jitter=1.0)
    return {"service_name": service_name, "metric_name": "memory_usage_percent",
            "interval": interval, "data_points": points,
            **_summarize(points, MEMORY_ALERT_THRESHOLD)}


if __name__ == "__main__":
    # streamable-http 模式: Agent 通过 http://127.0.0.1:8004/mcp 连接调用
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8004, path="/mcp")


