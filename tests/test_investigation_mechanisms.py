"""Exercise scheduling and evidence boundaries, without model or network calls."""
import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from src.agent.aiops.strategies import investigation as inv
from src.probe.protocol import evidence
from src.settings import settings


def check():
    return inv.CandidateCheck(next_check='核查入口服务状态', next_tools=['probe_service_status'],
        discriminating_question='入口服务是否停止', expected_observation='运行状态会反驳入口服务停止的预期')


def alternative():
    return inv.Alternative(explanation='入口服务停止', status='unresolved',
        condition=inv.ObservationCondition(operation='services', object_name='entry', field='state', expected='stopped'),
        claim_type='observed_condition', check=check())


def proposal(*, include_alternative=True):
    return inv.InvestigationDecision(hypothesis='下游 TCP 不可达',
        hypothesis_condition=inv.ObservationCondition(operation='dependency_probe', object_name='db', field='tcp', expected='failed'),
        next_check='继续核查下游', next_tools=['probe_dependency_probe'],
        discriminating_question='下游是否不可达', expected_observation='TCP 成功会反驳连通失败预期',
        alternatives=[alternative()] if include_alternative else [])


def initial(protection=True, trigger=True):
    return {'input': '入口 503', 'plan': [], 'past_steps': [('初始检查', '未知')], 'raw_evidence': [],
        'investigation_tools': [{'name': 'probe_dependency_probe'}, {'name': 'probe_service_status'}],
        'investigation_config': {'hypothesis_protection': protection, 'contradiction_trigger': trigger, 'protection_steps': 2}}


def decide(state, answer):
    return inv.decide_from_evidence(state, answer, inv.evidence_index(state))


def after_first(state):
    first = decide(state, proposal())
    return {**state, 'investigation_memory': first['investigation_memory'],
        'past_steps': [*state['past_steps'], ('首轮后续检查', '未确定')]}


def add_observation(state, **kwargs):
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
        payload={'dependency': 'db', 'tcp': 'ok'}, **kwargs)
    state['raw_evidence'].append(('检查下游', json.dumps(raw)))
    return raw


@pytest.mark.parametrize('protection,trigger', [(False, False), (True, False), (False, True), (True, True)])
def test_protection_preserves_an_omitted_candidate_and_changes_actual_next_check(protection, trigger):
    state = after_first(initial(protection, trigger))
    before = copy.deepcopy(state)
    answer = proposal(include_alternative=False)
    result = decide(state, answer)
    assert result['plan'] == ([check().next_check] if protection else [answer.next_check])
    tracking = result['investigation_memory']['hypothesis_tracking']
    candidate = next(c for c in tracking['candidates'] if c['explanation'] == alternative().explanation)
    assert candidate['status'] == ('protected' if protection else 'dropped')
    assert state == before
    assert answer.alternatives == []


@pytest.mark.parametrize('protection,trigger', [(False, False), (True, False), (False, True), (True, True)])
def test_new_counterevidence_redirects_the_previous_leader_only_when_trigger_is_on(protection, trigger):
    state = after_first(initial(protection, trigger))
    add_observation(state)
    answer = proposal()
    result = decide(state, answer)
    assert result['plan'] == ([check().next_check] if trigger else [answer.next_check])
    tracking = result['investigation_memory']['hypothesis_tracking']
    leader = next(c for c in tracking['candidates'] if c['explanation'] == answer.hypothesis)
    assert leader['relation'] == 'contradict'
    assert leader['contradicting_observations'] == 1
    events = [e for e in tracking['events'] if e['kind'] == 'contradiction_triggered']
    assert bool(events) is trigger
    if trigger:
        assert events[-1]['evidence_ids'] == ['e1.1']
        assert events[-1]['from_check'] == answer.next_check
        assert events[-1]['next_check'] == check().next_check


