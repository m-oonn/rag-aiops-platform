"""Concrete questions, arguments and evidence consumption without paid calls."""
import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.tools import StructuredTool

from src.agent.aiops.strategies import investigation as inv
from src.probe.protocol import evidence
from src.settings import settings


def state(*values):
    return {'input': 'entry unavailable', 'past_steps': [],
        'investigation_config': {'hypothesis_protection': False, 'contradiction_trigger': False, 'protection_steps': 2},
        'investigation_tools': [{'name': name} for name in ('probe_dependency_probe', 'probe_text_log')],
        'raw_evidence': [('check', json.dumps(evidence(target_id=settings.PROBE_TARGET_ID,
            operation=operation, payload=payload))) for operation, payload in values]}


def decision(**overrides):
    return inv.InvestigationDecision(**{'hypothesis': 'unknown', 'next_check': 'inspect entry',
        'next_tools': ['probe_dependency_probe'], 'next_arguments': {'probe_dependency_probe': {'dependency': 'entry'}},
        'discriminating_question': 'is the entry reachable?', 'expected_observation': 'TCP and HTTP response', **overrides})


def decide(current, answer):
    return inv.decide_from_evidence(current, answer, inv.evidence_index(current))


@pytest.mark.parametrize('main_error', ['missing_tool', 'completed'])
def test_unexecutable_main_check_uses_current_valid_alternative(main_error):
    current = state()
    answer = decision()
    if main_error == 'missing_tool':
        answer.next_tools = ['missing_probe']
        answer.next_arguments = {}
    else:
        current['past_steps'] = [(answer.next_check, 'already completed')]
    alternative = inv.Alternative(explanation='dependency_probe/entry: tcp == "failed"', status='unresolved',
        condition=inv.ObservationCondition(operation='dependency_probe', object_name='entry', field='tcp', expected='failed'),
        check=inv.CandidateCheck(next_check='differentiate entry', next_tools=['probe_dependency_probe'],
            next_arguments={'probe_dependency_probe': {'dependency': 'entry'}},
            discriminating_question='is the entry reachable?', expected_observation='TCP outcome'))
    answer.alternatives = [alternative]
    result = decide(current, answer)
    assert result['plan'] == ['differentiate entry']
    assert result['investigation_memory']['next_arguments'] == alternative.check.next_arguments
    assert result['investigation_memory']['model_suggestion']['next_check'] == 'inspect entry'


def test_missing_prose_does_not_block_an_executable_argument_map():
    """The argument map names the query; the prose only restates it."""
    answer = decision(discriminating_question='', expected_observation='')
    result = decide(state(), answer)
    assert result['plan'] == ['inspect entry']
    assert result['investigation_memory']['next_arguments'] == {
        'probe_dependency_probe': {'dependency': 'entry'}}


def test_blocked_check_does_not_claim_global_exhaustion():
    result = decide(state(), decision(next_tools=['missing_probe'], next_arguments={}))
    assert not result['plan']
    assert '未独立验证其余可用检查' in result['diagnosis']['stop_reason']
    assert '受阻' in result['response']


@pytest.mark.parametrize('matched,skipped,truncated', [(0, 0, False), (300, 0, True), (0, 2, False)])
def test_process_coverage_separates_matching_from_return_limit(matched, skipped, truncated):
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='processes', truncated=truncated,
        payload={'service': 'entry', 'selection': 'top_accessible_processes', 'inspected_count': 400,
            'matched_count': matched, 'skipped_count': skipped, 'processes': []})
    current = state()
    current['raw_evidence'] = [('process query', json.dumps(raw))]
    records = inv.evidence_index(current)
    note, = inv.process_query_notes(records, current)
    assert f'匹配{matched}' in note and f'跳过{skipped}' in note
    assert f'截断={"是" if truncated else "否"}' in note
    assert '不是只检查前256' in note and '不能证明启动或退出历史' in note
    context = inv.investigation_context(current, records)
    assert '截断前匹配数' in context['e1.1']['selection_semantics']
    result = decide(current, decision(next_check='', next_tools=[], next_arguments={}))
    assert result['diagnosis']['observation_notes'] == [note]
    assert note in result['response']


