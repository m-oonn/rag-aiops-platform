"""Exercise scheduling and evidence boundaries, without model or network calls."""
import copy
import hashlib
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


@pytest.mark.parametrize('live_tcp', [None, 'ok', 'failed'])
def test_handbook_cannot_trigger_contradiction_or_override_live_observations(live_tcp):
    state = after_first(initial(False, True))
    # 即便手册里嵌入格式合法的 Probe 示例，也仍然只是知识。
    example = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
        payload={'dependency': 'db', 'tcp': 'failed' if live_tcp == 'ok' else 'ok'})
    handbook = {'data_source': 'knowledge_base', 'results': [
        {'source': 'manual.pdf', 'page': 2, 'chunk_id': 'manual-1',
         'content': json.dumps(example)}], 'example': example}
    state['raw_evidence'].append(('规划前知识检索', json.dumps(handbook)))
    if live_tcp is not None:
        raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
            payload={'dependency': 'db', 'tcp': live_tcp})
        state['raw_evidence'].append(('真实工具观测格式的固定输入', json.dumps(raw)))
    result = decide(state, proposal())
    records = inv.evidence_index(state)
    assert list(records) == ([] if live_tcp is None else ['e2.1'])
    tracking = result['investigation_memory']['hypothesis_tracking']
    leader = next(c for c in tracking['candidates'] if c['explanation'] == proposal().hypothesis)
    assert leader['relation'] == {None: 'neutral', 'ok': 'contradict', 'failed': 'support'}[live_tcp]
    events = [e for e in tracking['events'] if e['kind'] == 'contradiction_triggered']
    assert bool(events) is (live_tcp == 'ok')
    assert result['plan'] == ([check().next_check] if live_tcp == 'ok' else [proposal().next_check])
    if events:
        assert events[-1]['evidence_ids'] == ['e2.1']


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
@pytest.mark.parametrize('keep_check', [False, True])
def test_unverified_exclusion_gets_a_bounded_check_only_with_protection(protection, trigger, keep_check):
    state = after_first(initial(protection, trigger))
    before = copy.deepcopy(state)
    answer = proposal()
    rejected = answer.alternatives[0]
    rejected.status = 'excluded'
    if not keep_check:
        rejected.check = None
    result = decide(state, answer)
    tracking = result['investigation_memory']['hypothesis_tracking']
    candidate = tracking['candidates'][1]
    assert result['plan'] == ([check().next_check] if protection else [answer.next_check])
    assert candidate['status'] == ('protected' if protection else 'active')
    assert candidate['check'] == check().model_dump()
    assert result['investigation_memory']['alternatives'][0]['status'] == 'unresolved'
    assert candidate['birth_step'] == before['investigation_memory']['hypothesis_tracking']['candidates'][1]['birth_step']
    assert state == before
    assert answer.alternatives[0].status == 'excluded'
    events = [e for e in tracking['events'] if e['kind'] == 'hypothesis_protected']
    assert bool(events) is protection
    if protection:
        assert '排除' in events[-1]['reason']


@pytest.mark.parametrize('boundary', ['expired', 'counterevidence', 'missing_tool', 'completed', 'invalid_check', 'unavailable'])
def test_unverified_exclusion_cannot_bypass_protection_boundaries(boundary):
    state = after_first(initial(True, False))
    answer = proposal()
    answer.alternatives[0].status = 'excluded'
    if boundary == 'expired':
        state['past_steps'].append(('第三项检查', '未知'))
    elif boundary == 'counterevidence':
        state['raw_evidence'] = [('服务检查', json.dumps(evidence(target_id=settings.PROBE_TARGET_ID,
            operation='services', payload={'service': 'entry', 'state': 'running'})))]
    elif boundary == 'missing_tool':
        state['investigation_tools'] = [{'name': 'probe_dependency_probe'}]
    elif boundary == 'completed':
        state['past_steps'][-1] = (check().next_check, '完成')
    elif boundary == 'invalid_check':
        answer.alternatives[0].check.next_tools = ['not_allowed']
    else:
        answer.alternatives[0].status = 'unavailable'
    result = decide(state, answer)
    tracking = result['investigation_memory']['hypothesis_tracking']
    assert result['plan'] == [answer.next_check]
    assert tracking['candidates'][1]['status'] != 'protected'
    assert not any(e['kind'] == 'protection_check_selected' for e in tracking['events'])


