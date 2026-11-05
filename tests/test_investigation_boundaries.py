"""Regressions for the real G11 citation, predicate and fault-layer failures."""
import copy
import json
from unittest.mock import AsyncMock

import pytest

from src.agent.aiops.strategies import investigation as inv
from src.probe.protocol import evidence
from src.settings import settings


def scene(*observations):
    return {'input': 'entry unavailable', 'past_steps': [], 'raw_evidence': [
        (str(i), json.dumps(evidence(target_id=settings.PROBE_TARGET_ID, operation=op,
            payload=body))) for i, (op, body) in enumerate(observations)]}


@pytest.mark.asyncio
async def test_model_selects_snippet_and_program_fetches_original_without_trusting_quote(monkeypatch):
    state = scene(('dependency_probe', {'dependency': 'db', 'host': '127.0.0.1',
        'dns': ['127.0.0.1'], 'tcp': 'failed'}))
    proposed = []

    async def answer(*args):
        offered = json.loads(args[3]['evidence'])['e1.1']['citation_snippets']
        key = next(key for key, quote in offered.items() if '"tcp": "failed"' in quote)
        result = inv.InvestigationDecision(hypothesis='unknown', supporting_evidence=[
            inv.Citation(evidence_id='e1.1', snippet_id=key, quote='model fabricated text')])
        proposed.append(result.model_dump())
        return result

    monkeypatch.setattr(inv, 'ainvoke_structured', answer)
    result = await inv.InvestigationStrategy().decide(state)
    memory = result['investigation_memory']
    assert memory['model_suggestion'] == proposed[0]
    resolved = next(c for c in memory['supporting_evidence'] if c.get('snippet_id'))
    assert resolved['quote'] in inv.evidence_index(state)['e1.1']['payload']
    assert 'model fabricated text' not in resolved['quote']


@pytest.mark.parametrize('mutation', ['wrong_id', 'wrong_record', 'stitched_quote', 'expired'])
def test_snippet_resolution_never_repairs_an_unbound_or_invented_citation(mutation):
    state = scene(('dependency_probe', {'dependency': 'db', 'dns': ['127.0.0.1'], 'tcp': 'failed'}),
                  ('resources', {'cpu_percent': 20}))
    records = inv.evidence_index(state)
    offered = inv.investigation_context(state, records)['e1.1']['citation_snippets']
    key = next(iter(offered))
    cite = inv.Citation(evidence_id='e1.1', snippet_id=key)
    if mutation == 'wrong_id': cite.snippet_id = 'invented'
    if mutation == 'wrong_record': cite.evidence_id = 'e2.1'
    if mutation == 'stitched_quote':
        cite.snippet_id = ''
        cite.quote = '"dependency": "db", "tcp": "failed"'
    if mutation == 'expired': records.pop('e1.1')
    proposal = inv.InvestigationDecision(hypothesis='unknown', supporting_evidence=[cite])
    resolved = proposal.model_copy(deep=True)
    inv._resolve_citations(resolved, records)
    assert not inv._valid_citations(resolved.supporting_evidence, records)
    result = inv.decide_from_evidence(state, proposal, records)
    assert result['investigation_memory']['validation_issues']


@pytest.mark.parametrize('protection,trigger', [(False, False), (True, False), (False, True), (True, True)])
@pytest.mark.parametrize('reported_status', ['supported', 'excluded'])
def test_unaligned_prose_is_preserved_while_only_finite_prediction_is_verified(protection, trigger, reported_status):
    state = scene(('ports', {'local_port': 5678, 'ports': [{'status': 'LISTEN',
        'local': {'port': 5678}}]}))
    state.update(investigation_config={'hypothesis_protection': protection,
        'contradiction_trigger': trigger, 'protection_steps': 2},
        investigation_tools=[{'name': 'probe_port_snapshot'}])
    condition = inv.ObservationCondition(operation='ports', object_name='5678', field='listening', expected=True)
    answer = inv.InvestigationDecision(hypothesis='entry not listening', hypothesis_condition=condition,
        alternatives=[inv.Alternative(explanation='entry not listening', claim_type='observed_condition',
            status=reported_status, condition=condition, evidence=[inv.Citation(evidence_id='e1.1', quote='LISTEN')])])
    result = inv.decide_from_evidence(state, answer, inv.evidence_index(state))
    alternative = result['investigation_memory']['alternatives'][0]
    assert alternative['status'] == 'supported'
    assert alternative['original_status'] == reported_status
    assert alternative['verification'] == 'predicate_verified'
    assert alternative['explanation'] == 'entry not listening'
    assert result['diagnosis']['alternatives'][0]['explanation'] == inv.condition_statement(condition)
    assert any('entry not listening' in issue and '只验证有限条件' in issue
               for issue in result['investigation_memory']['validation_issues'])
    assert result['investigation_memory']['model_suggestion']['alternatives'][0]['explanation'] == 'entry not listening'
    candidate = result['investigation_memory']['hypothesis_tracking']['candidates'][0]
    assert candidate['condition_binding'] == 'bound'
    assert candidate['explanation'] == 'ports/5678: listening == true'
    assert candidate['source_explanation'] == 'entry not listening'
    assert candidate['relation'] == 'support'
    assert inv._candidate_check(candidate, state, inv.evidence_index(state)) is None
    assert not result['investigation_memory']['hypothesis_tracking']['events']


