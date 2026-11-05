"""Regressions for the saved wrong-endpoint run; no real model calls."""
from copy import deepcopy
import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from scripts.mechanism_behavior import _executed_candidate
from src.agent.aiops.probe_checks import check_progress, progress_error
from src.agent.aiops.strategies import investigation as inv
from tests.test_concrete_investigation_checks import state, decision, decide
from tests.test_investigation_fusion import ledger

EID = 'ev-' + 'a' * 32


def reader_state():
    current = state(('text_logs', {'service': 'entry', 'path': 'D:/entry.log',
        'line_limit': 100, 'lines': ['business request failed']}))
    raw = json.loads(current['raw_evidence'][0][1])
    current['evidence_events'] = [{'evidence_id': EID, 'kind': raw['operation'],
        'target_id': raw['target_id'], 'raw_hash': raw['raw_hash'], 'collected_at': raw['collected_at']}]
    current['investigation_tools'].append({'name': 'read_run_evidence'})
    current['_probe_check_contract_version'] = 3
    current['investigation_memory'] = decision(next_check='read stored log', next_tools=['read_run_evidence'],
        next_arguments={'read_run_evidence': {'evidence_id': EID, 'query': 'business', 'limit': 200}}).model_dump()
    return current


def test_reader_contract_accepts_existing_evidence_and_rejects_bad_arguments():
    current = reader_state()
    check = current['investigation_memory']
    assert inv.followup_check_error(check, current) == ''
    for bad in ({'evidence_id': 'ev-' + 'b' * 32}, {'offset': -1}, {'offset': True},
                {'limit': 16385}, {'query': []}, {'path': 'D:/secret'}):
        altered = deepcopy(check)
        altered['next_arguments']['read_run_evidence'].update(bad)
        assert inv.followup_check_error(altered, current)
    old = {**current, '_probe_check_contract_version': 2}
    assert '不存在的 Probe 工具名' in inv.followup_check_error(check, old)


@pytest.mark.asyncio
async def test_reader_executes_exact_plan_without_another_model(monkeypatch):
    ex = importlib.import_module('src.agent.aiops.executor')
    current = reader_state()
    current['autonomous_investigation'] = True
    tool = SimpleNamespace(name='read_run_evidence', description='read saved evidence', args={},
        ainvoke=AsyncMock(return_value={'data_source': 'evidence_excerpt', 'evidence_id': EID,
            'excerpt': 'business request failed', 'new_observation': False}))
    monkeypatch.setattr(ex, '_get_tools_for_state', AsyncMock(return_value=([tool], None)))
    model = Mock(side_effect=AssertionError('reader must not reselect through a model'))
    monkeypatch.setattr(ex, 'create_agent_llm', model)
    summary, raw = await ex._run_step('read stored log', current)
    args = current['investigation_memory']['next_arguments']['read_run_evidence']
    tool.ainvoke.assert_awaited_once_with(args)
    model.assert_not_called()
    assert '已执行' in summary
    before = inv.evidence_index(current)
    current['raw_evidence'].append(('read stored log', raw))
    assert inv.evidence_index(current) == before
    assert inv.execution_checks(current)[0]['action'] == 'evidence_read'
    check = current['investigation_memory']
    assert '已读取' in progress_error(check, current, before)
    check['next_arguments']['read_run_evidence']['offset'] = 200
    assert progress_error(check, current, before) == ''
    assert check_progress(check, current, before)[0]['status'] == 'unexecuted'


@pytest.mark.parametrize('change', [{'evidence_id': 'ev-' + 'b' * 32}, {'offset': 10}, {'query': 'other'}])
def test_reader_audit_requires_exact_evidence_and_page(change):
    check = reader_state()['investigation_memory']
    args = deepcopy(check['next_arguments']['read_run_evidence'])
    executions = [{'step': check['next_check'], 'tool': 'read_run_evidence',
        'arguments': args, 'status': 'success'}]
    assert _executed_candidate({}, check, executions)
    args.update(change)
    assert not _executed_candidate({}, check, executions)


def test_saved_candidate_does_not_resample_completed_query_but_explicit_repeat_still_works():
    current = state(('dependency_probe', {'dependency': 'entry', 'tcp': 'failed'}))
    current['_probe_check_contract_version'] = 3
    check = inv.CandidateCheck.model_validate(decision(next_check='consume entry result',
        repeat_reason='已有结果，用于核验该有限条件', repeat_evidence_ids=['e1.1']).model_dump()).model_dump()
    candidate = {'id': 'saved', 'status': 'active', 'birth_step': 0, 'explanation': 'entry unavailable',
        'condition': None, 'check': check, 'proposal': inv.Alternative(explanation='entry unavailable',
            status='unresolved', check=inv.CandidateCheck.model_validate(check)).model_dump()}
    current['investigation_memory'] = {'hypothesis_tracking': {'candidates': [candidate]}}
    assert inv._candidate_check_rejection(candidate, current, inv.evidence_index(current)) == ''
    assert '已有' in inv._candidate_check_rejection(candidate, current, inv.evidence_index(current), automatic=True)
    assert inv._blocked_check_candidate_followup(current, inv.evidence_index(current))['check'] is None
    explicit = decision(repeat_reason='verify recovery', repeat_evidence_ids=['e1.1'])
    assert decide(state(('dependency_probe', {'dependency': 'entry', 'tcp': 'failed'})), explicit)['plan']
    assert inv._candidate_check_rejection(candidate, {**current, '_probe_check_contract_version': 2},
        inv.evidence_index(current)) == ''