def test_ordinary_or_new_unresolved_candidates_do_not_preempt_the_model():
    for state, answer in [(after_first(initial()), proposal()), (initial(), proposal())]:
        if not state.get('investigation_memory'):
            answer.alternatives[0].status = 'excluded'
        result = decide(state, answer)
        assert result['plan'] == [answer.next_check]
        assert not result['investigation_memory']['hypothesis_tracking']['events']


def test_verified_exclusion_is_not_protected_and_keeps_its_evidence():
    state = after_first(initial())
    state['raw_evidence'] = [('服务检查', json.dumps(evidence(target_id=settings.PROBE_TARGET_ID,
        operation='services', payload={'service': 'entry', 'state': 'running'})))]
    answer = proposal()
    answer.alternatives[0].status = 'excluded'
    answer.alternatives[0].evidence = [inv.Citation(evidence_id='e1.1', quote='running')]
    result = decide(state, answer)
    saved = result['investigation_memory']['alternatives'][0]
    assert saved['status'] == 'excluded' and saved['verification'] == 'predicate_verified'
    assert result['plan'] == [answer.next_check]
    assert result['investigation_memory']['hypothesis_tracking']['candidates'][1]['status'] == 'excluded'
    assert not result['investigation_memory']['hypothesis_tracking']['events']


def test_rejected_exclusion_does_not_restart_the_protection_window():
    state = after_first(initial(True, False))
    answer = proposal()
    answer.alternatives[0].status = 'excluded'
    protected = decide(state, answer)
    assert protected['plan'] == [check().next_check]
    state['investigation_memory'] = protected['investigation_memory']
    state['past_steps'].append(('另一项检查', '未知'))
    result = decide(state, answer)
    tracking = result['investigation_memory']['hypothesis_tracking']
    assert result['plan'] == [answer.next_check]
    assert tracking['candidates'][1]['birth_step'] == 1
    assert tracking['candidates'][1]['status'] == 'active'
    assert any(e['kind'] == 'protection_expired' for e in tracking['events'])


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


@pytest.mark.parametrize('protection,trigger', [(False, False), (True, False), (False, True), (True, True)])
def test_referenced_candidates_keep_identity_history_and_age_after_rephrasing(protection, trigger):
    state = initial(protection, trigger)
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
        payload={'dependency': 'db', 'tcp': 'failed'})
    state['raw_evidence'] = [('首次探测', json.dumps(raw))]
    first = decide(state, proposal())
    original = first['investigation_memory']['hypothesis_tracking']['candidates']
    state['investigation_memory'] = first['investigation_memory']
    state['past_steps'].append(('第二项检查', '未确定'))
    answer = proposal()
    answer.hypothesis_id = original[0]['id']
    answer.hypothesis = '数据库连接失败'
    answer.alternatives[0].hypothesis_id = original[1]['id']
    answer.alternatives[0].explanation = '入口业务服务未运行'
    result = decide(state, answer)
    tracking = result['investigation_memory']['hypothesis_tracking']
    assert [c['id'] for c in tracking['candidates']] == [c['id'] for c in original]
    for before, after in zip(original, tracking['candidates']):
        assert after['birth_step'] == before['birth_step']
        assert after['seen_observations'] == before['seen_observations']
        assert after['supporting_observations'] == before['supporting_observations']
        assert after['contradicting_observations'] == before['contradicting_observations']
    assert tracking['candidates'][0]['explanation'] == answer.hypothesis
    assert result['investigation_memory']['hypothesis_id'] == original[0]['id']
    assert result['investigation_memory']['alternatives'][0]['hypothesis_id'] == original[1]['id']
    # Rephrasing must not create another protection window on the next completed step.
    state['investigation_memory'] = result['investigation_memory']
    state['past_steps'].append(('第三项检查', '未确定'))
    next_answer = inv.InvestigationDecision(hypothesis='另一个待核查方向',
        next_check='核查其他允许对象', next_tools=['probe_dependency_probe'],
        discriminating_question='入口是否仍异常', expected_observation='入口状态用于区分原因')
    final = decide(state, next_answer)
    previous = {c['id']: c for c in final['investigation_memory']['hypothesis_tracking']['candidates']}
    assert all(previous[c['id']]['status'] == 'dropped' for c in original)


