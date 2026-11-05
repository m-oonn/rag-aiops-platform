"""Question/check handoff is derived offline; no model or collector access."""
from copy import deepcopy
import json
from unittest.mock import AsyncMock

import pytest

from src.agent.aiops.strategies import investigation as inv
from src.probe.protocol import evidence
from src.settings import settings
from tests.test_candidate_handoff import log_check, log_state
from tests.test_concrete_investigation_checks import decision, decide


def current_state(event_available=False):
    current = log_state(('inventory', {'configured_services': {
        'entry': {'kind': 'process', 'process_names': ['entry.exe'],
                  'text_logs_available': True, 'text_logs': ['D:/entry.log'],
                  'event_logs_available': event_available, 'configuration_available': False},
        'outside': {'event_logs_available': True}}}))
    current['target_resolution'] = {'status': 'resolved', 'target_id': settings.PROBE_TARGET_ID,
        'allowed_services': ['entry'], 'allowed_dependencies': ['entry']}
    current['investigation_tools'].append({'name': 'probe_event_log'})
    current['investigation_memory'] = log_check(
        repeat_reason='确认是否还有停止记录', repeat_evidence_ids=['e1.1']).model_dump()
    return current


def project(current):
    return inv._decision_memory_context(current['investigation_memory'], current, inv.evidence_index(current))


def event_check():
    return inv.CandidateCheck(next_check='inspect allowed event source', next_tools=['probe_event_log'],
        next_arguments={'probe_event_log': {'service': 'entry', 'since_minutes': 60, 'limit': 200}},
        discriminating_question='允许的事件来源是否有停止相关记录？',
        expected_observation='匹配事件或明确的空结果，不保证能识别发起者')


def test_completed_log_and_missing_history_source_are_explicit_before_model_decision():
    current = current_state()
    before = deepcopy(current)
    context = project(current)
    agenda = context['decision_agenda']
    previous = next(row for row in agenda['checks'] if row['origin'] == 'previous_check')
    assert previous['question'] == log_check().discriminating_question
    assert not previous['query_eligible'] and '新证据' in previous['rejection']
    progress, = previous['progress']
    assert progress['evidence_ids'] and progress['observation']['line_limit'] == 100
    assert progress['observation']['returned_excerpt'] == ['shutdown_requested; initiator=unknown']
    assert not progress['observation']['covers_full_history']
    assert '发起者' in progress['remaining_unknown']
    source = agenda['sources']
    assert source['evidence_id']
    assert source['services']['entry']['probe_event_log']['status'] == 'not_configured'
    assert 'outside' not in source['services']
    assert '未穷尽' in agenda['coverage'] and '新检查' in agenda['coverage']
    assert current == before


@pytest.mark.parametrize('available,tool_loaded,expected', [
    (True, True, 'configured'), (False, True, 'not_configured'),
    (None, True, 'unknown'), (True, False, 'tool_not_loaded')])
def test_source_availability_distinguishes_config_missing_unknown_and_unloaded(available, tool_loaded, expected):
    current = current_state(available)
    if not tool_loaded:
        current['investigation_tools'] = [row for row in current['investigation_tools'] if row['name'] != 'probe_event_log']
    sources = project(current)['decision_agenda']['sources']
    assert sources['services']['entry']['probe_event_log']['status'] == expected
    assert sources['services']['entry']['probe_event_log']['configured'] is available
    assert sources['services']['entry']['probe_event_log']['tool_loaded'] is tool_loaded


def test_invalid_or_missing_inventory_is_unknown_not_proof_of_source_absence():
    current = current_state()
    raw = json.loads(current['raw_evidence'][-1][1])
    raw['truncated'] = True
    current['raw_evidence'][-1] = ('incomplete inventory', json.dumps(raw))
    assert project(current)['decision_agenda']['sources'] == {'evidence_id': None, 'services': {}}
    current['raw_evidence'].pop()
    assert project(current)['decision_agenda']['sources'] == {'evidence_id': None, 'services': {}}


