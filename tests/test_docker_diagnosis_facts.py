import json

import pytest

from src.agent.aiops.observations import dependency_healthy, observation_clues
from src.agent.aiops.evidence_summary import evidence_summary
from src.agent.aiops.strategies import investigation as inv
from src.probe.protocol import evidence
from src.settings import settings


@pytest.mark.parametrize('kind,expected', [('docker', False), ('windows_service', True)])
def test_pid_namespaces_are_not_compared(kind, expected):
    rows = [evidence(target_id=settings.PROBE_TARGET_ID, operation='services',
                     payload={'service': 'web', 'kind': kind, 'state': 'running', 'pid': 12}),
            evidence(target_id=settings.PROBE_TARGET_ID, operation='ports',
                     payload={'local_port': 8310, 'ports': [{'status': 'LISTEN', 'pid': 34, 'local': {'port': 8310}}]})]
    state = {'raw_evidence': [('probe', json.dumps(row)) for row in rows]}
    scope = {'status': 'resolved', 'allowed_services': ['web'],
             'services': {'shop': {'probe_service': 'web', 'expected_ports': [8310]}}}
    clues = observation_clues(inv.evidence_index(state), scope)
    assert any(c['code'] == 'port_owner_mismatch' for c in clues) is expected


@pytest.mark.parametrize('query,expected', [('ok', True), ('failed', False), ('no_worker_reply', False), (None, False)])
def test_adapter_health_requires_actual_query(query, expected):
    body = {'dependency': 'db', 'tcp': 'ok', 'probe_kind': 'django_database', 'query': query}
    assert dependency_healthy(body) is expected
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe', payload=body)
    condition = inv.ObservationCondition(operation='dependency_probe', object_name='db', field='query', expected='ok')
    assert inv._condition_value(raw, condition) == query
    state = {'raw_evidence': [('probe', json.dumps(raw))]}
    clues = observation_clues(inv.evidence_index(state))
    assert any(c['code'] == 'dependency_query_failed' for c in clues) is (query in {'failed', 'no_worker_reply'})


def test_large_public_summary_stays_valid_and_retains_status():
    body = {'dependency': 'site', 'tcp': 'ok', 'http': {'status': 200, 'body_prefix': '<html>' * 4000},
            'lines': ['long log ' * 2000] * 100}
    summary = evidence_summary(body)
    result = json.loads(summary)
    assert result['http']['status'] == 200 and result['tcp'] == 'ok'
    assert result['_summary_limited'] and len(summary) < 12000
    assert body['http']['body_prefix'] == '<html>' * 4000


def test_invalid_adapter_condition_is_not_accepted():
    condition = inv.ObservationCondition(operation='dependency_probe', object_name='db', field='query', expected='success')
    assert not inv._legal_prediction(condition)


@pytest.mark.parametrize('query,healthy', [('ok', True), ('failed', False)])
def test_terminal_health_keeps_outcome_but_still_requires_query_success(monkeypatch, query, healthy):
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe', payload={
        'dependency': 'db', 'tcp': 'ok', 'probe_kind': 'django_database', 'query': query})
    state = {'input': '检查商城', 'raw_evidence': [('probe', json.dumps(raw))],
        'target_resolution': {'status': 'resolved', 'allowed_dependencies': ['db'], 'allowed_services': []}}
    cited = inv.Citation(evidence_id='e1.1', quote='ok')
    proposed = inv.InvestigationDecision(hypothesis='本次数据库查询可用', outcome='healthy',
        conclusion_level='healthy_within_scope', scope='本次数据库连通与只读查询',
        supporting_evidence=[cited], alternatives=[inv.Alternative(
            explanation='数据库端口不通', status='excluded', claim_type='observed_condition',
            condition=inv.ObservationCondition(operation='dependency_probe', object_name='db',
                                               field='tcp', expected='failed'), evidence=[cited])])
    def unwanted_fallback(*args, **kwargs):
        raise AssertionError('a terminal health proposal is not a missing-check proposal')
    monkeypatch.setattr(inv, '_blocked_check_candidate_followup', unwanted_fallback)
    result = inv.decide_from_evidence(state, proposed, inv.evidence_index(state))
    assert (result.get('diagnosis', {}).get('kind') == 'healthy_within_scope') is healthy


