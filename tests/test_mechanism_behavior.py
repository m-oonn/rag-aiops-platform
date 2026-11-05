"""Behavior audit must follow decisions, evidence and execution rather than event counts."""
from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

from scripts.evaluate_windows_probe import audit_mechanisms
from scripts.mechanism_behavior import _blocked_review_matches
from src.agent.aiops.strategies import investigation as inv
from src.probe.protocol import evidence
from src.settings import settings


def test_blocked_review_audit_ignores_fixed_remediation_hint_but_checks_reason():
    base = {'kind': 'no_eligible_saved_candidate', 'rejected_candidates': [
        {'candidate_id': 'candidate-1', 'reason': '该服务的事件通道未配置。'}]}
    decorated = {'kind': 'no_eligible_saved_candidate', 'rejected_candidates': [
        {'candidate_id': 'candidate-1', 'reason': '该服务的事件通道未配置。 请改用适用检查或说明实际限制。'}]}
    changed = {'kind': 'no_eligible_saved_candidate', 'rejected_candidates': [
        {'candidate_id': 'candidate-1', 'reason': '权限不足。'}]}
    assert _blocked_review_matches(base, decorated)
    assert not _blocked_review_matches(base, changed)


def trace(protection=True, trigger=True, case='contradiction', model_same=False, prose=False):
    from scripts.mechanism_behavior import behavior_snapshot
    config = {'hypothesis_protection': protection, 'contradiction_trigger': trigger, 'protection_steps': 2}
    state = {'input': 'entry unavailable', 'past_steps': [('initial', 'unknown')], 'raw_evidence': [],
        'investigation_config': config, 'investigation_tools': [{'name': 'probe_dependency_probe'}]}
    def proposal(omit=False):
        return inv.InvestigationDecision(hypothesis='dependency_probe/db: tcp == "failed"',
            hypothesis_condition=inv.ObservationCondition(operation='dependency_probe', object_name='db', field='tcp', expected='failed'),
            next_check='check db', next_tools=['probe_dependency_probe'],
            discriminating_question='is db reachable', expected_observation='tcp result',
            alternatives=[] if omit else [inv.Alternative(explanation='dependency_probe/entry: tcp == "failed"', status='unresolved',
                condition=inv.ObservationCondition(operation='dependency_probe', object_name='entry', field='tcp', expected='failed'),
                check=inv.CandidateCheck(next_check='check entry', next_tools=['probe_dependency_probe'],
                    discriminating_question='is entry reachable', expected_observation='tcp result'))])
    snapshots = []
    for turn in range(2):
        if turn:
            state['past_steps'].append(('intermediate', 'unknown'))
            if case == 'contradiction':
                raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe', payload={'dependency': 'db', 'tcp': 'ok'})
                state['raw_evidence'].append(('check db', json.dumps(raw)))
        decision = proposal(omit=turn == 1 and case == 'protection')
        if turn and model_same:
            decision.next_check = 'check entry'
        if prose:
            decision.hypothesis = '数据库进程退出'
            for alternative in decision.alternatives:
                alternative.explanation = '入口应用异常'
        state.update(inv.decide_from_evidence(state, decision, inv.evidence_index(state)))
        snapshots.append(behavior_snapshot(state, datetime.now(timezone.utc).isoformat()))
    executed = ['initial', 'intermediate', state['plan'][0]]
    state['raw_evidence'].append((state['plan'][0], json.dumps({'data_source': 'tool_execution',
        'tool': 'probe_dependency_probe', 'arguments': {'dependency': 'entry' if (
            protection if case == 'protection' else trigger) else 'db'}, 'status': 'success'})))
    values = {**state, 'diagnosis': {'mechanism_config': config,
        'mechanisms': state['investigation_memory']['hypothesis_tracking']}}
    return config, values, snapshots, executed