def test_decision_preserves_concrete_arguments_and_consumes_same_query_after_rephrasing():
    answer = decision()
    first = decide(state(), answer)
    assert first['investigation_memory']['next_arguments'] == answer.next_arguments
    current = state(('dependency_probe', {'dependency': 'entry', 'tcp': 'ok', 'http': {'status': 503}}))
    result = decide(current, decision(next_check='check entry one more time'))
    assert result['plan'] == []
    assert '已有' in result['diagnosis']['stop_reason']
    assert result['diagnosis']['kind'] == 'localized_fault'
    assert result['investigation_memory']['check_progress'][0]['evidence_ids'] == ['e1.1']


@pytest.mark.parametrize('reason,ids,allowed', [('', [], False), ('verify recovery', [], False),
    ('verify recovery', ['invented'], False), ('verify recovery', ['e1.1'], True)])
def test_same_query_requires_explicit_repeat_purpose_bound_to_existing_evidence(reason, ids, allowed):
    current = state(('dependency_probe', {'dependency': 'entry', 'tcp': 'failed'}))
    result = decide(current, decision(repeat_reason=reason, repeat_evidence_ids=ids))
    assert bool(result['plan']) is allowed


def test_consumed_primary_check_does_not_hide_unexecuted_alternative():
    current = state(('dependency_probe', {'dependency': 'entry', 'tcp': 'ok'}))
    answer = decision(alternatives=[inv.Alternative(explanation='downstream unreachable', status='unresolved',
        condition=inv.ObservationCondition(operation='dependency_probe', object_name='downstream', field='tcp', expected='failed'),
        check=inv.CandidateCheck(next_check='inspect downstream', next_tools=['probe_dependency_probe'],
            next_arguments={'probe_dependency_probe': {'dependency': 'downstream'}},
            discriminating_question='downstream reachable?', expected_observation='TCP response'))])
    result = decide(current, answer)
    assert result['plan'] == ['inspect downstream']
    assert result['investigation_memory']['next_arguments'] == {'probe_dependency_probe': {'dependency': 'downstream'}}


def test_stated_repeat_cannot_bypass_third_unchanged_query_limit():
    current = state(*[('dependency_probe', {'dependency': 'entry', 'tcp': 'failed'})] * 2)
    result = decide(current, decision(repeat_reason='verify recovery', repeat_evidence_ids=['e2.1']))
    assert not result['plan'] and 'raw_hash 未变化' in result['response']


def test_failed_tool_attempt_is_consumed_even_without_probe_observation():
    current = state()
    current['raw_evidence'] = [('old question', json.dumps({'data_source': 'tool_execution',
        'tool': 'probe_dependency_probe', 'arguments': {'dependency': 'entry'},
        'status': 'failed', 'reason': 'connection_error'}))]
    result = decide(current, decision(next_check='a rephrased question'))
    assert not result['plan'] and 'connection_error' in result['response']
    assert result['investigation_memory']['check_progress'][0]['status'] == 'unavailable'
    assert decide(current, decision(next_arguments={'probe_dependency_probe': {'dependency': 'downstream'}}))['plan']


@pytest.mark.parametrize('args', [{'service': 'entry', 'path': r'D:\logs\app.log', 'lines': None},
                                  {'service': 'entry', 'path': r'D:\logs\app.log', 'lines': True}])
def test_null_or_boolean_log_limit_is_rejected(args):
    result = decide(state(), decision(next_tools=['probe_text_log'], next_arguments={'probe_text_log': args}))
    assert not result['plan']


def test_new_log_path_and_line_window_remain_executable():
    current = state(('text_logs', {'service': 'entry', 'path': r'D:\logs\app.log', 'line_limit': 100, 'lines': []}))
    for args in [{'service': 'entry', 'path': r'D:\logs\other.log'},
                 {'service': 'entry', 'path': r'D:\logs\app.log', 'lines': 200}]:
        assert decide(current, decision(next_tools=['probe_text_log'], next_arguments={'probe_text_log': args}))['plan']


def test_fresh_model_missing_arguments_stops_and_preserves_original_proposal():
    proposed = decision(next_arguments=None)
    result = inv.decide_from_evidence(state(), proposed, {}, require_concrete_checks=True)
    assert not result['plan']
    assert '参数' in result['diagnosis']['stop_reason']
    assert result['investigation_memory']['model_suggestion']['next_arguments'] is None
    assert proposed.next_arguments is None


