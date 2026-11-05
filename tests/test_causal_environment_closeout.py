"""Offline checks for causal-evidence environment and decision audit boundaries."""
from datetime import datetime, timezone
import json

import pytest

from scripts.mechanism_behavior import audit_behavior, behavior_snapshot
from src.agent.aiops.strategies import investigation as inv
from tests.test_concrete_investigation_checks import state, decision, decide


def alternative_after_saved_review():
    current = state()
    current.update(decide(current, decision(next_check='', next_tools=[], next_arguments=None)))
    snapshots = [behavior_snapshot(current, datetime.now(timezone.utc).isoformat())]
    answer = decision(next_tools=['missing_probe'], next_arguments={})
    answer.alternatives = [inv.Alternative(explanation='入口是否可以连接', status='unresolved',
        check=inv.CandidateCheck(next_check='differentiate entry', next_tools=['probe_dependency_probe'],
            next_arguments={'probe_dependency_probe': {'dependency': 'entry'}},
            discriminating_question='入口连接失败还是内部错误？', expected_observation='TCP and HTTP outcome'))]
    current.update(decide(current, answer))
    snapshots.append(behavior_snapshot(current, datetime.now(timezone.utc).isoformat()))
    assert current['plan'] == ['differentiate entry']
    assert snapshots[-1]['tracking']['blocked_check_review']
    executions = [{'step': 'differentiate entry', 'tool': 'probe_dependency_probe',
        'arguments': {'dependency': 'entry'}, 'status': 'success'}]
    return current, snapshots, ['differentiate entry'], executions


@pytest.mark.parametrize('mutation', [None, 'plan', 'object', 'execution', 'review', 'candidate', 'missing_selection'])
def test_review_of_saved_checks_can_be_followed_by_current_alternative(mutation):
    current, snapshots, executed, executions = alternative_after_saved_review()
    if mutation == 'plan': snapshots[-1]['plan'] = ['unrelated check']
    if mutation == 'object': snapshots[-1]['next_arguments']['probe_dependency_probe']['dependency'] = 'other'
    if mutation == 'execution': executions.clear()
    if mutation == 'review': snapshots[-1]['tracking']['blocked_check_review']['kind'] = 'invented'
    if mutation == 'candidate': snapshots[-1]['tracking']['candidates'][-1]['check']['next_check'] = 'invented'
    if mutation == 'missing_selection':
        snapshots[-1]['plan'] = []
        executed.clear()
        executions.clear()
    result = audit_behavior(snapshots, executed, executions)
    assert result['status'] == ('failed' if mutation else 'passed'), result
    if mutation is None:
        assert current['investigation_memory']['blocked_reason'] == ''


@pytest.mark.asyncio
async def test_actual_model_input_explains_log_reference_is_not_a_file_path():
    from scripts.verify_competing_hypothesis_scenario import capture_decision_input
    current = state(('inventory', {'configured_services': {'entry': {
        'kind': 'process', 'text_logs_available': True, 'text_logs': ['D:/entry.log']}}}))
    current['target_resolution'] = {'status': 'resolved', 'service': 'entry',
        'allowed_services': ['entry'], 'log_refs': ['entry']}
    captured = await capture_decision_input(current)
    system = captured['messages'][0]['content']
    assert 'log_refs' in system and 'text_logs' in system and 'path' in system
    assert 'D:/entry.log' in json.dumps(captured)
    illegal = decision(next_tools=['probe_text_log'],
        next_arguments={'probe_text_log': {'service': 'entry', 'path': 'entry', 'lines': 100}})
    assert inv.followup_check_error(illegal.model_dump(), current)
    rejected = decide(current, illegal)
    assert rejected['plan'] == []
    feedback = await capture_decision_input({**current, **rejected})
    assert '日志路径不在配置允许范围' in feedback['inputs']['memory']
    illegal.next_arguments['probe_text_log']['path'] = 'D:/entry.log'
    assert not inv.followup_check_error(illegal.model_dump(), current)
    illegal.next_arguments['probe_text_log']['path'] = 'D:/other.log'
    assert inv.followup_check_error(illegal.model_dump(), current)


@pytest.mark.asyncio
@pytest.mark.parametrize('inventory_status', ['valid', 'expired', 'truncated', 'error', 'other_target'])
async def test_log_paths_survive_recent_evidence_cap_without_retaining_invalid_inventory(inventory_status):
    from datetime import timedelta
    from scripts.verify_competing_hypothesis_scenario import capture_decision_input
    from src.probe.protocol import evidence
    from src.settings import settings
    current = state(('inventory', {'configured_services': {
        'entry': {'text_logs_available': True, 'text_logs': ['D:/entry.log']},
        'outside': {'text_logs_available': True, 'text_logs': ['D:/outside.log']}}}))
    raw = json.loads(current['raw_evidence'][0][1])
    if inventory_status == 'expired':
        raw['collected_at'] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    if inventory_status == 'truncated': raw['truncated'] = True
    if inventory_status == 'error': raw['payload']['error'] = 'unavailable'
    if inventory_status == 'other_target': raw['target_id'] = 'another-target'
    current['raw_evidence'][0] = ('inventory', json.dumps(raw))
    current['target_resolution'] = {'status': 'resolved', 'service': 'entry',
        'allowed_services': ['entry']}
    for port in range(2000, 2009):
        current['raw_evidence'].append(('ports', json.dumps(evidence(target_id=settings.PROBE_TARGET_ID,
            operation='ports', payload={'local_port': port, 'ports': []}))))
    captured = await capture_decision_input(current)
    assert 'D:/entry.log' not in captured['inputs']['evidence']
    paths = json.loads(captured['inputs']['text_log_paths'])
    if inventory_status == 'valid':
        assert paths['services'] == {'entry': ['D:/entry.log']}
        assert paths['evidence_id'] in inv.evidence_index(current)
    else:
        assert paths == {}
