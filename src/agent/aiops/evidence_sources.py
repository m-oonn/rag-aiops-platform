"""证据源可用性可见化:把 MCP 工具加载结果确定性地映射为"证据源可用/缺席"。

背景: 某个 MCP 服务(如变更 8106、日志 8103)没起来时,executor 只是少几个工具,
诊断链路照常跑,报告却看不出"这次其实缺了日志/变更证据源" —— 静默失效。
本模块把工具清单映射为证据源清单,供三处消费:
  - executor 系统提示: 显式告知 LLM 本次缺哪些证据源,禁止用通用经验顶替真实观测;
  - 诊断报告: 标注本次可用/缺席的证据源,让结论的可信边界可见;
  - complete 事件: 随状态回传,供前端/审计核对。

注册状态与实际调用结果分开；未核验不等于正常。
"""

import json
from typing import Any, Iterable, List

# (证据源 key, 展示名, 该源包含的工具名)
EVIDENCE_SOURCES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("metrics", "指标(Prometheus)", ("query_cpu_metrics", "query_memory_metrics")),
    ("logs", "日志(Elasticsearch)",
     ("search_log", "search_topic_by_service_name", "get_current_timestamp")),
    ("changes", "变更/发布事件", ("search_changes", "get_change_detail")),
    ("knowledge", "知识库/经验检索",
     ("search_knowledge_base", "list_knowledge_bases", "get_document_info")),
    ("probe", "站点/端口/接口探测",
     ("check_website", "check_ports", "check_service_health", "check_api_endpoint")),
    ("host_probe", "Windows 主机 Probe",
     ("probe_inventory", "probe_resource_snapshot", "probe_service_status", "probe_process_snapshot",
      "probe_port_snapshot", "probe_event_log", "probe_text_log", "probe_dependency_probe", "probe_list_evidence")),
)

DIAGNOSTIC_SOURCE = (
    "diagnostic", "受限现场诊断",
    ("diagnostic_query", "diagnostic_exec", "diagnostic_probe_dependency", "diagnostic_list_evidence", "diagnostic_read_evidence"),
)


def _tool_names(tools: Iterable[Any] | None) -> set:
    """从工具对象/字典里抽出工具名集合(兼容 StructuredTool 与裸 dict)。"""
    names: set = set()
    for t in (tools or []):
        name = getattr(t, "name", None)
        if not name and isinstance(t, dict):
            name = t.get("name")
        if name:
            names.add(str(name))
    return names


def source_availability(tools: Iterable[Any] | None, checks: list | None = None) -> List[dict]:
    """把工具清单映射成证据源可用性快照(可序列化,供 state/事件/报告消费)。"""
    names = _tool_names(tools)
    snapshot: List[dict] = []
    for key, label, tool_names in EVIDENCE_SOURCES:
        present = [n for n in tool_names if n in names]
        # Probe is an opt-in target capability; do not make legacy Linux runs
        # appear degraded when the Windows gateway is intentionally disabled.
        if key == "host_probe" and not present:
            try:
                from src.settings import settings
                if not settings.PROBE_ENABLED:
                    continue
            except Exception:
                continue
        snapshot.append({
            "source": key,
            "label": label,
            "available": bool(present),
            "tools": present,
            'status': 'registered' if present else 'unavailable',
            'checked_at': None,
        })
    # 兼容未启用诊断服务的旧运行：只有工具实际加载时才展示该证据源。
    present = [n for n in DIAGNOSTIC_SOURCE[2] if n in names]
    if present:
        snapshot.append({
            "source": DIAGNOSTIC_SOURCE[0],
            "label": DIAGNOSTIC_SOURCE[1],
            "available": True,
            "tools": present,
            'status': 'registered', 'checked_at': None,
        })
    for item in snapshot:
        relevant = [c for c in checks or [] if c.get('tool') in item['tools']]
        if not relevant:
            continue
        latest_by_tool = {c['tool']: c for c in relevant}
        failed = [c for c in latest_by_tool.values() if c.get('status') != 'success']
        latest = failed[-1] if failed else relevant[-1]
        reason = str(latest.get('reason', '')).lower()
        status = latest.get('status')
        item['checked_at'] = latest.get('checked_at')
        item['status'] = ('authentication_failed' if any(s in reason for s in ('401', '403', 'auth'))
            else 'permission_denied' if any(s in reason for s in ('permission', 'access_denied', 'accessdenied'))
            else 'stale' if 'expired' in reason or 'stale' in reason
            else 'offline' if 'offline' in reason or 'connection' in reason
            else 'callable' if status == 'success' else 'unavailable')
    return snapshot