def test_unknown_tool_argument_mapping_returns_report_instead_of_keyerror():
    result = decide(state(), decision(next_arguments={'invented_tool': {}}))
    assert not result['plan'] and '参数' in result['diagnosis']['stop_reason']


def test_fake_probe_suffix_is_rejected_before_any_tool_plan():
    result = decide(state(), decision(next_arguments={
        'probe_dependency_probe': {'dependency': 'entry'},
        'probe_dependency_probe_2': {'dependency': 'downstream'},
    }))
    assert not result['plan']
    assert '不存在的 Probe 工具名' in result['diagnosis']['stop_reason']
    assert 'probe_dependency_probe_2' in result['diagnosis']['stop_reason']


def test_valid_probe_arguments_complete_omitted_tool_name():
    result = decide(state(), decision(
        next_tools=[],
        next_arguments={'probe_dependency_probe': {'dependency': 'entry'}},
    ))
    assert result['plan'] == ['inspect entry']
    assert result['investigation_memory']['next_tools'] == ['probe_dependency_probe']


@pytest.mark.parametrize('actual,expected', [({'local_port': 9001}, False),
    ({'local_port': 9000, 'limit': 100}, False), ({'local_port': 9000, 'limit': 256, 'listening_only': False}, True)])
def test_behavior_execution_requires_actual_query_arguments(actual, expected):
    from scripts.mechanism_behavior import _executed_candidate
    candidate = {'condition': {'operation': 'ports', 'object_name': '9000'}}
    check = {'next_check': 'listener', 'next_tools': ['probe_port_snapshot'],
             'next_arguments': {'probe_port_snapshot': {'local_port': 9000}}}
    executions = [{'step': 'listener', 'tool': 'probe_port_snapshot', 'arguments': actual, 'status': 'success'}]
    assert _executed_candidate(candidate, check, executions) is expected


@pytest.mark.parametrize('args', [{}, {'dependency': 'entry', 'host': 'outside'}, {'dependency': 1}])
def test_incomplete_or_invalid_probe_parameters_stop_before_tool_execution(args):
    result = decide(state(), decision(next_arguments={'probe_dependency_probe': args}))
    assert result['plan'] == []
    assert '参数' in result['diagnosis']['stop_reason']


def test_process_application_does_not_schedule_windows_service_query():
    current = state(('inventory', {'configured_services': {'entry': {'kind': 'process'}}}))
    current['investigation_tools'].append({'name': 'probe_service_status'})
    result = decide(current, decision(next_tools=['probe_service_status'],
        next_arguments={'probe_service_status': {'service': 'entry'}}))
    assert not result['plan']
    assert '不适用' in result['diagnosis']['stop_reason']


@pytest.mark.parametrize('stop_mode', ['blocked', 'model_stops'])
def test_inapplicable_main_check_continues_saved_unfinished_candidate(stop_mode):
    current = state(('inventory', {'configured_services': {
        'entry': {'kind': 'process'}, 'worker': {'kind': 'process'}}}))
    current['investigation_tools'].extend([{'name': 'probe_service_status'},
                                           {'name': 'probe_process_snapshot'}])
    saved = inv.InvestigationDecision(hypothesis='dependency_probe/entry: tcp == "failed"',
        hypothesis_condition=inv.ObservationCondition(operation='dependency_probe', object_name='entry',
                                                       field='tcp', expected='failed'),
        alternatives=[inv.Alternative(explanation='processes/worker: process_present == false',
            status='unresolved', claim_type='observed_condition',
            condition=inv.ObservationCondition(operation='processes', object_name='worker',
                                               field='process_present', expected=False),
            check=inv.CandidateCheck(next_check='inspect worker process',
                next_tools=['probe_process_snapshot'],
                next_arguments={'probe_process_snapshot': {'service': 'worker'}},
                discriminating_question='is worker present?', expected_observation='configured process result'))])
    current.update(decide(current, saved))
    current['past_steps'].append(('inspect entry', 'entry failed'))
    proposed = decision(next_check='inspect worker service', next_tools=['probe_service_status'],
        next_arguments={'probe_service_status': {'service': 'worker'}},
        discriminating_question='is worker service running?', expected_observation='service state')
    if stop_mode == 'model_stops':
        proposed.next_check, proposed.next_tools, proposed.next_arguments = '', [], None
    result = decide(current, proposed)
    assert result['plan'] == ['inspect worker process']
    assert result['investigation_memory']['next_arguments'] == {
        'probe_process_snapshot': {'service': 'worker'}}
    assert '此前保存' in result['investigation_memory']['validation_issues'][-1]