@pytest.mark.parametrize('case', ['protection', 'contradiction'])
@pytest.mark.parametrize('mutation', [None, 'source_explanation', 'condition'])
def test_prose_prediction_audit_validates_projection_and_rejects_tampering(case, mutation):
    config, values, snapshots, executed = trace(case=case, prose=True)
    if mutation == 'source_explanation':
        snapshots[-1]['tracking']['candidates'][0]['source_explanation'] = 'invented'
    if mutation == 'condition':
        snapshots[-1]['tracking']['candidates'][0]['condition']['expected'] = 'ok'
    result = audit_mechanisms(config, values, snapshots, executed_steps=executed,
                             execution_records=inv.execution_checks(values))['behavior']
    assert result['status'] == ('failed' if mutation else 'passed'), result
    if not mutation:
        assert result['executed_changes'][case] == 1


@pytest.mark.parametrize('mutation', [None, 'explanation', 'condition', 'source_list'])
def test_duplicate_prose_for_invalid_prediction_is_audited_as_one_neutral_candidate(mutation):
    from scripts.mechanism_behavior import behavior_snapshot, audit_behavior
    config = {'hypothesis_protection': True, 'contradiction_trigger': True, 'protection_steps': 2}
    state = {'input': 'entry unavailable', 'past_steps': [('initial', 'unknown')], 'raw_evidence': [],
        'investigation_config': config, 'investigation_tools': [{'name': 'probe_dependency_probe'}]}
    condition = inv.ObservationCondition(operation='dependency_probe', object_name='db', field='tcp', expected='success')
    first = inv.InvestigationDecision(hypothesis='依赖可能无法连接', hypothesis_condition=condition)
    state.update(inv.decide_from_evidence(state, first, {}))
    snapshots = [behavior_snapshot(state, datetime.now(timezone.utc).isoformat())]
    ident = state['investigation_memory']['hypothesis_tracking']['leading_id']
    state['past_steps'].append(('intermediate', 'unknown'))
    second = inv.InvestigationDecision(hypothesis='需继续核对该依赖的连接状态', hypothesis_id=ident,
        hypothesis_condition=condition, alternatives=[inv.Alternative(explanation=first.hypothesis,
            hypothesis_id=ident, condition=condition, status='unresolved', claim_type='causal_explanation')])
    state.update(inv.decide_from_evidence(state, second, {}))
    snapshots.append(behavior_snapshot(state, datetime.now(timezone.utc).isoformat()))
    candidate = snapshots[-1]['tracking']['candidates'][0]
    assert candidate['source_explanations'] == [second.hypothesis, first.hypothesis]
    assert candidate['condition_binding'] == 'unverified' and candidate['relation'] == 'neutral'
    if mutation == 'explanation': candidate['explanation'] = '伪造表达'
    if mutation == 'condition': candidate['condition']['expected'] = 'ok'
    if mutation == 'source_list': candidate['source_explanations'].pop()
    result = audit_behavior(snapshots, ['initial', 'intermediate'], [])
    assert result['status'] == ('failed' if mutation else 'passed'), result
    assert result['executed_changes'] == {'protection': 0, 'contradiction': 0}
    assert result['mechanism_effectiveness_verified'] is False


@pytest.mark.parametrize('case', ['protection', 'contradiction'])
@pytest.mark.parametrize('protection,trigger', [(False, False), (True, False), (False, True), (True, True)])
def test_behavior_records_opportunities_and_real_execution(case, protection, trigger):
    config, values, snapshots, executed = trace(protection, trigger, case)
    result = audit_mechanisms(config, values, snapshots, executed_steps=executed,
                             execution_records=inv.execution_checks(values))
    behavior = result['behavior']
    assert behavior['status'] == 'passed'
    assert behavior['opportunities'][case] == 1
    enabled = protection if case == 'protection' else trigger
    assert behavior['executed_changes'][case] == int(enabled)
    assert behavior['mechanism_effectiveness_verified'] is False