def test_contradicted_finite_condition_is_not_reported_as_an_unchecked_question():
    state = scene(('dependency_probe', {'dependency': 'db', 'tcp': 'ok', 'http': {'status': 200}}))
    condition = inv.ObservationCondition(operation='dependency_probe', object_name='db', field='tcp', expected='failed')
    answer = inv.InvestigationDecision(hypothesis='unknown', alternatives=[inv.Alternative(
        explanation='database crashed', status='excluded', claim_type='observed_condition', condition=condition)])
    result = inv.decide_from_evidence(state, answer, inv.evidence_index(state))
    alt = result['diagnosis']['alternatives'][0]
    assert alt['status'] == 'excluded' and alt['verification'] == 'predicate_verified'
    assert result['diagnosis']['unresolved_questions'] == []
    assert '未查清：dependency_probe/db' not in result['response']
    assert result['investigation_memory']['model_suggestion']['alternatives'][0]['explanation'] == 'database crashed'
    assert result['diagnosis']['kind'] != 'confirmed_cause'


def test_public_limits_replace_stale_process_top256_wording_and_preserve_audit_text():
    state = scene(('dependency_probe', {'dependency': 'db', 'tcp': 'failed'}))
    answer = inv.InvestigationDecision(hypothesis='unknown', alternatives=[inv.Alternative(
        explanation='entry process is missing', status='unresolved',
        limitation='进程快照为按内存排序的前 256 个可访问进程，非完整清单；matched_count=2、skipped_count=0。')])
    result = inv.decide_from_evidence(state, answer, inv.evidence_index(state))
    public = json.dumps(result['diagnosis'], ensure_ascii=False) + result['response']
    assert '前 256 个可访问进程' not in public
    assert '先按配置身份匹配再限制返回' in public
    assert result['investigation_memory']['alternatives'][0]['limitation'].startswith('进程快照为按内存排序')


def test_public_condition_mismatch_states_verified_condition_and_unverified_prose():
    state = scene(('ports', {'local_port': 14106, 'listening_only': True,
                              'ports': [{'status': 'LISTEN', 'local': {'port': 14106}}]}))
    condition = inv.ObservationCondition(operation='ports', object_name='14106',
        field='listening', expected=True)
    answer = inv.InvestigationDecision(hypothesis='unknown', alternatives=[inv.Alternative(
        explanation='entry is not listening', status='excluded', claim_type='observed_condition',
        condition=condition, evidence=[inv.Citation(evidence_id='e1.1', quote='LISTEN')])])
    result = inv.decide_from_evidence(state, answer, inv.evidence_index(state))
    alternative = result['diagnosis']['alternatives'][0]
    assert alternative['explanation'] == 'ports/14106: listening == true'
    assert '原始解释文字未验证' in alternative['limitation']
    assert '有限现场条件已独立核验' in alternative['limitation']