@pytest.mark.parametrize('invalidity', ['completed', 'failed', 'contradicted', 'expired', 'out_of_scope'])
def test_blocked_check_recovery_skips_stale_saved_candidate_and_uses_next_valid_one(invalidity):
    invalid_check_name = 'inspect worker process'
    current = state()
    current['investigation_tools'].append({'name': 'probe_process_snapshot'})
    if invalidity == 'completed':
        current['past_steps'] = [(invalid_check_name, 'previously executed')]
    elif invalidity == 'failed':
        current['raw_evidence'].append(('failed process check', json.dumps({
            'data_source': 'tool_execution', 'tool': 'probe_process_snapshot',
            'arguments': {'service': 'worker'}, 'status': 'failed', 'reason': 'permission denied'})))
    elif invalidity == 'contradicted':
        current['raw_evidence'].append(('worker process found', json.dumps(evidence(
            target_id=settings.PROBE_TARGET_ID, operation='processes', payload={
                'service': 'worker', 'selection': 'top_accessible_processes',
                'inspected_count': 1, 'matched_count': 1, 'skipped_count': 0,
                'processes': [{'pid': 42, 'name': 'worker.exe'}]}))))
    elif invalidity == 'expired':
        current['past_steps'] = [('one', 'done'), ('two', 'done')]
        current['investigation_config']['protection_steps'] = 2
    elif invalidity == 'out_of_scope':
        current['target_resolution'] = {'status': 'resolved', 'allowed_services': ['entry']}

    def candidate(name, service, expected=False, status='active', birth_step=0):
        condition = inv.ObservationCondition(operation='processes', object_name=service,
            field='process_present', expected=expected)
        proposal = inv.Alternative(explanation=inv.condition_statement(condition),
            claim_type='observed_condition', status='unresolved', condition=condition,
            check=inv.CandidateCheck(next_check=name, next_tools=['probe_process_snapshot'],
                next_arguments={'probe_process_snapshot': {'service': service}},
                discriminating_question=f'is {service} present?', expected_observation='configured process result'))
        return {'id': service, 'birth_step': birth_step, 'status': status,
            'condition_binding': 'bound', 'condition': condition.model_dump(),
            'explanation': proposal.explanation, 'proposal': proposal.model_dump(),
            'check': proposal.check.model_dump(), 'seen_observations': []}

    invalid_status = 'protected' if invalidity == 'expired' else 'active'
    valid_candidate = candidate('inspect entry process', 'entry')
    current['investigation_memory'] = {'hypothesis_tracking': {'candidates': [
        candidate(invalid_check_name, 'worker', status=invalid_status), valid_candidate]}}
    fallback = inv._blocked_check_candidate_followup(current, inv.evidence_index(current))
    assert fallback['check']['next_check'] == 'inspect entry process'
    assert fallback['selection']['candidate_id'] == 'entry'


def test_blocked_check_stop_records_why_saved_candidate_cannot_be_reused():
    current = state(('inventory', {'configured_services': {
        'entry': {'kind': 'process'}, 'worker': {'kind': 'process'}}}))
    current['investigation_tools'].extend([{'name': 'probe_service_status'},
                                           {'name': 'probe_process_snapshot'}])
    current['past_steps'].append(('inspect worker process', 'already executed'))
    condition = inv.ObservationCondition(operation='processes', object_name='worker',
        field='process_present', expected=False)
    saved = inv.Alternative(explanation=inv.condition_statement(condition), status='unresolved',
        claim_type='observed_condition', condition=condition,
        check=inv.CandidateCheck(next_check='inspect worker process', next_tools=['probe_process_snapshot'],
            next_arguments={'probe_process_snapshot': {'service': 'worker'}},
            discriminating_question='is worker present?', expected_observation='configured process result'))
    current['investigation_memory'] = {'hypothesis_tracking': {'candidates': [{
        'id': 'worker-process', 'birth_step': 0, 'status': 'active', 'condition_binding': 'bound',
        'condition': condition.model_dump(), 'explanation': saved.explanation,
        'proposal': saved.model_dump(), 'check': saved.check.model_dump(), 'seen_observations': []}]}}
    result = decide(current, decision(next_check='inspect worker service', next_tools=['probe_service_status'],
        next_arguments={'probe_service_status': {'service': 'worker'}}))
    memory = result['investigation_memory']
    assert result['plan'] == []
    assert memory['next_check'] == ''
    assert memory['hypothesis_tracking']['blocked_check_review']['kind'] == 'no_eligible_saved_candidate'
    assert '该检查步骤此前已执行' in memory['blocked_reason']
    assert '不代表所有可能检查已穷尽' in memory['blocked_reason']
    assert not result['diagnosis']['stop_reason'].startswith('模型停止建议')


