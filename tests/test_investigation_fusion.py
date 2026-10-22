import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.orm import sessionmaker

from src.agent.aiops import run_store
from src.agent.aiops.evidence_reader import read_run_evidence, evidence_read_tool
from src.agent.aiops.target_catalog import resolve_target, normalized_url
from src.agent.aiops.observations import observation_clues
from src.agent.aiops.strategies import investigation as inv
from src.probe.protocol import evidence
from src.settings import settings


def catalog(**services):
    return json.dumps({'version': 1, 'target_id': settings.PROBE_TARGET_ID, 'services': services})


def test_exact_business_resolution_and_conflicts_do_not_grant_permissions():
    raw = catalog(orders={'aliases': ['订单'], 'probe_service': 'svc', 'dependencies': ['db'],
                          'entries': {'http://localhost:8080/health': 'entry'}, 'expected_ports': [8080]})
    inventory = {'configured_services': {'svc': {}}, 'configured_dependencies': ['entry']}
    found = resolve_target(raw, '订单打不开', inventory, settings.PROBE_TARGET_ID)
    assert found['status'] == 'resolved'
    assert found['allowed_dependencies'] == ['entry'] and found['allowed_services'] == ['svc']
    assert found['mismatches']
    assert resolve_target(raw, '检查 https://unknown.example/', inventory, settings.PROBE_TARGET_ID)['status'] == 'unmatched'
    assert resolve_target(raw, '检查 https://orders.example/', inventory, settings.PROBE_TARGET_ID)['status'] != 'resolved'
    assert resolve_target(raw, 'orders-other', inventory, settings.PROBE_TARGET_ID)['status'] != 'resolved'
    assert resolve_target(raw, '本机运行概况', inventory, settings.PROBE_TARGET_ID)['status'] == 'host_overview'
    ambiguous = catalog(one={'aliases': ['共同']}, two={'aliases': ['共同']})
    assert resolve_target(ambiguous, '共同', inventory, settings.PROBE_TARGET_ID)['status'] == 'ambiguous'
    assert normalized_url('http://localhost:443/') != normalized_url('https://localhost/')
    assert resolve_target('old reference', 'orders', {}, settings.PROBE_TARGET_ID)['status'] == 'legacy_reference'


def test_negative_process_query_requires_configured_names_and_complete_access():
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='processes', payload={
        'service': 'svc', 'processes': [], 'skipped_count': 0})
    current = {'raw_evidence': [('processes', json.dumps(raw))]}
    assert observation_clues(inv.evidence_index(current)) == []
    inventory = evidence(target_id=settings.PROBE_TARGET_ID, operation='inventory', payload={
        'configured_services': {'svc': {'process_names': ['app.exe']}}})
    current['raw_evidence'].insert(0, ('inventory', json.dumps(inventory)))
    assert observation_clues(inv.evidence_index(current))[0]['code'] == 'configured_process_not_observed'
    raw['truncated'] = True
    current['raw_evidence'][-1] = ('processes', json.dumps(raw))
    assert [c['code'] for c in observation_clues(inv.evidence_index(current))] == ['truncated_observation']


@pytest.fixture
def ledger(engine, tmp_path, monkeypatch):
    monkeypatch.setattr(run_store, 'SessionLocal', sessionmaker(bind=engine))
    monkeypatch.setattr(settings, 'PROBE_EVIDENCE_DIR', str(tmp_path / 'evidence'))
    tid = 'fusion-' + uuid4().hex
    run_store.create_run(tid, 712, 'read evidence')
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='services', payload={'service': 'svc', 'state': 'running'},
        collected_at=(datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat().replace('+00:00', 'Z'))
    eid = run_store.add_evidence(tid, 712, settings.PROBE_TARGET_ID, 'services', raw)
    return tid, eid, raw


