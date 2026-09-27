"""Prometheus 指标后端(monitor_server "Mock→真实"双轨中的真实侧)。

monitor_server 的 query_cpu_metrics / query_memory_metrics 在
MONITOR_BACKEND=prometheus 且 PROMETHEUS_URL 已配置、可达时,把取数交给本模块;
否则(默认)走 mock_scenario 剧本。本模块返回结构与 mock 路径**完全一致**
(service_name / metric_name / scenario / interval / data_points / statistics / alert_info),
所以 Agent 侧(planner/executor)零改动 —— 这是"先 Mock 后真实"策略的落地方式。

设计取舍:
  - 只用 requests 直连 Prometheus HTTP API(/api/v1/query_range),不引入
    prometheus-api-client 之类额外 SDK,生产部署依赖越少越省事。
  - 实例化时探活一次。连接层失败(不可达/超时)标记 available=False,后续调用由
    monitor_server 自动回退 mock;查询本身报错(如 PromQL 非法)不回退,而是返回空
    data_points + error —— 宁可让 Agent 看到"取数失败",也不伪造指标数据污染根因判断。

由 monitor_server.py 在独立进程中 import 使用。
"""

import logging
import re
from datetime import datetime
from typing import Any, Dict, List

import requests

from mcp_servers.service_map import resolve_service
from src.settings import settings

logger = logging.getLogger("Prometheus_Client")

# 与 monitor_server 保持同源(超阈值即视为异常)
CPU_ALERT_THRESHOLD = 80.0
MEMORY_ALERT_THRESHOLD = 70.0


def use_prometheus_backend() -> bool:
    """MONITOR_BACKEND=prometheus 且配了 PROMETHEUS_URL 时才启用真实后端。"""
    return (settings.MONITOR_BACKEND.strip().lower() == "prometheus"
            and bool(settings.PROMETHEUS_URL.strip()))


def _request_kwargs() -> Dict[str, Any]:
    """鉴权 / TLS 参数(真实环境常启用;未配置时不带任何鉴权头)。

    Bearer 优先于 Basic:前置网关(如 Thanos/nginx)通常只认 token,同时配了两者
    时按 token 走,避免 Basic 头被网关拒绝。
    """
    kwargs: Dict[str, Any] = {"verify": settings.PROMETHEUS_VERIFY_SSL}
    if settings.PROMETHEUS_BEARER_TOKEN:
        kwargs["headers"] = {"Authorization": f"Bearer {settings.PROMETHEUS_BEARER_TOKEN}"}
    elif settings.PROMETHEUS_USERNAME:
        kwargs["auth"] = (settings.PROMETHEUS_USERNAME, settings.PROMETHEUS_PASSWORD)
    return kwargs


def _summarize(points: List[Dict[str, Any]], threshold: float) -> Dict[str, Any]:
    """把逐点序列压成 statistics(均值/峰值/p95) + alert_info(是否越阈值)。

    monitor_server 以 `**_summarize(...)` 展开进返回值,故返回的两个键名即工具输出契约。
    """
    values = [float(p["value"]) for p in points if p.get("value") is not None]
    if not values:
        return {
            "statistics": {"count": 0, "mean": 0.0, "max": 0.0, "min": 0.0, "p95": 0.0},
            "alert_info": {"triggered": False, "threshold": threshold,
                           "message": "无数据点,未触发告警"},
        }
    ordered = sorted(values)
    # 最近邻取 p95:样本量小时比线性插值更保守,不会低估峰值
    p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]
    peak = ordered[-1]
    triggered = peak > threshold
    return {
        "statistics": {
            "count": len(values),
            "mean": round(sum(values) / len(values), 2),
            "max": round(peak, 2),
            "min": round(ordered[0], 2),
            "p95": round(p95, 2),
        },
        "alert_info": {
            "triggered": triggered,
            "threshold": threshold,
            "message": (f"峰值 {round(peak, 2)}% 超过阈值 {threshold}%,触发告警"
                        if triggered
                        else f"峰值 {round(peak, 2)}% 未超过阈值 {threshold}%,无告警"),
        },
    }


# 字符类之外的 RE2 元字符(不含 "-":它在字符类之外是字面量)
_METACHARS = re.compile(r"([.^$*+?()\[\]{}|\\])")


def _escape_metachars(name: str) -> str:
    """转义正则元字符,保留 - _ / 等字面字符,让生成的 PromQL 可读。"""
    return _METACHARS.sub(r"\\\1", name)