@pytest.mark.parametrize('model_stops', [False, True])
def test_blocked_check_fallback_is_reconstructed_by_behavior_audit(model_stops):
    from datetime import datetime, timezone
    from scripts.mechanism_behavior import audit_behavior, behavior_snapshot

    current = state(('inventory', {'configured_services': {
        'entry': {'kind': 'process'}, 'worker': {'kind': 'process'}}}))
    current['investigation_tools'].extend([{'name': 'probe_service_status'},
                                           {'name': 'probe_process_snapshot'}])
    saved = inv.InvestigationDecision(hypothesis='dependency_probe/entry: tcp == "failed"',
        hypothesis_condition=inv.ObservationCondition(operation='dependency_probe', object_name='entry',
                                                       field='tcp', expected='failed'),
        alternatives=[inv.Alternative(explanation='processes/worker: process_present == false',
            status='unresolved', claim_type='observed_condition',
            condition=inv.ObservationCondition(operation='processes', object_name='worker',
                                               field='process_present', expected=False),
            check=inv.CandidateCheck(next_check='inspect worker process',
                next_tools=['probe_process_snapshot'],
                next_arguments={'probe_process_snapshot': {'service': 'worker'}},
                discriminating_question='is worker present?', expected_observation='configured process result'))])
    first = decide(current, saved)
    current.update(first)
    now = datetime.now(timezone.utc).isoformat()
    snapshots = [behavior_snapshot(current, now)]
    current['past_steps'].append(('inspect entry', 'entry probe completed'))
    proposed = decision(next_check='inspect worker service', next_tools=['probe_service_status'],
        next_arguments=None,
        discriminating_question='is worker service running?', expected_observation='service state')
    if model_stops:
        proposed.next_check, proposed.next_tools, proposed.next_arguments = '', [], None
    current.update(inv.decide_from_evidence(current, proposed, inv.evidence_index(current),
                                            require_concrete_checks=True))
    snapshots.append(behavior_snapshot(current, datetime.now(timezone.utc).isoformat()))
    executions = [
        {'step': 'inspect entry', 'tool': 'probe_dependency_probe',
         'arguments': {'dependency': 'entry'}, 'status': 'success'},
        {'step': 'inspect worker process', 'tool': 'probe_process_snapshot',
         'arguments': {'service': 'worker'}, 'status': 'success'},
    ]
    result = audit_behavior(snapshots, ['inspect entry', 'inspect worker process'], executions)
    assert result['status'] == 'passed', result


def test_verified_observation_condition_is_not_reported_as_unresolved():
    current = state(('processes', {'service': 'entry', 'selection': 'top_accessible_processes',
        'inspected_count': 20, 'matched_count': 1, 'skipped_count': 0,
        'processes': [{'pid': 123, 'name': 'python.exe'}]}),
        ('ports', {'local_port': 14106, 'listening_only': True, 'matched_count': 1,
                   'ports': [{'status': 'LISTEN', 'local': {'port': 14106}}]}))
    conditions = [
        inv.ObservationCondition(operation='processes', object_name='entry',
                                field='process_present', expected=False),
        inv.ObservationCondition(operation='ports', object_name='14106',
                                field='listening', expected=False),
    ]
    answer = decision(next_check='', next_tools=[], next_arguments={}, alternatives=[
        inv.Alternative(explanation=inv.condition_statement(condition), status='unresolved',
            claim_type='observed_condition', condition=condition)
        for condition in conditions])
    result = decide(current, answer)
    alternatives = result['diagnosis']['alternatives']
    assert [alternative['status'] for alternative in alternatives] == ['excluded', 'excluded']
    assert all(alternative['verification'] == 'predicate_verified' for alternative in alternatives)
    assert all(alternative['evidence'] and all(len(citation['quote']) < 250
               for citation in alternative['evidence']) for alternative in alternatives)
    assert all(question['question'] not in {a['explanation'] for a in alternatives}
               for question in result['diagnosis']['unresolved_questions'])