@pytest.mark.parametrize('note', ['空日志不能证明没有异常', '未确认退出原因', '模型认为存在矛盾'])
def test_free_text_limits_do_not_erase_verified_faults_or_confirm_causality(note):
    state = scene(('dependency_probe', {'dependency': 'db', 'tcp': 'failed'}))
    answer = inv.InvestigationDecision(hypothesis='crashed', root_cause='crashed',
        conclusion_level='confirmed_cause', contradictions=[note])
    original = copy.deepcopy(answer.model_dump())
    result = inv.decide_from_evidence(state, answer, inv.evidence_index(state))
    assert result['diagnosis']['kind'] == 'localized_fault'
    assert 'crashed' not in result['diagnosis']['conclusion']
    assert '诊断详情' in result['response']
    assert result['diagnosis']['contradictions'] == [note]
    assert result['diagnosis']['recommendations']
    assert answer.model_dump() == original


@pytest.mark.parametrize('unrelated_fault', [False, True])
def test_conflicting_query_scopes_block_only_affected_fault_findings(unrelated_fault):
    values = [('ports', {'local_port': 5679, 'listening_only': True, 'ports': []}),
              ('ports', {'local_port': 5679, 'listening_only': False, 'ports': [
                  {'status': 'LISTEN', 'local': {'port': 5679}}]})]
    if unrelated_fault: values.append(('dependency_probe', {'dependency': 'other', 'tcp': 'failed'}))
    state = scene(*values)
    result = inv.decide_from_evidence(state, inv.InvestigationDecision(hypothesis='unknown'), inv.evidence_index(state))
    diagnosis = result['diagnosis']
    assert diagnosis['kind'] == ('localized_fault' if unrelated_fault else 'unlocated')
    assert diagnosis['observation_conflicts']
    assert all(c['code'] != 'port_not_listening' for c in diagnosis['observed_findings'])
    assert all(r['finding_code'] != 'port_not_listening' for r in diagnosis['recommendations'])
    assert '现场查询结果不一致' in result['response']


@pytest.mark.parametrize('expected,status', [('failed', 'supported'), ('ok', 'excluded')])
def test_exact_condition_with_bound_snippet_is_verified_and_keeps_model_proposal(expected, status):
    state = scene(('dependency_probe', {'dependency': 'db', 'tcp': 'failed'}))
    records = inv.evidence_index(state)
    snippets = inv.investigation_context(state, records)['e1.1']['citation_snippets']
    key = next(k for k, quote in snippets.items() if quote == '"tcp": "failed"')
    condition = inv.ObservationCondition(operation='dependency_probe', object_name='db', field='tcp', expected=expected)
    proposal = inv.InvestigationDecision(hypothesis='unknown', alternatives=[inv.Alternative(
        explanation=inv.condition_statement(condition), condition=condition, status=status,
        claim_type='observed_condition', evidence=[inv.Citation(evidence_id='e1.1', snippet_id=key)])])
    result = inv.decide_from_evidence(state, proposal, records)
    saved = result['investigation_memory']['alternatives'][0]
    assert saved['verification'] == 'predicate_verified'
    assert saved['status'] == status
    assert saved['evidence'][0]['quote'] == '"tcp": "failed"'
    assert result['investigation_memory']['model_suggestion'] == proposal.model_dump()


def test_snippet_covers_a_field_beyond_the_truncated_context_prefix():
    state = scene(('dependency_probe', {'dependency': 'db', 'padding': 'x' * 2500, 'tcp': 'failed'}))
    records = inv.evidence_index(state)
    offered = inv.investigation_context(state, records)['e1.1']
    assert '"tcp": "failed"' not in offered['excerpt']
    assert '"tcp": "failed"' in offered['citation_snippets'].values()


def test_log_snippets_preserve_complete_escaped_fields_beyond_prefix():
    source_hash = '8bbb6e42' + 'a' * 56
    line = json.dumps({'padding': 'x' * 1400, 'error_type': 'ValueError',
        'configuration': {'field': 'max_attempts', 'value': 'invalid',
                          'source_sha256': source_hash}}, ensure_ascii=False)
    state = scene(('text_logs', {'service': 'localapp', 'path': 'app.log', 'lines': [line]}))
    records = inv.evidence_index(state)
    snippets = inv._citation_snippets(records['e1.1'])
    expected = json.dumps(json.dumps('source_sha256') + ': ' + json.dumps(source_hash))[1:-1]
    assert expected in snippets.values()
    assert len(snippets) <= 18 and all(len(q) <= 400 for q in snippets.values())
    assert all(q in records['e1.1']['payload'] for q in snippets.values())
    snippet_id = next(k for k, q in snippets.items() if q == expected)
    decision = inv.InvestigationDecision(hypothesis='unknown', supporting_evidence=[
        inv.Citation(evidence_id='e1.1', snippet_id=snippet_id, quote='fabricated')])
    inv._resolve_citations(decision, records)
    assert decision.supporting_evidence[0].quote == expected
    assert inv._valid_citations(decision.supporting_evidence, records)


