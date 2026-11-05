"""Candidate contract and decoded decision provenance; no real model calls."""
import json
import importlib
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from pydantic import ValidationError
from src.probe.protocol import evidence
from src.settings import settings

from src.agent.aiops import structured
from src.agent.aiops.strategies import investigation as inv
from tests.test_concrete_investigation_checks import state, decision, decide


def test_live_contract_requires_explicit_list_but_legacy_and_empty_remain_valid():
    assert inv.InvestigationDecision(hypothesis='unknown').alternatives == []
    with pytest.raises(ValidationError):
        inv.InvestigationProposal.model_validate({'hypothesis': 'unknown'})
    assert inv.InvestigationProposal(hypothesis='unknown', alternatives=[]).alternatives == []
    assert 'alternatives' in inv.InvestigationProposal.model_json_schema()['required']


def test_completed_alternatives_do_not_require_executable_check_fields():
    proposal = inv.InvestigationProposal.model_validate({
        'hypothesis': 'downstream 连通层失败',
        'next_check': '继续调查',
        'alternatives': [
            {'explanation': 'downstream TCP失败', 'status': 'supported',
             'check': {'next_check': '已有结果：downstream TCP failed', 'next_tools': []}},
            {'explanation': 'edge TCP失败', 'status': 'excluded',
             'check': {'next_check': '已有结果：edge TCP ok', 'next_tools': []}},
            {'explanation': 'localapp内部错误', 'status': 'unresolved',
             'check': {'next_check': '读取 localapp 日志', 'next_tools': [],
                       'discriminating_question': '是否有自身异常？',
                       'expected_observation': '有堆栈则支持自身错误'}}
        ]
    })

    missing = inv._incomplete_check_contract_fields(proposal, include_alternatives=True)

    assert missing == [
        'decision.next_tools',
        'decision.discriminating_question', 'decision.expected_observation',
        'alternatives[2].check.next_tools'
    ]


@pytest.mark.parametrize('status', ['supported', 'excluded'])
@pytest.mark.parametrize('execution_field', ['next_tools', 'next_arguments'])
def test_completed_status_does_not_hide_an_incomplete_new_check(status, execution_field):
    check = {'next_check': 'read another log'}
    check[execution_field] = (['probe_text_log'] if execution_field == 'next_tools' else
                              {'probe_text_log': {'service': 'edge', 'path': 'D:/edge.log', 'lines': 100}})
    proposal = inv.InvestigationProposal(hypothesis='unknown', alternatives=[
        inv.Alternative(explanation='edge explanation', status=status,
                        check=inv.CandidateCheck(**check))])

    missing = inv._incomplete_check_contract_fields(proposal, include_alternatives=True)

    assert 'alternatives[0].check.discriminating_question' in missing
    assert 'alternatives[0].check.expected_observation' in missing
    assert ('alternatives[0].check.next_tools' in missing) is (execution_field == 'next_arguments')


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['supported', 'excluded'])
async def test_unverified_completed_claim_with_execution_intent_gets_one_correction(monkeypatch, status):
    current = state(('inventory', {'configured_services': {'edge': {
        'kind': 'process', 'text_logs_available': True, 'text_logs': ['D:/edge.log']}}}))
    arguments = {'probe_text_log': {'service': 'edge', 'path': 'D:/edge.log', 'lines': 100}}
    partial = inv.InvestigationProposal(hypothesis='unknown', alternatives=[
        inv.Alternative(explanation='edge internal error', status=status,
            check=inv.CandidateCheck(next_check='inspect edge log',
                next_tools=['probe_text_log'], next_arguments=arguments))])
    corrected = inv.InvestigationProposal(hypothesis='unknown', alternatives=[],
        next_check='inspect edge log', next_tools=['probe_text_log'], next_arguments=arguments,
        discriminating_question='internal error or forwarding failure?',
        expected_observation='internal exception supports an edge error; forwarding failure leaves downstream unresolved')
    model = AsyncMock(side_effect=[partial, corrected])
    monkeypatch.setattr(inv, 'create_agent_llm', lambda **kwargs: object())
    monkeypatch.setattr(inv, 'ainvoke_structured', model)

    result = await inv.InvestigationStrategy().decide(current)

    assert model.await_count == 2
    assert result['plan'] == ['inspect edge log']
    assert result['investigation_memory']['next_arguments'] == arguments
    trace = result['investigation_memory']['decision_trace']['attempts']
    assert [attempt['purpose'] for attempt in trace] == ['initial', 'check_correction']
    assert not trace[0]['guard_result']['plan']
    assert not result['investigation_memory']['root_cause']
    assert result['investigation_memory']['outcome'] == 'investigating'


