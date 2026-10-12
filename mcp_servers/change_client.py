"""Elasticsearch 变更/发布事件后端(change_server 真实链路唯一实现)。

与日志侧(cls_client)同源同纪律:
  - 复用同一 ES 集群(settings.CHANGE_ES_URL 留空时回退 CLS_ES_URL);
  - 探活 / 鉴权(ApiKey 优先 Basic Auth) / TLS / 时间转换逻辑一致;
  - 不设 mock 分支: 后端不可达时如实返回"数据不可用"声明,绝不编造变更记录。

语义映射(变更事件 → ES 概念):
  - 变更事件集中存放于单个索引模式 settings.CHANGE_INDEX_PATTERN(默认
    "change-events-*"),用 service 字段区分服务 —— 与日志"每服务一索引"不同,
    变更事件天然是全局流水(一次发布可能同时影响多个服务)。
  - 服务名先经 service_map.resolve_service(name, "changes") 归一化并展开候选,
    解决"用户说订单服务、变更系统记 order-service"的对不齐问题。
  - 字段用 settings.CHANGE_*_FIELD 映射到语义字段。

设计取舍:
  - 只用 requests 直连 ES REST API,不引入 elasticsearch SDK(少一个重依赖)。
  - 变更事件是根因鉴别的**独立证据源**(与指标/日志正交): 造假同样会污染结论,
    故与日志侧一样只回真实数据或"不可用"声明。

由 change_server.py 在独立进程中 import 使用。
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from mcp_servers.service_map import resolve_service
from src.settings import settings

logger = logging.getLogger("Change_Client")

# 集群健康为这三种状态时都认为可查询(yellow=副本未分配,但主分片可读)
_HEALTHY_STATES = ("green", "yellow", "red")


def use_es_backend() -> bool:
    """配了变更事件 ES 地址时才启用真实后端(留空则回退 CLS_ES_URL)。"""
    return bool(settings.RESOLVED_CHANGE_ES_URL.strip())


def _to_iso_utc(ms: Optional[int]) -> str:
    """毫秒时间戳 → ES range 查询用的 ISO8601(UTC)。"""
    if not ms:
        return ""
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class ChangeClient:
    """Elasticsearch 变更事件客户端(单例由 change_server 持有)。"""

    def __init__(self) -> None:
        self.base_url = settings.RESOLVED_CHANGE_ES_URL.rstrip("/")
        self.timeout = settings.CHANGE_TIMEOUT_SECONDS
        self.index_pattern = settings.CHANGE_INDEX_PATTERN
        self.ts_field = settings.CHANGE_TIMESTAMP_FIELD
        self.service_field = settings.CHANGE_SERVICE_FIELD
        self.id_field = settings.CHANGE_ID_FIELD
        self.type_field = settings.CHANGE_TYPE_FIELD
        self.operator_field = settings.CHANGE_OPERATOR_FIELD
        self.version_field = settings.CHANGE_VERSION_FIELD
        self.desc_field = settings.CHANGE_DESCRIPTION_FIELD
        self.status_field = settings.CHANGE_STATUS_FIELD
        self.available = self._probe()

    def _request_kwargs(self) -> Dict[str, Any]:
        """鉴权 / TLS 参数(未配置时不带鉴权头)。

        ES ApiKey 优先于 Basic Auth(与日志侧一致);两者都未配则匿名直连。
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

    # —— 服务名归一化(经 service_map,让口头名/监控名也能落到变更 service 字段) ——

    def _service_candidates(self, service_name: str) -> List[str]:
        return resolve_service(service_name, "changes")

    def search_changes(self, service_name: str, start_time: int, end_time: int,
                       change_type: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
        """查某服务在 [start_time, end_time] 内的变更事件(按时间倒序)。

        返回结构与日志侧对齐: 带 data_source / total / changes,查询失败返回
        data_source=unavailable + error,不伪造记录。
        """
        base = {"service_name": service_name, "start_time": start_time, "end_time": end_time,
                "change_type": change_type, "limit": limit}
        must: List[Dict[str, Any]] = []
        window = {"gte": _to_iso_utc(start_time), "lte": _to_iso_utc(end_time)}
        if window["gte"] and window["lte"]:
            must.append({"range": {self.ts_field: window}})

        candidates = self._service_candidates(service_name)
        if candidates:
            # match_phrase 在 text 与 keyword 字段上都可用(term 只对 keyword 生效),
            # 避免真实集群 mapping 未知时因字段类型不符而检索落空。
            must.append({"bool": {
                "should": [{"match_phrase": {self.service_field: c}} for c in candidates],
                "minimum_should_match": 1,
            }})
        if change_type:
            must.append({"match_phrase": {self.type_field: change_type}})

        try:
            resp = requests.post(
                f"{self.base_url}/{self.index_pattern}/_search",
                json={"query": {"bool": {"must": must}},
                      "size": limit,
                      "sort": [{self.ts_field: {"order": "desc"}}]},
                timeout=self.timeout,
                **self._request_kwargs(),
            )
            resp.raise_for_status()
            body = resp.json()
        except Exception as e:
            logger.warning("ES 变更事件查询失败(service=%s): %s", service_name, e)
            return {**base, "total": 0, "changes": [], "took_ms": 0,
                    "data_source": "unavailable",
                    "data_source_note": f"[数据来源: 真实变更数据不可用 —— 查询失败({e}); 无有效变更记录]",
                    "error": f"ES 查询失败: {e}", "message": "ES 变更事件查询失败"}

        hits = body.get("hits", {})
        raw_total = hits.get("total")
        total = raw_total.get("value", 0) if isinstance(raw_total, dict) else (raw_total or 0)
        changes = [self._to_change(h.get("_source", {}), h.get("_id"))
                   for h in hits.get("hits", [])]
        return {**base, "total": total, "changes": changes,
                "took_ms": body.get("took", 0),
                "data_source": "elasticsearch",
                "message": f"成功查询 {len(changes)} 条变更记录"}

    def get_change_detail(self, change_id: str) -> Dict[str, Any]:
        """按 change_id 取单条变更的完整详情。"""
        base = {"change_id": change_id}
        try:
            resp = requests.post(
                f"{self.base_url}/{self.index_pattern}/_search",
                json={"query": {"bool": {"should": [
                          {"match_phrase": {self.id_field: change_id}},
                          {"term": {"_id": change_id}},
                      ], "minimum_should_match": 1}},
                      "size": 1},
                timeout=self.timeout,
                **self._request_kwargs(),
            )
            resp.raise_for_status()
            body = resp.json()
        except Exception as e:
            logger.warning("ES 变更详情查询失败(change_id=%s): %s", change_id, e)
            return {**base, "found": False, "change": None,
                    "data_source": "unavailable",
                    "data_source_note": f"[数据来源: 真实变更数据不可用 —— 查询失败({e}); 无有效变更记录]",
                    "error": f"ES 查询失败: {e}", "message": "ES 变更详情查询失败"}

        hits = body.get("hits", {}).get("hits", [])
        if not hits:
            return {**base, "found": False, "change": None,
                    "data_source": "elasticsearch",
                    "message": f"未找到 change_id={change_id} 的变更记录"}
        hit = hits[0]
        return {**base, "found": True,
                "change": self._to_change(hit.get("_source", {}), hit.get("_id")),
                "data_source": "elasticsearch",
                "message": "找到变更记录"}

    def _to_change(self, src: Dict[str, Any], doc_id: Optional[str] = None) -> Dict[str, Any]:
        """把一条 ES 文档按配置字段映射成变更事件语义结构。"""
        return {
            "change_id": str(src.get(self.id_field) or doc_id or ""),
            "timestamp": self._format_ts(src.get(self.ts_field)),
            "service": str(src.get(self.service_field) or ""),
            "change_type": str(src.get(self.type_field) or ""),
            "operator": str(src.get(self.operator_field) or ""),
            "version": str(src.get(self.version_field) or ""),
            "description": str(src.get(self.desc_field) or ""),
            "status": str(src.get(self.status_field) or ""),
        }

    @staticmethod
    def _format_ts(raw: Any) -> str:
        """时间字段归一化成 "YYYY-MM-DD HH:MM:SS"(与日志侧同格式,本地时区)。

        ES 存的多是 UTC,这里统一转成本地时区再打印 —— 否则排障时看到的时间
        比"现在"早 8 小时,会被误判成数据过期。
        """
        if isinstance(raw, (int, float)):
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