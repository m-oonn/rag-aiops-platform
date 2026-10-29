"""诊断事件契约（events.py 构造函数 + graph._format_event）测试。

覆盖：
  1. 8 类事件的构造函数字段快照（契约基线）
  2. _format_event 各分支输出（plan/executor×3/replanner×3/未知节点）
  3. 关键默认值（complete 元数据缺省 []）

契约红线：字段结构与会话集中化前（2026-10-12 基线）逐字段一致。
"""

from src.agent.aiops.events import (
    investigation_summary,
    EVENT_TYPES,
    make_complete_event,
    make_draft_event,
    make_error_event,
    make_pending_review_event,
    make_plan_event,
    make_report_event,
    make_status_event,
    make_step_complete_event,
)
from src.agent.aiops.graph import AIOpsService
from src.agent.aiops.strategies.investigation import _evidence_summaries
from src.settings import settings
import pytest


@pytest.mark.parametrize('response', ['', 'final report'])
@pytest.mark.parametrize('hitl', [False, True])
def test_replanner_projects_saved_investigation_without_raw_proposals(monkeypatch, response, hitl):
    monkeypatch.setattr(settings, 'ENABLE_HITL', hitl)
    state = {'response': response, 'plan': [] if response else ['check downstream'],
        'investigation_memory': {'discriminating_question': 'is downstream reachable?',
            'expected_observation': 'TCP result',
            'observed_findings': [{'evidence_id': 'ev-1', 'summary': '入口返回503'}],
            'evidence_summaries': [{'evidence_id': 'ev-1', 'summary': 'dependency_probe downstream: TCP ok, HTTP 200'}],
            'hypothesis_tracking': {
                'leading_id': 'h1', 'config': {'hypothesis_protection': True},
                'candidates': [{'id': 'h1', 'explanation': 'candidate password=hidden-value',
                    'status': 'protected', 'evidence_ids': ['ev-1'],
                    'proposal': {'raw': 'private-proposal'}, 'seen_observations': ['internal-token']}],
                'events': [{'kind': 'hypothesis_protected', 'step': 2, 'hypothesis_id': 'h1',
                    'reason': 'still checkable', 'private': 'internal-event'}]}}}
    result = AIOpsService._format_event('replanner', state)
    summary = result['investigation']
    assert summary['next_check'] == ('' if response else 'check downstream')
    assert summary['events'][0]['kind'] == 'hypothesis_protected'
    assert summary['candidates'][0]['evidence_ids'] == ['ev-1']
    assert summary['discriminating_question'] == 'is downstream reachable?'
    assert summary['observed_findings'] == [{'evidence_id': 'ev-1', 'summary': '入口返回503'}]
    assert summary['evidence_summaries'][0]['summary'].endswith('HTTP 200')
    assert 'hidden-value' not in str(summary) and 'private-proposal' not in str(summary)
    assert 'internal-token' not in str(summary) and 'internal-event' not in str(summary)
    assert state['investigation_memory']['hypothesis_tracking']['candidates'][0]['proposal'] == {'raw': 'private-proposal'}
    assert make_complete_event('done', investigation=summary)['investigation'] == summary


def test_old_state_has_no_invented_investigation():
    assert investigation_summary({}) is None
    assert 'investigation' not in make_complete_event('old result')
    assert 'investigation' not in AIOpsService._format_event('replanner', {'plan': ['old check']})