def test_evidence_reader_owner_thread_paging_integrity_and_old_time(ledger):
    tid, eid, raw = ledger
    first = read_run_evidence(tid, 712, eid, limit=40)
    assert first['fresh'] is False and first['new_observation'] is False
    assert run_store._parse_utc(first['collected_at']) == run_store._parse_utc(raw['collected_at'])
    assert first['next_offset'] == 40 and first['truncated']
    filtered = read_run_evidence(tid, 712, eid, query='running')
    assert 'running' in filtered['excerpt']
    with pytest.raises(PermissionError): read_run_evidence(tid, 999, eid)
    other = 'other-' + uuid4().hex
    run_store.create_run(other, 712, 'other')
    with pytest.raises(PermissionError): read_run_evidence(other, 712, eid)
    with pytest.raises(ValueError): read_run_evidence(tid, 712, eid, limit=16385)
    from pathlib import Path
    path = Path(run_store.get_evidence(tid, eid, 712)['raw_ref'])
    saved = json.loads(path.read_text(encoding='utf-8'))
    saved['payload']['state'] = 'stopped'
    path.write_text(json.dumps(saved), encoding='utf-8')
    with pytest.raises(ValueError, match='integrity'): read_run_evidence(tid, 712, eid)
    assert len(run_store.list_evidence(tid, 712)) == 1
    assert set(evidence_read_tool(tid, 712).args) == {'evidence_id', 'query', 'offset', 'limit'}


@pytest.mark.parametrize(('field', 'value'), [('platform', 'linux'), ('data_source', 'knowledge_base')])
def test_evidence_reader_rejects_changed_provenance(ledger, field, value):
    from pathlib import Path
    tid, eid, raw = ledger
    path = Path(run_store.get_evidence(tid, eid, 712)['raw_ref'])
    saved = json.loads(path.read_text(encoding='utf-8'))
    saved[field] = value
    path.write_text(json.dumps(saved), encoding='utf-8')
    with pytest.raises(ValueError, match='integrity'):
        read_run_evidence(tid, 712, eid)


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['critical_unavailable', 'status_only', 'global_healthy', 'entry_503', 'healthy_missing_dependency'])
async def test_strict_conclusions_reject_unsupported_cases(monkeypatch, case):
    payload = {'service': 'svc', 'state': 'running'}
    operation = 'services'
    level, outcome, cause, scope = 'confirmed_cause', 'root_cause', 'database crashed', 'svc'
    alternative = inv.Alternative(explanation='another explanation', status='excluded',
        evidence=[inv.Citation(evidence_id='e1.1', quote='running')])
    if case == 'critical_unavailable':
        operation, payload = 'text_logs', {'lines': ['fatal error']}
        alternative = inv.Alternative(explanation='network', status='unavailable', limitation='no permission')
    if case in {'global_healthy', 'healthy_missing_dependency'}:
        level, outcome, cause = 'healthy_within_scope', 'healthy', ''
        scope = '整机长期健康' if case == 'global_healthy' else 'orders'
    if case == 'entry_503':
        operation, payload = 'dependency_probe', {'dependency': 'entry', 'tcp': 'ok', 'http': {'status': 503}}
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation=operation, payload=payload)
    current = {'input': 'symptom', 'raw_evidence': [('check', json.dumps(raw))], 'plan': []}
    if case == 'healthy_missing_dependency':
        current['target_resolution'] = {'status': 'resolved', 'allowed_services': ['svc'], 'allowed_dependencies': ['db']}
    quote = next(iter(payload))
    answer = inv.InvestigationDecision(hypothesis='candidate', conclusion_level=level, outcome=outcome,
        root_cause=cause, scope=scope, supporting_evidence=[inv.Citation(evidence_id='e1.1', quote=quote)], alternatives=[alternative])
    monkeypatch.setattr(inv, 'ainvoke_structured', AsyncMock(return_value=answer))
    result = await inv.InvestigationStrategy().decide(current)
    assert result['diagnosis']['kind'] == ('localized_fault' if case == 'entry_503' else 'unlocated')


def test_concrete_repeat_guard_keeps_an_unchecked_service_executable():
    from src.agent.aiops.executor import _probe_request_limit
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='services', payload={'service': 'one', 'state': 'running'})
    state = {'autonomous_investigation': True, 'raw_evidence': [('one', json.dumps(raw)), ('again', json.dumps(raw))]}
    assert _probe_request_limit({'name': 'probe_service_status', 'args': {'service': 'one'}}, state)
    assert _probe_request_limit({'name': 'probe_service_status', 'args': {'service': 'two'}}, state) == ''