@pytest.mark.parametrize('mutation', ['not_executed', 'wrong_plan', 'invented_evidence', 'wrong_from_check',
    'outside_window', 'event_only', 'wrong_object', 'tool_failed', 'no_execution_record', 'missing_selection'])
def test_event_label_cannot_pass_without_behavior_chain(mutation):
    config, values, snapshots, executed = trace(case='protection' if mutation == 'outside_window' else 'contradiction')
    if mutation == 'not_executed': executed = executed[:2]
    if mutation == 'wrong_plan': snapshots[-1]['plan'] = ['unrelated']
    if mutation == 'outside_window': snapshots[-1]['tracking']['candidates'][1]['birth_step'] = -10
    if mutation in {'invented_evidence', 'wrong_from_check', 'event_only', 'missing_selection'}:
        event = next(e for e in snapshots[-1]['tracking']['events'] if e['kind'] == 'contradiction_triggered')
        if mutation == 'invented_evidence': event['evidence_ids'] = ['ev-fabricated']
        if mutation == 'wrong_from_check': event['from_check'] = 'invented previous check'
        if mutation == 'event_only': snapshots[-1]['tracking']['candidates'] = []
        if mutation == 'missing_selection': snapshots[-1]['tracking']['events'].remove(event)
    executions = inv.execution_checks(values)
    if mutation == 'wrong_object': executions[-1]['arguments']['dependency'] = 'wrong-db'
    if mutation == 'tool_failed': executions[-1]['status'] = 'failed'
    if mutation == 'no_execution_record': executions = []
    result = audit_mechanisms(config, values, snapshots, executed_steps=executed, execution_records=executions)
    assert result['behavior']['status'] == 'failed'
    assert result['passed'] is False


def test_old_trace_without_evidence_and_proposal_is_not_behavior_verified():
    config, values, snapshots, executed = trace()
    for row in snapshots:
        row.pop('behavior_context')
    result = audit_mechanisms(config, values, snapshots, executed_steps=executed)
    assert result['behavior']['status'] == 'not_assessed'
    assert result['mechanism_effectiveness_verified'] is False


def test_same_model_check_is_executed_but_not_counted_as_additional_change():
    config, values, snapshots, executed = trace(model_same=True)
    result = audit_mechanisms(config, values, snapshots, executed_steps=executed,
                             execution_records=inv.execution_checks(values))['behavior']
    assert result['status'] == 'passed'
    assert result['executed_checks']['contradiction'] == 1
    assert result['executed_changes']['contradiction'] == 0


def test_policy_check_preempts_mechanism_without_failing_contradiction_audit():
    config, values, snapshots, executed = trace()
    tracking = snapshots[-1]['tracking']
    tracking['policy_selected_check'] = {'kind': 'configuration_crosscheck'}
    tracking['events'] = [event for event in tracking['events']
                          if event['kind'] != 'contradiction_triggered']

    behavior = audit_mechanisms(config, values, snapshots, executed_steps=executed,
        execution_records=inv.execution_checks(values))['behavior']

    assert behavior['status'] == 'passed', behavior
    assert behavior['opportunities']['contradiction'] == 1
    assert behavior['executed_changes']['contradiction'] == 0
    assert behavior['decisions'][-1]['policy_preempted'] is True
    assert behavior['mechanism_effectiveness_verified'] is False


@pytest.mark.parametrize('mutation', [None, 'wrong_object', 'missing_tool', 'failed'])
def test_concrete_discriminating_check_audits_all_planned_queries(mutation):
    from scripts.mechanism_behavior import _executed_candidate
    check = {'next_check': 'inspect downstream and log',
        'next_tools': ['probe_dependency_probe', 'probe_text_log'],
        'next_arguments': {'probe_dependency_probe': {'dependency': 'downstream'},
            'probe_text_log': {'service': 'entry', 'path': 'D:/app.log', 'lines': 20}}}
    candidate = {'condition': {'operation': 'dependency_probe', 'object_name': 'entry',
        'field': 'http.status', 'expected': 200}, 'check': check}
    executions = [{'step': check['next_check'], 'tool': tool, 'arguments': deepcopy(args), 'status': 'success'}
        for tool, args in check['next_arguments'].items()]
    if mutation == 'wrong_object': executions[0]['arguments']['dependency'] = 'wrong'
    if mutation == 'missing_tool': executions.pop()
    if mutation == 'failed': executions[-1]['status'] = 'failed'
    assert _executed_candidate(candidate, check, executions) is (mutation is None)


