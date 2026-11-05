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
def test_configuration_crosscheck_requires_allowed_clue_and_never_retries(protection, trigger):
    state, _, add, _ = fixture(protection, trigger)
    state['raw_evidence'] = []
    state['investigation_tools'].append({'name': 'probe_config_snapshot'})
    add('inventory', {'configured_services': {'worker': {'configuration_available': True}}})
    add('text_logs', {'service': 'worker', 'path': 'C:/demo/db.log', 'lines': [json.dumps({
        'error_type': 'ValueError', 'configuration': {'field': 'max_attempts', 'value': 'invalid'}})]})
    records = inv.evidence_index(state)
    policy = inv.dependency_followup_policy(state, records)
    assert policy['selection']['kind'] == 'configuration_log_crosscheck'
    check = policy['check']
    assert check['next_arguments'] == {'probe_config_snapshot': {'service': 'worker'}}
    assert policy['selection']['dependency_evidence']
    from src.agent.aiops.probe_checks import arguments_error
    assert arguments_error('probe_config_snapshot', {'service': 'other'}, state, records)
    assert arguments_error('probe_config_snapshot', {'service': 'worker', 'path': 'C:/secret'}, state, records)
    outside = deepcopy(state)
    outside['target_resolution']['allowed_services'] = []
    assert inv.dependency_followup_policy(outside, inv.evidence_index(outside)) is None
    missing = deepcopy(state)
    inventory = json.loads(missing['raw_evidence'][0][1])
    inventory['payload']['configured_services']['worker']['configuration_available'] = False
    from src.probe.protocol import raw_hash
    inventory['raw_hash'] = raw_hash(inventory['payload'])
    missing['raw_evidence'][0] = ('inventory', json.dumps(inventory))
    assert inv.dependency_followup_policy(missing, inv.evidence_index(missing)) is None
    assert arguments_error('probe_config_snapshot', {'service': 'worker'}, missing, inv.evidence_index(missing))
    no_clue = deepcopy(state)
    no_clue['raw_evidence'] = no_clue['raw_evidence'][:1]
    assert inv.dependency_followup_policy(no_clue, inv.evidence_index(no_clue)) is None
    state['past_steps'].append((check['next_check'], 'read failed'))
    assert inv.dependency_followup_policy(state, records) is None
    state['past_steps'].pop()
    failed = deepcopy(state)
    failed['raw_evidence'].append(('failed configuration', json.dumps({'data_source': 'tool_execution',
        'tool': 'probe_config_snapshot', 'arguments': {'service': 'worker'},
        'status': 'failed', 'reason': 'access denied'})))
    assert inv.dependency_followup_policy(failed, inv.evidence_index(failed)) is None
    add('configuration', {'service': 'worker', 'values': {'max_attempts': 'invalid'}, 'source_sha256': 'abc'})
    records = inv.evidence_index(state)
    assert inv.dependency_followup_policy(state, records) is None
    assert any('独立配置快照' in note and 'max_attempts' in note for note in inv.log_observation_notes(records, state))


