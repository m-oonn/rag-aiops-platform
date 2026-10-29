import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest

from scripts.evaluation_record import EvaluationRecord
from scripts.evaluate_autonomous_investigation import PaidRequestBudget
from scripts.evaluate_windows_probe import trace_evaluation_tools


def test_source_snapshot_preserves_dirty_source_and_excludes_credentials(tmp_path):
    root, output = tmp_path / 'repo', tmp_path / 'output'
    (root / 'src').mkdir(parents=True)
    output.mkdir()
    source = root / 'src/example.py'
    source.write_text('value = 42\n', encoding='utf-8')
    helper = root / 'scripts/model_request_diagnostics.py'
    helper.parent.mkdir()
    helper.write_text('# diagnostic source fixture\n', encoding='utf-8')
    (root / '.env').write_text('SECRET=never-copy')
    record = EvaluationRecord(root, output, {'mechanism_group': 'G11'})
    source.write_text('value = 99\n', encoding='utf-8')
    saved = output / 'source-snapshot/src/example.py'
    assert saved.read_text() == 'value = 42\n'
    assert record.value['source']['sources']['src/example.py'] == hashlib.sha256(saved.read_bytes()).hexdigest()
    assert (output / 'source-snapshot/scripts/model_request_diagnostics.py').read_bytes() == helper.read_bytes()
    assert not (output / 'source-snapshot/.env').exists()
    initial = json.loads((output / 'evaluation-record.json').read_text())
    assert initial['ended_at'] is None and initial['elapsed_ms'] is None
    assert initial['config_sha256'] == hashlib.sha256(json.dumps(
        {'mechanism_group': 'G11'}, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
    record.finish('failed', 'TimeoutError')
    final = json.loads((output / 'evaluation-record.json').read_text())
    assert final['status'] == 'failed' and final['error_type'] == 'TimeoutError'
    assert final['ended_at'] and final['elapsed_ms'] >= 0


@pytest.mark.parametrize('usage', [None, {}, {'prompt_tokens': 3},
    {'prompt_tokens': True, 'completion_tokens': 2},
    {'prompt_tokens': 3, 'completion_tokens': -1},
    {'prompt_tokens': 3, 'completion_tokens': float('nan')}])
def test_unknown_usage_is_not_zero_cost(tmp_path, usage):
    budget = PaidRequestBudget(tmp_path)
    budget.ledger = [{'reserved_cny': 0.4, 'http_status': 200, 'usage': usage}]
    assert budget.actual_cost_cny() is None
    assert budget.cost_summary()['usage_unknown_requests'] == 1
    assert budget.cost_summary()['reserved_cny'] == 0.4


def test_cost_summary_separates_inherited_and_new_requests(tmp_path):
    budget = PaidRequestBudget(tmp_path)
    inherited = {'reserved_cny': 0.4, 'http_status': 200,
        'usage': {'prompt_tokens': 100, 'completion_tokens': 10}}
    budget.ledger = [inherited.copy(), {'reserved_cny': 0.2, 'status': 'ReadTimeout'}]
    current = budget.cost_summary(1)
    assert current['requests'] == 1 and current['estimated_cny_peak'] is None
    assert current['reserved_cny'] == 0.2
    assert budget.cost_summary()['known_estimated_cny_peak'] > 0
    assert budget.ledger[0] == inherited
    assert budget.cost_summary(2)['estimated_cny_peak'] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('error', [RuntimeError, asyncio.CancelledError])
async def test_failed_tool_call_is_persisted_and_not_live_evidence(tmp_path, error):
    from langchain_core.tools import StructuredTool
    async def fail(query: str):
        started = json.loads((tmp_path / 'tool_trace.json').read_text())
        assert started[0]['status'] == 'started'
        raise error('do not serialize arbitrary error text')
    tool = StructuredTool.from_function(coroutine=fail, name='search_knowledge_base', description='test')
    trace = []
    wrapped = trace_evaluation_tools([tool], 'test-target', tmp_path, trace)
    with pytest.raises(error):
        await wrapped[0].ainvoke({'query': 'localapp'})
    row = json.loads((tmp_path / 'tool_trace.json').read_text())[0]
    assert row['status'] == 'failed' and row['error_type'] == error.__name__
    assert row['elapsed_ms'] >= 0 and row['ended_at']
    assert row['validated_live_evidence'] is False
    assert 'do not serialize' not in json.dumps(row)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['old_evidence', 'old_event', 'old_log'])
async def test_four_group_observation_boundary_rejects_pre_reset_data_but_preserves_trace(tmp_path, kind):
    from datetime import datetime, timedelta, timezone
    from langchain_core.tools import StructuredTool
    from src.probe.protocol import evidence
    boundary = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    old = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat().replace('+00:00', 'Z')
    if kind == 'old_evidence':
        name, payload = 'probe_dependency_probe', {'dependency': 'db'}
        value = evidence(target_id='test-target', operation='dependency_probe', payload=payload, collected_at=old)
    elif kind == 'old_event':
        name, payload = 'probe_event_log', {'events': [{'collected_at': old}]}
        value = evidence(target_id='test-target', operation='event_logs', payload=payload)
    else:
        name, payload = 'probe_text_log', {'lines': [json.dumps({'at': old, 'status': 200})]}
        value = evidence(target_id='test-target', operation='text_logs', payload=payload)
    async def read():
        return value
    tool = StructuredTool.from_function(coroutine=read, name=name, description='probe')
    trace = []
    wrapped = trace_evaluation_tools([tool], 'test-target', tmp_path, trace, boundary)
    with pytest.raises(ValueError, match='predates'):
        await wrapped[0].ainvoke({})
    saved = json.loads((tmp_path / 'tool_trace.json').read_text())
    assert saved[0]['result']['raw_hash'] == value['raw_hash']
    assert saved[0]['validated_live_evidence'] is False and saved[0]['status'] == 'failed'


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['launch', 'exit'])
async def test_controller_preserves_failed_child_attempt_without_model(tmp_path, failure):
    from scripts.verify_windows_local_faults import evaluate_model_case
    def launch(args, name):
        if failure == 'launch':
            raise OSError('test launch failure')
        return SimpleNamespace(wait=lambda: 7)
    with pytest.raises((OSError, RuntimeError)):
        await evaluate_model_case(tmp_path, 'normal', launch)
    row = json.loads(next(tmp_path.glob('model-attempt-*.json')).read_text())
    assert row['status'] == 'failed' and row['ended_at'] and row['elapsed_ms'] >= 0
    assert row['exit_code'] == (7 if failure == 'exit' else None)


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['ok', 'missing_usage', 'timeout', 'invalid_json', 'blocked', 'run_cap', 'sdk_timeout', 'failed_report', 'sdk_metadata'])
async def test_model_http_attempts_are_bound_to_inputs_and_preserve_prior_ledger(tmp_path, monkeypatch, mode):
    import importlib
    import httpx
    from unittest.mock import AsyncMock
    from scripts import evaluate_windows_probe as evaluation
    from src.agent.aiops import graph, planner, executor
    from src.probe.windows.config import ProbeConfig
    from src.settings import settings
    modules = [planner, executor, importlib.import_module('src.agent.aiops.strategies.investigation')]
    for module in modules:
        monkeypatch.setattr(module, 'create_agent_llm', module.create_agent_llm)
    for module in [planner, executor]:
        monkeypatch.setattr(module, 'load_agent_tools', module.load_agent_tools)
    for name in ['PROBE_ENABLED', 'PROBE_TARGET_ID', 'DIAGNOSTIC_TARGET_CATALOG',
            'PROBE_EVIDENCE_DIR', 'TERMCP_ENABLED', 'ENABLE_HITL', 'ENABLE_LLM_RETRY']:
        monkeypatch.setattr(settings, name, getattr(settings, name))
    monkeypatch.setattr(executor, '_tools_cache', {})
    monkeypatch.setattr(executor, '_tools_cache_at', {})
    calls = []
    async def respond(request):
        calls.append(json.loads(request.content))
        if mode in {'timeout', 'sdk_timeout'}:
            raise httpx.ReadTimeout('mock only')
        if mode == 'invalid_json':
            return httpx.Response(200, text='invalid')
        return httpx.Response(200, headers={'x-request-id': 'req-offline'}, json={'model': 'served-test',
            'id': 'chatcmpl-offline', 'object': 'chat.completion', 'created': 0,
            'choices': [{'index': 0, 'finish_reason': 'tool_calls', 'message': {'role': 'assistant',
                'content': None, 'tool_calls': [{'id': 'c1', 'type': 'function',
                    'function': {'name': 'offline_tool', 'arguments': '{}'}}]}}],
            **({'usage': {'prompt_tokens': 10, 'completion_tokens': 2}} if mode in {'ok', 'failed_report', 'sdk_metadata'} else {})})
    monkeypatch.setattr(httpx, 'AsyncHTTPTransport', lambda: httpx.MockTransport(respond))
    from src.agent import aiops_llm
    monkeypatch.setattr(aiops_llm, 'create_agent_llm', lambda **kwargs: SimpleNamespace(
        root_async_client=SimpleNamespace(_client=None, max_retries=2),
        root_client=SimpleNamespace(_client=None, max_retries=2)))
    if mode in {'sdk_timeout', 'sdk_metadata'}:
        from langchain_openai import ChatOpenAI
        monkeypatch.setattr(aiops_llm, 'create_agent_llm', lambda **kwargs: ChatOpenAI(
            api_key='offline-test-only', model='deepseek-flash',
            base_url='https://api.deepseek.com', **kwargs))
    monkeypatch.setattr(evaluation, 'save_mechanism_audit', AsyncMock(return_value={'passed': True}))
    class Service:
        async def execute(self, symptom, **kwargs):
            if mode == 'ok':
                loaded, _ = await planner.load_agent_tools()
                assert loaded == []
            llm = planner.create_agent_llm()
            assert llm.max_retries == 0
            assert llm.root_async_client.max_retries == 0
            assert llm.root_client.max_retries == 0
            if mode == 'sdk_timeout':
                await llm.ainvoke('offline timeout reproduction')
                pytest.fail('SDK timeout must propagate')
            if mode == 'sdk_metadata':
                message = await llm.ainvoke('offline response metadata')
                assert message.tool_calls[0]['name'] == 'offline_tool'
            else:
                await llm.http_async_client.post('https://api.deepseek.com/chat/completions',
                    json={'model': 'unpriced-test' if mode == 'blocked' else 'deepseek-flash',
                        'max_tokens': 99999, 'messages': []})
            if mode == 'failed_report':
                yield {'type': 'report', 'report': '未定位根因：mock transport only'}
                yield {'type': 'error', 'stage': 'investigation_failed',
                    'response': '未定位根因：mock transport only',
                    'investigation_failure': {'code': 'model_request_failed', 'message': 'mock timeout'}}
            else:
                yield {'type': 'complete', 'response': '未定位根因：mock transport only'}
        async def close(self):
            pass
    monkeypatch.setattr(graph, 'AIOpsService', Service)
    old = {'number': 1, 'reserved_cny': 0.4, 'http_status': 200,
        'usage': {'prompt_tokens': 10, 'completion_tokens': 2}}
    prior = tmp_path / 'prior.json'
    prior.write_text(json.dumps({'limit_cny': 5, 'reserved_cny': 0.4, 'requests': [old]}))
    before = prior.read_bytes()
    args = SimpleNamespace(previous_cost=prior, local_runbooks=None, knowledge_mcp_url=None,
        symptom_file=None, mechanism_group=None, knowledge_disabled=False)
    if mode == 'run_cap':
        args.run_budget_cny = 0.000001
    cfg = ProbeConfig('test-target', 'ws://127.0.0.1:18767/probe/ws', tmp_path / 'token')
    args.isolate_history = mode == 'ok'
    tools = [SimpleNamespace(name='probe_list_evidence')] if mode == 'ok' else []
    await evaluation.run_model(args, cfg, tmp_path, tools)
    if mode in {'blocked', 'run_cap'}:
        assert calls == []
        cost = json.loads((tmp_path / 'cost.json').read_text())
        assert cost['requests'] == [old] and prior.read_bytes() == before
        assert cost['blocked_requests'][-1]['sent'] is False
        assert cost['blocked_requests'][-1]['reason_code'] == {
            'blocked': 'unpriced_model', 'run_cap': 'per_run_cost_limit'}[mode]
        record = json.loads((tmp_path / 'evaluation-record.json').read_text())
        assert record['status'] == 'incomplete'
        assert record['blocked_requests'][0]['sent'] is False
        assert record['blocked_requests'][0]['reason_code'] == cost['blocked_requests'][-1]['reason_code']
        assert (tmp_path / record['blocked_requests'][0]['input_file']).exists()
        summary = json.loads((tmp_path / 'summary.json').read_text())
        assert summary['budget_stop_reason'] == cost['blocked_requests'][-1]['reason_code']
        return
    assert len(calls) == 1 and calls[0]['max_tokens'] == 4096 and calls[0]['stream'] is False
    cost = json.loads((tmp_path / 'cost.json').read_text())
    row = cost['requests'][1]
    assert cost['requests'][0] == old and prior.read_bytes() == before
    assert json.loads((tmp_path / row['input_file']).read_text()) == calls[0]
    assert row['started_at'] and row['ended_at'] and row['elapsed_ms'] >= 0
    summary = json.loads((tmp_path / 'summary.json').read_text())
    assert summary['cost_scope']['this_run']['requests'] == 1
    assert (summary['actual_estimated_cny_peak'] is None) == (mode not in {'ok', 'failed_report', 'sdk_metadata'})
    record = json.loads((tmp_path / 'evaluation-record.json').read_text())
    assert record['ended_at'] and record['elapsed_ms'] >= 0
    assert record['status'] == ('incomplete' if mode in {'timeout', 'invalid_json', 'sdk_timeout', 'failed_report'} else 'completed')
    if mode == 'failed_report':
        assert summary['has_final_report'] is True and summary['workflow_completed'] is False
        assert summary['error_events'] == 1
        assert summary['investigation_failure']['code'] == 'model_request_failed'
        assert (tmp_path / 'report.txt').read_text(encoding='utf-8') == '未定位根因：mock transport only'
    if mode == 'sdk_timeout':
        assert summary['execution_error'] == 'APITimeoutError'
    if mode in {'timeout', 'sdk_timeout'}:
        assert row['failure_stage'] == 'transport_unknown'
        assert row['response_metadata']['choices'] is None
    elif mode == 'invalid_json':
        assert row['http_status'] == 200 and row['failure_stage'] == 'response_parse'
    else:
        assert row['response_metadata'] == {'request_id': 'req-offline', 'completion_id': 'chatcmpl-offline',
            'choices': [{'index': 0, 'finish_reason': 'tool_calls', 'tool_call_count': 1}]}
    assert record['config']['retry']['structured_format_fallback'] is True
    assert record['config']['shared_history_enabled'] is (mode != 'ok')