@pytest.mark.asyncio
@pytest.mark.parametrize('repair', [True, False])
async def test_partial_saved_candidate_and_argument_only_intent_get_one_contract_correction(monkeypatch, repair):
    current = state(('inventory', {'configured_services': {
        'edge': {'kind': 'process', 'text_logs_available': True, 'text_logs': ['D:/edge.log']}}}))
    edge_id = 'h-9cce480e737bafc4'
    question_id = 'q-223d9dbadc45'
    current['investigation_memory'] = {
        'hypothesis_tracking': {'leading_id': 'h-ee419a9bf2c7580f', 'identity_issues': [],
            'candidates': [
                {'id': 'h-ee419a9bf2c7580f', 'birth_step': 1, 'seen_observations': [],
                 'supporting_observations': 0, 'contradicting_observations': 0,
                 'explanation': 'ports/14188: listening == false',
                 'source_explanation': 'ports/14188: listening == false',
                 'source_explanations': ['ports/14188: listening == false'],
                 'condition': {'operation': 'ports', 'object_name': '14188',
                     'field': 'listening', 'expected': False},
                 'condition_binding': 'bound', 'prediction_bound': True,
                 'check': None,
                 'proposal': {'explanation': 'ports/14188: listening == false',
                              'status': 'unresolved', 'hypothesis_id': 'h-ee419a9bf2c7580f',
                              'evidence': [], 'limitation': '', 'critical': True,
                              'noncritical_reason': '',
                              'condition': {'operation': 'ports', 'object_name': '14188',
                                  'field': 'listening', 'expected': False},
                              'original_status': '', 'verification': 'unverified',
                              'claim_type': 'observed_condition', 'check': None},
                 'status': 'active', 'check_rejection': '',
                 'relation': 'neutral', 'evidence_history': [], 'evidence_ids': []},
                {'id': edge_id, 'birth_step': 1, 'seen_observations': [],
                 'supporting_observations': 0, 'contradicting_observations': 0,
                 'explanation': 'edge 入口返回503，原因未查明',
                 'source_explanation': 'edge 入口自身故障，需要读取 edge 日志区分自身错误与转发失败',
                 'source_explanations': ['edge 入口自身故障，需要读取 edge 日志区分自身错误与转发失败'],
                 'condition': None, 'condition_binding': 'not_applicable', 'prediction_bound': False,
                 'check': {'next_check': '读取 edge 日志', 'next_tools': ['probe_text_log'],
                           'discriminating_question': '', 'expected_observation': '',
                           'next_arguments': {'probe_text_log': {'service': 'edge', 'path': 'D:/edge.log', 'lines': 100}},
                           'repeat_reason': '', 'repeat_evidence_ids': []},
                 'proposal': {'explanation': 'edge 入口自身故障，需要读取 edge 日志区分自身错误与转发失败',
                              'status': 'unresolved', 'hypothesis_id': edge_id, 'evidence': [],
                              'limitation': '', 'critical': True, 'noncritical_reason': '',
                              'condition': None, 'original_status': '', 'verification': 'unverified',
                              'claim_type': 'causal_explanation',
                              'check': {'next_check': '读取 edge 日志', 'next_tools': ['probe_text_log'],
                                        'discriminating_question': '', 'expected_observation': '',
                                        'next_arguments': {'probe_text_log': {'service': 'edge', 'path': 'D:/edge.log', 'lines': 100}},
                                        'repeat_reason': '', 'repeat_evidence_ids': []}},
                 'status': 'active', 'check_rejection': '',
                 'relation': 'neutral', 'evidence_history': [], 'evidence_ids': []},
            ]},
        'unresolved_questions': [{'id': question_id,
            'question': 'edge 入口自身故障还是转发 localapp 失败？'}],
    }
    edge_log = {'probe_text_log': {'service': 'edge', 'path': 'D:/edge.log', 'lines': 100}}
    partial = inv.InvestigationProposal.model_validate({
        'hypothesis': 'edge 入口自身故障，需要读取 edge 日志区分自身错误与转发失败',
        'hypothesis_id': edge_id,
        'alternatives': [
            {'explanation': 'edge 日志能区分入口故障与上游传播失败', 'status': 'unresolved',
             'check': {'next_check': '读取 edge 日志', 'next_tools': [],
                       'discriminating_question': 'edge 日志记录自身异常还是转发失败？',
                       'expected_observation': '自身异常支持入口故障，转发错误保留下游解释'}},
        ],
        'next_question_id': question_id,
        'next_arguments': edge_log,
    })
    corrected = inv.InvestigationProposal.model_validate({
        'hypothesis': 'edge 入口错误与转发失败需由日志区分', 'alternatives': [],
        'next_check': '读取 edge 允许日志，区分入口自身错误与转发失败', 'next_tools': ['probe_text_log'],
        'discriminating_question': 'edge 日志是否记录自身异常或向 localapp 转发失败？',
        'expected_observation': '入口自身错误支持 edge 故障；转发失败保留下游解释',
        'next_arguments': edge_log,
    })
    prompts = []

    async def model(llm, schema, prompt, inputs):
        prompts.append(inputs)
        return partial if len(prompts) == 1 or not repair else corrected

    monkeypatch.setattr(inv, 'create_agent_llm', lambda **kwargs: object())
    monkeypatch.setattr(inv, 'ainvoke_structured', model)
    result = await inv.InvestigationStrategy().decide(current)

    assert len(prompts) == 2
    feedback = json.loads(prompts[1]['check_feedback'])
    assert feedback['attempts'] == 1
    assert feedback['missing_fields']
    assert 'decision.next_check' in feedback['missing_fields']
    assert any(name.startswith('alternatives[') for name in feedback['missing_fields'])
    trace = result['investigation_memory']['decision_trace']['attempts']
    assert [item['purpose'] for item in trace] == ['initial', 'check_correction']
    assert result['investigation_memory']['check_correction']['status'] == ('continued' if repair else 'rejected')
    assert result['investigation_memory'].get('identity_correction') is None
    assert result['plan'] == (['读取 edge 允许日志，区分入口自身错误与转发失败'] if repair else [])
    if not repair:
        assert result['investigation_memory']['check_correction']['remaining_missing_fields']
        assert '仍缺执行字段' in result['diagnosis']['stop_reason']
    else:
        from langchain_core.tools import StructuredTool
        ex = importlib.import_module('src.agent.aiops.executor')

        async def read_edge_log(service: str, path: str, lines: int = 100):
            return evidence(target_id=settings.PROBE_TARGET_ID, operation='text_logs', payload={
                'service': service, 'path': path, 'line_limit': lines,
                'lines': ['{"status": 200, "detail": "healthy"}']})

        tool = StructuredTool.from_function(coroutine=read_edge_log, name='probe_text_log', description='fixture')
        monkeypatch.setattr(ex, '_get_tools_for_state', AsyncMock(return_value=([tool], None)))
        execution_state = {**current, 'autonomous_investigation': True,
                           'investigation_memory': result['investigation_memory']}
        summary, raw = await ex._run_step(result['plan'][0], execution_state)
        assert '已执行计划检查' in summary

        after = {**execution_state,
                 'past_steps': [*execution_state['past_steps'], (result['plan'][0], summary)],
                 'raw_evidence': [*execution_state['raw_evidence'], (result['plan'][0], raw)]}
        records = inv.evidence_index(after)
        context = inv._decision_memory_context(result['investigation_memory'], after, records)
        edge_summary = next(row for row in context['evidence_summaries']
                            if row['operation'] == 'text_logs' and row['subject'] == 'edge')
        assert edge_summary['summary'] == 'text_logs edge: 1 log lines'
        agenda = next(row for row in context['decision_agenda']['checks']
                      if row['next_check'] == result['plan'][0])
        assert agenda['progress'][0]['evidence_ids']
        assert '日志是应用自身记录' in agenda['progress'][0]['remaining_unknown']


