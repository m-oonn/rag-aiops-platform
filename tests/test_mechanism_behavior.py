"""Behavior audit must follow decisions, evidence and execution rather than event counts."""
from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

from scripts.evaluate_windows_probe import audit_mechanisms
from src.agent.aiops.strategies import investigation as inv
from src.probe.protocol import evidence
from src.settings import settings


def trace(protection=True, trigger=True, case='contradiction', model_same=False):
    from scripts.mechanism_behavior import behavior_snapshot
    config = {'hypothesis_protection': protection, 'contradiction_trigger': trigger, 'protection_steps': 2}
    state = {'input': 'entry unavailable', 'past_steps': [('initial', 'unknown')], 'raw_evidence': [],
        'investigation_config': config, 'investigation_tools': [{'name': 'probe_dependency_probe'}]}
    def proposal(omit=False):
        return inv.InvestigationDecision(hypothesis='downstream failed',
            hypothesis_condition=inv.ObservationCondition(operation='dependency_probe', object_name='db', field='tcp', expected='failed'),
            next_check='check db', next_tools=['probe_dependency_probe'],
            discriminating_question='is db reachable', expected_observation='tcp result',
            alternatives=[] if omit else [inv.Alternative(explanation='entry failed', status='unresolved',
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
