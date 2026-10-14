"""监控数据 MCP Server —— 真实指标 + 真实网站/服务探测(已移除运行时 Mock)

把"查监控指标"封装成一个独立的 HTTP 服务,通过 MCP 协议暴露给运维 Agent。
指标来自真实 Prometheus(MONITOR_BACKEND=prometheus + PROMETHEUS_URL)。
本服务已移除运行时 Mock 回退: 未启用真实后端或后端不可达时, 一律如实返回
"数据不可用"声明, 绝不生成编造指标污染根因判断。

真实探测能力(核心,解决"页面好、服务坏"盲区):
  - check_website(url, deep): 页面级可达性 + 深度检查首页子资源;
  - check_ports(host, ports): 端口级 TCP 探测,区分"服务未启动(拒绝)"与"网络不通(超时)";
  - check_service_health(base_url, health_path): 服务级健康端点探测;
  - check_api_endpoint(url, method, payload): 接口级业务探测,识别"页面能打开但功能坏"。
  这些探测的**判定口径与实现**统一收敛在 mcp_servers/site_probe.py(纯标准库引擎),
  命令行工具 scripts/probe_site.py 复用同一套逻辑,保证"Agent 看到的"与"人看到的"一致。

指标工具(query_cpu_metrics/query_memory_metrics)返回体统一带 data_source
("prometheus"真实 / "unavailable"不可用)。

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

from mcp_servers.prometheus_client import (
    PrometheusClient,
    _summarize,
    use_prometheus_backend,
)
from mcp_servers.site_probe import (
    DEFAULT_HEALTH_PATHS,
    deep_check,
    probe_http_api,
    probe_website,
    summarize_probe,
    tcp_connect,
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


# ── 数据来源标记(2026-10-10): 消除 Mock 假数据污染根因判断 ───────────────
# 背景: 实测中 MONITOR_BACKEND=prometheus 但 PROMETHEUS_URL 为空时静默回退 Mock,
# 服务名又回退 infra_cpu 默认剧本,凭空生成"CPU 爬升到 96%"并被当成真实证据定根因。
# 纪律: 每个指标返回都带 data_source;运行时 Mock 回退已彻底移除, 指标只可能来自
# Prometheus 或"不可用", 不拿假数据充数。


def _unavailable_metric(service_name: str, metric_name: str, interval: str,
                        reason: str, threshold: float) -> Dict[str, Any]:
    """真实监控不可用时返回的"如实声明"结构:无数据点、明确标注不可用。"""
    note = (f"[数据来源: 真实监控不可用 —— {reason}; 本次未取得真实指标, "
            f"不得据此判断资源瓶颈, 也不得在报告中给出具体 CPU/内存数值]")
    return {"service_name": service_name, "metric_name": metric_name,
            "scenario": "unavailable", "interval": interval,
            "data_source": "unavailable", "data_source_note": note,
            "data_points": [], **_summarize([], threshold)}


def _real_metric(service_name: str, metric: str, start: datetime, end: datetime,
                 interval_min: int, metric_name: str, interval: str,
                 threshold: float) -> Dict[str, Any]:
    """真实监控后端(Prometheus)取数 —— 真实链路唯一路径。

    已移除运行时 Mock 回退: 未启用真实后端或后端不可达时, 一律返回"不可用"声明,
    绝不生成编造指标。
    """
    if settings.MONITOR_BACKEND.strip().lower() != "prometheus":
        return _unavailable_metric(service_name, metric_name, interval,
                                   "MONITOR_BACKEND 未设为 prometheus", threshold)
    if not use_prometheus_backend():
        return _unavailable_metric(service_name, metric_name, interval,
                                   "PROMETHEUS_URL 未配置", threshold)
    client = _get_prom_client()
    if not client.available:
        logger.warning("Prometheus 不可达(%s)", settings.PROMETHEUS_URL)
        return _unavailable_metric(service_name, metric_name, interval,
                                   f"Prometheus({settings.PROMETHEUS_URL}) 不可达", threshold)
    query = client.query_cpu if metric == "cpu" else client.query_memory
    return query(service_name, start, end, interval_min)


@mcp.tool()
@log_tool_call
def query_cpu_metrics(service_name: str, start_time: Optional[str] = None,
                      end_time: Optional[str] = None, interval: str = "1m") -> Dict[str, Any]:
    """查询某个服务在一段时间内的 CPU 使用率(百分比),数据来自真实 Prometheus。

    Args:
        service_name: 服务名,如 "data-sync-service"(必填)
        start_time: 开始时间 "YYYY-MM-DD HH:MM:SS"(可选,默认 1 小时前)
        end_time: 结束时间 "YYYY-MM-DD HH:MM:SS"(可选,默认当前)
        interval: 采样间隔 "1m"/"5m"/"1h"(可选,默认 "1m")

    Returns:
        含 data_points(逐点 CPU%)、statistics(均值/峰值/p95)、alert_info(是否越过 80% 阈值)、
        data_source("prometheus"真实 / "unavailable"不可用)。
    """
    start = _parse_time(start_time, -1)
    end = _parse_time(end_time, 0)
    return _real_metric(service_name, "cpu", start, end, _interval_minutes(interval),
                        "cpu_usage_percent", interval, CPU_ALERT_THRESHOLD)


@mcp.tool()
@log_tool_call
def query_memory_metrics(service_name: str, start_time: Optional[str] = None,
                         end_time: Optional[str] = None, interval: str = "1m") -> Dict[str, Any]:
    """查询某个服务在一段时间内的内存使用率(百分比),数据来自真实 Prometheus。参数同 query_cpu_metrics。

    Returns:
        含 data_points(逐点内存%)、statistics、alert_info(是否越过 70% 阈值)、
        data_source("prometheus"真实 / "unavailable"不可用)。
    """
    start = _parse_time(start_time, -1)
    end = _parse_time(end_time, 0)
    return _real_metric(service_name, "memory", start, end, _interval_minutes(interval),
                        "memory_usage_percent", interval, MEMORY_ALERT_THRESHOLD)


# ── 真实探测工具(实现见 mcp_servers/site_probe.py,这里只做 MCP 协议封装) ──


@mcp.tool()
@log_tool_call
def check_website(url: str, timeout_s: float = 10.0, deep: bool = False) -> Dict[str, Any]:
    """检查一个网址/网站是否可正常访问,并报告访问质量(真实发起 HTTP 请求)。

    典型使用场景:用户直接给出一个网址(如"帮我看看 https://example.com 有没有问题"),
    或要求对某个在线服务做健康检查。**这是真实探测,不是模拟数据**。

    判定口径(如实报告,不得臆造故障):
      - 可访问(2xx): 结论为"网站正常",报告状态码与响应耗时;响应慢可提示性能观察;
      - 可访问(3xx): 报告重定向到哪、最终落地状态;
      - 可访问(4xx/5xx): 报告具体错误码与含义(如 404 页面不存在、503 服务不可用);
      - 不可访问: 报告错误类型(DNS 失败/连接拒绝/超时/TLS 失败)及可能的含义。

    deep=True 时额外做**深度检查**(当用户要求"全面检查/排查问题"时用它):
      - 抽取首页引用的图片与链接,逐个真实访问,发现 404/500/响应慢的子资源;
      - 汇总成 issues 列表(每条含具体 URL、现象、严重度),供报告如实引用。

    Args:
        url: 目标网址,如 "https://example.com"(必填,可省略 http:// 前缀)
        timeout_s: 超时秒数(可选,默认 10)
        deep: 是否做深度检查(首页资源逐个探测),默认 False

    Returns:
        reachable(是否可达)、final_url(最终地址)、http_status(状态码)、
        http_reason(状态码含义)、response_ms(响应耗时毫秒)、title(页面标题)、
        server(服务器标识);不可达时含 error_type/error_hint;
        deep=True 时另有 sub_checks(逐资源结果)与 issues(问题清单)。
    """
    result = probe_website(url, timeout_s)
    summary = summarize_probe(url, result)

    payload: Dict[str, Any] = {"url": url, "timeout_s": timeout_s, "deep": deep,
                               "summary": summary, **result}

    if deep and result.get("reachable") and result.get("http_status") == 200:
        sub_checks, issues = deep_check(url, result, timeout_s)
        payload["sub_checks"] = sub_checks
        payload["issues"] = issues
        if issues:
            brief = "；".join(f"{i['url']} {i['severity']}（{i['detail']}）" for i in issues[:5])
            payload["summary"] = f"{summary} 深度检查发现 {len(issues)} 个问题：{brief}"
        else:
            payload["summary"] = f"{summary} 深度检查未发现子资源问题。"
    return payload


@mcp.tool()
@log_tool_call
def check_ports(host: str, ports: str = "80,443,8000,8080,3000,5000") -> Dict[str, Any]:
    """探测某台主机上若干端口是否有服务在监听(真实 TCP 连接探测)。

    用途: 判断"服务到底起没起"。**同机/同网段**下:
      - 端口"连接被拒绝" → 该端口无监听, 服务未启动/已退出;
      - 端口"连接超时"   → 网络层不可达, **不能**据此判断服务状态。
    这是区分"服务未启动"与"网络不通"的关键证据, 页面检查无法替代。

    Args:
        host: 主机名或 IP, 如 "127.0.0.1" 或 "192.168.3.251"(必填)
        ports: 逗号分隔的端口列表, 如 "8080,8000"(可选, 默认常见 Web 端口)

    Returns:
        results(逐端口 open/refused/timeout)、open_ports(有监听的端口)、summary(人话结论)。
    """
    port_list = [int(p.strip()) for p in str(ports).split(",") if p.strip().isdigit()]
    # 超时 4s: 部分 Windows 环境对本地关闭端口的"拒绝"回包延迟约 2s, 留足余量避免误判为超时
    results = [tcp_connect(host, p, 4.0) for p in port_list]
    open_ports = [r["port"] for r in results if r["open"]]
    refused = [r["port"] for r in results if r["status"] == "refused"]
    timeouts = [r["port"] for r in results if r["status"] == "timeout"]

    if open_ports:
        summary = f"{host} 上 {open_ports} 端口有服务在监听。"
    elif refused and not timeouts:
        summary = f"{host} 上被探测的端口均无监听(连接被拒绝), 对应服务很可能未启动。"
    elif timeouts and not refused:
        summary = f"{host} 不可达(连接超时), 无法判断服务是否启动——请先确认网络与防火墙。"
    else:
        summary = f"{host} 端口探测: 拒绝 {refused}, 超时 {timeouts}。"
    return {"host": host, "ports": port_list, "results": results,
            "open_ports": open_ports, "summary": summary}


@mcp.tool()
@log_tool_call
def check_service_health(base_url: str, health_path: Optional[str] = None,
                         timeout_s: float = 10.0) -> Dict[str, Any]:
    """检查一个服务的健康检查端点(真实 HTTP 探测), 判断"服务本身"是否健康。

    与 check_website 的区别: check_website 看"网页能不能打开"(页面级),
    本工具看"服务进程是否健康"(服务级)。**页面正常不代表服务正常**——
    典型场景: 前端页面 200, 但后台服务已卡死/未就绪。

    Args:
        base_url: 服务根地址, 如 "https://api.example.com"(必填)
        health_path: 健康检查路径(可选)。不传则依次尝试 /health /healthz /ready /api/health /status
        timeout_s: 超时秒数(可选, 默认 10)

    Returns:
        checked(逐个端点的探测结果)、healthy(是否有端点返回 2xx)、summary(人话结论)。
    """
    base = base_url.rstrip("/")
    paths = [health_path] if health_path else list(DEFAULT_HEALTH_PATHS)
    checked = []
    for p in paths:
        path = p if str(p).startswith("/") else "/" + str(p)
        r = probe_http_api(base + path, "GET", None, timeout_s)
        checked.append({"endpoint": base + path, **r})
    healthy = [c for c in checked
               if isinstance(c.get("http_status"), int) and 200 <= c["http_status"] < 300]
    if healthy:
        h = healthy[0]
        summary = (f"服务健康检查通过: {h['endpoint']} 返回 HTTP {h['http_status']}, "
                   f"耗时 {h['response_ms']} ms。")
    else:
        detail = "; ".join(
            f"{c['endpoint']} -> "
            + (f"HTTP {c['http_status']}" if c.get("http_status") else str(c.get("error_type")))
            for c in checked
        )
        summary = (f"未找到可用的健康检查端点({detail})。"
                   f"注意: 没有健康端点不等于服务一定异常, 需结合业务接口判断。")
    return {"base_url": base_url, "checked": checked, "healthy": bool(healthy), "summary": summary}


@mcp.tool()
@log_tool_call
def check_api_endpoint(url: str, method: str = "GET", payload: Optional[str] = None,
                       timeout_s: float = 10.0, headers: Optional[str] = None) -> Dict[str, Any]:
    """真实请求一个**业务接口**, 判断业务功能是否正常(而不只是页面能不能打开)。

    典型场景: 用户说"页面能打开, 但点某个功能报错 / 提交后一直没反应 / 任务不返回"
    —— 这类故障页面检查看不出来, 必须实际打业务接口看返回。

    判定口径(如实报告): 2xx=接口正常; 4xx=请求/权限问题; 5xx=服务端异常;
    超时/连接失败=服务未响应或不可达。

    Args:
        url: 接口地址, 如 "https://api.example.com/v1/tasks"(必填)
        method: HTTP 方法, GET/POST/PUT/DELETE/HEAD(可选, 默认 GET)
        payload: 请求体(JSON 字符串, 可选, 用于 POST/PUT)
        timeout_s: 超时秒数(可选, 默认 10)
        headers: 额外请求头(JSON 字符串, 可选), 如 '{"Authorization": "Bearer xxx"}'

    Returns:
        reachable、http_status、response_ms、body_snippet(响应体摘要)、
        failure_layer; 不可达时含 error_type/error_hint。
    """
    extra = None
    if headers:
        try:
            extra = json.loads(headers)
        except Exception:
            extra = None
    r = probe_http_api(url, method, payload, timeout_s, extra)
    code = r.get("http_status")
    if not r.get("reachable"):
        r["summary"] = f"业务接口不可达: {r.get('error_type')}({r.get('error_hint') or '无'})。"
    elif isinstance(code, int) and 200 <= code < 300:
        r["summary"] = f"业务接口正常: HTTP {code}, 耗时 {r.get('response_ms')} ms。"
    elif isinstance(code, int) and code >= 500:
        r["summary"] = f"业务接口服务端异常: HTTP {code}, 说明后台服务在运行但处理失败(需查后台日志)。"
    elif isinstance(code, int) and code >= 400:
        r["summary"] = f"业务接口返回客户端错误: HTTP {code}(请求/权限问题)。"
    else:
        r["summary"] = f"业务接口返回 HTTP {code}。"
    return {"url": url, "method": str(method).upper(), **r}


if __name__ == "__main__":
    # streamable-http 模式: Agent 通过 http://<host>:8104/mcp 连接调用
    # 端口 8104 避开 Windows 保留段 7911-8010(否则 winerror 10013)
    # MCP_HOST 环境变量: 容器内生产部署设 0.0.0.0,本机默认 127.0.0.1 不变
    mcp.run(transport="streamable-http",
            host=os.environ.get("MCP_HOST", "127.0.0.1"), port=8104, path="/mcp")