@pytest.mark.parametrize('role', ['primary', 'alternative'])
def test_unknown_candidate_reference_stops_without_creating_or_replacing_candidates(role):
    state = after_first(initial())
    before = copy.deepcopy(state)
    answer = proposal()
    if role == 'primary':
        answer.hypothesis_id = 'h-not-in-this-run'
    else:
        answer.alternatives[0].hypothesis_id = 'h-not-in-this-run'
    result = decide(state, answer)
    assert result['plan'] == []
    assert result['diagnosis']['kind'] == 'unlocated'
    assert '候选 ID' in result['diagnosis']['stop_reason']
    saved = state['investigation_memory']['hypothesis_tracking']['candidates']
    assert [c['id'] for c in result['investigation_memory']['hypothesis_tracking']['candidates']] == [c['id'] for c in saved]
    assert state == before


@pytest.mark.parametrize('role', ['primary', 'alternative'])
@pytest.mark.parametrize('scope_change', ['object', 'operation', 'field'])
def test_candidate_reference_cannot_retarget_a_saved_prediction(role, scope_change):
    state = after_first(initial())
    tracking = state['investigation_memory']['hypothesis_tracking']
    answer = proposal()
    index = 0 if role == 'primary' else 1
    if role == 'primary':
        answer.hypothesis_id = tracking['candidates'][index]['id']
        condition = answer.hypothesis_condition
    else:
        answer.alternatives[0].hypothesis_id = tracking['candidates'][index]['id']
        condition = answer.alternatives[0].condition
    if scope_change == 'object':
        condition.object_name = 'other-object'
    elif scope_change == 'operation':
        condition.operation = 'ports'
    else:
        condition.field = 'listening'
    result = decide(state, answer)
    assert result['plan'] == []
    assert '候选' in result['diagnosis']['stop_reason']
    saved = next(c for c in result['investigation_memory']['hypothesis_tracking']['candidates']
                 if c['id'] == tracking['candidates'][index]['id'])
    assert saved['condition'] == tracking['candidates'][index]['condition']


@pytest.mark.parametrize('rewrite', ['remove', 'change'])
@pytest.mark.parametrize('protection,trigger', [(False, False), (True, False), (False, True), (True, True)])
def test_referenced_rephrased_leader_keeps_saved_prediction_and_counterevidence(protection, trigger, rewrite):
    state = after_first(initial(protection, trigger))
    original = state['investigation_memory']['hypothesis_tracking']['candidates'][0]
    add_observation(state)
    answer = proposal()
    answer.hypothesis_id = original['id']
    answer.hypothesis = '数据库连接故障'
    answer.hypothesis_condition = None if rewrite == 'remove' else inv.ObservationCondition(
        operation='dependency_probe', object_name='db', field='tcp', expected='ok')
    result = decide(state, answer)
    tracking = result['investigation_memory']['hypothesis_tracking']
    leader = next(c for c in tracking['candidates'] if c['id'] == original['id'])
    assert leader['condition'] == original['condition']
    assert leader['relation'] == 'contradict'
    assert leader['contradicting_observations'] == 1
    assert result['plan'] == ([check().next_check] if trigger else [answer.next_check])
    assert bool([e for e in tracking['events'] if e['kind'] == 'contradiction_triggered']) is trigger


def test_reference_keeps_evidence_history_when_a_new_snapshot_supersedes_the_old_one():
    state = initial(False, False)
    add_observation(state)
    answer = proposal()
    answer.hypothesis_condition.expected = 'ok'
    first = decide(state, answer)
    original = first['investigation_memory']['hypothesis_tracking']['candidates'][0]
    state['investigation_memory'] = first['investigation_memory']
    add_observation(state)
    answer.hypothesis_id = original['id']
    answer.hypothesis = '下游 TCP 正常'
    result = decide(state, answer)
    current = next(c for c in result['investigation_memory']['hypothesis_tracking']['candidates']
                   if c['id'] == original['id'])
    assert set(current['evidence_history']) == {'e1.1', 'e2.1'}
    assert current['supporting_observations'] == 1
    assert current['seen_observations'] == original['seen_observations']