def test_live_investigation_summary_hides_unverified_causal_candidate_text():
    claim = '下游进程崩溃导致入口服务拒绝请求'
    candidate = {'id': 'h1', 'explanation': claim, 'status': 'active',
        'proposal': {'explanation': claim, 'status': 'unresolved',
            'claim_type': 'causal_explanation', 'original_status': 'excluded',
            'condition': {'operation': 'dependency_probe', 'field': 'tcp', 'expected': 'ok'},
            'verification': 'causal_claim_unverified'}}
    state = {'plan': [f'核查：{claim}'], 'investigation_memory': {
        'blocked_reason': claim, 'discriminating_question': claim,
        'expected_observation': claim, 'hypothesis_tracking': {
            'config': {}, 'leading_id': 'h1', 'candidates': [candidate],
            'events': [{'kind': 'hypothesis_protected', 'step': 1, 'hypothesis_id': 'h1',
                'reason': claim, 'from_check': claim, 'next_check': claim}],
        }}}

    summary = investigation_summary(state)

    assert claim not in str(summary)
    assert '该因果解释尚无可验证的现场条件。' in str(summary)
    assert state['investigation_memory']['hypothesis_tracking']['candidates'][0]['explanation'] == claim
    assert state['investigation_memory']['hypothesis_tracking']['events'][0]['reason'] == claim


@pytest.mark.parametrize('verification', ['causal_claim_unverified', 'unverified'])
def test_public_diagnosis_tracking_and_sse_share_sanitized_events(verification):
    from copy import deepcopy
    from src.agent.aiops.strategies.investigation import _public_tracking

    claim = '根因已确认是进程崩溃'
    tracking = {'config': {}, 'candidates': [{
        'id': 'h1', 'explanation': claim, 'condition': {'field': 'tcp', 'expected': 'ok'},
        'check': {'next_check': f'核查{claim}', 'next_tools': ['probe_dependency_probe']},
        'proposal': {'verification': verification, 'original_status': 'excluded',
                     'claim_type': 'causal_explanation', 'condition': {'field': 'tcp'}}}],
        'events': [{'kind': 'hypothesis_protected', 'step': 1, 'hypothesis_id': 'h1',
                    'reason': claim, 'from_check': claim, 'next_check': claim}]}
    before = deepcopy(tracking)

    public = _public_tracking(tracking)
    summary = investigation_summary({'diagnosis': {'mechanisms': public}})

    assert claim not in str(public)
    assert public['events'] == summary['events']
    assert public['candidates'][0]['check']['next_tools'] == ['probe_dependency_probe']
    assert tracking == before


@pytest.mark.parametrize(('operation', 'payload', 'truncated', 'status', 'parts'), [
    ('services', {'service': 'localapp', 'state': 'not_applicable',
                  'reason': 'process application; use process observations'},
     False, 'not_applicable', ['state', 'not_applicable', 'process application']),
    ('event_logs', {'service': 'localapp', 'channels': [], 'events': [],
                    'error': 'no event channels configured'},
     False, 'not_applicable', ['not applicable', 'no event channels configured']),
    ('ports', {'local_port': 7063, 'ports': [], 'matched_count': 0,
               'error': 'AccessDenied'},
     False, 'unavailable', ['unavailable (AccessDenied)']),
    ('resources', {'cpu_percent': 12.5, 'memory': {'percent': 55.2},
                   'disks': [{'mountpoint': 'C:', 'percent': 22},
                             {'mountpoint': 'D:', 'error': 'unavailable'}]},
     False, 'partial', ['CPU 12.5%', 'memory 55.2%', '2 disk records']),
    ('processes', {'service': 'localapp', 'processes': [{'pid': 42}],
                   'matched_count': 1, 'skipped_count': 2,
                   'memory_unavailable_count': 1, 'cpu_unavailable_count': 0},
     False, 'partial', ['1 returned process records', 'matched 1', 'skipped 2',
                        'memory unavailable 1', 'CPU unavailable 0']),
    ('dependency_probe', {'dependency': 'downstream', 'tcp': 'failed',
                          'http': {'error': 'URLError'}},
     False, 'observed', ['TCP failed', 'HTTP unavailable (URLError)']),
    ('text_logs', {'service': 'localapp', 'path': 'app.log', 'lines': ['tail']},
     True, 'partial', ['1 log lines']),
])
def test_evidence_summaries_describe_coverage_and_failure_semantics(
        operation, payload, truncated, status, parts):
    value = {'target_id': settings.PROBE_TARGET_ID, 'operation': operation,
             'data_source': 'probe_target', 'collected_at': '2026-10-26T02:21:41Z',
             'payload': payload, 'truncated': truncated}
    records = {'ev-1': {'payload': __import__('json').dumps(value)}}
    item = _evidence_summaries(records, {'target_resolution': {}})[0]
    assert item['status'] == status
    assert all(part in item['summary'] for part in parts)
    if operation == 'event_logs':
        assert item['error'] == 'no event channels configured'
    if operation == 'ports':
        assert '0 matched port records' not in item['summary']


