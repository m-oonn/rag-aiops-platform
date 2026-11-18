"""Question identity must survive a detour while its candidate remains open."""

import hashlib
from copy import deepcopy

import pytest

from src.agent.aiops.strategies import investigation as inv


def question_id(text):
    return 'q-' + hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]


def detour(status='active', relation='neutral', saved_id=None):
    question = 'Did the request fail in a dependency or inside the application?'
    ident = saved_id or question_id(question)
    saved = inv.CandidateCheck(
        next_check='inspect application log', next_tools=['diagnostic_query'],
        discriminating_question=question,
        expected_observation='The request error identifies its failure stage.')
    current = {
        'input': 'checkout failed', 'past_steps': [], 'raw_evidence': [],
        'investigation_tools': [{'name': 'diagnostic_query'}],
        'investigation_memory': {'unresolved_questions': [
            {'id': ident, 'question': question, 'limitation': 'previous limitation'}]},
    }
    tracking = {'candidates': [
        {'id': 'h-application', 'status': status, 'relation': relation,
         'check': saved.model_dump()}]}
    selected = inv.InvestigationDecision(
        hypothesis='dependency unavailable', next_check='inspect another dependency',
        next_tools=['diagnostic_query'], discriminating_question='Is another dependency available?',
        expected_observation='A successful dependency response excludes its unavailability.')
    return current, selected, tracking, ident, question


@pytest.mark.parametrize('status', ['active', 'protected'])
def test_open_candidate_question_survives_a_different_selected_check(status):
    current, selected, tracking, ident, question = detour(status)
    before = deepcopy((current, selected.model_dump(), tracking))

    memory = inv._decision_memory(selected, selected.model_dump(), {}, current, tracking)

    retained = next(row for row in memory['unresolved_questions'] if row['id'] == ident)
    assert retained['question'] == question
    assert retained['expected_observation'] == tracking['candidates'][0]['check']['expected_observation']
    assert '尚未执行' in retained['limitation']
    assert (current, selected.model_dump(), tracking) == before
    # The public diagnosis and the next model request see the same open question.
    diagnosis = inv.diagnosis_result(current, selected, 'unlocated', {}, tracking=tracking)
    assert diagnosis['unresolved_questions'] == memory['unresolved_questions']
    context = inv._decision_memory_context(memory)
    assert context['unresolved_questions'] == memory['unresolved_questions']


@pytest.mark.parametrize(('status', 'relation'), [
    ('excluded', 'contradict'), ('dropped', 'neutral'), ('unavailable', 'neutral'),
    ('active', 'contradict'),
])
def test_closed_or_contradicted_candidate_does_not_restore_old_question(status, relation):
    current, selected, tracking, ident, _ = detour(status, relation)
    memory = inv._decision_memory(selected, selected.model_dump(), {}, current, tracking)
    assert ident not in {row['id'] for row in memory['unresolved_questions']}


def test_retained_question_keeps_existing_identity_and_is_deduplicated():
    current, selected, tracking, ident, _ = detour(saved_id='q-saved-legacy')
    tracking['candidates'].append(deepcopy(tracking['candidates'][0]))
    memory = inv._decision_memory(selected, selected.model_dump(), {}, current, tracking)
    assert sum(row['id'] == ident for row in memory['unresolved_questions']) == 1


def test_replaced_candidate_question_does_not_reuse_previous_identity():
    current, selected, tracking, ident, _ = detour()
    replacement = 'Does a different service have an error?'
    tracking['candidates'][0]['check']['discriminating_question'] = replacement
    memory = inv._decision_memory(selected, selected.model_dump(), {}, current, tracking)
    ids = {row['id'] for row in memory['unresolved_questions']}
    assert ident not in ids
    assert question_id(replacement) in ids


def test_redacted_question_text_does_not_merge_distinct_candidate_ids():
    current, selected, tracking, _, _ = detour()
    claims = ['first unverified causal claim', 'second unverified causal claim']
    safe = '该因果解释尚无可验证的现场条件。'
    current['investigation_memory']['unresolved_questions'] = [
        {'id': 'q-redacted-legacy', 'question': safe}]
    selected.alternatives = [inv.Alternative(
        explanation=claim, status='unresolved', verification='causal_claim_unverified')
        for claim in claims]
    original = tracking['candidates'][0]
    tracking['candidates'] = []
    for index, claim in enumerate(claims):
        candidate = deepcopy(original)
        candidate['id'] = f'h-{index}'
        candidate['check']['discriminating_question'] = claim
        tracking['candidates'].append(candidate)

    memory = inv._decision_memory(selected, selected.model_dump(), {}, current, tracking)

    rows = [row for row in memory['unresolved_questions'] if row['question'] == safe]
    assert {row['id'] for row in rows} == {question_id(claim) for claim in claims}
    assert all(claim not in str(rows) for claim in claims)


def test_retained_question_cannot_repeat_an_already_executed_check():
    current, selected, tracking, ident, question = detour()
    current['past_steps'] = [('inspect application log', 'completed observation')]
    memory = inv._decision_memory(selected, selected.model_dump(), {}, current, tracking)
    resumed = {**current, 'investigation_memory': {
        'unresolved_questions': memory['unresolved_questions']}}
    proposal = inv.InvestigationDecision(
        hypothesis='failure stage unknown', next_check='inspect application log',
        next_tools=['diagnostic_query'], discriminating_question=question,
        expected_observation='The request error identifies its failure stage.',
        next_question_id=ident)

    result = inv.decide_from_evidence(resumed, proposal, {})

    assert result['plan'] == []
    assert '已执行' in result['diagnosis']['stop_reason']
    assert '不存在的未决问题' not in result['diagnosis']['stop_reason']


@pytest.mark.parametrize('known', [True, False])
def test_continuation_requires_an_actually_saved_question(known):
    current, selected, tracking, ident, _ = detour()
    memory = inv._decision_memory(selected, selected.model_dump(), {}, current, tracking)
    resumed = {**current, 'investigation_memory': {
        'unresolved_questions': memory['unresolved_questions']}}
    proposal = inv.InvestigationDecision(
        hypothesis='failure stage unknown', next_check='inspect service state',
        next_tools=['diagnostic_query'], discriminating_question='Is the service running?',
        expected_observation='The current service state distinguishes stopped and running.',
        next_question_id=ident if known else 'q-never-saved')

    result = inv.decide_from_evidence(resumed, proposal, {})

    assert bool(result.get('plan')) is known
    if not known:
        assert '不存在的未决问题' in result['diagnosis']['stop_reason']
