"""Rejected candidate IDs cannot corrupt state or block independent scoped checks."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import importlib
from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.tools import StructuredTool

from scripts.mechanism_behavior import audit_behavior, behavior_snapshot
from src.agent.aiops.strategies import investigation as inv
from src.probe.protocol import evidence
from src.settings import settings


def fixture(protection=False, trigger=False):
    state = {'input': 'entry unavailable', 'past_steps': [('initial', 'inventory')], 'raw_evidence': [],
        'investigation_tools': [{'name': name} for name in (
            'probe_dependency_probe', 'probe_port_snapshot', 'probe_process_snapshot', 'probe_text_log')],
        'investigation_config': {'hypothesis_protection': protection, 'contradiction_trigger': trigger, 'protection_steps': 2},
        'target_resolution': {'status': 'resolved', 'target_id': settings.PROBE_TARGET_ID,
            'allowed_dependencies': ['entry', 'db'], 'allowed_services': ['worker'], 'services': {},
            'dependency_services': {'db': 'worker'}}}
    def add(operation, payload):
        state['raw_evidence'].append((operation, json.dumps(evidence(
            target_id=settings.PROBE_TARGET_ID, operation=operation, payload=payload))))
    add('inventory', {'configured_services': {'worker': {'kind': 'process', 'process_names': ['python.exe'],
        'process_identity_configured': True, 'text_logs_available': True, 'text_logs': ['C:/demo/db.log']}}})
    condition = inv.ObservationCondition(operation='dependency_probe', object_name='entry', field='http.status', expected=503)
    first = inv.InvestigationDecision(hypothesis='entry HTTP state', hypothesis_condition=condition,
        next_check='inspect entry', next_tools=['probe_dependency_probe'],
        next_arguments={'probe_dependency_probe': {'dependency': 'entry'}},
        discriminating_question='entry HTTP status?', expected_observation='HTTP response')
    state.update(inv.decide_from_evidence(state, first, inv.evidence_index(state)))
    first_snapshot = behavior_snapshot(state, datetime.now(timezone.utc).isoformat())
    state['past_steps'].append(('inspect entry', '503'))
    ident = state['investigation_memory']['hypothesis_tracking']['leading_id']
    wrong = inv.InvestigationDecision(hypothesis='db TCP state', hypothesis_id=ident,
        hypothesis_condition=inv.ObservationCondition(operation='dependency_probe', object_name='db', field='tcp', expected='failed'),
        next_check='model asks arbitrary log', next_tools=['probe_text_log'],
        next_arguments={'probe_text_log': {'service': 'worker', 'path': 'C:/secret.txt'}},
        discriminating_question='read secret?', expected_observation='untrusted proposed check')
    add('dependency_probe', {'dependency': 'db', 'host': '127.0.0.1', 'port': 5678, 'tcp': 'failed'})
    return state, wrong, add, first_snapshot


def saved_check_fixture(protection=False, trigger=False, multi=False):
    state, _, add, _ = fixture(protection, trigger)
    # Start before any downstream observation. Only checks saved in a valid round may resume.
    state['raw_evidence'] = state['raw_evidence'][:1]
    state['past_steps'] = [('initial', 'inventory')]
    state.pop('investigation_memory')
    proposal = inv.InvestigationDecision(hypothesis='entry TCP status',
        hypothesis_condition=inv.ObservationCondition(operation='dependency_probe', object_name='entry', field='tcp', expected='ok'),
        next_check='inspect entry', next_tools=['probe_dependency_probe'],
        next_arguments={'probe_dependency_probe': {'dependency': 'entry'}},
        discriminating_question='entry reachable?', expected_observation='TCP status',
        alternatives=[inv.Alternative(explanation='check db independently', status='unresolved',
            check=inv.CandidateCheck(next_check='inspect saved db', next_tools=['probe_dependency_probe'],
                next_arguments={'probe_dependency_probe': {'dependency': 'db'}},
                discriminating_question='db reachable?', expected_observation='independent db status'))])
    if multi:
        proposal.alternatives[0].check.next_tools.append('probe_process_snapshot')
        proposal.alternatives[0].check.next_arguments['probe_process_snapshot'] = {'service': 'worker'}
    state.update(inv.decide_from_evidence(state, proposal, inv.evidence_index(state)))
    first = behavior_snapshot(state, datetime.now(timezone.utc).isoformat())
    state['past_steps'].append(('inspect entry', '503'))
    add('dependency_probe', {'dependency': 'entry', 'host': '127.0.0.1', 'port': 8080,
                             'tcp': 'ok', 'http': {'status': 503}})
    ident = state['investigation_memory']['hypothesis_tracking']['leading_id']
    wrong = inv.InvestigationDecision(hypothesis='entry HTTP state', hypothesis_id=ident,
        hypothesis_condition=inv.ObservationCondition(operation='dependency_probe', object_name='entry', field='http.status', expected=503),
        next_check='untrusted new check', next_tools=['probe_text_log'],
        next_arguments={'probe_text_log': {'service': 'worker', 'path': 'C:/secret.txt'}},
        discriminating_question='untrusted question', expected_observation='untrusted expectation')
    return state, wrong, add, first


@pytest.mark.parametrize('protection,trigger', [(False, False), (True, False), (False, True), (True, True)])
def test_identity_rejection_continues_previously_saved_check_before_downstream_observation(protection, trigger):
    state, wrong, _, _ = saved_check_fixture(protection, trigger)
    original = deepcopy(state['investigation_memory']['hypothesis_tracking'])
    result = inv.decide_from_evidence(state, wrong, inv.evidence_index(state))
    memory = result['investigation_memory']; tracking = memory['hypothesis_tracking']
    assert result['plan'] == ['inspect saved db'] and 'response' not in result
    assert memory['next_arguments'] == {'probe_dependency_probe': {'dependency': 'db'}}
    assert tracking['identity_issues']
    assert tracking['identity_recovery']['selection']['kind'] == 'saved_candidate_check'
    assert tracking['leading_id'] == original['leading_id']
    assert [c['proposal'] for c in tracking['candidates']] == [c['proposal'] for c in original['candidates']]
    assert [c['birth_step'] for c in tracking['candidates']] == [c['birth_step'] for c in original['candidates']]
    assert memory['model_suggestion'] == wrong.model_dump()
    assert not tracking['events']


@pytest.mark.parametrize('block', ['completed', 'observed', 'failed', 'unavailable', 'cancelled',
    'out_of_scope', 'missing_tool', 'no_parameters', 'dropped', 'excluded', 'noncritical',
    'contradicted', 'expired_protected', 'unresolved_scope', 'wrong_target', 'new_only', 'unsafe_tool', 'invalid_log'])
def test_saved_agenda_recovery_preserves_existing_safety_and_progress_gates(block):
    state, wrong, add, _ = saved_check_fixture()
    candidates = state['investigation_memory']['hypothesis_tracking']['candidates']
    saved = candidates[1]
    if block == 'completed': state['past_steps'].append(('inspect saved db', 'completed'))
    elif block == 'observed': add('dependency_probe', {'dependency': 'db', 'tcp': 'ok'})
    elif block in {'failed', 'unavailable', 'cancelled'}:
        state['raw_evidence'].append(('previous attempt', json.dumps({'data_source': 'tool_execution',
            'tool': 'probe_dependency_probe', 'arguments': {'dependency': 'db'}, 'status': block})))
    elif block == 'out_of_scope': state['target_resolution']['allowed_dependencies'] = ['entry']
    elif block == 'missing_tool': state['investigation_tools'] = []
    elif block == 'no_parameters': saved['check']['next_arguments'] = None
    elif block in {'dropped', 'excluded'}: saved['status'] = block
    elif block == 'noncritical': saved['proposal']['critical'] = False
    elif block == 'contradicted':
        saved['condition'] = {'operation': 'dependency_probe', 'object_name': 'entry', 'field': 'tcp', 'expected': 'failed'}
        saved['condition_binding'] = 'bound'
    elif block == 'expired_protected': saved.update(status='protected', birth_step=0)
    elif block == 'unresolved_scope': state['target_resolution']['status'] = 'ambiguous'
    elif block == 'wrong_target': state['target_resolution']['target_id'] = 'another-host'
    elif block == 'new_only':
        wrong.alternatives = [inv.Alternative.model_validate(saved['proposal'])]
        candidates.pop()
    elif block == 'unsafe_tool':
        saved['check'].update(next_tools=['terminal'], next_arguments={})
        state['investigation_tools'].append({'name': 'terminal'})
    elif block == 'invalid_log':
        saved['check'].update(next_tools=['probe_text_log'],
            next_arguments={'probe_text_log': {'service': 'worker', 'path': 'C:/secret.txt'}})
    result = inv.decide_from_evidence(state, wrong, inv.evidence_index(state))
    assert result['plan'] == [], block
    assert not result['investigation_memory']['hypothesis_tracking'].get('identity_recovery')
    assert '未独立验证' in result['diagnosis']['stop_reason']


@pytest.mark.parametrize('mutation', [None, 'forged_candidate', 'wrong_arguments', 'failed_tool',
    'prior_failure', 'missing_execution', 'changed_candidate', 'dropped_source'])
def test_saved_agenda_audit_binds_previous_candidate_and_exact_successful_execution(mutation):
    state, wrong, _, first = saved_check_fixture()
    state.update(inv.decide_from_evidence(state, wrong, inv.evidence_index(state)))
    snapshots = [first, behavior_snapshot(state, datetime.now(timezone.utc).isoformat())]
    step = state['plan'][0]
    execution = [{'step': step, 'tool': 'probe_dependency_probe', 'arguments': {'dependency': 'db'}, 'status': 'success'}]
    if mutation == 'forged_candidate': snapshots[-1]['tracking']['identity_recovery']['selection']['candidate_id'] = 'invented'
    elif mutation == 'wrong_arguments': execution[0]['arguments']['dependency'] = 'entry'
    elif mutation == 'failed_tool': execution[0]['status'] = 'failed'
    elif mutation == 'prior_failure': snapshots[-1]['behavior_context']['tool_execution_checks'] = [{**execution[0], 'status': 'failed'}]
    elif mutation == 'missing_execution': execution = []
    elif mutation == 'changed_candidate': snapshots[-1]['tracking']['candidates'][1]['birth_step'] = 99
    elif mutation == 'dropped_source': snapshots[0]['tracking']['candidates'][1]['status'] = 'dropped'
    result = audit_behavior(snapshots, ['initial', 'inspect entry', step], execution)
    assert result['status'] == ('failed' if mutation else 'passed'), result
    assert result['executed_changes'] == {'protection': 0, 'contradiction': 0}
    if mutation is None:
        assert result['decisions'][-1]['saved_check_continued'] is True


@pytest.mark.asyncio
@pytest.mark.parametrize('multi', [False, True])
async def test_saved_agenda_survives_json_restore_executes_without_model_then_stops_repeating(monkeypatch, multi):
    state, wrong, _, _ = saved_check_fixture(multi=multi)
    state.update(inv.decide_from_evidence(state, wrong, inv.evidence_index(state)))
    state = json.loads(json.dumps({**state, 'autonomous_investigation': True}))
    ex = importlib.import_module('src.agent.aiops.executor')
    observed = []

    async def probe(dependency: str):
        """Return a constructed healthy dependency; no socket or model operations."""
        observed.append(dependency)
        return evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
                        payload={'dependency': dependency, 'tcp': 'ok', 'http': {'status': 200}})

    tool = StructuredTool.from_function(coroutine=probe, name='probe_dependency_probe')
    async def processes(service: str):
        """Return constructed process evidence without accessing the local system."""
        observed.append(service)
        return evidence(target_id=settings.PROBE_TARGET_ID, operation='processes',
                        payload={'service': service, 'processes': [], 'skipped_count': 0})
    process_tool = StructuredTool.from_function(coroutine=processes, name='probe_process_snapshot')
    monkeypatch.setattr(ex, '_get_tools_for_state', AsyncMock(return_value=([tool, process_tool], None)))
    monkeypatch.setattr(ex, 'create_agent_llm', Mock(side_effect=AssertionError('saved check must execute directly')))
    step = state['plan'][0]
    result, raw = await ex._run_step(step, state)
    assert observed == (['db', 'worker'] if multi else ['db'])
    state['raw_evidence'].append((step, raw))
    state['past_steps'].append((step, result))
    final = inv.decide_from_evidence(state, wrong, inv.evidence_index(state))
    assert final['plan'] == [] and final['diagnosis']['kind'] == 'localized_fault'
    assert not final['investigation_memory']['hypothesis_tracking'].get('identity_recovery')


@pytest.mark.parametrize('protection,trigger', [(False, False), (True, False), (False, True), (True, True)])
def test_id_error_keeps_candidates_and_completes_finite_independent_followups(protection, trigger):
    state, wrong, add, _ = fixture(protection, trigger)
    original = deepcopy(state['investigation_memory']['hypothesis_tracking']['candidates'])
    original_proposal = wrong.model_dump()
    for operation, tool, arguments, payload in [
        ('ports', 'probe_port_snapshot', {'local_port': 5678, 'listening_only': True},
            {'local_port': 5678, 'listening_only': True, 'ports': []}),
        ('processes', 'probe_process_snapshot', {'service': 'worker'},
            {'service': 'worker', 'processes': [], 'skipped_count': 0}),
        ('text_logs', 'probe_text_log', {'service': 'worker', 'path': 'C:/demo/db.log', 'lines': 100},
            {'service': 'worker', 'path': 'C:/demo/db.log', 'line_limit': 100, 'lines': []}),
    ]:
        result = inv.decide_from_evidence(state, wrong, inv.evidence_index(state))
        memory = result['investigation_memory']; tracking = memory['hypothesis_tracking']
        assert result['plan'] == [memory['next_check']] and 'response' not in result
        assert tracking['identity_issues'] and tracking['identity_recovery']
        assert memory['next_tools'] == [tool] and memory['next_arguments'] == {tool: arguments}
        assert memory['model_suggestion'] == original_proposal
        assert tracking['candidates'] == original
        assert not tracking['events']
        assert '继续独立现场补查' in memory['blocked_reason']
        state.update(result)
        state['past_steps'].append((memory['next_check'], 'offline fixture observation'))
        add(operation, payload)
    result = inv.decide_from_evidence(state, wrong, inv.evidence_index(state))
    assert result['plan'] == [] and result['diagnosis']['kind'] == 'localized_fault'
    assert '候选 ID' in result['diagnosis']['stop_reason']
    assert '未独立验证' in result['diagnosis']['stop_reason']
    assert not result['investigation_memory']['hypothesis_tracking'].get('identity_recovery')


@pytest.mark.parametrize('block', ['remote', 'unresolved', 'wrong_target', 'unallowlisted', 'missing_tool', 'already_observed'])
def test_id_error_does_not_grant_new_observation_permissions(block):
    state, wrong, add, _ = fixture()
    if block == 'remote':
        state['raw_evidence'].pop()
        add('dependency_probe', {'dependency': 'db', 'host': 'external.example', 'port': 5678, 'tcp': 'failed'})
    elif block == 'unresolved': state['target_resolution']['status'] = 'ambiguous'
    elif block == 'wrong_target': state['target_resolution']['target_id'] = 'other-target'
    elif block == 'unallowlisted': state['target_resolution']['allowed_dependencies'] = ['entry']
    elif block == 'missing_tool': state['investigation_tools'] = []
    else:
        add('ports', {'local_port': 5678, 'ports': []})
        state['target_resolution']['dependency_services'] = {}
    result = inv.decide_from_evidence(state, wrong, inv.evidence_index(state))
    assert result['plan'] == []
    assert not result['investigation_memory']['hypothesis_tracking'].get('identity_recovery')


@pytest.mark.parametrize('status', ['failed', 'unavailable', 'cancelled'])
def test_failed_independent_checks_are_not_automatically_retried(status):
    state, wrong, _, _ = fixture()
    for tool, args in [('probe_port_snapshot', {'local_port': 5678, 'listening_only': True}),
                       ('probe_process_snapshot', {'service': 'worker'}),
                       ('probe_text_log', {'service': 'worker', 'path': 'C:/demo/db.log', 'lines': 100})]:
        result = inv.decide_from_evidence(state, wrong, inv.evidence_index(state))
        assert result['investigation_memory']['next_tools'] == [tool]
        state.update(result)
        step = state['plan'][0]
        state['past_steps'].append((step, status))
        state['raw_evidence'].append((step, json.dumps({'data_source': 'tool_execution',
            'tool': tool, 'arguments': args, 'status': status, 'reason': 'offline controlled failure'})))
    result = inv.decide_from_evidence(state, wrong, inv.evidence_index(state))
    assert result['plan'] == []
    assert not result['investigation_memory']['hypothesis_tracking'].get('identity_recovery')
    assert '不原样自动重试' in result['response']


@pytest.mark.parametrize('mutation', [None, 'forged_source', 'wrong_arguments', 'failed_tool', 'prior_failure', 'missing_execution', 'changed_candidate'])
def test_followup_audit_requires_unchanged_candidates_scoped_evidence_and_successful_execution(mutation):
    state, wrong, _, first = fixture()
    state.update(inv.decide_from_evidence(state, wrong, inv.evidence_index(state)))
    memory = state['investigation_memory']; step = memory['next_check']
    snapshots = [first, behavior_snapshot(state, datetime.now(timezone.utc).isoformat())]
    execution = [{'step': step, 'tool': 'probe_port_snapshot', 'arguments': {'local_port': 5678, 'listening_only': True}, 'status': 'success'}]
    if mutation == 'forged_source': snapshots[-1]['tracking']['identity_recovery']['selection']['dependency_evidence'] = 'invented'
    if mutation == 'wrong_arguments': execution[0]['arguments']['local_port'] = 9999
    if mutation == 'failed_tool': execution[0]['status'] = 'error'
    if mutation == 'prior_failure': snapshots[-1]['behavior_context']['tool_execution_checks'] = [
        {**execution[0], 'status': 'failed', 'reason': 'previous call failed'}]
    if mutation == 'missing_execution': execution = []
    if mutation == 'changed_candidate': snapshots[-1]['tracking']['candidates'][0]['condition']['object_name'] = 'db'
    result = audit_behavior(snapshots, ['initial', 'inspect entry', step], execution)
    assert result['status'] == ('failed' if mutation else 'passed'), result
    assert result['executed_changes'] == {'protection': 0, 'contradiction': 0}
    assert result['mechanism_effectiveness_verified'] is False


@pytest.mark.asyncio
async def test_saved_recovery_executes_only_the_scoped_check_without_an_executor_model(monkeypatch):
    state, wrong, _, _ = fixture()
    state.update(inv.decide_from_evidence(state, wrong, inv.evidence_index(state)))
    # A checkpoint JSON roundtrip must preserve the same concrete request.
    state = json.loads(json.dumps({**state, 'autonomous_investigation': True}))
    ex = importlib.import_module('src.agent.aiops.executor')
    observed = []

    async def ports(local_port: int, listening_only: bool = True):
        """Return constructed port evidence without accessing the local system."""
        observed.append((local_port, listening_only))
        return evidence(target_id=settings.PROBE_TARGET_ID, operation='ports',
                        payload={'local_port': local_port, 'listening_only': listening_only, 'ports': []})

    tool = StructuredTool.from_function(coroutine=ports, name='probe_port_snapshot')
    monkeypatch.setattr(ex, '_get_tools_for_state', AsyncMock(return_value=([tool], None)))
    model = Mock(side_effect=AssertionError('independent concrete check must not call a model'))
    monkeypatch.setattr(ex, 'create_agent_llm', model)
    step = state['plan'][0]
    _, raw = await ex._run_step(step, state)
    assert observed == [(5678, True)]
    model.assert_not_called()
    checks = inv.execution_checks({'raw_evidence': [(step, raw)]})
    assert len(checks) == 1 and checks[0]['status'] == 'success'
    assert checks[0]['arguments'] == {'local_port': 5678, 'listening_only': True}