@pytest.mark.asyncio
async def test_concrete_executor_runs_exact_query_without_model_reselection(monkeypatch):
    ex = importlib.import_module('src.agent.aiops.executor')
    async def probe(dependency: str):
        """Return a constructed observation."""
        return evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
                        payload={'dependency': dependency, 'tcp': 'failed'})
    schema = StructuredTool.from_function(coroutine=probe, name='probe_dependency_probe')
    async def invoke(args):
        return await probe(**args)
    tool = SimpleNamespace(name=schema.name, description=schema.description, args=schema.args,
        ainvoke=AsyncMock(side_effect=invoke))
    monkeypatch.setattr(ex, '_get_tools_for_state', AsyncMock(return_value=([tool], None)))
    model = Mock(side_effect=AssertionError('concrete check must not call model'))
    monkeypatch.setattr(ex, 'create_agent_llm', model)
    current = {**state(), 'autonomous_investigation': True, 'investigation_memory': decision().model_dump()}
    result, raw = await ex._run_step('inspect entry', current)
    tool.ainvoke.assert_awaited_once_with({'dependency': 'entry'})
    model.assert_not_called()
    assert '已执行' in result
    checks = inv.execution_checks({'raw_evidence': [('inspect entry', raw)]})
    assert len(checks) == 1 and checks[0]['status'] == 'success'
    assert checks[0]['question'] == current['investigation_memory']['discriminating_question']
    assert ex._probe_request_limit({'name': tool.name, 'args': {'dependency': 'other'}}, current) == 'planned_probe_arguments_mismatch'


@pytest.mark.asyncio
async def test_unavailable_event_query_runs_alternative_and_consumes_result(monkeypatch):
    ex = importlib.import_module('src.agent.aiops.executor')
    current = state(('inventory', {'configured_services': {'entry': {'event_logs_available': False}}}))
    current['investigation_tools'].append({'name': 'probe_event_log'})
    alternative = inv.Alternative(explanation='dependency_probe/entry: tcp == \"failed\"',
        claim_type='observed_condition', status='unresolved',
        condition=inv.ObservationCondition(operation='dependency_probe', object_name='entry', field='tcp', expected='failed'),
        check=inv.CandidateCheck(next_check='inspect entry connectivity', next_tools=['probe_dependency_probe'],
            next_arguments={'probe_dependency_probe': {'dependency': 'entry'}},
            discriminating_question='entry reachable?', expected_observation='TCP and HTTP'))
    scheduled = decide(current, decision(next_check='query entry events', next_tools=['probe_event_log'],
        next_arguments={'probe_event_log': {'service': 'entry'}}, alternatives=[alternative]))
    assert scheduled['plan'] == ['inspect entry connectivity']
    async def probe(dependency: str):
        return evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
                        payload={'dependency': dependency, 'tcp': 'failed'})
    schema = StructuredTool.from_function(coroutine=probe, name='probe_dependency_probe', description='fixture')
    async def invoke(args):
        return await probe(**args)
    tool = SimpleNamespace(name=schema.name, description=schema.description, args=schema.args,
        ainvoke=AsyncMock(side_effect=invoke))
    monkeypatch.setattr(ex, '_get_tools_for_state', AsyncMock(return_value=([tool], None)))
    monkeypatch.setattr(ex, 'create_agent_llm', Mock(side_effect=AssertionError('no model needed')))
    current.update(scheduled, autonomous_investigation=True)
    step = scheduled['plan'][0]
    text, raw = await ex._run_step(step, current)
    tool.ainvoke.assert_awaited_once_with({'dependency': 'entry'})
    current['raw_evidence'].append((step, raw))
    current['past_steps'].append((step, text))
    stopped = decide(current, decision(next_check='', next_tools=[], next_arguments=None, alternatives=[alternative]))
    assert not stopped['plan']
    assert any(f['code'] == 'dependency_tcp_failed' for f in stopped['diagnosis']['observed_findings'])
    assert any(c['evidence_ids'] for c in stopped['investigation_memory']['hypothesis_tracking']['candidates'])