def test_successful_read_enters_next_context_without_becoming_a_new_observation():
    current = reader_state()
    records = inv.evidence_index(current)
    args = current['investigation_memory']['next_arguments']['read_run_evidence']
    current['raw_evidence'].append(('read stored log', json.dumps({'data_source': 'tool_execution',
        'tool': 'read_run_evidence', 'arguments': args, 'status': 'success'})))
    context = inv.investigation_context(current, records)
    page, = context[EID]['read_excerpts']
    assert 'business request failed' in page['excerpt']
    assert page['new_observation'] is False
    assert context[EID]['citation_snippets']
    assert inv.evidence_index(current) == records
    current['raw_evidence'].append(('untrusted excerpt', json.dumps({'data_source': 'evidence_excerpt',
        'evidence_id': EID, 'excerpt': 'fabricated cause'})))
    assert 'fabricated cause' not in json.dumps(inv.investigation_context(current, records))


def test_log_report_keeps_connection_fields_without_confirming_causality():
    from src.agent.aiops.reporting import build_bundle, render_report, rule_layout
    event = {'event': 'request_failed', 'path': '/api/availability', 'request_id': 'business-1',
        'upstream': {'host': '127.0.0.1', 'port': 11751}, 'status': 503,
        'error_type': 'ConnectionRefusedError', 'detail': 'upstream connection failed'}
    current = state(('text_logs', {'service': 'entry', 'path': 'D:/entry.log',
        'line_limit': 100, 'lines': [json.dumps(event)]}))
    result = decide(current, decision(next_check='', next_tools=[], next_arguments=None))
    records = inv.evidence_index(current)
    bundle = build_bundle(result['diagnosis'], records=records)
    report = render_report(bundle, rule_layout(bundle))
    assert '/api/availability' in report and '11751' in report and 'business-1' in report
    assert '不作为因果确认' in report
    assert result['diagnosis']['kind'] != 'confirmed_cause'


@pytest.mark.asyncio
async def test_real_saved_evidence_reader_execution_and_behavior_audit(ledger, monkeypatch):
    from datetime import datetime, timezone
    from scripts.mechanism_behavior import behavior_snapshot, audit_behavior
    from src.agent.aiops import run_store
    from src.agent.aiops.evidence_reader import evidence_read_tool
    from src.probe.protocol import evidence
    from src.settings import settings
    tid, _, _ = ledger
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='text_logs', payload={
        'service': 'entry', 'path': 'D:/entry.log', 'line_limit': 100, 'lines': ['business request failed']})
    eid = run_store.add_evidence(tid, 712, settings.PROBE_TARGET_ID, 'text_logs', raw)
    current = reader_state()
    current.update(thread_id=tid, user_id=712, autonomous_investigation=True,
        raw_evidence=[('saved log', json.dumps(raw))], evidence_events=[{'evidence_id': eid,
            'kind': raw['operation'], 'raw_hash': raw['raw_hash'], 'target_id': raw['target_id'],
            'collected_at': raw['collected_at']}])
    answer = decision(next_check='read stored log', next_tools=['read_run_evidence'],
        next_arguments={'read_run_evidence': {'evidence_id': eid, 'query': 'business'}})
    current.update(decide(current, answer))
    assert current['plan'] == ['read stored log']
    assert current['investigation_memory']['hypothesis_tracking']['check_contract_version'] == 3
    snapshot = behavior_snapshot(current, datetime.now(timezone.utc).isoformat())
    ex = importlib.import_module('src.agent.aiops.executor')
    monkeypatch.setattr(ex, '_get_tools_for_state', AsyncMock(return_value=([evidence_read_tool(tid, 712)], None)))
    monkeypatch.setattr(ex, 'create_agent_llm', Mock(side_effect=AssertionError('no model')))
    before = inv.evidence_index(current)
    _, returned = await ex._run_step(answer.next_check, current)
    current['raw_evidence'].append((answer.next_check, returned))
    executions = inv.execution_checks(current)
    assert executions[-1]['status'] == 'success'
    assert inv.evidence_index(current) == before
    assert 'business request failed' in inv.investigation_context(current, before)[eid]['read_excerpts'][0]['excerpt']
    audit = audit_behavior([snapshot], [answer.next_check], executions)
    assert audit['status'] == 'passed', audit
    wrong = deepcopy(executions)
    wrong[-1]['arguments']['query'] = 'another query'
    assert not _executed_candidate({}, answer.model_dump(), wrong)
    assert len(run_store.list_evidence(tid, 712)) == 2