def test_behavior_audit_rejects_tampered_binding_of_a_free_text_candidate():
    from scripts.mechanism_behavior import audit_behavior, behavior_snapshot
    from datetime import datetime, timezone

    state = scene(('ports', {'local_port': 5678, 'ports': []}))
    result = inv.decide_from_evidence(state, inv.InvestigationDecision(hypothesis='not listening',
        hypothesis_condition=inv.ObservationCondition(operation='ports', object_name='5678',
            field='listening', expected=True)), inv.evidence_index(state))
    state.update(result)
    snapshot = behavior_snapshot(state, datetime.now(timezone.utc).isoformat())
    snapshot['tracking']['candidates'][0]['explanation'] = 'ports/5678: listening == false'
    audited = audit_behavior([snapshot], [], [])
    assert audited['status'] == 'failed'
    assert any('条件绑定' in issue for issue in audited['issues'])


@pytest.mark.parametrize('protection,trigger', [(False, False), (True, False), (False, True), (True, True)])
@pytest.mark.parametrize('case', ['protection', 'contradiction'])
def test_prose_candidates_use_independent_finite_predictions_for_mechanisms(protection, trigger, case):
    state = scene()
    state.update(investigation_tools=[{'name': 'probe_dependency_probe'}, {'name': 'probe_service_status'}],
        investigation_config={'hypothesis_protection': protection, 'contradiction_trigger': trigger,
            'protection_steps': 3})
    answer = inv.InvestigationDecision(hypothesis='database crashed',
        hypothesis_condition=inv.ObservationCondition(operation='dependency_probe', object_name='db', field='tcp', expected='failed'),
        next_check='inspect db', next_tools=['probe_dependency_probe'],
        discriminating_question='is db reachable', expected_observation='tcp result',
        alternatives=[inv.Alternative(explanation='entry process is gone', status='unresolved',
            condition=inv.ObservationCondition(operation='services', object_name='entry', field='state', expected='stopped'),
            check=inv.CandidateCheck(next_check='inspect entry', next_tools=['probe_service_status'],
                discriminating_question='entry service stopped', expected_observation='service state'))])
    original = copy.deepcopy(answer.model_dump())
    first = inv.decide_from_evidence(state, answer, inv.evidence_index(state))
    tracking = first['investigation_memory']['hypothesis_tracking']
    assert tracking['version'] == 4
    assert tracking['candidates'][0]['explanation'] == 'dependency_probe/db: tcp == "failed"'
    assert tracking['candidates'][0]['source_explanation'] == 'database crashed'
    assert answer.model_dump() == original
    assert first['investigation_memory']['model_suggestion'] == original
    state.update(first)
    state['past_steps'].append(('other step', 'unknown'))
    # A reliable observation contradicts only the finite prediction, never proves the prose.
    if case == 'contradiction':
        state['raw_evidence'].append(('db probe', json.dumps(evidence(target_id=settings.PROBE_TARGET_ID,
            operation='dependency_probe', payload={'dependency': 'db', 'tcp': 'ok'}))))
    following = answer.model_copy(deep=True)
    if case == 'protection':
        following.alternatives = []
    result = inv.decide_from_evidence(state, following, inv.evidence_index(state))
    enabled = protection if case == 'protection' else trigger
    assert result['plan'] == (['inspect entry'] if enabled else ['inspect db'])
    assert 'diagnosis' not in result
    events = result['investigation_memory']['hypothesis_tracking']['events']
    assert any(e['kind'] == 'contradiction_triggered' for e in events) is (trigger and case == 'contradiction')
    assert any(e['kind'] == 'protection_check_selected' for e in events) is (protection and case == 'protection')