@pytest.mark.parametrize(('operation', 'payload', 'parts'), [
    ('processes', {'service': 'localapp', 'processes': [{'pid': 42}]},
     ['1 returned process records', 'matched unknown', 'skipped unknown',
      'memory unavailable unknown', 'CPU unavailable unknown']),
    ('ports', {'local_port': 7063, 'ports': [{'status': 'LISTEN'}], 'matched_count': 5},
     ['1 returned port records', 'matched 5']),
])
def test_summary_distinguishes_returned_counts_from_missing_coverage(operation, payload, parts):
    import json
    value = {'target_id': settings.PROBE_TARGET_ID, 'operation': operation,
             'data_source': 'probe_target', 'collected_at': '2026-10-26T02:21:41Z',
             'payload': payload}
    item = _evidence_summaries({'ev-legacy': {'payload': json.dumps(value)}}, {})[0]
    assert all(part in item['summary'] for part in parts), item
    if operation == 'processes':
        assert item['status'] == 'partial'


def test_evidence_summaries_keep_neutral_probe_facts_without_raw_payload():
    records = {'ev-1': {'payload': '{"target_id":"windows-local-01",'
        '"operation":"dependency_probe","data_source":"probe_target",'
        '"collected_at":"2026-10-26T02:21:41Z",'
        '"payload":{"dependency":"downstream","tcp":"ok",'
        '"http":{"status":200},"secret":"must-not-leak"},"raw_hash":"sha256:x"}',
        'provenance': {'operation': 'dependency_probe'}}}
    result = _evidence_summaries(records, {'target_resolution': {}})
    assert result[0]['summary'] == 'dependency_probe downstream: TCP ok, HTTP 200'
    assert 'secret' not in str(result)
    assert result[0]['evidence_id'] == 'ev-1'


# ═══════════════ 构造函数字段快照 ═══════════════