@pytest.mark.asyncio
async def test_newer_normal_observation_blocks_old_fault_conclusion(monkeypatch):
    stopped = evidence(target_id=settings.PROBE_TARGET_ID, operation='services', payload={'service': 'svc', 'state': 'stopped'})
    running = evidence(target_id=settings.PROBE_TARGET_ID, operation='services', payload={'service': 'svc', 'state': 'running'})
    current = {'input': 'symptom', 'raw_evidence': [('old', json.dumps(stopped)), ('new', json.dumps(running))]}
    answer = inv.InvestigationDecision(hypothesis='stopped', conclusion_level='localized_fault',
        scope='svc', localized_fault='someone deliberately stopped service',
        supporting_evidence=[inv.Citation(evidence_id='e1.1', quote='stopped')])
    monkeypatch.setattr(inv, 'ainvoke_structured', AsyncMock(return_value=answer))
    result = await inv.InvestigationStrategy().decide(current)
    assert result['diagnosis']['kind'] == 'unlocated'
    assert result['diagnosis']['contradictions']


def test_superseded_observations_use_collection_time_not_insertion_order():
    now = datetime.now(timezone.utc)
    newer = evidence(target_id=settings.PROBE_TARGET_ID, operation='services',
        payload={'service': 'svc', 'state': 'running'}, collected_at=now.isoformat())
    older = evidence(target_id=settings.PROBE_TARGET_ID, operation='services',
        payload={'service': 'svc', 'state': 'stopped'}, collected_at=(now - timedelta(seconds=15)).isoformat())
    records = inv.evidence_index({'raw_evidence': [('newer', json.dumps(newer)), ('older delayed', json.dumps(older))]})
    assert inv.superseded_citations([inv.Citation(evidence_id='e1.1', quote='running')], records) == []
    assert inv.superseded_citations([inv.Citation(evidence_id='e2.1', quote='stopped')], records)


@pytest.mark.parametrize('changed', [False, True])
def test_dependency_timing_jitter_is_not_a_conflict_or_new_diagnostic_information(changed):
    from src.agent.aiops.executor import _probe_request_limit
    samples = [evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
        payload={'dependency': 'db', 'tcp': 'ok' if changed and i else 'failed',
                 'http': {'status': 503}, 'elapsed_ms': 10 + i}) for i in range(2)]
    state = {'autonomous_investigation': True,
             'raw_evidence': [('probe', json.dumps(item)) for item in samples]}
    records = inv.evidence_index(state)
    conflicts = inv.superseded_citations([inv.Citation(evidence_id='e1.1', quote='failed')], records)
    repeated = _probe_request_limit({'name': 'probe_dependency_probe', 'args': {'dependency': 'db'}}, state)
    assert bool(conflicts) is changed
    assert bool(repeated) is not changed
    assert samples[0]['raw_hash'] != samples[1]['raw_hash']


@pytest.mark.asyncio
async def test_localized_conclusion_uses_observed_fault_not_model_causal_claim(monkeypatch):
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='services', payload={'service': 'svc', 'state': 'stopped'})
    current = {'input': 'symptom', 'raw_evidence': [('check', json.dumps(raw))]}
    answer = inv.InvestigationDecision(hypothesis='candidate', conclusion_level='localized_fault',
        scope='svc', localized_fault='administrator stopped it',
        supporting_evidence=[inv.Citation(evidence_id='e1.1', quote='stopped')])
    monkeypatch.setattr(inv, 'ainvoke_structured', AsyncMock(return_value=answer))
    result = await inv.InvestigationStrategy().decide(current)
    assert result['diagnosis']['kind'] == 'localized_fault'
    assert 'administrator' not in result['diagnosis']['conclusion']
    assert 'svc' in result['diagnosis']['conclusion']


@pytest.mark.asyncio
async def test_unlocated_model_keeps_observed_dependency_fault_layer(monkeypatch):
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
        payload={'dependency': 'downstream', 'tcp': 'failed', 'tcp_error': 'ConnectionRefusedError'})
    current = {'input': 'application unavailable', 'raw_evidence': [('check', json.dumps(raw))]}
    answer = inv.InvestigationDecision(hypothesis='downstream failure', conclusion_level='unlocated',
        scope='configured downstream', supporting_evidence=[inv.Citation(evidence_id='e1.1', quote='failed')])
    monkeypatch.setattr(inv, 'ainvoke_structured', AsyncMock(return_value=answer))
    result = await inv.InvestigationStrategy().decide(current)
    assert result['diagnosis']['kind'] == 'localized_fault'
    assert 'TCP' in result['diagnosis']['conclusion']
    assert 'confirmed_cause' not in result['diagnosis']['kind']