def test_health_feedback_identifies_missing_port_and_real_query_result():
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe', payload={
        'dependency': 'db', 'tcp': 'ok', 'probe_kind': 'django_database', 'query': 'ok'})
    state = {'raw_evidence': [('probe', json.dumps(raw))], 'target_resolution': {
        'status': 'resolved', 'allowed_dependencies': ['db'], 'allowed_services': ['web'],
        'services': {'shop': {'probe_service': 'web', 'expected_ports': [8310]}}}}
    result = inv._health_dependency_coverage(state, inv.evidence_index(state), inv.InvestigationDecision(hypothesis='待核查'))
    assert result['dependencies'][0]['status'] == 'valid_collected_but_supporting_uncited'
    assert result['dependencies'][0]['observed']['query'] == 'ok'
    assert result['services_and_ports'] == [
        {'operation': 'services', 'object': 'web', 'evidence_id': '', 'status': 'not_collected'},
        {'operation': 'ports', 'object': 8310, 'evidence_id': '', 'status': 'not_collected'}]


def test_agenda_shows_live_scope_coverage_before_a_health_proposal():
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='services',
        payload={'service': 'web', 'kind': 'docker', 'state': 'running'})
    state = {'raw_evidence': [('probe', json.dumps(raw))], 'target_resolution': {
        'status': 'resolved', 'allowed_dependencies': ['db'], 'allowed_services': ['web'],
        'services': {'shop': {'probe_service': 'web', 'expected_ports': [8310]}}}}
    agenda = inv._decision_check_agenda({}, state, inv.evidence_index(state))
    coverage = agenda['scope_observations']
    assert coverage['dependencies'][0]['status'] == 'not_collected'
    assert coverage['services_and_ports'][0]['status'] == 'valid_collected_but_supporting_uncited'
    assert coverage['services_and_ports'][1]['status'] == 'not_collected'
    assert not agenda['direct_cause_review']['evidence_complete']
    assert 'diagnosis' not in state and 'plan' not in state


@pytest.mark.asyncio
@pytest.mark.parametrize('correction_valid', [True, False])
async def test_identity_correction_after_health_feedback_is_bounded(monkeypatch, correction_valid):
    from copy import deepcopy
    from unittest.mock import AsyncMock
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
        payload={'dependency': 'db', 'tcp': 'ok', 'probe_kind': 'django_database', 'query': 'ok'})
    state = {'input': '检查商城', 'raw_evidence': [('probe', json.dumps(raw))],
        'target_resolution': {'status': 'resolved', 'allowed_services': [], 'allowed_dependencies': ['db']}}
    records = inv.evidence_index(state)
    original = inv.ObservationCondition(operation='dependency_probe', object_name='db', field='tcp', expected='ok')
    leader = inv.InvestigationDecision(hypothesis='dependency_probe/db: tcp == "ok"', hypothesis_condition=original)
    tracking = inv._apply_investigation_mechanisms(state, leader, records)
    state['investigation_memory'] = {'hypothesis_tracking': tracking}
    initial = inv.InvestigationProposal(hypothesis='本次范围未见异常', outcome='healthy', alternatives=[])
    broken = inv.InvestigationProposal(hypothesis='本次数据库查询通过', outcome='healthy',
        conclusion_level='healthy_within_scope', scope='仅本次数据库只读查询',
        supporting_evidence=[inv.Citation(evidence_id='e1.1', quote='ok')], alternatives=[inv.ModelAlternative.model_validate(
            inv.Alternative(explanation='dependency_probe/db: tcp == "failed"', hypothesis_id=leader.hypothesis_id,
                condition=original.model_copy(update={'expected': 'failed'}), status='excluded',
                claim_type='observed_condition', evidence=[inv.Citation(evidence_id='e1.1', quote='ok')]).model_dump())])
    corrected = deepcopy(broken)
    if correction_valid:
        corrected.alternatives[0].hypothesis_id = ''
    model = AsyncMock(side_effect=[initial, broken, corrected])
    monkeypatch.setattr(inv, 'create_agent_llm', lambda **kwargs: object())
    monkeypatch.setattr(inv, 'ainvoke_structured', model)
    result = await inv.InvestigationStrategy().decide(state)
    assert model.await_count == 3
    memory = result['investigation_memory']
    assert [a['purpose'] for a in memory['decision_trace']['attempts']] == ['initial', 'health_correction', 'identity_correction']
    assert memory['identity_correction']['attempts'] == 1
    assert (result['diagnosis']['kind'] == 'healthy_within_scope') is correction_valid
    assert memory['hypothesis_tracking']['candidates'][0]['condition'] == original.model_dump()