@pytest.mark.asyncio
async def test_valid_saved_candidate_fallback_does_not_add_contract_correction(monkeypatch):
    current = state()
    proposal = inv.InvestigationProposal.model_validate({
        'hypothesis': '原因仍需检查', 'alternatives': [
            {'explanation': 'downstream TCP不可达', 'status': 'unresolved',
             'condition': {'operation': 'dependency_probe', 'object_name': 'downstream',
                          'field': 'tcp', 'expected': 'failed'},
             'check': {'next_check': '检查 downstream 连通性',
                       'next_tools': ['probe_dependency_probe'],
                       'discriminating_question': 'downstream 是否可连接？',
                       'expected_observation': 'TCP failed支持不可达',
                       'next_arguments': {'probe_dependency_probe': {'dependency': 'downstream'}}}}
        ],
    })
    calls = 0

    async def model(llm, schema, prompt, inputs):
        nonlocal calls
        calls += 1
        return proposal

    monkeypatch.setattr(inv, 'create_agent_llm', lambda **kwargs: object())
    monkeypatch.setattr(inv, 'ainvoke_structured', model)
    result = await inv.InvestigationStrategy().decide(current)
    assert calls == 1
    assert result['plan'] == ['检查 downstream 连通性']


@pytest.mark.asyncio
@pytest.mark.parametrize('arguments', [{'hypothesis': 'unknown'}, {'hypothesis': 'unknown', 'alternatives': []}])
async def test_decoded_trace_distinguishes_omission_and_empty_without_response_body(monkeypatch, arguments):
    llm = RunnableLambda(lambda _: None)
    llm.with_structured_output = lambda *args, **kwargs: RunnableLambda(lambda _: None)
    raw = AIMessage(content='private reasoning must not be recorded', tool_calls=[
        {'name': 'InvestigationDecision', 'args': arguments, 'id': 'call-1'}])
    monkeypatch.setattr(structured, 'ainvoke_with_retry', AsyncMock(return_value={
        'raw': raw, 'parsed': inv.InvestigationDecision.model_validate(arguments), 'parsing_error': None}))
    with structured.capture_decision_output() as trace:
        result = await structured.ainvoke_structured(llm, inv.InvestigationDecision,
            ChatPromptTemplate.from_template('{input}'), {'input': 'check'})
    assert result.alternatives == []
    assert trace[0]['decoded_arguments'] == arguments
    assert trace[0]['alternatives_presence'] == ('empty' if 'alternatives' in arguments else 'omitted')
    assert trace[0]['parsed_proposal']['alternatives'] == []
    assert 'private reasoning' not in json.dumps(trace)