@pytest.mark.asyncio
async def test_supported_observation_cannot_be_reported_as_excluded(monkeypatch):
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
        payload={'dependency': 'downstream', 'tcp': 'failed', 'tcp_error': 'ConnectionRefusedError'})
    current = {'input': 'application unavailable', 'raw_evidence': [('check', json.dumps(raw))]}
    answer = inv.InvestigationDecision(hypothesis='downstream failure', conclusion_level='unlocated',
        scope='configured downstream', supporting_evidence=[inv.Citation(evidence_id='e1.1', quote='failed')],
        alternatives=[inv.Alternative(explanation='downstream TCP 不可达', status='excluded',
            evidence=[inv.Citation(evidence_id='e1.1', quote='failed')])])
    monkeypatch.setattr(inv, 'ainvoke_structured', AsyncMock(return_value=answer))
    result = await inv.InvestigationStrategy().decide(current)
    alternative = result['investigation_memory']['alternatives'][0]
    assert alternative['status'] == 'unresolved'
    assert alternative['original_status'] == 'excluded'
    assert result['investigation_memory']['validation_issues']


@pytest.mark.parametrize('truncated', [False, True])
def test_time_wait_is_not_listen_and_actual_truncation_controls_negative_findings(truncated):
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='ports', payload={
        'local_port': 8000, 'limit': 256, 'ports': [
            {'status': 'TIME_WAIT', 'local': {'port': 8000}, 'pid': 0}]}, truncated=truncated)
    clues = observation_clues(inv.evidence_index({'raw_evidence': [('ports', json.dumps(raw))]}))
    assert ('port_not_listening' in {c['code'] for c in clues}) is not truncated


@pytest.mark.parametrize('invalid', ['expired', 'wrong_target', 'outside_scope', 'incomplete', 'hash'])
def test_fault_fallback_rejects_untrusted_or_out_of_scope_observations(invalid):
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
        payload={'dependency': 'db', 'tcp': 'failed'})
    current = {'input': 'symptom', 'raw_evidence': []}
    if invalid == 'expired':
        raw['collected_at'] = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    if invalid == 'wrong_target': raw['target_id'] = 'other'
    if invalid == 'hash': raw['payload']['tcp'] = 'ok'
    if invalid == 'incomplete': raw['truncated'] = True
    if invalid == 'outside_scope':
        current['target_resolution'] = {'status': 'resolved', 'allowed_dependencies': ['entry']}
    current['raw_evidence'] = [('probe', json.dumps(raw))]
    result = inv.decide_from_evidence(current, inv.InvestigationDecision(hypothesis='unknown'), inv.evidence_index(current))
    assert result['diagnosis']['kind'] == 'unlocated'
    assert result['diagnosis']['observed_findings'] == []


def test_observed_fault_does_not_stop_a_valid_new_check_and_question_id_survives():
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
        payload={'dependency': 'db', 'tcp': 'failed'})
    current = {'input': 'symptom', 'raw_evidence': [('probe', json.dumps(raw))],
        'investigation_tools': [{'name': 'probe_text_log'}]}
    proposal = inv.InvestigationDecision(hypothesis='db unreachable', next_check='inspect application log',
        next_tools=['probe_text_log'], discriminating_question='does the log show dependency failure',
        expected_observation='connection error or another application error')
    original = proposal.model_dump()
    first = inv.decide_from_evidence(current, proposal, inv.evidence_index(current))
    assert first['plan'] == ['inspect application log'] and 'diagnosis' not in first
    assert proposal.model_dump() == original
    assert first['investigation_memory']['model_suggestion'] == original
    current['investigation_memory'] = first['investigation_memory']
    second = inv.decide_from_evidence(current, proposal, inv.evidence_index(current))
    assert second['investigation_memory']['next_question_id'] == first['investigation_memory']['next_question_id']


