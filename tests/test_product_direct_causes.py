"""Direct cause contract and report regressions, without model/network calls."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import AsyncMock

import pytest

from src.agent.aiops.strategies import investigation as inv
from src.agent.aiops.reporting import finalize_report
from src.settings import settings
from tests.test_concrete_investigation_checks import state, decision


def stopped_state():
    when = datetime.now(timezone.utc) - timedelta(seconds=10)
    def event(name, seconds, **extra):
        return {'event': name, 'at': (when + timedelta(seconds=seconds)).isoformat(), **extra}
    config = {'source': 'D:/localapp.json', 'source_sha256': 'same-loaded-hash'}
    logs = [event('service_started', 0, pid=123, instance_id='worker-1', listen_port=9002),
            event('shutdown_requested', 1, pid=123, reason='controlled_stop',
                  stop_request={'channel': 'file_presence', 'initiator': 'unknown'}),
            event('service_exited', 2, pid=123, instance_id='worker-1', reason='shutdown_completed')]
    app = event('request_completed', 3, pid=124, instance_id='app-1', request_id='req-1',
        path='/api/availability', status=503, detail='upstream connection failed',
        configuration=config, upstream={'host': '127.0.0.1', 'port': 9002})
    edge = event('request_completed', 4, request_id='req-1', path='/api/availability', status=503)
    current = state(
        ('inventory', {'configured_services': {'downstream': {'kind': 'process', 'process_identity_configured': True}}}),
        ('configuration', {'service': 'localapp', 'path': config['source'], 'source_sha256': config['source_sha256'],
                           'values': {'downstream_port': 9002}}),
        ('dependency_probe', {'dependency': 'downstream', 'host': '127.0.0.1', 'port': 9002, 'tcp': 'failed'}),
        ('ports', {'local_port': 9002, 'ports': [], 'matched_count': 0}),
        ('processes', {'service': 'downstream', 'processes': [], 'matched_count': 0, 'skipped_count': 0}),
        ('text_logs', {'service': 'downstream', 'lines': [json.dumps(e) for e in logs]}),
        ('text_logs', {'service': 'localapp', 'lines': [json.dumps(app)]}),
        ('text_logs', {'service': 'edge', 'lines': [json.dumps(edge)]}))
    current['target_resolution'] = {'status': 'resolved', 'target_id': settings.PROBE_TARGET_ID,
        'allowed_services': ['downstream', 'localapp', 'edge'], 'allowed_dependencies': ['downstream'],
        'dependency_services': {'downstream': 'downstream'}, 'services': {}}
    return current


def mutate_record(records, key, change):
    raw = json.loads(records[key]['payload'])
    change(raw)
    records[key]['payload'] = json.dumps(raw)


def cause_decision(current, records):
    ids = inv._confirmed_stopped_cause_evidence(records, current)
    return decision(next_check='', next_tools=[], next_arguments=None,
        discriminating_question='', expected_observation='', outcome='root_cause',
        conclusion_level='confirmed_cause', root_cause_code='downstream_stopped_after_request',
        root_cause='downstream 收到停止请求后完成退出，当前无进程和监听；localapp 连接失败，edge 同请求返回503。发起者未知。',
        scope='本次 edge → localapp → downstream /api/availability 请求及采样窗口',
        supporting_evidence=[inv.Citation(evidence_id=i, quote=records[i]['payload']) for i in sorted(ids)],
        alternatives=[inv.Alternative(explanation='停止发起者和动机', status='unavailable', critical=False,
            limitation='应用日志的initiator为unknown，无身份审计来源。',
            noncritical_reason='不影响本次停止请求、完成退出和请求失败的直接运行链。')])


@pytest.mark.parametrize('missing', range(8))
def test_stopped_cause_rejects_each_missing_part(missing):
    current = stopped_state()
    records = inv.evidence_index(current)
    assert len(inv._confirmed_stopped_cause_evidence(records, current)) == 8
    del records[f'e{missing + 1}.1']
    assert not inv._confirmed_stopped_cause_evidence(records, current)


@pytest.mark.parametrize('case', ['pid', 'instance', 'restart', 'order', 'hash', 'request', 'success', 'skipped', 'truncated', 'target'])
def test_stopped_cause_rejects_conflicting_or_incomplete_chain(case):
    current = stopped_state()
    records = inv.evidence_index(current)
    if case in {'pid', 'instance', 'restart', 'order'}:
        def change(raw):
            lines = [json.loads(line) for line in raw['payload']['lines']]
            if case == 'pid': lines[1]['pid'] = 999
            if case == 'instance': lines[2]['instance_id'] = 'other'
            if case == 'restart': lines.append({**lines[0], 'at': datetime.now(timezone.utc).isoformat()})
            if case == 'order': lines[1]['at'] = datetime.now(timezone.utc).isoformat()
            raw['payload']['lines'] = [json.dumps(e) for e in lines]
        mutate_record(records, 'e6.1', change)
    elif case in {'hash', 'request'}:
        key = 'e7.1' if case == 'hash' else 'e8.1'
        def change(raw):
            event = json.loads(raw['payload']['lines'][0])
            if case == 'hash': event['configuration']['source_sha256'] = 'other'
            else: event['request_id'] = 'other'
            raw['payload']['lines'] = [json.dumps(event)]
        mutate_record(records, key, change)
    elif case == 'success':
        mutate_record(records, 'e3.1', lambda r: r['payload'].update(tcp='ok'))
    elif case == 'skipped':
        mutate_record(records, 'e5.1', lambda r: r['payload'].update(skipped_count=1))
    elif case == 'target':
        mutate_record(records, 'e6.1', lambda r: r.update(target_id='outside'))
    else:
        mutate_record(records, 'e6.1', lambda r: r.update(truncated=True))
    assert not inv._confirmed_stopped_cause_evidence(records, current)


@pytest.mark.parametrize('status, accepted', [('TIME_WAIT', True), ('ESTABLISHED', True), ('LISTEN', False)])
def test_stopped_cause_checks_listeners_instead_of_requiring_zero_connections(status, accepted):
    current = stopped_state()
    records = inv.evidence_index(current)
    mutate_record(records, 'e4.1', lambda raw: raw['payload'].update(
        ports=[{'status': status, 'local': {'host': '127.0.0.1', 'port': 9002}, 'pid': 0}],
        matched_count=1, listening_only=False))
    assert bool(inv._confirmed_stopped_cause_evidence(records, current)) is accepted


@pytest.mark.asyncio
async def test_valid_terminal_cause_survives_saved_candidate_fallback_and_generates_complete_report():
    current = stopped_state()
    records = inv.evidence_index(current)
    current['investigation_memory'] = {'hypothesis_tracking': {'candidates': [
        {'id': 'saved', 'status': 'unavailable', 'explanation': 'unavailable history',
         'birth_step': 0, 'seen_observations': [], 'supporting_observations': 0,
         'contradicting_observations': 0}]}}
    answer = cause_decision(current, records)
    result = inv.decide_from_evidence(current, answer, records)
    assert result['diagnosis']['kind'] == 'confirmed_cause'
    report = await finalize_report(current, result)
    assert report['diagnosis']['root_cause_code'] == 'downstream_stopped_after_request'
    text = report['response']
    assert '诊断结论（已确认直接原因）' in text and answer.root_cause in text
    assert '影响范围：' in text and '建议：' in text and '处理后验证：' in text
    assert all('[' + ref.evidence_id + ']' in text for ref in answer.supporting_evidence)
    assert '启动、退出及异常传播原因尚未确认' not in text
    assert '发起者未知' in text
    assert '现有日志内容尚未独立验证停止或启动失败' not in text
    assert '直接原因已核验；停止请求发起者' in text


def test_unconfirmed_cause_keeps_dependency_gap():
    current = stopped_state()
    records = inv.evidence_index(current)
    mutate_record(records, 'e1.1', lambda raw: raw['payload']['configured_services']['downstream'].update(
        text_logs_available=True, process_names=['python.exe']))
    answer = cause_decision(current, records)
    result = inv.diagnosis_result(current, answer, 'localized_fault', records)
    assert any(q['id'].startswith('gap-dependency-') for q in result['unresolved_questions'])
    assert any('尚未独立验证停止' in text for text in result['limitations'])
    confirmed = inv.diagnosis_result(current, answer, 'confirmed_cause', records)
    assert not any(q['id'].startswith('gap-dependency-') for q in confirmed['unresolved_questions'])
    assert not any('尚未独立验证停止' in text for text in confirmed['limitations'])
    assert any('发起者' in text for text in confirmed['limitations'])


@pytest.mark.asyncio
async def test_terminal_cause_feedback_requires_model_proposal_and_uses_one_attempt(monkeypatch):
    current = stopped_state()
    records = inv.evidence_index(current)
    answer = cause_decision(current, records)
    pending = decision(next_check='', next_tools=[], next_arguments=None)
    proposals = AsyncMock(side_effect=[pending, answer])
    monkeypatch.setattr(inv, 'create_agent_llm', lambda **kw: object())
    monkeypatch.setattr(inv, 'ainvoke_structured', proposals)
    result = await inv.InvestigationStrategy().decide(current)
    assert proposals.await_count == 2
    assert result['diagnosis']['kind'] == 'confirmed_cause'
    assert result['investigation_memory']['cause_correction']['attempts'] == 1
    proposals.reset_mock(side_effect=True)
    proposals.side_effect = [pending, pending]
    result = await inv.InvestigationStrategy().decide(current)
    assert proposals.await_count == 2
    assert result['diagnosis']['kind'] != 'confirmed_cause'
    assert not result['investigation_memory']['root_cause']


@pytest.mark.asyncio
@pytest.mark.parametrize('cleared_by_candidate_review', [False, True])
async def test_incomplete_cause_check_is_corrected_before_terminal_review(monkeypatch, cleared_by_candidate_review):
    current = stopped_state()
    del current['raw_evidence'][2]  # The dependency probe has not been collected.
    records = inv.evidence_index(current)
    initial = cause_decision(current, records)
    initial.next_check = 'probe the registered downstream dependency'
    initial.next_tools = ['probe_dependency_probe']
    initial.next_arguments = None
    initial.discriminating_question = 'is downstream currently reachable?'
    initial.expected_observation = 'TCP connection outcome'
    repaired = initial.model_copy(deep=True)
    repaired.outcome, repaired.root_cause, repaired.root_cause_code = 'investigating', '', ''
    repaired.conclusion_level = 'unlocated'
    repaired.next_arguments = {'probe_dependency_probe': {'dependency': 'downstream'}}
    proposals = AsyncMock(side_effect=[initial, repaired])
    monkeypatch.setattr(inv, 'create_agent_llm', lambda **kw: object())
    monkeypatch.setattr(inv, 'ainvoke_structured', proposals)
    if cleared_by_candidate_review:
        monkeypatch.setattr(inv, '_blocked_check_candidate_followup', lambda *args: {
            'check': None, 'selection': {'rejected_candidates': []}})
    result = await inv.InvestigationStrategy().decide(current)
    assert result['plan'] == [initial.next_check]
    assert [a['purpose'] for a in result['investigation_memory']['decision_trace']['attempts']] == [
        'initial', 'check_correction']
    assert result['investigation_memory']['check_correction']['status'] == 'continued'
    assert not result['investigation_memory'].get('cause_correction')


def test_cause_citation_review_identifies_missing_and_invalid_refs_without_completing_them():
    current = stopped_state()
    records = inv.evidence_index(current)
    answer = cause_decision(current, records)
    answer.supporting_evidence = [ref for ref in answer.supporting_evidence
                                 if ref.evidence_id not in {'e1.1', 'e2.1'}]
    answer.supporting_evidence.append(inv.Citation(evidence_id='e1.1', snippet_id='wrong'))
    before = answer.model_dump()
    review = inv._cause_citation_review(answer, {'stopped': set(records)}, records)['stopped']
    assert review['missing_valid_supporting_evidence_ids'] == ['e1.1', 'e2.1']
    inventory = review['required_evidence']['e1.1']
    assert inventory['operation'] == 'inventory' and not inventory['validly_cited']
    config = review['required_evidence']['e2.1']
    assert config['service'] == 'localapp' and config['operation'] == 'configuration'
    assert config['citation_snippets'] == inv._citation_snippets(records['e2.1'])
    assert review['required_evidence']['e3.1']['validly_cited']
    assert answer.model_dump() == before
    assert inv.decide_from_evidence(current, answer, records)['diagnosis']['kind'] != 'confirmed_cause'


@pytest.mark.asyncio
@pytest.mark.parametrize('missing_cause_fields', [False, True])
async def test_terminal_incomplete_cause_gets_collection_gap_feedback_and_can_continue(monkeypatch, missing_cause_fields):
    from src.probe.protocol import evidence
    current = stopped_state()
    current['raw_evidence'].pop()  # The same missing edge log as round 026.
    inventory = json.loads(current['raw_evidence'][0][1])['payload']
    inventory['configured_services']['edge'] = {'text_logs': ['D:/edge.log'], 'text_logs_available': True}
    current['raw_evidence'][0] = ('inventory', json.dumps(evidence(
        target_id=settings.PROBE_TARGET_ID, operation='inventory', payload=inventory)))
    current['investigation_tools'].append({'name': 'probe_text_log'})
    pending = decision(next_check='', next_tools=[], next_arguments=None, outcome='root_cause',
        conclusion_level='confirmed_cause', root_cause_code='downstream_stopped_after_request',
        root_cause='停止后退出，入口503')
    if missing_cause_fields:
        pending.root_cause, pending.root_cause_code = '', ''
    continued = decision(next_check='read edge request log', next_tools=['probe_text_log'],
        next_arguments={'probe_text_log': {'service': 'edge', 'path': 'D:/edge.log', 'lines': 100}},
        discriminating_question='入口是否同请求返回503', expected_observation='请求编号相同支持传播链')
    proposals = AsyncMock(side_effect=[pending, continued])
    monkeypatch.setattr(inv, 'create_agent_llm', lambda **kw: object())
    monkeypatch.setattr(inv, 'ainvoke_structured', proposals)
    result = await inv.InvestigationStrategy().decide(current)
    assert proposals.await_count == 2
    assert result['plan'] == ['read edge request log']
    feedback = json.loads(proposals.await_args_list[1].args[3]['cause_feedback'])
    assert not feedback['supported_causes']
    missing = [row for row in feedback['collection_review'] if not row['evidence_ids']]
    assert missing == [{'operation': 'text_logs', 'service': 'edge', 'evidence_ids': []}]
    prompt, inputs = proposals.await_args_list[1].args[2:4]
    assert '未通过完整性检查' in prompt.format_messages(**inputs)[2].content


@pytest.mark.asyncio
async def test_cause_feedback_precedes_fallback_checks_and_persists_once(monkeypatch):
    current = stopped_state()
    current['investigation_tools'].append({'name': 'probe_port_snapshot'})
    current['target_resolution']['services']['edge'] = {'probe_service': 'edge', 'expected_ports': [9000]}
    records = inv.evidence_index(current)
    answer = cause_decision(current, records)
    pending = decision(next_check='', next_tools=[], next_arguments=None,
        outcome='root_cause', conclusion_level='confirmed_cause', root_cause='停止请求后退出',
        alternatives=[inv.Alternative(explanation='ports/9000: listening == false', status='unresolved',
            evidence=[inv.Citation(evidence_id='e4.1')],
            claim_type='observed_condition', condition=inv.ObservationCondition(
                operation='ports', object_name='9000', field='listening', expected=False),
            check=inv.CandidateCheck(next_check='inspect entry listener', next_tools=['probe_port_snapshot'],
                next_arguments={'probe_port_snapshot': {'local_port': 9000}},
                discriminating_question='入口端口是否未监听？', expected_observation='监听反驳端口未监听'))])
    # This is the live failure: a terminal proposal becomes an executable fallback
    # before its missing cause fields receive feedback.
    assert inv.decide_from_evidence(current, pending, records, require_concrete_checks=True)['plan']
    proposals = AsyncMock(side_effect=[pending, answer])
    monkeypatch.setattr(inv, 'create_agent_llm', lambda **kw: object())
    monkeypatch.setattr(inv, 'ainvoke_structured', proposals)
    result = await inv.InvestigationStrategy().decide(current)
    assert proposals.await_count == 2
    assert result['diagnosis']['kind'] == 'confirmed_cause'
    feedback = json.loads(proposals.await_args_list[1].args[3]['cause_feedback'])
    assert feedback['citable_evidence']['e4.1']['citation_snippets'] == inv._citation_snippets(records['e4.1'])
    assert feedback['supporting_evidence_review']['downstream_stopped_after_request'][
        'missing_valid_supporting_evidence_ids'] == sorted(inv._confirmed_stopped_cause_evidence(records, current))
    assert feedback['validated_alternatives'][0]['explanation'] == pending.alternatives[0].explanation
    assert [a['purpose'] for a in result['investigation_memory']['decision_trace']['attempts']] == ['initial', 'cause_correction']
    current.update(result)
    proposals.reset_mock(side_effect=True)
    proposals.side_effect = [pending]
    again = await inv.InvestigationStrategy().decide(current)
    assert proposals.await_count == 1
    assert again['investigation_memory']['cause_correction']['attempts'] == 1


@pytest.mark.parametrize('change', ['valid', 'request', 'service', 'missing', 'conflict', 'truncated', 'type'])
def test_request_log_condition_is_bounded_and_never_excludes_free_text(change):
    from tests.test_concrete_investigation_checks import state
    trace = {'connection_established': False, 'phase': 'connect'}
    event = {'event': 'request_completed', 'request_id': 'req-1', 'upstream_request': trace}
    lines = [json.dumps(event)]
    if change == 'missing':
        lines = [json.dumps({**event, 'upstream_request': {}})]
    elif change == 'conflict':
        lines.append(json.dumps({**event, 'upstream_request': {'connection_established': True}}))
    elif change == 'type':
        lines = [json.dumps({**event, 'upstream_request': {'connection_established': 'false'}})]
    current = state(('text_logs', {'service': 'entry', 'lines': lines}))
    records = inv.evidence_index(current)
    condition = inv.ObservationCondition(operation='text_logs', object_name=(
        'other#req-1' if change == 'service' else 'entry#other' if change == 'request' else 'entry#req-1'),
        field='upstream_request.connection_established', expected=True)
    if change == 'truncated':
        mutate_record(records, 'e1.1', lambda raw: raw.update(truncated=True))
    answer = decision(alternatives=[inv.Alternative(explanation=inv.condition_statement(condition),
        condition=condition, claim_type='observed_condition', status='unresolved')])
    inv._validate_alternatives(answer, records)
    alternative = answer.alternatives[0]
    assert alternative.status == ('excluded' if change == 'valid' else 'unresolved')
    if change == 'valid':
        assert alternative.verification == 'predicate_verified'
        assert inv._valid_citations(alternative.evidence, records)
        assert any('req-1' in ref.quote for ref in alternative.evidence)
        assert any('connection_established' in ref.quote for ref in alternative.evidence)
        causal = decision(alternatives=[inv.Alternative(explanation='内部错误导致503',
            condition=condition, claim_type='causal_explanation', status='excluded',
            evidence=alternative.evidence)])
        inv._validate_alternatives(causal, records)
        assert causal.alternatives[0].status == 'unresolved'


@pytest.mark.parametrize('field,expected,actual', [
    ('upstream_request.phase', 'read_body', 'connect'),
    ('upstream_request.response_status', 200, 503)])
def test_request_log_phase_and_status_verify_exact_values(field, expected, actual):
    from tests.test_concrete_investigation_checks import state
    event = {'event': 'request_completed', 'request_id': 'req-1',
        'upstream_request': {field.partition('.')[2]: actual}}
    current = state(('text_logs', {'service': 'entry', 'lines': [json.dumps(event)]}))
    current['target_resolution'] = {'status': 'resolved', 'allowed_services': ['entry']}
    records = inv.evidence_index(current)
    condition = inv.ObservationCondition(operation='text_logs', object_name='entry#req-1',
        field=field, expected=expected)
    assert inv._condition_value(json.loads(records['e1.1']['payload']), condition) == actual
    assert inv._candidate_scope_limit(current, inv.Alternative(explanation='finite', status='unresolved',
        condition=condition)) == ''
    condition.object_name = 'outside#req-1'
    assert inv._candidate_scope_limit(current, inv.Alternative(explanation='finite', status='unresolved',
        condition=condition))


def test_log_predicates_can_support_direct_cause_but_missing_chain_still_rejects():
    from src.probe.protocol import evidence
    current = stopped_state()
    for index, trace in ((6, {'connection_established': False, 'phase': 'connect'}),
                         (7, {'connection_established': True, 'response_status': 503, 'phase': 'completed'})):
        title, payload = current['raw_evidence'][index]
        raw = json.loads(payload)
        event = json.loads(raw['payload']['lines'][0])
        event['upstream_request'] = trace
        raw['payload']['lines'] = [json.dumps(event)]
        current['raw_evidence'][index] = (title, json.dumps(evidence(
            target_id=raw['target_id'], operation=raw['operation'], payload=raw['payload'])))
    records = inv.evidence_index(current)
    answer = cause_decision(current, records)
    answer.alternatives = []
    for service, field, expected in (('localapp', 'upstream_request.connection_established', True),
                                     ('edge', 'upstream_request.response_status', 200)):
        condition = inv.ObservationCondition(operation='text_logs', object_name=service + '#req-1',
            field=field, expected=expected)
        answer.alternatives.append(inv.Alternative(explanation=inv.condition_statement(condition),
            claim_type='observed_condition', condition=condition, status='unresolved'))
    result = inv.decide_from_evidence(current, answer, records)
    assert result['diagnosis']['kind'] == 'confirmed_cause'
    assert all(a['verification'] == 'predicate_verified' for a in result['investigation_memory']['alternatives'])
    del records['e6.1']
    assert inv.decide_from_evidence(current, answer, records)['diagnosis']['kind'] != 'confirmed_cause'


def test_alternative_review_exposes_binding_and_citation_failures_without_changing_claim():
    current = state(('ports', {'local_port': 9000, 'ports': [
        {'status': 'LISTEN', 'local': {'port': 9000}}], 'matched_count': 1}))
    records = inv.evidence_index(current)
    condition = inv.ObservationCondition(operation='ports', object_name='9000', field='listening', expected=False)
    alternative = inv.Alternative(explanation='服务内部错误导致失败', status='excluded',
        condition=condition, claim_type='observed_condition', evidence=[inv.Citation(evidence_id='e1.1'),
            inv.Citation(evidence_id='outside')])
    before = alternative.model_dump()
    review, = inv._alternative_review([alternative], records)
    assert alternative.model_dump() == before
    assert not review['text_bound']
    assert review['exact_condition_text'] == 'ports/9000: listening == false'
    assert review['observations'][0]['actual'] is True
    assert inv._valid_citations([inv.Citation(**ref) for ref in review['observations'][0]['citations']], records)
    assert len(review['citation_issues']) == 2
    assert review['citation_issues'][0]['citation_snippets']
    assert '当前有效业务范围' in review['citation_issues'][1]['reason']
    answer = decision(alternatives=[alternative])
    inv._validate_alternatives(answer, records)
    assert not inv._condition_bound(alternative.explanation, alternative.condition)


def test_cause_alternative_guidance_points_to_evidence_without_mutating_review():
    finite = {'explanation': 'ports/9000: listening == false (服务未启动)',
        'claim_type': 'observed_condition', 'condition': {'expected': False}, 'text_bound': False,
        'observations': [{'actual': True}]}
    causal = {'explanation': 'network policy caused the timeout', 'claim_type': 'causal_explanation',
        'condition': None, 'text_bound': False, 'observations': []}
    before = json.dumps([finite, causal], sort_keys=True)

    guidance = inv._cause_alternative_guidance([finite, causal])

    assert 'exact_condition_text' in guidance[0]['text_binding']
    assert 'not the causal wording' in guidance[0]['text_binding']
    assert 'contradicts expected' in guidance[0]['observed_result']
    assert 'keep it unresolved' in guidance[1]['causal_claim']
    assert guidance[1]['admissible_statuses'] == ['unresolved', 'unavailable']
    assert 'cannot accept supported/excluded' in guidance[1]['status_contract']
    assert guidance[0]['admissible_statuses'] == ['supported', 'excluded', 'unresolved', 'unavailable']
    assert json.dumps([finite, causal], sort_keys=True) == before


def test_supported_primary_facts_are_reported_as_terminal_blockers_without_reclassifying():
    current = stopped_state()
    records = inv.evidence_index(current)
    condition = inv.ObservationCondition(operation='ports', object_name='9002', field='listening', expected=False)
    answer = decision(alternatives=[inv.Alternative(explanation=inv.condition_statement(condition),
        claim_type='observed_condition', condition=condition, status='unresolved')])
    inv._validate_alternatives(answer, records)
    alternative = answer.alternatives[0]
    assert alternative.status == 'supported'
    before = alternative.model_dump()
    review, = inv._alternative_review([alternative], records)
    assert review['terminal_eligible'] is False
    assert review['status'] == 'supported' and review['critical'] is True
    guidance, = inv._cause_alternative_guidance([review])
    assert 'supported is not excluded' in guidance['terminal_contract']
    assert 'supporting_evidence' in guidance['terminal_contract']
    assert alternative.model_dump() == before


def test_causal_review_does_not_instruct_replacing_causal_claim_with_supported_fact():
    current = stopped_state()
    records = inv.evidence_index(current)
    condition = inv.ObservationCondition(operation='ports', object_name='9002', field='listening', expected=False)
    alternative = inv.Alternative(explanation='a competing cause', claim_type='causal_explanation',
        condition=condition, status='unresolved')
    review, = inv._alternative_review([alternative], records)
    before = alternative.model_dump()
    guidance, = inv._cause_alternative_guidance([review])
    assert 'Use exactly exact_condition_text' not in guidance['text_binding']
    assert 'critical=false' in guidance['terminal_contract']
    assert 'noncritical_reason' in guidance['terminal_contract']
    assert 'supporting_evidence' in guidance['terminal_contract']
    assert alternative.model_dump() == before


@pytest.mark.asyncio
async def test_cause_feedback_uses_inherited_conditions_and_only_persisted_candidate_ids(monkeypatch):
    current = stopped_state()
    condition = inv.ObservationCondition(operation='ports', object_name='9002', field='listening', expected=True)
    seed = decision(alternatives=[inv.Alternative(explanation=inv.condition_statement(condition),
        condition=condition, claim_type='observed_condition', status='unresolved')])
    records = inv.evidence_index(current)
    current.update(inv.decide_from_evidence(current, seed, records))
    candidate = next(c for c in current['investigation_memory']['hypothesis_tracking']['candidates']
                     if c.get('condition') == condition.model_dump())
    pending = cause_decision(current, records)
    pending.alternatives = [inv.Alternative(explanation=inv.condition_statement(condition),
        hypothesis_id=candidate['id'], claim_type='observed_condition', status='excluded'),
        inv.Alternative(explanation='unverified new causal history', status='unresolved')]
    before = pending.model_dump()
    proposals = AsyncMock(side_effect=[pending, cause_decision(current, records)])
    monkeypatch.setattr(inv, 'create_agent_llm', lambda **kw: object())
    monkeypatch.setattr(inv, 'ainvoke_structured', proposals)
    result = await inv.InvestigationStrategy().decide(current)
    prompt, inputs = proposals.await_args_list[1].args[2:4]
    feedback = json.loads(inputs['cause_feedback'])
    assert 'evidence' not in inputs and 'memory' not in inputs
    assert json.loads(inputs['saved_candidates'])
    rendered = prompt.format_messages(**inputs)
    assert rendered and 'unverified new causal history' in rendered[-1].content
    inherited, new = feedback['validated_alternatives']
    assert inherited['hypothesis_id'] == candidate['id']
    assert inherited['condition'] == condition.model_dump()
    assert new['hypothesis_id'] == ''
    review = feedback['alternative_review'][0]
    assert feedback['alternative_guidance'][0]['observed_result'].startswith('The actual value contradicts expected')
    assert review['condition'] == condition.model_dump()
    assert review['observations'][0]['actual'] is False
    assert inv._valid_citations([inv.Citation(**ref) for ref in review['observations'][0]['citations']], records)
    assert pending.model_dump() == before
    assert result['diagnosis']['kind'] == 'confirmed_cause'