def competing_decision():
    return decision(hypothesis='entry process absent', hypothesis_condition=inv.ObservationCondition(
        operation='processes', object_name='entry', field='process_present', expected=False),
        next_check='', next_tools=[], next_arguments=None, alternatives=[inv.Alternative(
            explanation='downstream TCP unreachable', status='unresolved',
            condition=inv.ObservationCondition(operation='dependency_probe', object_name='downstream',
                field='tcp', expected='failed'),
            check=inv.CandidateCheck(next_check='inspect downstream', next_tools=['probe_dependency_probe'],
                next_arguments={'probe_dependency_probe': {'dependency': 'downstream'}},
                discriminating_question='downstream failure or entry internal error?',
                expected_observation='TCP failed supports connectivity fault; TCP ok contradicts this predicate'))])


def test_reemitted_candidate_keeps_saved_check_and_candidate_specific_progress():
    current = state()
    first = decide(current, competing_decision())
    current.update(first)
    candidate = next(c for c in first['investigation_memory']['hypothesis_tracking']['candidates']
                     if c['condition']['object_name'] == 'downstream')
    answer = competing_decision()
    answer.alternatives[0].hypothesis_id = candidate['id']
    answer.alternatives[0].check = None
    second = decide(current, answer)
    assert second['plan'] == ['inspect downstream']
    saved = next(c for c in second['investigation_memory']['hypothesis_tracking']['candidates'] if c['id'] == candidate['id'])
    assert saved['check'] == candidate['check']
    progress = second['investigation_memory']['candidate_check_progress'][candidate['id']]
    assert progress[0]['status'] == 'unexecuted'
    assert progress[0]['arguments'] == {'dependency': 'downstream'}