def test_no_opportunity_and_repeated_event_are_not_counted_twice():
    config, values, snapshots, executed = trace(case='no_refutation')
    result = audit_mechanisms(config, values, snapshots, executed_steps=executed)['behavior']
    assert result['status'] == 'passed' and result['no_opportunity']
    config, values, snapshots, executed = trace()
    snapshots.append(deepcopy(snapshots[-1]))
    result = audit_mechanisms(config, values, snapshots, executed_steps=executed,
                             execution_records=inv.execution_checks(values))['behavior']
    assert result['status'] == 'passed'
    assert result['executed_changes']['contradiction'] == 1


@pytest.mark.parametrize('mutation', ['wrong_target', 'wrong_object', 'expired', 'truncated', 'invalid_proposal'])
def test_invalid_refutation_cannot_validate_trigger(mutation):
    from datetime import timedelta
    config, values, snapshots, executed = trace()
    context = snapshots[-1]['behavior_context']
    if mutation == 'invalid_proposal':
        context['model_suggestion'] = {'unexpected': True}
    else:
        raw = evidence(target_id='wrong' if mutation == 'wrong_target' else settings.PROBE_TARGET_ID,
            operation='dependency_probe', payload={'dependency': 'wrong' if mutation == 'wrong_object' else 'db', 'tcp': 'ok'},
            truncated=mutation == 'truncated')
        if mutation == 'expired':
            raw['collected_at'] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        key = next(iter(context['records']))
        context['records'][key]['payload'] = json.dumps(raw)
    result = audit_mechanisms(config, values, snapshots, executed_steps=executed,
                             execution_records=inv.execution_checks(values))
    assert result['behavior']['status'] == 'failed' and result['passed'] is False


def test_blocked_refutation_is_not_counted_as_executed_change():
    from scripts.mechanism_behavior import behavior_snapshot
    config, state, snapshots, executed = trace()
    state['past_steps'].append(('check entry', 'done'))
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe', payload={'dependency': 'entry', 'tcp': 'ok'})
    state['raw_evidence'].append(('check entry', json.dumps(raw)))
    state.update(inv.decide_from_evidence(state, inv.InvestigationDecision(hypothesis='unknown'), inv.evidence_index(state)))
    snapshots.append(behavior_snapshot(state, datetime.now(timezone.utc).isoformat()))
    result = audit_mechanisms(config, state, snapshots, executed_steps=executed,
                             execution_records=inv.execution_checks(state))['behavior']
    assert result['status'] == 'passed'
    assert result['blocked_events'] == 1
    assert result['executed_changes']['contradiction'] == 1


