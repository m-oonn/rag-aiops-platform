"""Candidate handoff and evidence-driven log repeats; never call a real model."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import AsyncMock

import pytest

from scripts.mechanism_behavior import audit_behavior, behavior_snapshot
from src.agent.aiops.probe_checks import progress_error
from src.agent.aiops.strategies import investigation as inv
from src.probe.protocol import evidence
from src.settings import settings
from tests.test_concrete_investigation_checks import state, decision, decide


def log_check(**overrides):
    return decision(**{'hypothesis': '停止请求的发起者未知', 'next_check': 'inspect exit log',
        'next_tools': ['probe_text_log'],
        'next_arguments': {'probe_text_log': {'service': 'entry', 'path': 'D:/entry.log', 'lines': 100}},
        'discriminating_question': '是否出现新的退出或启动记录？',
        'expected_observation': '新记录可能解释生命周期变化', **overrides})


def log_state(*extra):
    values = [('text_logs', {'service': 'entry', 'path': 'D:/entry.log', 'line_limit': 100,
                            'lines': ['shutdown_requested; initiator=unknown']}), *extra]
    current = state(*values)
    current['investigation_tools'].append({'name': 'probe_port_snapshot'})
    start = datetime.now(timezone.utc) - timedelta(seconds=20)
    for index, (name, raw) in enumerate(current['raw_evidence']):
        value = json.loads(raw)
        value['collected_at'] = (start + timedelta(seconds=index)).isoformat()
        current['raw_evidence'][index] = (name, json.dumps(value))
    return current


def test_handoff_exposes_missing_condition_and_preserves_causal_unknown():
    answer = decision(next_check='', next_tools=[], next_arguments=None, alternatives=[
        inv.Alternative(explanation='进程不存在', status='unresolved', claim_type='observed_condition'),
        inv.Alternative(explanation='有人停止了服务', status='excluded', limitation='发起者未知')])
    current = log_state()
    result = decide(current, answer)
    memory = result['investigation_memory']
    before = deepcopy(memory)
    projected = inv._decision_memory_context(memory, current, inv.evidence_index(current))
    candidates = projected['hypothesis_tracking']['candidates']
    finite = next(c for c in candidates if c.get('source_explanation') == '进程不存在')
    feedback = finite['decision_feedback']
    assert feedback['condition_status'] == 'missing'
    assert 'condition' in feedback['required_update']
    cause = next(c for c in candidates if c.get('source_explanation') == '有人停止了服务')
    assert cause['decision_feedback']['claim_status'] == 'unresolved'
    assert cause['decision_feedback']['proposed_status'] == 'excluded'
    assert cause['decision_feedback']['condition_status'] == 'not_expressible_or_unspecified'
    assert '因果' in cause['decision_feedback']['limitation']
    assert memory == before
    assert not result['plan'] and result['diagnosis']['kind'] != 'confirmed_cause'


@pytest.mark.asyncio
async def test_existing_request_gets_current_predicate_verdict_separate_from_causal_claim(monkeypatch):
    current = state()
    current['investigation_tools'].append({'name': 'probe_port_snapshot'})
    answer = decision(hypothesis='进程可能运行但未监听', hypothesis_condition=inv.ObservationCondition(
        operation='ports', object_name='9000', field='listening', expected=False),
        next_check='inspect listener', next_tools=['probe_port_snapshot'],
        next_arguments={'probe_port_snapshot': {'local_port': 9000, 'listening_only': True}})
    current.update(decide(current, answer))
    before = deepcopy(current['investigation_memory'])
    current['raw_evidence'].append(('inspect listener', json.dumps(evidence(
        target_id=settings.PROBE_TARGET_ID, operation='ports', payload={'local_port': 9000,
            'listening_only': True, 'ports': [{'status': 'LISTEN', 'local': {'port': 9000}}]}))))
    async def model(llm, schema, prompt, inputs):
        projected = json.loads(inputs['memory'])
        candidate, = projected['hypothesis_tracking']['candidates']
        assert candidate['source_explanation'] == '进程可能运行但未监听'
        feedback = candidate['decision_feedback']
        assert feedback['condition_status'] == 'excluded'
        assert feedback['evidence_ids'] and feedback['claim_status'] == 'unresolved'
        assert '因果' in feedback['limitation']
        assert candidate['check_rejection']
        return decision(hypothesis='更深原因未知', next_check='', next_tools=[], next_arguments=None)
    invoke = AsyncMock(side_effect=model)
    monkeypatch.setattr(inv, 'create_agent_llm', lambda **kwargs: object())
    monkeypatch.setattr(inv, 'ainvoke_structured', invoke)
    result = await inv.InvestigationStrategy().decide(current)
    assert invoke.await_count == 1 and not result['plan']
    assert current['investigation_memory'] == before


@pytest.mark.parametrize('kind,allowed', [
    ('none', False), ('other_service', False), ('older', False), ('new_same_service', True),
    ('same_content', False), ('truncated', False), ('error', False), ('invented', False),
    ('not_applicable', False), ('same_path_spelling', False)])
def test_same_log_repeat_requires_new_relevant_evidence(kind, allowed):
    current = log_state()
    if kind != 'none':
        service = 'outside' if kind == 'other_service' else 'entry'
        raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='processes', payload={
            'service': service, 'matched_count': 0, 'processes': []})
        if kind == 'not_applicable':
            raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='services', payload={
                'service': service, 'state': 'not_applicable'})
        if kind == 'same_path_spelling':
            body = json.loads(current['raw_evidence'][0][1])['payload']
            raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='text_logs',
                payload={**body, 'path': 'd:\\ENTRY.log'})
        when = datetime.fromisoformat(json.loads(current['raw_evidence'][0][1])['collected_at'])
        raw['collected_at'] = (when + timedelta(seconds=-1 if kind == 'older' else 1)).isoformat()
        if kind == 'truncated': raw['truncated'] = True
        if kind == 'error': raw['payload']['error'] = 'unavailable'
        if kind == 'same_content':
            old = deepcopy(raw)
            old['collected_at'] = (when - timedelta(seconds=1)).isoformat()
            current['raw_evidence'].append(('old process', json.dumps(old)))
        current['raw_evidence'].append(('new process', json.dumps(raw)))
    records = inv.evidence_index(current)
    ids = list(records)
    if kind == 'invented': ids.append('invented')
    check = log_check(repeat_reason='检查是否出现启动记录', repeat_evidence_ids=ids)
    error = progress_error(check.model_dump(), current, records)
    assert bool(error) is not allowed
    if not allowed and kind != 'invented':
        assert ('重复已有查询' if kind == 'same_path_spelling' else '新证据') in error


@pytest.mark.parametrize('event,target_matches,allowed', [
    ({'request_id': 'req-1', 'status': 503, 'fresh': True}, True, True),
    ({'request_id': 'req-1', 'status': 200, 'fresh': True}, True, False),
    ({'status': 503, 'fresh': True}, True, False),
    ({'request_id': 'req-1', 'status': 503, 'fresh': False}, True, False),
    ({'request_id': 'req-1', 'status': 503, 'fresh': True}, False, False),
])
def test_log_repeat_can_follow_a_new_cross_service_failure_request_log(event, target_matches, allowed):
    current = log_state()
    previous = datetime.fromisoformat(json.loads(current['raw_evidence'][0][1])['collected_at'])
    event['at'] = (previous + timedelta(seconds=1 if event.pop('fresh') else -1)).isoformat()
    log = evidence(target_id=settings.PROBE_TARGET_ID if target_matches else 'other-target',
        operation='text_logs', payload={'service': 'edge', 'path': 'D:/edge.log',
            'lines': [json.dumps(event)]})
    log['collected_at'] = (previous + timedelta(seconds=1)).isoformat()
    current['raw_evidence'].append(('edge request log', json.dumps(log)))
    records = inv.evidence_index(current)
    check = log_check(repeat_reason='重新读取 localapp 日志',
        repeat_evidence_ids=list(records))

    error = progress_error(check.model_dump(), current, records)

    assert bool(error) is not allowed


def test_cross_service_failure_log_can_trigger_repeat_when_old_service_has_no_request_id():
    current = log_state()
    previous = datetime.fromisoformat(json.loads(current['raw_evidence'][0][1])['collected_at'])
    edge_log = evidence(target_id=settings.PROBE_TARGET_ID, operation='text_logs', payload={
        'service': 'edge', 'path': 'D:/edge.log', 'lines': [json.dumps({
            'request_id': 'req-edge-1', 'status': 503,
            'at': (previous + timedelta(seconds=1)).isoformat()})]})
    edge_log['collected_at'] = (previous + timedelta(seconds=1)).isoformat()
    current['raw_evidence'].append(('edge request log', json.dumps(edge_log)))
    records = inv.evidence_index(current)

    check = log_check(repeat_reason='复核 localapp 日志',
        repeat_evidence_ids=['e1.1', list(records)[-1]])

    assert progress_error(check.model_dump(), current, records) == ''


def test_rejected_log_repeat_continues_unexecuted_check_and_then_stops_honestly():
    current = log_state()
    answer = log_check(repeat_reason='再看看', repeat_evidence_ids=['e1.1'], alternatives=[
        inv.Alternative(explanation='下游连接是否失败', status='unresolved', check=inv.CandidateCheck(
            next_check='inspect downstream', next_tools=['probe_dependency_probe'],
            next_arguments={'probe_dependency_probe': {'dependency': 'downstream'}},
            discriminating_question='是否有下游连通问题？', expected_observation='TCP result'))])
    first = decide(current, answer)
    assert first['plan'] == ['inspect downstream']
    answer.alternatives = []
    stopped = decide(current, answer)
    assert stopped['plan'] == []
    assert '新证据' in stopped['diagnosis']['stop_reason']
    assert stopped['diagnosis']['kind'] != 'confirmed_cause'
    assert '穷尽' in stopped['diagnosis']['stop_reason']


@pytest.mark.parametrize('version', [1, 2])
def test_repeat_guard_audit_uses_recorded_contract_and_detects_tampering(version):
    current = state()
    current['_probe_check_contract_version'] = version
    first = log_check()
    current.update(decide(current, first))
    snapshots = [behavior_snapshot(current, datetime.now(timezone.utc).isoformat())]
    current['raw_evidence'] = log_state()['raw_evidence']
    current['past_steps'] = [(first.next_check, 'shutdown requested')]
    second = log_check(next_check='recheck exit log', repeat_reason='再确认', repeat_evidence_ids=['e1.1'])
    current.update(decide(current, second))
    snapshots.append(behavior_snapshot(current, datetime.now(timezone.utc).isoformat()))
    assert bool(current['plan']) is (version == 1)
    executed = [first.next_check] + current['plan']
    executions = [{'step': step, 'tool': 'probe_text_log',
        'arguments': first.next_arguments['probe_text_log'], 'status': 'success'} for step in executed]
    assert audit_behavior(snapshots, executed, executions)['status'] == 'passed'
    if version == 1:
        legacy = deepcopy(snapshots)
        for row in legacy:
            row['tracking'].pop('check_contract_version', None)
            row['behavior_context'].pop('check_contract_version', None)
        assert audit_behavior(legacy, executed, executions)['status'] == 'passed'
    else:
        snapshots[-1]['tracking']['check_contract_version'] = 1
        assert audit_behavior(snapshots, executed, executions)['status'] == 'failed'


def test_repeat_guard_audit_rejects_boolean_version():
    current = state()
    current.update(decide(current, log_check()))
    snapshot = behavior_snapshot(current, datetime.now(timezone.utc).isoformat())
    snapshot['tracking']['check_contract_version'] = True
    snapshot['behavior_context']['check_contract_version'] = True
    assert audit_behavior([snapshot], [], [])['status'] == 'failed'