def test_saved_failed_query_remains_visible_but_is_not_reexecuted():
    current = state()
    current.update(decide(current, competing_decision()))
    candidate = next(c for c in current['investigation_memory']['hypothesis_tracking']['candidates']
                     if c['condition']['object_name'] == 'downstream')
    current['raw_evidence'].append(('failed check', json.dumps({'data_source': 'tool_execution',
        'tool': 'probe_dependency_probe', 'arguments': {'dependency': 'downstream'},
        'status': 'failed', 'reason': 'fixture failure'})))
    answer = competing_decision()
    answer.alternatives[0].hypothesis_id = candidate['id']
    answer.alternatives[0].check = None
    result = decide(current, answer)
    assert result['plan'] == []
    progress = result['investigation_memory']['candidate_check_progress'][candidate['id']]
    assert progress[0]['status'] == 'unavailable'
    assert '不原样自动重试' in progress[0]['limitation']


@pytest.mark.asyncio
async def test_capture_is_isolated_between_concurrent_decisions_and_resets(monkeypatch):
    import asyncio
    llm = RunnableLambda(lambda _: None)
    llm.with_structured_output = lambda *args, **kwargs: RunnableLambda(lambda _: None)
    async def model(chain, inputs, **kwargs):
        await asyncio.sleep(0)
        arguments = {'hypothesis': inputs['input'], 'alternatives': []}
        raw = AIMessage(content='', tool_calls=[{'name': 'InvestigationDecision', 'args': arguments, 'id': 'one'}])
        return {'raw': raw, 'parsed': inv.InvestigationProposal.model_validate(arguments), 'parsing_error': None}
    monkeypatch.setattr(structured, 'ainvoke_with_retry', model)
    async def capture(name):
        with structured.capture_decision_output() as rows:
            await structured.ainvoke_structured(llm, inv.InvestigationProposal,
                ChatPromptTemplate.from_template('{input}'), {'input': name})
        return rows
    left, right = await asyncio.gather(capture('left'), capture('right'))
    assert [row['decoded_arguments']['hypothesis'] for row in left] == ['left']
    assert [row['decoded_arguments']['hypothesis'] for row in right] == ['right']
    assert structured._decision_capture.get() is None