@pytest.mark.parametrize('omit_boundary', [False, True])
def test_historical_reconstruction_is_read_only_and_requires_all_boundaries(tmp_path, omit_boundary):
    import hashlib
    import sqlite3
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
    from scripts.verify_historical_mechanism_behavior import verify_history
    config, values, snapshots, executed = trace()
    source = tmp_path / 'source'
    directory = source / 'mechanisms-test-G11'
    directory.mkdir(parents=True)
    original = {'thread_id': 'test', 'decisions': [{k: r[k] for k in ('step', 'plan', 'tracking', 'next_tools')}
        for r in snapshots], 'executed_steps': executed}
    (directory / 'mechanism_trace.json').write_text(json.dumps(original), encoding='utf-8')
    database = directory / 'checkpoints.sqlite'
    connection = sqlite3.connect(database)
    connection.execute('CREATE TABLE checkpoints(thread_id,checkpoint_ns,checkpoint_id,type,checkpoint)')
    serde = JsonPlusSerializer()
    states = []
    for row in snapshots:
        context = row['behavior_context']
        state = {**context, 'plan': row['plan'], 'investigation_config': config,
            'investigation_memory': {'hypothesis_tracking': row['tracking'],
                'model_suggestion': context['model_suggestion'], 'next_tools': row['next_tools']},
            'raw_evidence': [('intermediate', record['payload']) for record in context['records'].values()]}
        states.append((context['validated_at'], state))
    states.append((snapshots[-1]['behavior_context']['validated_at'], {**values,
                   'past_steps': [(s, 'done') for s in executed], 'plan': []}))
    for index, (stamp, state) in enumerate(states):
        if omit_boundary and index == 1:
            continue
        kind, blob = serde.dumps_typed({'ts': stamp, 'channel_values': state})
        connection.execute('INSERT INTO checkpoints VALUES (?,?,?,?,?)', ('test', '', str(index), kind, blob))
    connection.commit()
    connection.close()
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    result = verify_history(source, tmp_path / 'audit')
    assert result['passed'] is (not omit_boundary)
    assert result['model_calls'] == result['new_observations'] == 0
    assert result['results'][0]['source_unchanged']
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    with pytest.raises(FileExistsError):
        verify_history(source, tmp_path / 'audit')


@pytest.mark.parametrize('mutation', [None, 'accepted_candidate', 'missing_identity_issue'])
def test_identity_rejection_audits_atomic_preservation_not_partial_proposal(mutation):
    from scripts.mechanism_behavior import behavior_snapshot, audit_behavior
    config = {'hypothesis_protection': True, 'contradiction_trigger': True, 'protection_steps': 2}
    state = {'input': 'entry unavailable', 'past_steps': [('initial', 'unknown')],
        'raw_evidence': [], 'investigation_config': config, 'investigation_tools': []}
    first = inv.InvestigationDecision(hypothesis='入口状态待查',
        hypothesis_condition=inv.ObservationCondition(operation='dependency_probe', object_name='entry', field='tcp', expected='ok'),
        alternatives=[inv.Alternative(explanation='下游状态待查', status='unresolved')])
    state.update(inv.decide_from_evidence(state, first, {}))
    snapshots = [behavior_snapshot(state, datetime.now(timezone.utc).isoformat())]
    candidates = state['investigation_memory']['hypothesis_tracking']['candidates']
    primary, alternative = candidates
    state['past_steps'].append(('intermediate', 'unknown'))
    second = inv.InvestigationDecision(hypothesis='下游连接失败', hypothesis_id=primary['id'],
        hypothesis_condition=inv.ObservationCondition(operation='dependency_probe', object_name='db', field='tcp', expected='failed'),
        alternatives=[inv.Alternative(explanation='下游状态已更新', hypothesis_id=alternative['id'], status='unresolved',
            condition=inv.ObservationCondition(operation='dependency_probe', object_name='db', field='tcp', expected='failed'))])
    state.update(inv.decide_from_evidence(state, second, {}))
    snapshots.append(behavior_snapshot(state, datetime.now(timezone.utc).isoformat()))
    assert snapshots[-1]['tracking']['identity_issues']
    if mutation == 'accepted_candidate':
        snapshots[-1]['tracking']['candidates'][1]['source_explanation'] = '下游状态已更新'
    if mutation == 'missing_identity_issue':
        snapshots[-1]['tracking']['identity_issues'] = []
    result = audit_behavior(snapshots, ['initial', 'intermediate'], [])
    assert result['status'] == ('failed' if mutation else 'passed'), result
    assert result['executed_changes'] == {'protection': 0, 'contradiction': 0}
