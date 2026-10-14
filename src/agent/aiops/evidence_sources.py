"""证据源可用性可见化:把 MCP 工具加载结果确定性地映射为"证据源可用/缺席"。

背景: 某个 MCP 服务(如变更 8106、日志 8103)没起来时,executor 只是少几个工具,
诊断链路照常跑,报告却看不出"这次其实缺了日志/变更证据源" —— 静默失效。
本模块把工具清单映射为证据源清单,供三处消费:
  - executor 系统提示: 显式告知 LLM 本次缺哪些证据源,禁止用通用经验顶替真实观测;
  - 诊断报告: 标注本次可用/缺席的证据源,让结论的可信边界可见;
  - complete 事件: 随状态回传,供前端/审计核对。

判定完全基于"工具名是否存在",不解析工具返回内容,故确定、可复现。
"""

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


def source_availability(tools: Iterable[Any] | None) -> List[dict]:
    """把工具清单映射成证据源可用性快照(可序列化,供 state/事件/报告消费)。"""
    names = _tool_names(tools)
    snapshot: List[dict] = []
    for key, label, tool_names in EVIDENCE_SOURCES:
        present = [n for n in tool_names if n in names]
        snapshot.append({
            "source": key,
            "label": label,
            "available": bool(present),
            "tools": present,
        })
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
        f"- {item.get('label', item.get('source', '?'))}：{'可用' if item.get('available') else '缺席'}"
        for item in availability
    ]
    return "## 证据来源\n" + "\n".join(lines) + "\n\n"