class TestConstructors:
    def test_plan_event(self):
        ev = make_plan_event(["a", "b", "c"])
        assert ev == {
            "type": "plan",
            "stage": "plan_created",
            "role": "planner",
            "message": "诊断计划已制定,共 3 步",
            "plan": ["a", "b", "c"],
        }

    def test_step_complete_event(self):
        ev = make_step_complete_event(2, 5, "查日志", 3)
        assert ev == {
            "type": "step_complete",
            "stage": "step_executed",
            "role": "executor",
            "message": "步骤完成 (2/5)",
            "done": 2,
            "total": 5,
            "current_step": "查日志",
            "remaining_steps": 3,
        }

    def test_status_event_base(self):
        assert make_status_event("executor", "executor", "执行步骤中") == {
            "type": "status",
            "stage": "executor",
            "role": "executor",
            "message": "执行步骤中",
        }

    def test_status_event_with_extra(self):
        ev = make_status_event("replanner", "replanner", "准备生成报告", remaining_steps=2)
        assert ev["remaining_steps"] == 2
        assert set(ev.keys()) == {"type", "stage", "role", "message", "remaining_steps"}

    def test_draft_event(self):
        assert make_draft_event("草稿") == {
            "type": "draft",
            "stage": "draft_ready",
            "role": "replanner",
            "message": "报告草稿已生成",
            "report": "草稿",
        }

    def test_report_event(self):
        ev = make_report_event("报告")
        assert ev["type"] == "report" and ev["stage"] == "final_report" and ev["report"] == "报告"

    def test_pending_review_event(self):
        ev = make_pending_review_event("t-1", "草稿")
        assert ev == {
            "type": "pending_review",
            "stage": "pending_review",
            "thread_id": "t-1",
            "message": "报告草稿已生成, 等待人工审批",
            "draft": "草稿",
        }

    def test_complete_event_defaults(self):
        ev = make_complete_event("结论")
        assert ev["type"] == "complete" and ev["response"] == "结论"
        assert ev["hypothesis_space"] == []
        assert ev["sidebar_branches"] == []
        assert ev["belief_history"] == []
        assert ev["evidence_source_availability"] == []

    def test_complete_event_with_payload(self):
        ev = make_complete_event(
            "结论", hypothesis_space=[{"id": "h1"}], belief_history=[{"step": 1}]
        )
        assert ev["hypothesis_space"] == [{"id": "h1"}]
        assert ev["belief_history"] == [{"step": 1}]
        assert ev["sidebar_branches"] == []

    def test_error_event_stages(self):
        assert make_error_event("boom") == {"type": "error", "stage": "error", "message": "boom"}
        assert make_error_event("bad", stage="validation_error")["stage"] == "validation_error"
        assert make_error_event("gone", stage="not_found")["stage"] == "not_found"

    def test_event_types_constant_covers_all(self):
        assert set(EVENT_TYPES) == {
            "plan",
            "step_complete",
            "status",
            "draft",
            "report",
            "pending_review",
            "complete",
            "error",
            'evidence',
        }


# ═══════════════ _format_event 各分支 ═══════════════


class TestFormatEvent:
    def test_planner_branch(self):
        ev = AIOpsService._format_event("planner", {"plan": ["s1", "s2"]})
        assert ev["type"] == "plan" and ev["message"] == "诊断计划已制定,共 2 步"

    def test_executor_step_complete_with_progress(self):
        ev = AIOpsService._format_event(
            "executor",
            {
                "past_steps": [("步1", "结果")],
                "plan": ["剩1"],
                "_step_progress": {"done": 4, "total": 6},
            },
        )
        assert ev == {
            "type": "step_complete",
            "stage": "step_executed",
            "role": "executor",
            "message": "步骤完成 (4/6)",
            "done": 4,
            "total": 6,
            "current_step": "步1",
            "remaining_steps": 1,
        }

    def test_executor_step_complete_without_progress(self):
        ev = AIOpsService._format_event(
            "executor", {"past_steps": [("a", "r")], "plan": ["x", "y"]}
        )
        assert ev["done"] == 1 and ev["total"] == 3

    def test_executor_status_when_no_steps(self):
        ev = AIOpsService._format_event("executor", {})
        assert ev["type"] == "status" and ev["stage"] == "executor"

    def test_replanner_report_and_draft(self, monkeypatch):
        monkeypatch.setattr(settings, "ENABLE_HITL", False)
        ev = AIOpsService._format_event("replanner", {"response": "R"})
        assert ev["type"] == "report" and ev["report"] == "R"

        monkeypatch.setattr(settings, "ENABLE_HITL", True)
        ev = AIOpsService._format_event("replanner", {"response": "R"})
        assert ev["type"] == "draft" and ev["report"] == "R"

    def test_replanner_status_with_sidebar_note(self):
        ev = AIOpsService._format_event(
            "replanner",
            {
                "plan": ["x"],
                "sidebar_branches": [{"status": "running"}, {"status": "done"}],
            },
        )
        assert ev["type"] == "status"
        assert "旁开支线 1 条" in ev["message"]
        assert ev["remaining_steps"] == 1

    def test_unknown_node_status(self):
        ev = AIOpsService._format_event("weird", {})
        assert ev == {
            "type": "status",
            "stage": "weird",
            "role": "weird",
            "message": "weird 执行中",
        }