def test_finite_prediction_identity_survives_prose_rephrasing_without_a_model_id():
    state = scene()
    condition = inv.ObservationCondition(operation='ports', object_name='5678', field='listening', expected=False)
    first = inv.decide_from_evidence(state, inv.InvestigationDecision(hypothesis='entry stopped',
        hypothesis_condition=condition), inv.evidence_index(state))
    state.update(first)
    second = inv.decide_from_evidence(state, inv.InvestigationDecision(hypothesis='port unavailable',
        hypothesis_condition=condition), inv.evidence_index(state))
    candidates = second['investigation_memory']['hypothesis_tracking']['candidates']
    assert len(candidates) == 1
    assert candidates[0]['source_explanation'] == 'port unavailable'


def test_finite_prediction_does_not_publish_source_causality_as_a_verified_claim():
    from src.agent.aiops.events import investigation_summary
    state = scene(('dependency_probe', {'dependency': 'db', 'tcp': 'failed'}))
    answer = inv.InvestigationDecision(hypothesis='unknown', alternatives=[inv.Alternative(
        explanation='operator killed database', status='supported',
        condition=inv.ObservationCondition(operation='dependency_probe', object_name='db', field='tcp', expected='failed'),
        evidence=[inv.Citation(evidence_id='e1.1', quote='failed')])])
    result = inv.decide_from_evidence(state, answer, inv.evidence_index(state))
    assert 'operator killed database' in json.dumps(result['investigation_memory'])
    assert 'operator killed database' not in json.dumps(result['diagnosis'])
    summary = investigation_summary({**state, **result})
    assert 'operator killed database' not in json.dumps(summary)
    assert any(c['explanation'] == 'dependency_probe/db: tcp == "failed"' for c in summary['candidates'])


@pytest.mark.parametrize('tamper', [False, True])
def test_shared_prediction_keeps_all_source_explanations_and_audits_the_list(tamper):
    from datetime import datetime, timezone
    from scripts.mechanism_behavior import audit_behavior, behavior_snapshot
    state = scene()
    condition = inv.ObservationCondition(operation='dependency_probe', object_name='db', field='tcp', expected='failed')
    answer = inv.InvestigationDecision(hypothesis='database stopped', hypothesis_condition=condition,
        alternatives=[inv.Alternative(explanation='database network is blocked', status='unresolved', condition=condition)])
    state.update(inv.decide_from_evidence(state, answer, inv.evidence_index(state)))
    candidates = state['investigation_memory']['hypothesis_tracking']['candidates']
    assert len(candidates) == 1
    assert candidates[0]['source_explanations'] == ['database stopped', 'database network is blocked']
    snapshot = behavior_snapshot(state, datetime.now(timezone.utc).isoformat())
    if tamper:
        snapshot['tracking']['candidates'][0]['source_explanations'].pop()
    assert audit_behavior([snapshot], [], [])['status'] == ('failed' if tamper else 'passed')


@pytest.mark.parametrize('expected', [True, 'impossible', 'success', 503])
def test_invalid_prediction_cannot_schedule_a_protected_candidate(expected):
    state = scene()
    state.update(investigation_tools=[{'name': 'probe_dependency_probe'}],
        investigation_config={'hypothesis_protection': True, 'contradiction_trigger': True, 'protection_steps': 3})
    condition = inv.ObservationCondition(operation='dependency_probe', object_name='db', field='tcp', expected=expected)
    first = inv.decide_from_evidence(state, inv.InvestigationDecision(hypothesis=inv.condition_statement(condition),
        hypothesis_condition=condition, next_check='inspect db', next_tools=['probe_dependency_probe'],
        discriminating_question='db reachable', expected_observation='tcp result'), inv.evidence_index(state))
    state.update(first)
    result = inv.decide_from_evidence(state, inv.InvestigationDecision(hypothesis='unknown'), inv.evidence_index(state))
    assert not result['investigation_memory']['hypothesis_tracking']['events']
    assert result['plan'] == []