@pytest.mark.asyncio
@pytest.mark.parametrize('protection,trigger', [(False, False), (True, False), (False, True), (True, True)])
@pytest.mark.parametrize('second_invalid', [False, True])
@pytest.mark.parametrize('conflict', ['field', 'expected'])
async def test_live_identity_error_gets_one_correction_without_mutating_saved_state(monkeypatch, second_invalid, protection, trigger, conflict):
    state, wrong, _, first = saved_check_fixture(protection, trigger)
    if conflict == 'expected':
        wrong.hypothesis_condition.field = 'tcp'
        wrong.hypothesis_condition.expected = 'failed'
    state['past_steps'].append(('inspect saved db', 'already checked'))
    before = deepcopy(state)
    corrected = wrong.model_copy(deep=True)
    corrected.hypothesis_id = ''
    corrected.next_check = 'inspect db after correction'
    corrected.next_tools = ['probe_dependency_probe']
    corrected.next_arguments = {'probe_dependency_probe': {'dependency': 'db'}}
    corrected.discriminating_question = 'db reachable?'
    corrected.expected_observation = 'db TCP and HTTP status'
    invoke = AsyncMock(side_effect=[wrong, wrong if second_invalid else corrected])
    monkeypatch.setattr(inv, 'ainvoke_structured', invoke)
    monkeypatch.setattr(inv, 'create_agent_llm', Mock())
    result = await inv.InvestigationStrategy().decide(state)
    assert invoke.await_count == 2
    assert state == before
    assert wrong.model_dump() == json.loads(invoke.call_args.args[3]['identity_feedback'])['rejected_model_suggestion']
    assert 'identity_feedback' in invoke.call_args.args[2].input_variables
    formatted = invoke.call_args.args[2].format_messages(**invoke.call_args.args[3])
    assert 'rejected_model_suggestion' in formatted[-1].content
    correction = result['investigation_memory']['identity_correction']
    assert correction['attempts'] == 1
    assert correction['status'] == ('identity_rejected' if second_invalid else 'corrected')
    assert correction['conflicts'][0]['saved_condition']['field'] == 'tcp'
    assert correction['conflicts'][0]['proposed_condition']['field'] == ('tcp' if conflict == 'expected' else 'http.status')
    if conflict == 'expected':
        assert correction['conflicts'][0]['proposed_condition']['expected'] == 'failed'
        assert correction['conflicts'][0]['saved_condition']['expected'] == 'ok'
    tracking = result['investigation_memory']['hypothesis_tracking']
    if second_invalid:
        assert result['plan'] == []
        assert tracking['identity_issues']
        for actual, original in zip(tracking['candidates'], before['investigation_memory']['hypothesis_tracking']['candidates']):
            for key in ('id', 'condition', 'birth_step', 'check', 'proposal'):
                assert actual[key] == original[key]
        assert '纠正一次后仍未通过' in result['response']
    else:
        assert result['plan'] == ['inspect db after correction']
        assert not tracking['identity_issues']
        old = before['investigation_memory']['hypothesis_tracking']['candidates'][0]
        saved = next(c for c in tracking['candidates'] if c['id'] == old['id'])
        assert saved['condition'] == old['condition'] and saved['birth_step'] == old['birth_step']
    final = behavior_snapshot({**state, **result}, datetime.now(timezone.utc).isoformat())
    audit = audit_behavior([first, final], [name for name, _ in state['past_steps']])
    assert audit['status'] == 'passed', audit
    assert audit['executed_changes'] == {'protection': 0, 'contradiction': 0}
    for mutation in ('attempts', 'conflicts', 'status'):
        forged = deepcopy(final)
        forged['behavior_context']['identity_correction'][mutation] = {
            'attempts': 2, 'conflicts': [], 'status': 'invented'}[mutation]
        assert audit_behavior([first, forged], [name for name, _ in state['past_steps']])['status'] == 'failed'


@pytest.mark.asyncio
@pytest.mark.parametrize('error_kind', ['timeout', 'budget', 'invalid_output', 'truncated'])
async def test_identity_correction_failure_preserves_evidence_and_does_not_retry(monkeypatch, error_kind):
    import httpx
    from openai import APIStatusError
    from src.agent.aiops.structured import StructuredOutputError
    state, wrong, _, first = saved_check_fixture()
    state['past_steps'].append(('inspect saved db', 'already checked'))
    before = deepcopy(state)
    errors = {
        'timeout': httpx.ReadTimeout('constructed outage'),
        'budget': APIStatusError('budget gate', response=httpx.Response(402,
            request=httpx.Request('POST', 'https://example.invalid')),
            body={'error': {'type': 'evaluation_budget_exceeded', 'code': 'per_run_cost_limit'}}),
        'invalid_output': StructuredOutputError('invalid decision'),
        'truncated': StructuredOutputError('truncated', code='output_truncated')}
    invoke = AsyncMock(side_effect=[wrong, errors[error_kind]])
    monkeypatch.setattr(inv, 'ainvoke_structured', invoke)
    monkeypatch.setattr(inv, 'create_agent_llm', Mock())
    result = await inv.InvestigationStrategy().decide(state)
    assert invoke.await_count == 2 and state == before
    assert result['plan'] == [] and result['investigation_failure']
    memory = result['investigation_memory']
    assert memory['model_suggestion'] == wrong.model_dump()
    assert memory['identity_correction']['status'] == result['investigation_failure']['code']
    final = behavior_snapshot({**state, **result}, datetime.now(timezone.utc).isoformat())
    audit = audit_behavior([first, final], [name for name, _ in state['past_steps']])
    assert audit['status'] == 'passed', audit


