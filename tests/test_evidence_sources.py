"""证据源可用性可见化测试:工具→证据源映射、缺席告警、报告标注。"""

import json
from types import SimpleNamespace

from src.agent.aiops.evidence_sources import (
    availability_warning,
    format_availability_note,
    missing_source_labels,
    source_availability,
)
from src.agent.aiops.strategies.dynamic_classification import _local_respond

ALL_TOOLS = [
    "query_cpu_metrics", "query_memory_metrics",
    "search_log", "search_topic_by_service_name", "get_current_timestamp",
    "search_changes", "get_change_detail",
    "search_knowledge_base", "list_knowledge_bases", "get_document_info",
    "check_website", "check_ports", "check_service_health", "check_api_endpoint",
]


def _tools(*names):
    return [SimpleNamespace(name=n) for n in names]


def test_all_sources_available():
    snap = source_availability(_tools(*ALL_TOOLS))
    assert all(it["available"] for it in snap)
    assert missing_source_labels(_tools(*ALL_TOOLS)) == []
    assert availability_warning(_tools(*ALL_TOOLS)) == ""


def test_missing_sources_detected():
    """只有指标工具时,日志/变更/知识库/探测应判为缺席。"""
    snap = source_availability(_tools("query_cpu_metrics", "query_memory_metrics"))
    by_source = {it["source"]: it for it in snap}
    assert by_source["metrics"]["available"] is True
    for key in ("logs", "changes", "knowledge", "probe"):
        assert by_source[key]["available"] is False
    missing = missing_source_labels(_tools("query_cpu_metrics"))
    assert any("日志" in m for m in missing)
    assert any("变更" in m for m in missing)


def test_availability_warning_lists_missing():
    warn = availability_warning(_tools("query_cpu_metrics"))
    assert "证据源缺席提醒" in warn
    assert "日志(Elasticsearch)" in warn
    assert "不得" in warn


def test_format_note_marks_available_and_absent():
    snap = source_availability(_tools("query_cpu_metrics"))
    note = format_availability_note(snap)
    assert note.startswith("## 证据来源")
    assert "指标(Prometheus)：可用" in note
    assert "日志(Elasticsearch)：缺席" in note
    assert format_availability_note(None) == ""


def test_local_respond_annotates_evidence_sources():
    """报告应含证据来源小节,并在 diagnostic_meta 里记录缺席源。"""
    availability = source_availability(_tools("query_cpu_metrics", "search_log"))
    state = {
        "input": "CPU 高",
        "plan": [],
        "past_steps": [("检查 CPU", "cpu 高")],
        "response": "",
        "evidence_source_availability": availability,
    }
    space = [{"id": "h_infra", "name": "基础设施/资源瓶颈", "probability": 0.8}]
    report = _local_respond(state, space)["response"]
    assert "## 证据来源" in report
    assert "变更/发布事件：缺席" in report
    meta_line = next(line for line in report.splitlines() if "diagnostic_meta" in line)
    meta = json.loads(meta_line.split("diagnostic_meta:")[1].split("-->")[0].strip())
    assert "变更/发布事件" in meta["evidence_sources_missing"]


def test_local_respond_without_availability_has_no_section():
    """无可用性快照(旧状态)时不应凭空渲染证据来源小节。"""
    state = {"input": "CPU 高", "plan": [], "past_steps": [], "response": ""}
    report = _local_respond(state, [])["response"]
    assert "## 证据来源" not in report