def missing_source_labels(tools: Iterable[Any] | None) -> List[str]:
    """返回缺席证据源的展示名列表(按 EVIDENCE_SOURCES 顺序)。"""
    return [s["label"] for s in source_availability(tools) if not s["available"]]


def availability_warning(tools: Iterable[Any] | None) -> str:
    """生成注入 executor 系统提示的"证据源缺席"警告;全部可用时返回空串。"""
    missing = missing_source_labels(tools)
    if not missing:
        return ""
    return (
        '\n⚠️ 证据源缺席提醒：本次仅有部分证据源可用，缺席 '
        + "、".join(missing)
        + '。\n涉及这些证据源的步骤必须如实说明"该项无真实数据、无法取证"，'
        "**不得**用通用运维经验顶替真实观测、**不得**据此下确定性根因结论。"
    )


def format_availability_note(availability: List[dict] | None) -> str:
    """把可用性快照渲染成报告用的 Markdown 小节;无快照时返回空串。"""
    if not availability:
        return ""
    lines = [
        f"- {item.get('label', item.get('source', '?'))}：{('缺席' if not item.get('available') else '已注册（未核验）' if item.get('status') == 'registered' else item.get('status', '未知'))}"
        for item in availability
    ]
    return "## 证据来源\n" + "\n".join(lines) + "\n\n"


def format_knowledge_references(raw_evidence: Iterable[tuple[str, Any]] | None) -> str:
    """从原始工具返回中提取知识库来源，供报告稳定展示引用。"""
    references: list[tuple[str, str, str]] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except (TypeError, ValueError):
                # Executor may concatenate one JSON-encoded MCP result per line.
                # Parse each record independently so a later tool result cannot
                # hide traceable knowledge-base references from an earlier one.
                for line in value.splitlines():
                    if line.strip() and line != value:
                        walk(line)
                return
            if parsed != value:
                walk(parsed)
            return
        if isinstance(value, list):
            for item in value:
                walk(item)
            return
        if not isinstance(value, dict):
            return
        source = value.get("source") or value.get("filename")
        chunk_id = value.get("chunk_id") or ""
        page = value.get("page")
        if source and (chunk_id or page is not None):
            item = (str(source), str(page) if page is not None else "", str(chunk_id))
            if item not in references:
                references.append(item)
        for child in value.values():
            walk(child)

    for _, evidence in raw_evidence or []:
        walk(evidence)
    if not references:
        return ""
    lines = []
    for source, page, chunk_id in references:
        suffix = f"，第 {page} 页" if page else ""
        chunk = f"，chunk {chunk_id}" if chunk_id else ""
        lines.append(f"- {source}{suffix}{chunk}")
    return (
        "## 参考知识库\n" + "\n".join(lines)
        + "\n\n以上内容仅用于排查方向参考，现场指标、日志和变更证据优先。\n\n"
    )


def knowledge_context(raw_evidence: Iterable[tuple[str, Any]] | None) -> list[dict]:
    """Recent bounded knowledge snippets, separate from live evidence citations."""
    from src.probe.protocol import redact
    rows = []

    def walk(value):
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except ValueError:
                for line in value.splitlines():
                    if line.strip() and line != value:
                        walk(line)
                return
            if parsed != value:
                walk(parsed)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            if value.get('data_source') == 'knowledge_base':
                items = value.get('results', [value])
                if not isinstance(items, list):
                    return
                for item in items:
                    if not isinstance(item, dict) or not isinstance(item.get('content'), str):
                        continue
                    content = redact(item['content'])
                    if not content.strip():
                        continue
                    row = {'data_source': 'knowledge_base',
                        'source': str(redact(item.get('source') or item.get('filename') or 'unknown'))[:300],
                        'chunk_id': str(redact(item.get('chunk_id') or ''))[:200],
                        'page': str(item['page'])[:30] if item.get('page') is not None else None,
                        'content': content[:1200],
                        'truncated': bool(item.get('truncated')) or len(content) > 1200}
                    for key in ('kb_id', 'doc_id'):
                        identifier = item.get(key, value.get(key))
                        if type(identifier) is int:
                            row[key] = identifier
                    if isinstance(item.get('source_url'), str):
                        row['source_url'] = str(redact(item['source_url']))[:1000]
                    if row not in rows:
                        rows.append(row)
            elif value.get('type') == 'text':
                walk(value.get('text'))
            # Do not traverse arbitrary host/log payloads as knowledge results.

    for _, value in raw_evidence or []:
        walk(value)
    return rows[-6:]
