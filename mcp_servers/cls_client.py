"""Elasticsearch 日志后端(cls_server "Mock→真实"双轨中的真实侧)。

cls_server 的 search_topic_by_service_name / search_log 在
CLS_BACKEND=elasticsearch 且 CLS_ES_URL 已配置、可达时,把查询交给本模块;
否则(默认)走 mock_scenario 剧本。本模块返回结构与 mock 路径**完全一致**
(search_topic → total/topics/query/message;search_log → topic_id/logs/took_ms/...),
所以 Agent 侧零改动。

语义映射(Mock 概念 → ES 概念):
  - "日志主题 topic" → ES 索引(index)。故 topics[i]["topic_id"] 即索引名,
    search_log 拿它当索引查询,两层链路语义不变。
  - 服务名 → 索引模式用 settings.CLS_INDEX_PATTERN(默认 "{service}-logs-*")。
  - 日志字段用 settings.CLS_LOG_{TIMESTAMP,LEVEL,MESSAGE}_FIELD 映射到
    timestamp/level/message,兼容真实平台字段命名。

设计取舍:
  - 只用 requests 直连 ES REST API,不引入 elasticsearch SDK(少一个重依赖)。
  - 探活失败(不可达/超时)标记 available=False,由 cls_server 自动回退 mock;
    单次查询报错不回退,如实返回空结果 + error,不伪造日志(日志是根因鉴别的
    关键证据,造假会直接污染结论)。

由 cls_server.py 在独立进程中 import 使用。
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from mcp_servers.service_map import resolve_service
from src.settings import settings

logger = logging.getLogger("CLS_Client")

# 集群健康为这三种状态时都认为可查询(yellow=副本未分配,但主分片可读)
_HEALTHY_STATES = ("green", "yellow", "red")


def use_es_backend() -> bool:
    """CLS_BACKEND=elasticsearch 且配了 CLS_ES_URL 时才启用真实后端。"""
    return (settings.CLS_BACKEND.strip().lower() == "elasticsearch"
            and bool(settings.CLS_ES_URL.strip()))


def _to_iso_utc(ms: Optional[int]) -> str:
    """毫秒时间戳 → ES range 查询用的 ISO8601(UTC)。"""
    if not ms:
        return ""
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class ClsClient:
    """Elasticsearch 日志客户端(单例由 cls_server 持有)。"""

    def __init__(self) -> None:
        self.base_url = settings.CLS_ES_URL.rstrip("/")
        self.timeout = settings.CLS_TIMEOUT_SECONDS
        self.ts_field = settings.CLS_LOG_TIMESTAMP_FIELD
        self.level_field = settings.CLS_LOG_LEVEL_FIELD
        self.msg_field = settings.CLS_LOG_MESSAGE_FIELD
        self.available = self._probe()

    def _request_kwargs(self) -> Dict[str, Any]:
        """鉴权 / TLS 参数(未配置时不带鉴权头)。

        ES ApiKey 优先于 Basic Auth:同时配了两者时按 ApiKey 走(官方推荐做法,
        且 Basic 头会被启用安全功能的集群拒绝)。
        """
        kwargs: Dict[str, Any] = {"verify": settings.CLS_ES_VERIFY_SSL}
        if settings.CLS_ES_API_KEY:
            kwargs["headers"] = {"Authorization": f"ApiKey {settings.CLS_ES_API_KEY}"}
        elif settings.CLS_ES_USERNAME:
            kwargs["auth"] = (settings.CLS_ES_USERNAME, settings.CLS_ES_PASSWORD)
        return kwargs

    def _probe(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/_cluster/health", timeout=self.timeout,
                                **self._request_kwargs())
            if resp.status_code != 200:
                logger.warning("ES 探活异常: HTTP %s", resp.status_code)
                return False
            return resp.json().get("status") in _HEALTHY_STATES
        except Exception as e:
            logger.warning("ES 探活失败(%s): %s", self.base_url, e)
            return False

    # —— 服务名归一化(经 service_map,让口头名/监控名也能落到真实索引) ——

    def _index_expressions(self, service_name: str) -> List[str]:
        """服务名 → ES 索引表达式列表(归一化 + 展开候选)。

        别名值已是索引模式(含 *)时原样使用,否则套用 CLS_INDEX_PATTERN 补齐 ——
        兼容别名表里写 "order-service"(索引前缀)或 "order-service-logs-*"(完整模式)两种写法。
        """
        exprs: List[str] = []
        for name in resolve_service(service_name, "logs"):
            expr = name if "*" in name else settings.CLS_INDEX_PATTERN.format(service=name)
            if expr not in exprs:
                exprs.append(expr)
        return exprs

    def _resolve_index_target(self, topic_id: str) -> str:
        """topic_id → ES 索引表达式(逗号分隔,ES 原生支持一次查多个索引)。

        topic_id 通常已是 search_topics 返回的索引名,此时原样使用;仅当它命中了
        别名表(说明传进来的是口头名/监控名,而非索引名)才展开成索引模式 ——
        否则会把合法索引名二次包装成 "xxx-logs-*" 而查不到。
        """
        if resolve_service(topic_id, "logs") == [topic_id]:
            return topic_id
        return ",".join(self._index_expressions(topic_id))

    # —— 第一层:服务名 → 日志主题(索引) ——

    def search_topics(self, service_name: str, fuzzy: bool = True) -> Dict[str, Any]:
        query = {"service_name": service_name, "fuzzy": fuzzy}
        try:
            indices = self._list_indices()
        except Exception as e:
            logger.warning("ES 索引列举失败: %s", e)
            return {"total": 0, "topics": [], "query": query,
                    "error": f"ES 查询失败: {e}",
                    "message": "ES 索引列举失败,未找到日志主题"}

        # 归一化 + 展开候选后取各索引模式的前缀(去掉 "*" 及之后)
        prefixes = [expr.split("*")[0] for expr in self._index_expressions(service_name)]
        target = service_name.lower()
        matched = []
        for name in indices:
            low = name.lower()
            hit = (any(p in name for p in prefixes) or target in low) if fuzzy \
                else any(name.startswith(p) for p in prefixes)
            if hit:
                matched.append({"topic_id": name, "topic_name": name,
                                "service_name": service_name,
                                "description": f"Elasticsearch 索引(模式 {settings.CLS_INDEX_PATTERN})"})
        # 倒序: 索引名按天滚动(order-service-logs-2026.09.25),字典序即时间序,
        # 最新的排最前 —— 调用方默认取 topics[0] 时拿到的才是当天的日志
        matched.sort(key=lambda t: t["topic_id"], reverse=True)
        return {"total": len(matched), "topics": matched, "query": query,
                "message": (f"找到 {len(matched)} 个日志主题" if matched
                            else f"未找到服务 '{service_name}' 的日志主题")}

    def _list_indices(self) -> List[str]:
        """列出可查询索引(排除 . 开头的系统索引)。"""
        resp = requests.get(f"{self.base_url}/_cat/indices",
                            params={"format": "json", "h": "index"}, timeout=self.timeout,
                            **self._request_kwargs())
        resp.raise_for_status()
        return sorted({row["index"] for row in resp.json()
                       if row.get("index") and not row["index"].startswith(".")})

    # —— 第二层:topic_id(索引) → 日志 ——

    def search_logs(self, topic_id: str, start_time: int, end_time: int,
                    query: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        must: List[Dict[str, Any]] = []
        window = {"gte": _to_iso_utc(start_time), "lte": _to_iso_utc(end_time)}
        if window["gte"] and window["lte"]:
            must.append({"range": {self.ts_field: window}})
        if query:
            # mock 侧 query 形如 "level:ERROR",正好是 ES query_string 的原生语法
            must.append({"query_string": {"query": query}})

        base = {"topic_id": topic_id, "start_time": start_time, "end_time": end_time,
                "query": query, "limit": limit}
        index_target = self._resolve_index_target(topic_id)
        logger.debug("ES 索引表达式: %s → %s", topic_id, index_target)
        try:
            resp = requests.post(
                f"{self.base_url}/{index_target}/_search",
                json={"query": {"bool": {"must": must}},
                      "size": limit,
                      "sort": [{self.ts_field: {"order": "desc"}}]},
                timeout=self.timeout,
                **self._request_kwargs(),
            )
            resp.raise_for_status()
            body = resp.json()
        except Exception as e:
            logger.warning("ES 日志查询失败(topic=%s): %s", topic_id, e)
            return {**base, "total": 0, "logs": [], "took_ms": 0,
                    "error": f"ES 查询失败: {e}", "message": "ES 日志查询失败"}

        hits = body.get("hits", {})
        raw_total = hits.get("total")
        # ES7+ 返回 {"value": n, "relation": ...},ES6 直接返回整数
        total = raw_total.get("value", 0) if isinstance(raw_total, dict) else (raw_total or 0)
        logs = [self._to_log(h.get("_source", {})) for h in hits.get("hits", [])]
        return {**base, "total": total, "logs": logs,
                "took_ms": body.get("took", 0),
                "message": f"成功查询 {len(logs)} 条日志"}

    def _to_log(self, src: Dict[str, Any]) -> Dict[str, Any]:
        """把一条 ES 文档按配置字段映射成 {timestamp, level, message}。"""
        level = src.get(self.level_field) or src.get("log.level") or src.get("severity") or "INFO"
        message = src.get(self.msg_field) or src.get("msg") or src.get("log") or ""
        return {"timestamp": self._format_ts(src.get(self.ts_field)),
                "level": str(level).upper(),
                "message": str(message)}

    @staticmethod
    def _format_ts(raw: Any) -> str:
        """时间字段归一化成 "YYYY-MM-DD HH:MM:SS"(与 mock 输出同格式)。

        ES 存的多是 UTC,这里统一转成本地时区再打印 —— 否则排障时看到的时间
        比"现在"早 8 小时,会被误判成数据过期。
        """
        if isinstance(raw, (int, float)):
            # 数值:ES 默认 epoch_millis;超过 1e11 视为毫秒,否则按秒兜底
            secs = raw / 1000.0 if raw > 1e11 else float(raw)
            return datetime.fromtimestamp(secs).strftime("%Y-%m-%d %H:%M:%S")
        text = str(raw or "")
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                dt = dt.astimezone()
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            return text