def test_new_candidate_with_same_text_and_a_different_condition_gets_its_own_id():
    state = after_first(initial(False, False))
    original = state['investigation_memory']['hypothesis_tracking']['candidates'][0]
    answer = proposal()
    answer.hypothesis_condition.object_name = 'another-db'
    result = decide(state, answer)
    candidates = result['investigation_memory']['hypothesis_tracking']['candidates']
    assert len(candidates) == 3
    assert result['investigation_memory']['hypothesis_id'] != original['id']
    assert next(c for c in candidates if c['id'] == original['id'])['condition'] == original['condition']


def test_new_candidates_with_same_text_in_one_proposal_are_distinguished_by_their_predicates():
    answer = proposal()
    answer.alternatives[0].explanation = answer.hypothesis
    result = decide(initial(False, False), answer)
    candidates = result['investigation_memory']['hypothesis_tracking']['candidates']
    assert len(candidates) == 2
    assert candidates[0]['id'] != candidates[1]['id']
    assert {c['condition']['object_name'] for c in candidates} == {'db', 'entry'}


def test_ambiguous_legacy_description_requires_an_explicit_id():
    state = initial(False, False)
    answer = proposal()
    answer.alternatives[0].explanation = answer.hypothesis
    first = decide(state, answer)
    state['investigation_memory'] = first['investigation_memory']
    next_answer = proposal(include_alternative=False)
    next_answer.hypothesis_condition = None
    result = decide(state, next_answer)
    assert result['plan'] == []
    assert '多个已保存 ID' in result['diagnosis']['stop_reason']


def test_legacy_output_and_tracking_without_identity_fields_remain_usable_after_rephrasing():
    state = after_first(initial(False, False))
    legacy_tracking = state['investigation_memory']['hypothesis_tracking']
    for candidate in legacy_tracking['candidates']:
        candidate['id'] = 'h-' + hashlib.sha256(candidate['explanation'].casefold().encode()).hexdigest()[:16]
        candidate['proposal'].pop('hypothesis_id')
        candidate.pop('evidence_history')
    original = legacy_tracking['candidates'][0]
    legacy_tracking['leading_id'] = original['id']
    answer = proposal()
    answer.hypothesis_id = original['id']
    answer.hypothesis = '数据库连接失败'
    renamed = decide(state, answer)
    state['investigation_memory'] = renamed['investigation_memory']
    state['investigation_memory'].pop('hypothesis_id')
    tracking = state['investigation_memory']['hypothesis_tracking']
    tracking.pop('identity_issues')
    for candidate in tracking['candidates']:
        candidate.pop('evidence_history')
        candidate['proposal'].pop('hypothesis_id')
    legacy = inv.InvestigationDecision(hypothesis=answer.hypothesis,
        hypothesis_condition=answer.hypothesis_condition, next_check=answer.next_check,
        next_tools=answer.next_tools, discriminating_question=answer.discriminating_question,
        expected_observation=answer.expected_observation)
    result = decide(state, legacy)
    current = result['investigation_memory']['hypothesis_tracking']
    assert len(current['candidates']) == 2
    assert current['leading_id'] == original['id']
    assert current['candidates'][0]['birth_step'] == original['birth_step']