def _service_regex(service_name: str) -> str:
    """服务名 → PromQL 正则择一(经 service_map 归一化 + 展开候选)。

    解决"用户说订单服务,监控叫 order-svc"导致 instance 匹配落空:展开后得到
    `(?:order-svc|order-service)`,替换进模板的 {service} 占位。

    两个细节:
      1) 用**非捕获分组**包裹。模板里 {service} 后面通常还跟着 `.*`
         (如 instance=~"{service}.*"),而 `|` 优先级最低 —— 若返回裸的
         `a|b`,整条会解析成 `a` 或 `b.*`,第一个候选就退化成精确匹配,
         instance 带后缀(如 order-svc-0)时反而匹配不上。
      2) 对每个候选转义正则元字符。模板里 {service} 是**字面服务名占位**(正则结构由
         用户在 PROMETHEUS_*_PROMQL 里自行书写),转义可避免名字里的 . 或 *
         被当成元字符导致误匹配或 PromQL 语法错误。

         这里只转义字符类之外的元字符(. ^ $ * + ? ( ) [ ] { } | \\),不用
         re.escape —— 后者连 `-` 一起转义,会把 data-sync-service 变成
         data\\-sync\\-service,在 RE2 里虽合法但可读性差。
    """
    alternatives = "|".join(_escape_metachars(c) for c in resolve_service(service_name, "monitor"))
    return f"(?:{alternatives})"


class PrometheusClient:
    """Prometheus HTTP API 客户端(单例由 monitor_server 持有)。"""

    def __init__(self) -> None:
        self.base_url = settings.PROMETHEUS_URL.rstrip("/")
        self.timeout = settings.PROMETHEUS_TIMEOUT_SECONDS
        self.available = self._probe()

    def _probe(self) -> bool:
        """探活:能成功执行一次最轻量的即时查询即视为可用。"""
        try:
            resp = requests.get(f"{self.base_url}/api/v1/query",
                                params={"query": "up"}, timeout=self.timeout,
                                **_request_kwargs())
            ok = resp.status_code == 200 and resp.json().get("status") == "success"
            if not ok:
                logger.warning("Prometheus 探活异常: HTTP %s", resp.status_code)
            return ok
        except Exception as e:
            logger.warning("Prometheus 探活失败(%s): %s", self.base_url, e)
            return False

    def query_cpu(self, service_name: str, start: datetime, end: datetime,
                  interval_min: int) -> Dict[str, Any]:
        """查询 CPU 使用率(结构与 mock 路径一致)。"""
        return self._query_range(service_name, "cpu", settings.PROMETHEUS_CPU_PROMQL,
                                 start, end, interval_min, CPU_ALERT_THRESHOLD)

    def query_memory(self, service_name: str, start: datetime, end: datetime,
                     interval_min: int) -> Dict[str, Any]:
        """查询内存使用率(结构与 mock 路径一致)。"""
        return self._query_range(service_name, "memory", settings.PROMETHEUS_MEMORY_PROMQL,
                                 start, end, interval_min, MEMORY_ALERT_THRESHOLD)

    def _query_range(self, service_name: str, metric: str, promql_template: str,
                     start: datetime, end: datetime, interval_min: int,
                     threshold: float) -> Dict[str, Any]:
        metric_name = "cpu_usage_percent" if metric == "cpu" else "memory_usage_percent"
        interval_str = f"{interval_min}m"
        promql = promql_template.replace("{service}", _service_regex(service_name))
        logger.debug("PromQL(%s, service=%s): %s", metric, service_name, promql)

        def _payload(points: List[Dict[str, Any]], error: str = "") -> Dict[str, Any]:
            data = {"service_name": service_name, "metric_name": metric_name,
                    "scenario": "prometheus", "interval": interval_str,
                    "data_points": points, **_summarize(points, threshold)}
            if error:
                data["error"] = error
            return data

        try:
            resp = requests.get(
                f"{self.base_url}/api/v1/query_range",
                params={"query": promql,
                        "start": start.timestamp(),
                        "end": end.timestamp(),
                        "step": interval_min * 60},
                timeout=self.timeout,
                **_request_kwargs(),
            )
            resp.raise_for_status()
            body = resp.json()
            if body.get("status") != "success":
                raise RuntimeError(body.get("error") or "Prometheus 返回非 success")
            points = self._to_points(body.get("data", {}).get("result", []))
        except (requests.ConnectionError, requests.Timeout) as e:
            # 连接层失败 = 后端真的不可达,标记后由 monitor_server 回退 mock
            self.available = False
            logger.warning("Prometheus 不可达(service=%s, metric=%s): %s",
                           service_name, metric, e)
            return _payload([], f"Prometheus 不可达: {e}")
        except Exception as e:
            # 查询/解析错误(如 PromQL 非法):保留 available,如实上报取数失败
            logger.warning("Prometheus 查询失败(service=%s, metric=%s): %s",
                           service_name, metric, e)
            return _payload([], f"Prometheus 查询失败: {e}")

        return _payload(points)

    @staticmethod
    def _to_points(result: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """把 Prometheus series 拍平成 [{timestamp: HH:MM, value: float}](与 mock 同构)。

        多序列(多实例/多核)时按时间戳求均值聚合。
        """
        buckets: Dict[int, List[float]] = {}
        for series in result:
            for ts, raw in series.get("values", []) or []:
                try:
                    buckets.setdefault(int(float(ts)), []).append(float(raw))
                except (TypeError, ValueError):
                    continue
        return [{"timestamp": datetime.fromtimestamp(ts).strftime("%H:%M"),
                 "value": round(sum(vals) / len(vals), 1)}
                for ts, vals in sorted(buckets.items())]