@pytest.mark.asyncio
async def test_corrected_check_survives_json_restore_and_executes_without_another_model(monkeypatch):
    state, wrong, _, _ = saved_check_fixture()
    state['past_steps'].append(('inspect saved db', 'already checked'))
    corrected = wrong.model_copy(deep=True)
    corrected.hypothesis_id = ''
    corrected.next_check = 'inspect db after correction'
    corrected.next_tools = ['probe_dependency_probe']
    corrected.next_arguments = {'probe_dependency_probe': {'dependency': 'db'}}
    corrected.discriminating_question = 'db reachable?'
    corrected.expected_observation = 'db TCP status'
    invoke = AsyncMock(side_effect=[wrong, corrected])
    monkeypatch.setattr(inv, 'ainvoke_structured', invoke)
    monkeypatch.setattr(inv, 'create_agent_llm', Mock())
    result = await inv.InvestigationStrategy().decide(state)
    restored = json.loads(json.dumps({**state, **result, 'autonomous_investigation': True}))
    ex = importlib.import_module('src.agent.aiops.executor')
    observed = []

    async def probe(dependency: str):
        """Return constructed dependency evidence without network access."""
        observed.append(dependency)
        return evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
            payload={'dependency': dependency, 'tcp': 'ok', 'http': {'status': 200}})

    tool = StructuredTool.from_function(coroutine=probe, name='probe_dependency_probe')
    monkeypatch.setattr(ex, '_get_tools_for_state', AsyncMock(return_value=([tool], None)))
    monkeypatch.setattr(ex, 'create_agent_llm', Mock(side_effect=AssertionError('concrete check must execute directly')))
    await ex._run_step(restored['plan'][0], restored)
    assert observed == ['db'] and invoke.await_count == 2
    assert restored['investigation_memory']['identity_correction']['status'] == 'corrected'


@pytest.mark.asyncio
async def test_live_identity_error_uses_safe_saved_check_without_extra_model_call(monkeypatch):
    state, wrong, _, _ = saved_check_fixture()
    invoke = AsyncMock(return_value=wrong)
    monkeypatch.setattr(inv, 'ainvoke_structured', invoke)
    monkeypatch.setattr(inv, 'create_agent_llm', Mock())
    result = await inv.InvestigationStrategy().decide(state)
    assert invoke.await_count == 1
    assert result['plan'] == ['inspect saved db']
    assert 'identity_correction' not in result['investigation_memory']


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


def test_identity_rejection_allows_wider_read_of_same_mapped_log():
    state, wrong, add, _ = fixture()
    add('ports', {'local_port': 5678, 'listening_only': True, 'ports': []})
    add('processes', {'service': 'worker', 'processes': [], 'skipped_count': 0})
    add('text_logs', {'service': 'worker', 'path': 'C:/demo/db.log', 'line_limit': 20, 'lines': []})
    before = deepcopy(state['investigation_memory']['hypothesis_tracking']['candidates'])

    result = inv.decide_from_evidence(state, wrong, inv.evidence_index(state))

    memory = result['investigation_memory']
    tracking = memory['hypothesis_tracking']
    assert result['plan'] == [memory['next_check']]
    assert tracking['identity_issues']
    assert tracking['identity_recovery']['selection']['kind'] == 'failed_dependency_mapped_check'
    assert memory['next_tools'] == ['probe_text_log']
    assert memory['next_arguments'] == {'probe_text_log': {
        'service': 'worker', 'path': 'C:/demo/db.log', 'lines': 100}}
    assert tracking['candidates'] == before
    assert memory['model_suggestion'] == wrong.model_dump()

    state.update(result)
    add('text_logs', {'service': 'worker', 'path': 'C:/demo/db.log', 'line_limit': 100, 'lines': []})
    repeated = inv.decide_from_evidence(state, wrong, inv.evidence_index(state))
    assert repeated['plan'] == []


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