@pytest.mark.parametrize('invalid', ['truncated', 'expired', 'wrong_target', 'wrong_object', 'outside_scope', 'error', 'hash'])
def test_invalid_or_unrelated_observations_cannot_trigger_redirection(invalid):
    state = after_first(initial(False, True))
    kwargs = {}
    if invalid == 'truncated': kwargs['truncated'] = True
    if invalid == 'expired': kwargs['collected_at'] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    raw = add_observation(state, **kwargs)
    if invalid == 'wrong_target': raw['target_id'] = 'other-host'
    if invalid == 'hash': raw['payload']['tcp'] = 'failed'
    if invalid in {'wrong_object', 'error'}:
        payload = {'dependency': 'other' if invalid == 'wrong_object' else 'db', 'tcp': 'ok'}
        if invalid == 'error': payload['error'] = 'permission denied'
        raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe', payload=payload)
    if invalid == 'outside_scope':
        state['target_resolution'] = {'status': 'resolved', 'allowed_dependencies': ['entry']}
    state['raw_evidence'][-1] = ('检查下游', json.dumps(raw))
    answer = proposal()
    result = decide(state, answer)
    assert result['plan'] == [answer.next_check]
    assert not any(e['kind'] == 'contradiction_triggered'
        for e in result['investigation_memory']['hypothesis_tracking']['events'])


def test_protection_expires_and_reliable_counterevidence_is_not_ignored():
    state = after_first(initial())
    protected = decide(state, proposal(include_alternative=False))
    assert protected['plan'] == [check().next_check]
    state['investigation_memory'] = protected['investigation_memory']
    state['past_steps'].append(('第三项检查', '未知'))
    result = decide(state, proposal(include_alternative=False))
    assert result['plan'] == [proposal().next_check]
    assert any(e['kind'] == 'protection_expired' for e in result['investigation_memory']['hypothesis_tracking']['events'])
    state = after_first(initial())
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='services', payload={'service': 'entry', 'state': 'running'})
    state['raw_evidence'] = [('服务检查', json.dumps(raw))]
    result = decide(state, proposal(include_alternative=False))
    candidate = next(c for c in result['investigation_memory']['hypothesis_tracking']['candidates']
        if c['explanation'] == alternative().explanation)
    assert candidate['relation'] == 'contradict' and candidate['status'] != 'protected'
    assert result['plan'] == [proposal().next_check]


def test_reread_and_identical_resampling_do_not_repeat_counterevidence_or_trigger():
    state = after_first(initial(False, True))
    add_observation(state)
    result = decide(state, proposal())
    first = result['investigation_memory']['hypothesis_tracking']
    state['investigation_memory'] = result['investigation_memory']
    result = decide(state, proposal())
    assert result['investigation_memory']['hypothesis_tracking']['events'] == first['events']
    add_observation(state)
    result = decide(state, proposal())
    tracking = result['investigation_memory']['hypothesis_tracking']
    candidate = next(c for c in tracking['candidates'] if c['explanation'] == proposal().hypothesis)
    assert candidate['contradicting_observations'] == 1
    assert tracking['events'] == first['events']


def test_mechanisms_cannot_select_missing_tools_or_repeat_completed_checks():
    state = after_first(initial())
    add_observation(state)
    state['investigation_tools'] = [{'name': 'probe_dependency_probe'}]
    result = decide(state, proposal())
    assert result['plan'] == []
    assert '没有可执行' in result['diagnosis']['stop_reason']
    assert result['diagnosis']['kind'] == 'unlocated'
    state = after_first(initial())
    add_observation(state)
    state['past_steps'].append((check().next_check, 'checked'))
    result = decide(state, proposal())
    assert result['plan'] == []
    assert result['investigation_memory']['hypothesis_tracking']['events'][-1]['kind'] == 'contradiction_blocked'


def test_config_is_frozen_and_legacy_ablation_flags_do_not_change_the_new_groups(monkeypatch):
    state = after_first(initial(False, False))
    state.pop('investigation_config')
    monkeypatch.setattr(settings, 'INVESTIGATION_HYPOTHESIS_PROTECTION', True)
    monkeypatch.setattr(settings, 'INVESTIGATION_CONTRADICTION_TRIGGER', True)
    monkeypatch.setattr(settings, 'ABLATION_DISABLE_HYPOTHESIS_PROTECTION', True)
    result = decide(state, proposal(include_alternative=False))
    assert result['plan'] == [proposal().next_check]
    assert result['investigation_memory']['hypothesis_tracking']['config'] == initial(False, False)['investigation_config']