@pytest.mark.parametrize('role', ['primary', 'alternative'])
@pytest.mark.parametrize('condition', [
    {'operation': 'dependency_probe', 'object_name': 'db', 'field': 'tcp', 'expected': 'success'},
    {'operation': 'ports', 'object_name': '5678', 'field': 'listening', 'expected': 'true'},
    {'operation': 'processes', 'object_name': 'worker', 'field': 'tcp', 'expected': 'ok'},
    {'operation': 'dependency_probe', 'object_name': 'db', 'field': 'http.status', 'expected': True},
    {'operation': 'ports', 'object_name': ' ', 'field': 'listening', 'expected': False},
])
def test_invalid_prediction_is_explained_through_memory_report_and_sse_without_repair(role, condition):
    from src.agent.aiops.events import investigation_summary

    state = scene(('dependency_probe', {'dependency': 'db', 'tcp': 'failed'}))
    prediction = inv.ObservationCondition(**condition)
    proposed = inv.InvestigationDecision(hypothesis='unknown', contradictions=['日志为空，退出原因未知'])
    if role == 'primary':
        proposed.hypothesis_condition = prediction
    else:
        proposed.alternatives = [inv.Alternative(explanation='unverified explanation', status='supported',
            condition=prediction, evidence=[inv.Citation(evidence_id='e1.1', quote='failed')])]
    original = proposed.model_dump()
    result = inv.decide_from_evidence(state, proposed, inv.evidence_index(state))
    memory = result['investigation_memory']
    candidate = next(c for c in memory['hypothesis_tracking']['candidates'] if c['condition'] == condition)
    assert candidate['condition_binding'] == 'unverified'
    assert candidate['relation'] == 'neutral'
    assert not memory['hypothesis_tracking']['events']
    issues = memory['validation_issues']
    assert any('有限预期无效' in item for item in issues)
    assert issues == result['diagnosis']['validation_issues']
    assert issues == investigation_summary({**state, **result})['validation_issues']
    assert '有限预期无效' in result['response']
    assert result['diagnosis']['contradictions'] == ['日志为空，退出原因未知']
    assert '诊断详情' in result['response']
    assert result['diagnosis']['kind'] == 'localized_fault'
    assert memory['model_suggestion'] == original == proposed.model_dump()


def test_rejected_event_check_reports_its_actual_limitation_in_unresolved_questions():
    state = scene(('inventory', {'configured_services': {'worker': {'event_logs_available': False}}}),
                  ('dependency_probe', {'dependency': 'db', 'tcp': 'failed'}))
    state['investigation_tools'] = [{'name': 'probe_event_log'}]
    proposed = inv.InvestigationDecision(hypothesis='unknown', next_check='read worker exit history',
        next_tools=['probe_event_log'], next_arguments={'probe_event_log': {'service': 'worker'}},
        discriminating_question='did worker exit or never start', expected_observation='exit event')
    result = inv.decide_from_evidence(state, proposed, inv.evidence_index(state))
    question = result['diagnosis']['unresolved_questions'][0]
    assert '事件通道未配置' in question['limitation']
    assert '尚未执行' not in question['limitation']
    assert '事件通道未配置' in result['diagnosis']['stop_reason']
    assert result['investigation_memory']['unresolved_questions'][0] == question
    assert result['plan'] == []


def test_executed_query_is_not_unexecuted_just_because_the_model_renames_it():
    state = scene(('dependency_probe', {'dependency': 'db', 'tcp': 'failed'}))
    state['investigation_tools'] = [{'name': 'probe_dependency_probe'}]
    proposed = inv.InvestigationDecision(hypothesis='unknown', next_check='renamed reachability check',
        next_tools=['probe_dependency_probe'], next_arguments={'probe_dependency_probe': {'dependency': 'db'}},
        discriminating_question='is db reachable', expected_observation='tcp result')
    result = inv.decide_from_evidence(state, proposed, inv.evidence_index(state))
    question = result['diagnosis']['unresolved_questions'][0]
    assert '已有现场结果' in question['limitation']
    assert '尚未执行' not in question['limitation']
    assert not result['plan']


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [None, {'error': {'type': 'insufficient_quota'}},
    {'error': {'type': 'evaluation_budget_exceeded', 'code': 'unrecognized'}}])
async def test_unrecognized_payment_errors_are_not_mislabeled_local_budget(monkeypatch, body):
    import httpx
    from openai import APIStatusError
    error = APIStatusError('payment error', response=httpx.Response(402,
        request=httpx.Request('POST', 'https://test.invalid')), body=body)
    monkeypatch.setattr(inv, 'create_agent_llm', lambda **kwargs: object())
    monkeypatch.setattr(inv, 'ainvoke_structured', AsyncMock(side_effect=error))
    with pytest.raises(APIStatusError):
        await inv.InvestigationStrategy().decide({'input': 'check localapp'})