@pytest.mark.asyncio
async def test_existing_decision_request_can_choose_different_source_and_consume_empty_result(monkeypatch):
    current = current_state(True)
    check = event_check()
    alternative = inv.Alternative(explanation='停止的历史原因未知', status='unresolved', check=check)
    candidate = {'id': 'history-question', 'birth_step': 0, 'status': 'active', 'explanation': alternative.explanation,
        'condition': None, 'check': check.model_dump(), 'proposal': alternative.model_dump(),
        'seen_observations': [], 'supporting_observations': 0, 'contradicting_observations': 0}
    current['investigation_memory']['hypothesis_tracking'] = {'candidates': [candidate]}

    async def model(llm, schema, prompt, inputs):
        agenda = json.loads(inputs['memory'])['decision_agenda']
        option = next(row for row in agenda['checks'] if row.get('candidate_id') == 'history-question')
        assert option['query_eligible'] and option['progress'][0]['status'] == 'unexecuted'
        assert agenda['sources']['services']['entry']['probe_event_log']['status'] == 'configured'
        return decision(**check.model_dump())

    invoke = AsyncMock(side_effect=model)
    monkeypatch.setattr(inv, 'create_agent_llm', lambda **kwargs: object())
    monkeypatch.setattr(inv, 'ainvoke_structured', invoke)
    result = await inv.InvestigationStrategy().decide(current)
    assert invoke.await_count == 1 and result['plan'] == [check.next_check]
    current.update(result)
    current['past_steps'].append((check.next_check, 'empty allowed event source'))
    current['raw_evidence'].append((check.next_check, json.dumps(evidence(
        target_id=settings.PROBE_TARGET_ID, operation='event_logs', payload={
            'service': 'entry', 'since_minutes': 60, 'limit': 200, 'channels': ['Application'], 'events': []}))))
    option = next(row for row in project(current)['decision_agenda']['checks'] if row['origin'] == 'previous_check')
    assert not option['query_eligible']
    progress, = option['progress']
    assert progress['observation']['event_count'] == 0
    assert progress['observation']['since_minutes'] == 60
    assert '空结果' in progress['remaining_unknown']
    stopped = decide(current, decision(next_check='', next_tools=[], next_arguments=None))
    assert not stopped['plan'] and stopped['diagnosis']['kind'] != 'confirmed_cause'


def test_failed_query_and_new_legal_query_remain_distinct():
    current = current_state(True)
    check = event_check()
    current['investigation_memory'] = check.model_dump()
    current['raw_evidence'].append((check.next_check, json.dumps({
        'data_source': 'tool_execution', 'tool': 'probe_event_log',
        'arguments': check.next_arguments['probe_event_log'], 'status': 'failed', 'reason': 'access denied'})))
    option, = project(current)['decision_agenda']['checks']
    assert not option['query_eligible'] and 'access denied' in option['rejection']
    assert not option['progress'][0]['evidence_ids']
    # A source label does not override the execution failure or authorize retries.
    assert not decide(current, decision(**check.model_dump()))['plan']


def test_legacy_memory_without_new_fields_and_new_query_are_still_usable():
    current = current_state()
    current['investigation_memory'] = log_check(next_arguments={
        'probe_text_log': {'service': 'entry', 'path': 'D:/entry.log', 'lines': 200}}).model_dump()
    projected = project(current)
    assert projected['decision_agenda']['checks'][0]['query_eligible']
    assert decide(current, inv.InvestigationDecision.model_validate(current['investigation_memory']))['plan']
    assert 'decision_agenda' not in current['investigation_memory']
    assert inv._decision_memory_context({})['hypothesis_tracking']['candidates'] == []