def test_saved_prediction_is_restored_before_validating_a_rewritten_exclusion():
    state = after_first(initial(False, False))
    original = state['investigation_memory']['hypothesis_tracking']['candidates'][1]
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='services',
        payload={'service': 'entry', 'state': 'stopped'})
    state['raw_evidence'] = [('查询服务', json.dumps(raw))]
    answer = proposal()
    rejected = answer.alternatives[0]
    rejected.hypothesis_id = original['id']
    rejected.condition.expected = 'running'
    rejected.status = 'excluded'
    rejected.evidence = [inv.Citation(evidence_id='e1.1', quote='stopped')]
    result = decide(state, answer)
    saved = result['investigation_memory']['alternatives'][0]
    assert saved['condition'] == original['condition']
    assert saved['status'] == 'unresolved'
    assert saved['verification'] == 'predicate_mismatch'


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['protection', 'contradiction', 'rejected_exclusion'])
@pytest.mark.parametrize('protection,trigger', [(False, False), (True, False), (False, True), (True, True)])
async def test_real_graph_routes_to_investigation_and_executes_the_mechanism_selected_step(
        monkeypatch, tmp_path, case, protection, trigger):
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
        if len(executed) == 3:
            tool, args = ('probe_service_status', {'service': 'entry'}) if task == check().next_check else (
                'probe_dependency_probe', {'dependency': 'db'})
            raw = [(task, json.dumps({'data_source': 'tool_execution', 'tool': tool,
                'arguments': args, 'status': 'success'}))]
        if len(executed) == 2 and case == 'contradiction':
            raw = [('下游探测', json.dumps(evidence(target_id=settings.PROBE_TARGET_ID,
                operation='dependency_probe', payload={'dependency': 'db', 'tcp': 'ok'})))]
        return {'plan': state['plan'][1:], 'past_steps': [(task, '执行记录')], 'raw_evidence': raw}

    monkeypatch.setattr(graph_module, 'planner', planner)
    monkeypatch.setattr(graph_module, 'executor', executor)
    monkeypatch.setattr(inv, 'create_agent_llm', lambda **kwargs: object())
    second = proposal(include_alternative=(case != 'protection'))
    if case == 'rejected_exclusion':
        second.alternatives[0].status = 'excluded'
        second.alternatives[0].check = None
    second.next_check = '再次核查下游'
    model = AsyncMock(side_effect=[proposal(), second,
        inv.InvestigationDecision(hypothesis='未查清', blocked_reason='没有更多可执行检查')])
    monkeypatch.setattr(inv, 'ainvoke_structured', model)
    service = graph_module.AIOpsService()
    graph = service._build_graph(DefaultReplanStrategy())
    current = initial(protection, trigger)
    current.update(autonomous_investigation=True, past_steps=[], response='')
    config = {'configurable': {'thread_id': f'{case}-{protection}-{trigger}'}}
    streamed = [event async for event in service._stream_events(graph, config, current)]
    final = (await graph.aget_state(config)).values
    changed = trigger if case == 'contradiction' else protection
    assert executed == ['初始检查', proposal().next_check, check().next_check if changed else second.next_check]
    assert model.await_count == 3
    assert final['investigation_config'] == current['investigation_config']
    assert final['diagnosis']['mechanisms'] == final['investigation_memory']['hypothesis_tracking']
    assert final['diagnosis']['kind'] == 'unlocated'
    from scripts.evaluate_windows_probe import save_mechanism_audit
    monkeypatch.setattr(service, '_persistent_graph', AsyncMock(return_value=graph))
    audit = await save_mechanism_audit(service, f'{case}-{protection}-{trigger}',
        current['investigation_config'], tmp_path)
    assert audit['passed'], audit
    trace = json.loads((tmp_path / 'mechanism_trace.json').read_text(encoding='utf-8'))
    assert len(trace['decisions']) == 3
    assert trace['executed_steps'] == executed
    assert trace['decisions'][1]['plan'] == [executed[-1]]
    summaries = [event['investigation'] for event in streamed if event.get('investigation')]
    assert len(summaries) == 3
    assert summaries[1]['next_check'] == executed[-1]
    assert summaries[-1]['events'] == final['diagnosis']['mechanisms']['events']
    if changed:
        kind = 'contradiction_triggered' if case == 'contradiction' else 'protection_check_selected'
        assert any(event['kind'] == kind for event in summaries[1]['events'])


@pytest.mark.asyncio
@pytest.mark.parametrize('explicit_identity', [False, True])
async def test_sqlite_reopen_preserves_candidates_and_run_switches(tmp_path, monkeypatch, explicit_identity):
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
    async def model(_llm, _schema, _prompt, context):
        memory = json.loads(context['memory'])
        if not memory:
            return proposal()
        answer = proposal(include_alternative=False)
        if explicit_identity:
            answer.hypothesis_id = memory['hypothesis_tracking']['leading_id']
            answer.hypothesis = '数据库连接失败'
        return answer

    mocked_model = AsyncMock(side_effect=model)
    monkeypatch.setattr(inv, 'ainvoke_structured', mocked_model)
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
        before = paused.values['investigation_memory']['hypothesis_tracking']['candidates']
        after = result['investigation_memory']['hypothesis_tracking']['candidates']
        assert [c['id'] for c in after] == [c['id'] for c in before]
        assert [c['birth_step'] for c in after] == [c['birth_step'] for c in before]
        assert mocked_model.await_count == 2
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
