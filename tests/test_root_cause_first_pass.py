"""First-pass evidence handoff regressions; no paid model calls."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from scripts.evaluate_windows_probe import business_catalog
from scripts.mechanism_behavior import behavior_snapshot, audit_behavior
from src.agent.aiops import observations
from src.agent.aiops.probe_checks import arguments_error, progress_error
from src.agent.aiops.strategies import investigation as inv
from src.agent.aiops.target_catalog import resolve_target
from src.probe.windows.config import ProbeConfig, ServiceConfig, DependencyConfig
from src.settings import settings
from tests.test_candidate_handoff import log_state, log_check
from tests.test_concrete_investigation_checks import state, decision, decide


def test_transport_phase_is_citable_and_visible_after_context_rollover():
    trace = {'timeout_seconds': 0.5, 'phase': 'connect', 'connection_established': False}
    event = {'event': 'request_completed', 'request_id': 'transport-request',
        'upstream_request': trace, 'error_type': 'TimeoutError', 'status': 503}
    current = state(('text_logs', {'service': 'entry', 'lines': [json.dumps(event)]}),
        *[('ports', {'local_port': 6000 + i, 'ports': []}) for i in range(9)])
    records = inv.evidence_index(current)
    snippets = inv._citation_snippets(records['e1.1'])
    assert any('connection_established' in quote and 'connect' in quote for quote in snippets.values())
    assert all(quote in records['e1.1']['payload'] for quote in snippets.values())
    notes = inv.log_observation_notes(records, current)
    assert any('upstream_request=' in note and 'connection_established' in note for note in notes)


def test_agenda_exposes_fresh_log_repeat_basis_without_changing_original_check():
    current = log_state(('dependency_probe', {'dependency': 'entry', 'host': '127.0.0.1',
        'port': 8080, 'tcp': 'ok', 'http': {'status': 503}}))
    check = log_check(repeat_reason='核查新业务失败后的日志', repeat_evidence_ids=['e1.1'])
    current['investigation_memory'] = check.model_dump()
    before = deepcopy(current)
    records = inv.evidence_index(current)
    agenda = inv._decision_memory_context(current['investigation_memory'], current, records)['decision_agenda']
    row = agenda['checks'][0]['progress'][0]
    assert row['repeat_basis_evidence_ids'] == ['e1.1', 'e2.1']
    assert row['collected_at'] == json.loads(records['e1.1']['payload'])['collected_at']
    assert not agenda['checks'][0]['query_eligible']
    check.repeat_evidence_ids = row['repeat_basis_evidence_ids']
    assert progress_error(check.model_dump(), current, records) == ''
    assert current == before


@pytest.mark.parametrize('kind', ['none', 'old', 'outside', 'truncated'])
def test_agenda_does_not_offer_invalid_log_repeat_basis(kind):
    current = log_state()
    if kind != 'none':
        from src.probe.protocol import evidence
        raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='processes',
            payload={'service': 'outside' if kind == 'outside' else 'entry', 'processes': []})
        when = datetime.fromisoformat(json.loads(current['raw_evidence'][0][1])['collected_at'])
        raw['collected_at'] = (when + timedelta(seconds=-1 if kind == 'old' else 1)).isoformat()
        raw['truncated'] = kind == 'truncated'
        current['raw_evidence'].append(('new observation', json.dumps(raw)))
    current['investigation_memory'] = log_check().model_dump()
    records = inv.evidence_index(current)
    agenda = inv._decision_memory_context(current['investigation_memory'], current, records)['decision_agenda']
    assert agenda['checks'][0]['progress'][0]['repeat_basis_evidence_ids'] == []


def test_configuration_and_request_evidence_remain_citable_after_context_rollover():
    current = state(('configuration', {'service': 'entry', 'path': 'D:/connection.json',
        'source_sha256': 'config-hash', 'values': {'downstream_port': 3919}}),
        ('dependency_probe', {'dependency': 'entry', 'tcp': 'ok', 'http': {'status': 503}}),
        ('text_logs', {'service': 'entry', 'path': 'D:/entry.log', 'line_limit': 100,
            'lines': ['request failed request_id=req-1']}),
        *[('ports', {'local_port': 6000 + i, 'ports': []}) for i in range(9)])
    records = inv.evidence_index(current)
    context = inv.investigation_context(current, records)
    for ident in ('e1.1', 'e2.1', 'e3.1'):
        assert context[ident]['citation_snippets']
        assert all(quote in records[ident]['payload'] for quote in context[ident]['citation_snippets'].values())
    assert '3919' in context['e1.1']['excerpt']
    assert 'req-1' in context['e3.1']['excerpt']
    assert not decide(current, decision(next_check='', next_tools=[], next_arguments=None))['diagnosis']['kind'] == 'confirmed_cause'


def resolved_port_state(*, host='127.0.0.1', observed=False):
    cfg = ProbeConfig(settings.PROBE_TARGET_ID, 'ws://127.0.0.1:1/probe/ws', None,
        services={'entry': ServiceConfig('', kind='process')},
        dependencies={'entry': DependencyConfig(host, 3916, 'http', '/api/availability')})
    current = state(*([('ports', {'local_port': 3916, 'ports': [], 'matched_count': 0})] if observed else []))
    current['target_resolution'] = resolve_target(business_catalog(cfg), 'entry',
        {'configured_services': {'entry': {}}, 'configured_dependencies': ['entry']}, settings.PROBE_TARGET_ID)
    current['investigation_tools'].append({'name': 'probe_port_snapshot'})
    return current


def test_registered_local_entry_port_survives_scope_and_cannot_be_scheduled_twice():
    current = resolved_port_state(observed=True)
    records = inv.evidence_index(current)
    raw = json.loads(records['e1.1']['payload'])
    assert observations.in_business_scope(raw, current['target_resolution'], records)
    answer = decision(next_check='check entry listener again', next_tools=['probe_port_snapshot'],
        next_arguments={'probe_port_snapshot': {'local_port': 3916}})
    result = decide(current, answer)
    assert not result['plan']
    current.update(result)
    snapshot = behavior_snapshot(current, datetime.now(timezone.utc).isoformat())
    assert 'e1.1' in snapshot['behavior_context']['records']
    assert audit_behavior([snapshot], [], [])['status'] == 'passed'


@pytest.mark.parametrize('host,port,allowed', [('127.0.0.1', 3916, True),
    ('localhost', 3916, True), ('::1', 3916, True), ('127.0.0.1', 9999, False),
    ('remote.example', 3916, False), ('127.0.0.1', None, False)])
def test_port_planning_and_execution_use_same_business_scope(host, port, allowed):
    from src.agent.aiops.executor import _probe_request_limit
    current = resolved_port_state(host=host)
    args = {'local_port': port}
    check = decision(next_tools=['probe_port_snapshot'], next_arguments={'probe_port_snapshot': args})
    error = arguments_error('probe_port_snapshot', args, current, inv.evidence_index(current))
    assert bool(error) is not allowed
    current.update(autonomous_investigation=True, investigation_memory=check.model_dump())
    assert bool(_probe_request_limit({'name': 'probe_port_snapshot', 'args': args}, current)) is not allowed


def test_only_allowlisted_mapped_service_ports_enter_resolved_scope():
    cfg = ProbeConfig(settings.PROBE_TARGET_ID, 'ws://127.0.0.1:1/probe/ws', None,
        services={name: ServiceConfig('', kind='process') for name in ('entry', 'worker', 'other')},
        dependencies={name: DependencyConfig('127.0.0.1', port, 'http')
            for name, port in (('entry', 3916), ('worker', 3917), ('other', 9999))})
    inventory = {'configured_services': {'entry': {}, 'worker': {}},
        'configured_dependencies': ['entry', 'worker']}
    resolved = resolve_target(business_catalog(cfg), 'entry', inventory, settings.PROBE_TARGET_ID)
    assert resolved['allowed_services'] == ['entry', 'worker']
    assert set(resolved['services']) == {'entry', 'worker'}
    current = state()
    current['target_resolution'] = resolved
    assert not arguments_error('probe_port_snapshot', {'local_port': 3917}, current, {})
    assert arguments_error('probe_port_snapshot', {'local_port': 9999}, current, {})
    assert arguments_error('probe_port_snapshot', {'local_port': 3918}, current, {})


@pytest.mark.asyncio
@pytest.mark.parametrize('model_claims_cause', [False, True])
async def test_complete_cause_evidence_reaches_actual_decision_input_without_autofill(monkeypatch, model_claims_cause):
    from tests.test_investigation_fusion import _wrong_endpoint_state
    current = _wrong_endpoint_state()
    current.update(input='edge business failure', past_steps=[],
        investigation_config={'hypothesis_protection': False, 'contradiction_trigger': False, 'protection_steps': 2})
    current['target_resolution']['allowed_services'].append('edge')
    from src.probe.protocol import evidence
    app = {'event': 'request_completed', 'path': '/api/availability', 'request_id': 'req-1',
        'status': 503, 'detail': 'upstream connection failed', 'upstream': {'port': 11751},
        'configuration': {'source_sha256': 'abc123'}}
    edge = {'event': 'request_completed', 'path': '/api/availability', 'request_id': 'req-1', 'status': 503}
    for service, event in (('localapp', app), ('edge', edge)):
        current['raw_evidence'].append(('request log', json.dumps(evidence(target_id=settings.PROBE_TARGET_ID,
            operation='text_logs', payload={'service': service, 'lines': [json.dumps(event)]}))))
    current['raw_evidence'].extend(state(*[('ports', {'local_port': 6000 + i, 'ports': []})
        for i in range(9)])['raw_evidence'])
    before = deepcopy(current)
    captured = {}
    async def model(llm, schema, prompt, inputs):
        captured.update(inputs)
        if 'cause_feedback' in inputs:
            feedback = json.loads(inputs['cause_feedback'])
            review = {'evidence_complete': True, 'evidence_ids':
                feedback['supported_causes']['configured_downstream_endpoint_mismatch']}
            context = feedback['citable_evidence']
        else:
            review = json.loads(inputs['memory'])['decision_agenda']['direct_cause_review']
            context = json.loads(inputs['evidence'])
        assert review['evidence_complete']
        assert set(review['evidence_ids']) == {'e1.1', 'e2.1', 'e3.1', 'e4.1', 'e5.1'}
        assert all(context[ident]['citation_snippets'] for ident in review['evidence_ids'])
        if model_claims_cause:
            return decision(next_check='', next_tools=[], next_arguments=None,
                root_cause='localapp 加载的下游端口与登记端口不同，导致本次请求连接失败',
                root_cause_code='configured_downstream_endpoint_mismatch', outcome='root_cause',
                conclusion_level='confirmed_cause', scope='edge 本次 /api/availability 请求',
                supporting_evidence=[inv.Citation(evidence_id=ident,
                    snippet_id=next(iter(context[ident]['citation_snippets'])))
                    for ident in review['evidence_ids']],
                alternatives=[inv.Alternative(explanation='dependency_probe/downstream: tcp == "failed"',
                    status='excluded', claim_type='observed_condition',
                    condition=inv.ObservationCondition(operation='dependency_probe', object_name='downstream',
                        field='tcp', expected='failed'),
                    evidence=[inv.Citation(evidence_id='e3.1',
                        snippet_id=next(iter(context['e3.1']['citation_snippets'])))])])
        return decision(next_check='', next_tools=[], next_arguments=None)
    monkeypatch.setattr(inv, 'create_agent_llm', lambda **kwargs: object())
    monkeypatch.setattr(inv, 'ainvoke_structured', AsyncMock(side_effect=model))
    result = await inv.InvestigationStrategy().decide(current)
    assert captured
    assert (result['diagnosis']['kind'] == 'confirmed_cause') is model_claims_cause
    if model_claims_cause:
        assert len(result['investigation_memory']['supporting_evidence']) == 5
        assert all(item['quote'] for item in result['investigation_memory']['supporting_evidence'])
    else:
        assert result['investigation_memory']['root_cause'] == ''
        assert result['investigation_memory']['root_cause_code'] == ''
        assert result['investigation_memory']['model_suggestion']['supporting_evidence'] == []
    assert current == before
    incomplete = deepcopy(current)
    del incomplete['raw_evidence'][4]
    records = inv.evidence_index(incomplete)
    review = inv._decision_memory_context({}, incomplete, records)['decision_agenda']['direct_cause_review']
    assert not review['evidence_complete'] and review['evidence_ids'] == []


@pytest.mark.asyncio
async def test_fresh_failure_basis_reaches_exact_log_execution_without_second_model(monkeypatch):
    current = log_state(('dependency_probe', {'dependency': 'entry', 'tcp': 'ok', 'http': {'status': 503}}))
    current['investigation_memory'] = log_check().model_dump()
    records = inv.evidence_index(current)
    agenda = inv._decision_memory_context(current['investigation_memory'], current, records)['decision_agenda']
    basis = agenda['checks'][0]['progress'][0]['repeat_basis_evidence_ids']
    answer = log_check(next_check='inspect new failed request', repeat_reason='核对失败请求后的日志',
        repeat_evidence_ids=basis)
    current.update(decide(current, answer), autonomous_investigation=True)
    assert current['plan'] == [answer.next_check]
    ex = importlib.import_module('src.agent.aiops.executor')
    from src.probe.protocol import evidence
    returned = evidence(target_id=settings.PROBE_TARGET_ID, operation='text_logs',
        payload={'service': 'entry', 'path': 'D:/entry.log', 'line_limit': 100, 'lines': ['new request failed']})
    tool = SimpleNamespace(name='probe_text_log', description='read log', args={}, ainvoke=AsyncMock(return_value=returned))
    monkeypatch.setattr(ex, '_get_tools_for_state', AsyncMock(return_value=([tool], None)))
    monkeypatch.setattr(ex, 'create_agent_llm', Mock(side_effect=AssertionError('no execution model')))
    _, raw = await ex._run_step(answer.next_check, current)
    tool.ainvoke.assert_awaited_once_with(answer.next_arguments['probe_text_log'])
    current['raw_evidence'].append((answer.next_check, raw))
    assert inv.execution_checks(current)[-1]['status'] == 'success'
