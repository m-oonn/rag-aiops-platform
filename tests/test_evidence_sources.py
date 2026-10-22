"""证据源可用性可见化测试:工具→证据源映射、缺席告警、报告标注。"""

import json
from types import SimpleNamespace

from src.agent.aiops.evidence_sources import (
    availability_warning,
    format_availability_note,
    format_knowledge_references,
    missing_source_labels,
    source_availability,
    knowledge_context,
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


def test_readiness_distinguishes_registration_failure_and_recovery():
    tools = _tools('probe_inventory', 'probe_text_log')
    def status(checks):
        return next(s for s in source_availability(tools, checks) if s['source'] == 'host_probe')
    assert status([])['status'] == 'registered'
    denied = {'tool': 'probe_text_log', 'status': 'failed', 'reason': 'PermissionError', 'checked_at': 'time1'}
    good = {'tool': 'probe_inventory', 'status': 'success', 'checked_at': 'time2'}
    assert status([denied, good])['status'] == 'permission_denied'
    recovered = {**denied, 'status': 'success', 'reason': '', 'checked_at': 'time3'}
    assert status([denied, good, recovered])['status'] == 'callable'
    assert status([denied, good, recovered])['available'] is True


def test_diagnostic_source_only_appears_when_tool_loaded():
    absent = source_availability(_tools("query_cpu_metrics"))
    assert all(item["source"] != "diagnostic" for item in absent)
    present = source_availability(_tools("diagnostic_exec"))
    diagnostic = next(item for item in present if item["source"] == "diagnostic")
    assert diagnostic["available"] is True
    assert diagnostic["tools"] == ["diagnostic_exec"]


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
    assert "指标(Prometheus)：已注册（未核验）" in note
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


def test_knowledge_references_are_rendered_from_raw_tool_output():
    raw = [("检索经验", json.dumps({
        "results": [{
            "source": "cpu-spike.md", "page": 1,
            "chunk_id": "doc_cpu_chunk_0", "content": "...",
        }]
    }, ensure_ascii=False))]
    report = format_knowledge_references(raw)
    assert "## 参考知识库" in report
    assert "cpu-spike.md" in report
    assert "doc_cpu_chunk_0" in report
    assert "现场指标、日志和变更证据优先" in report


def test_knowledge_context_only_accepts_marked_results_and_bounds_content():
    payload = {'data_source': 'knowledge_base', 'results': [
        {'source': 'runbook.md', 'chunk_id': str(i), 'page': 1,
         'content': 'password=private-value\n' + 'X' * 1400} for i in range(9)]}
    wrapped = json.dumps([{'type': 'text', 'text': json.dumps(payload)}])
    rows = knowledge_context([('search', wrapped + '\n' + json.dumps(payload))])
    assert len(rows) == 6 and rows[0]['chunk_id'] == '3'
    assert all(len(row['content']) == 1200 and row['truncated'] for row in rows)
    assert 'private-value' not in str(rows)
    assert knowledge_context([('host', json.dumps({'data_source': 'probe_target', 'payload': payload}))]) == []
    assert knowledge_context([('unmarked', json.dumps({'results': payload['results']}))]) == []
    assert knowledge_context([('empty', json.dumps({'data_source': 'knowledge_base', 'results': []}))]) == []