@pytest.mark.asyncio
@pytest.mark.parametrize('omit', [False, True])
async def test_live_sdk_records_predefault_arguments_and_existing_json_fallback(monkeypatch, omit):
    import httpx
    from langchain_openai import ChatOpenAI
    requests = []
    async def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        arguments = {'hypothesis': 'unknown', **({} if omit else {'alternatives': []})}
        if len(requests) == 1:
            function = body['tools'][0]['function']
            assert function['name'] == 'InvestigationDecision'
            assert 'alternatives' in function['parameters']['required']
            message = {'role': 'assistant', 'content': 'private reasoning', 'tool_calls': [
                {'id': 'one', 'type': 'function', 'function': {
                    'name': function['name'], 'arguments': json.dumps(arguments)}}]}
        else:
            assert 'tools' not in body
            message = {'role': 'assistant', 'content': json.dumps({'hypothesis': 'unknown', 'alternatives': []})}
        return httpx.Response(200, json={'id': 'fixture', 'object': 'chat.completion', 'created': 1,
            'model': 'offline', 'choices': [{'index': 0, 'finish_reason': 'stop', 'message': message}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 10, 'total_tokens': 20}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        llm = ChatOpenAI(model='offline', api_key='offline', base_url='https://offline.invalid/v1',
                         http_async_client=client, max_retries=0)
        monkeypatch.setattr(inv, 'create_agent_llm', lambda **kwargs: llm)
        result = await inv.InvestigationStrategy().decide(state())
    attempt, = result['investigation_memory']['decision_trace']['attempts']
    assert len(requests) == (2 if omit else 1)
    assert attempt['outputs'][0]['alternatives_presence'] == ('omitted' if omit else 'empty')
    assert attempt['outputs'][0]['status'] == ('rejected' if omit else 'parsed')
    assert attempt['parsed_proposal']['alternatives'] == []
    assert attempt['guard_result']['plan'] == []
    assert 'private reasoning' not in json.dumps(attempt)
    if omit:
        assert attempt['outputs'][1]['stage'] == 'json_fallback'
        assert attempt['outputs'][1]['status'] == 'parsed'


@pytest.mark.asyncio
async def test_candidates_execute_consume_and_reopen_without_model_reselection(tmp_path, monkeypatch):
    from langchain_core.tools import StructuredTool
    from src.agent.aiops.events import investigation_summary
    from src.agent.aiops.strategies.default import DefaultReplanStrategy
    from scripts.mechanism_behavior import behavior_snapshot, audit_behavior
    from datetime import datetime, timezone
    ex = importlib.import_module('src.agent.aiops.executor')
    graph_module = importlib.import_module('src.agent.aiops.graph')
    monkeypatch.setattr(settings, 'ENABLE_HITL', False)
    monkeypatch.setattr(settings, 'AIOPS_CHECKPOINT_DB_PATH', str(tmp_path / 'candidates.sqlite'))
    initial = state(('dependency_probe', {'dependency': 'entry', 'tcp': 'ok', 'http': {'status': 503}}))
    initial.update(autonomous_investigation=True, plan=['initial'], response='')
    async def planner(current):
        return {'plan': ['initial']}
    async def probe(dependency: str):
        return evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
                        payload={'dependency': dependency, 'tcp': 'ok', 'http': {'status': 200}})
    tool = StructuredTool.from_function(coroutine=probe, name='probe_dependency_probe', description='fixture')
    invoke_tool = AsyncMock(side_effect=tool.ainvoke)
    wrapped = SimpleNamespace(name=tool.name, description=tool.description, args=tool.args, ainvoke=invoke_tool)
    monkeypatch.setattr(ex, '_get_tools_for_state', AsyncMock(return_value=([wrapped], None)))
    monkeypatch.setattr(ex, 'create_agent_llm', Mock(side_effect=AssertionError('no executor model')))
    async def executor(current):
        step = current['plan'][0]
        if step == 'initial':
            return {'plan': [], 'past_steps': [(step, 'entry HTTP503')]}
        text, raw = await ex._run_step(step, current)
        return {'plan': [], 'past_steps': [(step, text)], 'raw_evidence': [(step, raw)]}
    monkeypatch.setattr(graph_module, 'planner', planner)
    monkeypatch.setattr(graph_module, 'executor', executor)
    llm = RunnableLambda(lambda _: None)
    llm.with_structured_output = lambda *args, **kwargs: RunnableLambda(lambda _: None)
    monkeypatch.setattr(inv, 'create_agent_llm', lambda **kwargs: llm)
    prompts = []
    async def model(chain, inputs, **kwargs):
        prompts.append(inputs)
        assert 'decision_trace' not in json.loads(inputs['memory'])
        answer = competing_decision()
        if len(prompts) == 2:
            saved = json.loads(inputs['memory'])['hypothesis_tracking']['candidates']
            alternative = next(c for c in saved if c['condition']['object_name'] == 'downstream')
            answer.alternatives[0].hypothesis_id = alternative['id']
            answer.alternatives[0].check = None
        arguments = answer.model_dump()
        raw = AIMessage(content='', tool_calls=[{'name': 'InvestigationDecision', 'args': arguments, 'id': 'one'}])
        return {'raw': raw, 'parsed': inv.InvestigationProposal.model_validate(arguments), 'parsing_error': None}
    monkeypatch.setattr(structured, 'ainvoke_with_retry', AsyncMock(side_effect=model))
    config = {'configurable': {'thread_id': 'candidate-contract'}}
    service = graph_module.AIOpsService()
    snapshots = []
    try:
        graph = await service._persistent_graph(DefaultReplanStrategy())
        paused = await graph.ainvoke(initial, config, interrupt_after=['replanner'])
        snapshots.append(behavior_snapshot(paused, datetime.now(timezone.utc).isoformat()))
        assert paused['plan'] == ['inspect downstream']
        final = await graph.ainvoke(None, config)
        snapshots.append(behavior_snapshot(final, datetime.now(timezone.utc).isoformat()))
        summary = investigation_summary(final)
        candidates = final['investigation_memory']['hypothesis_tracking']['candidates']
        downstream = next(c for c in candidates if c['condition']['object_name'] == 'downstream')
        entry = next(c for c in candidates if c['condition']['object_name'] == 'entry')
        assert downstream['id'] != entry['id']
        assert downstream['relation'] == 'contradict' and downstream['evidence_ids']
        assert entry['relation'] == 'neutral'  # The common HTTP503 cannot answer the process question.
        progress = summary['candidate_check_progress'][downstream['id']]
        assert progress[0]['status'] == 'observed' and progress[0]['evidence_ids']
        assert not final['plan']
        invoke_tool.assert_awaited_once_with({'dependency': 'downstream'})
        assert len(prompts) == 2
        audit = audit_behavior(snapshots, final['past_steps'], inv.execution_checks(final))
        assert audit['status'] == 'passed', audit
        tampered = deepcopy(snapshots)
        tampered[-1]['behavior_context']['decision_trace']['attempts'][-1]['outputs'][0]['decoded_arguments']['hypothesis'] = 'invented'
        assert audit_behavior(tampered, final['past_steps'], inv.execution_checks(final))['status'] == 'failed'
    finally:
        await service.close()
    reopened = graph_module.AIOpsService()
    try:
        graph = await reopened._persistent_graph(DefaultReplanStrategy())
        saved = (await graph.aget_state(config)).values
        assert saved['diagnosis'] == final['diagnosis']
        assert saved['response'] == final['response']
        assert saved['response'] == inv.localized_report(saved['diagnosis'])
        assert saved['investigation_memory']['decision_trace'] == final['investigation_memory']['decision_trace']
        details = await reopened.run_details('candidate-contract')
        assert details['investigation'] == summary
        assert details['diagnosis'] == final['diagnosis']
        assert 'decision_trace' not in json.dumps(summary)
    finally:
        await reopened.close()