def test_missing_source_can_stop_without_promoting_log_to_confirmed_cause():
    current = current_state()
    before = deepcopy(current)
    assert not any(row['query_eligible'] for row in project(current)['decision_agenda']['checks'])
    stopped = decide(current, log_check())
    assert not stopped['plan'] and stopped['diagnosis']['kind'] != 'confirmed_cause'
    assert '未核验' in stopped['diagnosis']['stop_reason']
    assert current == before


def test_projection_never_invents_question_ids_or_duplicates_saved_check_context():
    current = current_state()
    memory = current['investigation_memory']
    memory['next_question_id'] = 'not-a-saved-question'
    memory['unresolved_questions'] = [{'id': 'known-question', 'question': log_check().discriminating_question}]
    alternative = inv.Alternative(explanation='停止原因未知', status='unresolved',
                                  check=inv.CandidateCheck.model_validate(memory))
    memory['hypothesis_tracking'] = {'candidates': [{'id': 'saved', 'birth_step': 0,
        'status': 'active', 'explanation': alternative.explanation, 'condition': None,
        'proposal': alternative.model_dump(), 'check': alternative.check.model_dump()}]}
    before = deepcopy(memory)
    context = project(current)
    option, = context['decision_agenda']['checks']
    assert option['question_id'] == 'known-question'
    assert len(option['references']) == 2
    assert 'candidate_check_progress' not in context
    assert 'check' not in context['hypothesis_tracking']['candidates'][0]
    assert memory == before and memory['hypothesis_tracking']['candidates'][0]['check']


@pytest.mark.parametrize('lines,truncated,shortened', [([], False, False),
    (['one', 'two', 'three', 'four'], True, True), (['x' * 401], False, True)])
def test_log_excerpt_preserves_empty_and_truncated_coverage(lines, truncated, shortened):
    current = current_state()
    raw = json.loads(current['raw_evidence'][0][1])
    raw['payload']['lines'] = lines
    updated = evidence(target_id=settings.PROBE_TARGET_ID, operation='text_logs',
                       payload=raw['payload'], truncated=truncated)
    updated['collected_at'] = raw['collected_at']
    current['raw_evidence'][0] = ('read allowed log', json.dumps(updated))
    option, = project(current)['decision_agenda']['checks']
    observation = option['progress'][0]['observation']
    assert observation['line_count'] == len(lines) and observation['truncated'] is truncated
    assert observation['excerpt_shortened'] is shortened
    assert observation['returned_excerpt'] == [line[:400] for line in lines[-3:]]
    assert not observation['covers_full_history']


@pytest.mark.parametrize('invalidity', ['dropped', 'expired', 'contradicted', 'out_of_scope'])
def test_saved_check_is_not_advertised_as_eligible_when_guards_reject_it(invalidity):
    current = current_state(True)
    check = event_check()
    if invalidity == 'out_of_scope':
        check.next_arguments['probe_event_log']['service'] = 'outside'
    condition = inv.ObservationCondition(operation='processes', object_name='entry',
                                         field='process_present', expected=False)
    alternative = inv.Alternative(explanation='进程可能停止', status='unresolved', condition=condition, check=check)
    candidate = {'id': 'saved', 'birth_step': 0, 'status': 'active', 'explanation': alternative.explanation,
        'condition': condition.model_dump(), 'proposal': alternative.model_dump(), 'check': check.model_dump()}
    if invalidity == 'dropped':
        candidate['status'] = 'dropped'
    elif invalidity == 'expired':
        candidate['status'] = 'protected'
        current['past_steps'] = [('one', 'done'), ('two', 'done')]
    elif invalidity == 'contradicted':
        current['raw_evidence'].append(('process found', json.dumps(evidence(
            target_id=settings.PROBE_TARGET_ID, operation='processes', payload={
                'service': 'entry', 'matched_count': 1, 'skipped_count': 0,
                'processes': [{'pid': 42, 'name': 'entry.exe'}]}))))
    current['investigation_memory'] = {'hypothesis_tracking': {'candidates': [candidate]}}
    option, = project(current)['decision_agenda']['checks']
    assert not option['query_eligible'] and option['rejection']