@pytest.mark.parametrize('protection,trigger', [(False, False), (True, False), (False, True), (True, True)])
def test_no_group_can_promote_a_status_snapshot_into_a_confirmed_cause(protection, trigger):
    state = initial(protection, trigger)
    state['raw_evidence'] = [('service', json.dumps(evidence(target_id=settings.PROBE_TARGET_ID,
        operation='services', payload={'service': 'entry', 'state': 'stopped'})))]
    answer = inv.InvestigationDecision(hypothesis='entry crashed', root_cause='program bug',
        scope='entry', conclusion_level='confirmed_cause', outcome='root_cause',
        supporting_evidence=[inv.Citation(evidence_id='e1.1', quote='stopped')])
    result = decide(state, answer)
    assert result['diagnosis']['kind'] == 'localized_fault'
    assert 'program bug' not in result['diagnosis']['conclusion']


def test_empty_process_list_without_configured_names_is_not_a_refutation():
    state = initial(False, True)
    answer = proposal()
    answer.hypothesis_condition = inv.ObservationCondition(
        operation='processes', object_name='entry', field='process_present', expected=True)
    first = decide(state, answer)
    state['investigation_memory'] = first['investigation_memory']
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='processes',
        payload={'service': 'entry', 'processes': [], 'skipped_count': 0})
    state['raw_evidence'] = [('process query', json.dumps(raw))]
    result = decide(state, answer)
    tracking = result['investigation_memory']['hypothesis_tracking']
    assert not tracking['events']
    assert tracking['candidates'][0]['relation'] == 'neutral'


@pytest.mark.parametrize('rewrite', ['remove', 'change'])
def test_trigger_uses_the_saved_prediction_before_the_model_rewrites_it(rewrite):
    state = after_first(initial(False, True))
    add_observation(state)
    answer = proposal()
    answer.hypothesis_condition = None if rewrite == 'remove' else inv.ObservationCondition(
        operation='dependency_probe', object_name='db', field='tcp', expected='ok')
    result = decide(state, answer)
    assert result['plan'] == [check().next_check]
    event = result['investigation_memory']['hypothesis_tracking']['events'][-1]
    assert event['kind'] == 'contradiction_triggered'
    assert event['condition']['expected'] == 'failed'


def test_existing_observation_cannot_become_new_counterevidence_by_rewriting_prediction():
    state = initial(False, True)
    add_observation(state)
    answer = proposal()
    answer.hypothesis_condition.expected = 'ok'
    first = decide(state, answer)
    state['investigation_memory'] = first['investigation_memory']
    result = decide(state, proposal())
    assert result['plan'] == [proposal().next_check]
    assert not result['investigation_memory']['hypothesis_tracking']['events']


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['protection', 'contradiction'])
@pytest.mark.parametrize('protection,trigger', [(False, False), (True, False), (False, True), (True, True)])
async def test_real_graph_routes_to_investigation_and_executes_the_mechanism_selected_step(
        monkeypatch, case, protection, trigger):
    import importlib
    from unittest.mock import AsyncMock
    graph_module = importlib.import_module('src.agent.aiops.graph')
    from src.agent.aiops.strategies.default import DefaultReplanStrategy
    monkeypatch.setattr(settings, 'ENABLE_HITL', False)
    monkeypatch.setattr(settings, 'ENABLE_DYNAMIC_CLASSIFICATION', False)
    executed = []

    async def planner(state):
        return {'plan': ['初始检查']}

    async def executor(state):
        task = state['plan'][0]
        executed.append(task)
        raw = []
        if len(executed) == 2 and case == 'contradiction':
            raw = [('下游探测', json.dumps(evidence(target_id=settings.PROBE_TARGET_ID,
                operation='dependency_probe', payload={'dependency': 'db', 'tcp': 'ok'})))]
        return {'plan': state['plan'][1:], 'past_steps': [(task, '执行记录')], 'raw_evidence': raw}

    monkeypatch.setattr(graph_module, 'planner', planner)
    monkeypatch.setattr(graph_module, 'executor', executor)
    monkeypatch.setattr(inv, 'create_agent_llm', lambda **kwargs: object())
    second = proposal(include_alternative=(case == 'contradiction'))
    second.next_check = '再次核查下游'
    model = AsyncMock(side_effect=[proposal(), second,
        inv.InvestigationDecision(hypothesis='未查清', blocked_reason='没有更多可执行检查')])
    monkeypatch.setattr(inv, 'ainvoke_structured', model)
    service = graph_module.AIOpsService()
    graph = service._build_graph(DefaultReplanStrategy())
    current = initial(protection, trigger)
    current.update(autonomous_investigation=True, past_steps=[], response='')
    final = await graph.ainvoke(current, {'configurable': {'thread_id': f'{case}-{protection}-{trigger}'}})
    changed = protection if case == 'protection' else trigger
    assert executed == ['初始检查', proposal().next_check, check().next_check if changed else second.next_check]
    assert model.await_count == 3
    assert final['investigation_config'] == current['investigation_config']
    assert final['diagnosis']['mechanisms'] == final['investigation_memory']['hypothesis_tracking']
    assert final['diagnosis']['kind'] == 'unlocated'