@pytest.mark.parametrize(('status', 'expected', 'claim_type', 'verified'), [
    ('excluded', 'failed', 'observed_condition', False),
    ('excluded', 'ok', 'observed_condition', True),
    ('supported', 'failed', 'observed_condition', True),
    ('supported', 'failed', 'causal_explanation', False),
    ('excluded', 'ok', 'causal_explanation', False),
])
def test_explicit_predicates_validate_direction_without_rewriting_model(status, expected, claim_type, verified):
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
        payload={'dependency': 'db', 'tcp': 'failed'})
    current = {'input': 'symptom', 'raw_evidence': [('probe', json.dumps(raw))]}
    proposal = inv.InvestigationDecision(hypothesis='candidate', alternatives=[inv.Alternative(
        explanation='configured TCP condition', status=status, claim_type=claim_type,
        condition=inv.ObservationCondition(operation='dependency_probe', object_name='db', field='tcp', expected=expected),
        evidence=[inv.Citation(evidence_id='e1.1', quote='failed')])])
    result = inv.decide_from_evidence(current, proposal, inv.evidence_index(current))
    alternative = result['diagnosis']['alternatives'][0]
    assert alternative['original_status'] == status
    assert alternative['status'] == (status if verified else 'unresolved')
    assert result['investigation_memory']['model_suggestion'] == proposal.model_dump()
    assert result['diagnosis']['kind'] == 'localized_fault'
    assert result['diagnosis']['evidence']
    assert result['diagnosis']['observed_findings'][0]['causal'] is False


def test_latest_normal_observation_removes_old_fault_from_findings():
    now = datetime.now(timezone.utc)
    old = evidence(target_id=settings.PROBE_TARGET_ID, operation='services', payload={'service': 'svc', 'state': 'stopped'},
        collected_at=(now - timedelta(seconds=10)).isoformat())
    new = evidence(target_id=settings.PROBE_TARGET_ID, operation='services', payload={'service': 'svc', 'state': 'running'},
        collected_at=now.isoformat())
    current = {'input': 'symptom', 'raw_evidence': [('new', json.dumps(new)), ('delayed old', json.dumps(old))]}
    result = inv.decide_from_evidence(current, inv.InvestigationDecision(hypothesis='unknown'), inv.evidence_index(current))
    assert result['diagnosis']['kind'] == 'unlocated'
    assert result['diagnosis']['observed_findings'] == []


@pytest.mark.parametrize('expected', ['impossible-state', 1, True])
def test_invalid_condition_value_cannot_prove_exclusion(expected):
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
        payload={'dependency': 'db', 'tcp': 'ok'})
    state = {'input': 'symptom', 'raw_evidence': [('check', json.dumps(raw))]}
    proposal = inv.InvestigationDecision(hypothesis='candidate', alternatives=[inv.Alternative(
        explanation='TCP condition', status='excluded', claim_type='observed_condition',
        condition=inv.ObservationCondition(operation='dependency_probe', object_name='db', field='tcp', expected=expected),
        evidence=[inv.Citation(evidence_id='e1.1', quote='ok')])])
    result = inv.decide_from_evidence(state, proposal, inv.evidence_index(state))
    assert result['diagnosis']['alternatives'][0]['status'] == 'unresolved'
    assert result['diagnosis']['validation_issues']


def test_different_objects_cannot_be_combined_as_one_verified_condition():
    samples = [evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
        payload={'dependency': name, 'tcp': 'failed'}) for name in ('one', 'two')]
    state = {'input': 'symptom', 'raw_evidence': [('check', json.dumps(item)) for item in samples]}
    proposal = inv.InvestigationDecision(hypothesis='candidate', alternatives=[inv.Alternative(
        explanation='unspecified dependency', status='supported', claim_type='observed_condition',
        condition=inv.ObservationCondition(operation='dependency_probe', field='tcp', expected='failed'),
        evidence=[inv.Citation(evidence_id=f'e{i+1}.1', quote='failed') for i in range(2)])])
    result = inv.decide_from_evidence(state, proposal, inv.evidence_index(state))
    assert result['diagnosis']['alternatives'][0]['status'] == 'unresolved'