@pytest.mark.asyncio
async def test_sqlite_reopen_preserves_candidates_and_run_switches(tmp_path, monkeypatch):
    import importlib
    from unittest.mock import AsyncMock
    graph_module = importlib.import_module('src.agent.aiops.graph')
    from src.agent.aiops.strategies.default import DefaultReplanStrategy
    monkeypatch.setattr(settings, 'ENABLE_HITL', False)
    monkeypatch.setattr(settings, 'AIOPS_CHECKPOINT_DB_PATH', str(tmp_path / 'mechanisms.sqlite'))

    async def planner(state):
        return {'plan': ['初始检查']}

    async def executor(state):
        return {'plan': [], 'past_steps': [(state['plan'][0], '未知')]}

    monkeypatch.setattr(graph_module, 'planner', planner)
    monkeypatch.setattr(graph_module, 'executor', executor)
    monkeypatch.setattr(inv, 'create_agent_llm', lambda **kwargs: object())
    monkeypatch.setattr(inv, 'ainvoke_structured', AsyncMock(side_effect=[proposal(), proposal(include_alternative=False)]))
    config = {'configurable': {'thread_id': 'persisted-mechanism-group'}}
    state = initial(True, False)
    state.update(autonomous_investigation=True, past_steps=[], response='')
    service = graph_module.AIOpsService()
    try:
        graph = await service._persistent_graph(DefaultReplanStrategy())
        await graph.ainvoke(state, config, interrupt_after=['replanner'])
        paused = await graph.aget_state(config)
        assert paused.next == ('executor',)
    finally:
        await service.close()
    monkeypatch.setattr(settings, 'INVESTIGATION_HYPOTHESIS_PROTECTION', False)
    monkeypatch.setattr(settings, 'INVESTIGATION_CONTRADICTION_TRIGGER', True)
    reopened = graph_module.AIOpsService()
    try:
        graph = await reopened._persistent_graph(DefaultReplanStrategy())
        restored = await graph.aget_state(config)
        assert restored.values['investigation_memory'] == paused.values['investigation_memory']
        assert restored.values['investigation_config'] == state['investigation_config']
        result = await graph.ainvoke(None, config, interrupt_after=['replanner'])
        assert result['plan'] == [check().next_check]
        assert result['investigation_memory']['hypothesis_tracking']['config'] == state['investigation_config']
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_invalid_model_output_still_records_group_config(monkeypatch):
    from unittest.mock import AsyncMock
    from src.agent.aiops.structured import StructuredOutputError
    monkeypatch.setattr(inv, 'create_agent_llm', lambda **kwargs: object())
    monkeypatch.setattr(inv, 'ainvoke_structured', AsyncMock(side_effect=StructuredOutputError('invalid')))
    state = initial(False, True)
    result = await inv.InvestigationStrategy().decide(state)
    assert result['diagnosis']['kind'] == 'unlocated'
    assert result['diagnosis']['mechanism_config'] == state['investigation_config']
