import pytest

from scripts.evaluate_windows_probe import classify_report, parse_args, mcp_url
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from scripts.evaluate_windows_probe import preflight
from scripts.evaluate_windows_probe import read_cost_ledger
from scripts.evaluate_windows_probe import local_runbook_retrieval, target_catalog
import json
from pathlib import Path


@pytest.mark.parametrize('reserved, rows', [
    (-1, []), (float('nan'), []), (6, []),
    (1, []), (1, [{'number': 2, 'reserved_cny': 1}]),
])
def test_invalid_cumulative_cost_never_resets_budget(tmp_path, reserved, rows):
    path = tmp_path / 'cost.json'
    path.write_text(json.dumps({'limit_cny': 5, 'reserved_cny': reserved, 'requests': rows}))
    with pytest.raises(ValueError):
        read_cost_ledger(path)


def test_reserved_request_without_usage_is_preserved(tmp_path):
    value = {'limit_cny': 5, 'reserved_cny': 0.4,
        'requests': [{'number': 1, 'reserved_cny': 0.4, 'status': 'reserved'}]}
    path = tmp_path / 'cost.json'
    path.write_text(json.dumps(value))
    assert read_cost_ledger(path) == value


def test_second_scenario_reservation_uses_remaining_shared_budget(tmp_path):
    from scripts.evaluate_autonomous_investigation import PaidRequestBudget, EvaluationBudgetExceeded
    first_dir, second_dir = tmp_path / 'first', tmp_path / 'second'
    first_dir.mkdir()
    second_dir.mkdir()
    first = PaidRequestBudget(first_dir, max_output_tokens=4096)
    while True:
        try:
            first.reserve({'model': 'deepseek-v4-flash', 'max_tokens': 4096})
        except EvaluationBudgetExceeded:
            break
    saved = read_cost_ledger(first_dir / 'cost.json')
    second = PaidRequestBudget(second_dir, max_output_tokens=4096)
    second.reserved, second.ledger = saved['reserved_cny'], saved['requests']
    before = len(second.ledger)
    with pytest.raises(EvaluationBudgetExceeded):
        second.reserve({'model': 'deepseek-v4-flash', 'max_tokens': 4096})
    assert second.reserved <= 5 and len(second.ledger) == before
    assert read_cost_ledger(first_dir / 'cost.json') == saved


@pytest.mark.asyncio
async def test_preflight_rejects_unexpected_tool_without_executing_it(tmp_path, monkeypatch):
    import src.agent.mcp_client as client
    from src.probe.evidence import PROBE_TOOL_OPERATIONS
    token = tmp_path / 'token'
    token.write_text('local-test-token', encoding='utf-8')
    names = [*PROBE_TOOL_OPERATIONS, 'probe_exec']
    tools = [SimpleNamespace(name=name, ainvoke=AsyncMock()) for name in names]
    monkeypatch.setattr(client, 'load_tools_for_config', AsyncMock(return_value=(tools, None)))
    close = Mock()
    monkeypatch.setattr(client, 'close_client_for_config', close)
    cfg = SimpleNamespace(token_file=token, gateway_url='ws://127.0.0.1:2040/probe/ws')
    with pytest.raises(AssertionError, match='unexpected Probe tools'):
        await preflight(cfg, tmp_path)
    for tool in tools:
        tool.ainvoke.assert_not_awaited()
    close.assert_called_once()
    assert not (tmp_path / 'preflight.json').exists()


def test_evaluation_defaults_to_free_preflight_and_requires_explicit_paid_mode():
    assert parse_args([]).run_model is False
    assert parse_args(['--run-model']).run_model is True
    args = parse_args(['--knowledge-mcp-url', 'http://127.0.0.1:9200/mcp'])
    assert not args.run_model and args.knowledge_mcp_url == 'http://127.0.0.1:9200/mcp'


@pytest.mark.parametrize('gateway, expected', [
    ('ws://127.0.0.1:2040/probe/ws', 'http://127.0.0.1:2040/mcp'),
    ('wss://127.0.0.1:2040/probe/ws', 'https://127.0.0.1:2040/mcp'),
])
def test_evaluation_uses_configured_gateway(gateway, expected):
    assert mcp_url(gateway) == expected


@pytest.mark.parametrize('report, expected', [
    ('', 'none'),
    ('未定位根因：模型结构化决策无效\n已保留证据', 'unlocated'),
    ('当前检查范围内未发现故障\n现场证据：[e1.1] running', 'healthy_within_checked_scope'),
    ('根因：服务停止\n现场证据：[e1.1] stopped', 'root_cause_reported'),
    ('服务正常', 'unrecognized'),
])
def test_evaluation_does_not_count_report_presence_as_diagnostic_success(report, expected):
    assert classify_report(report) == expected


def test_local_runbook_retrieval_is_real_isolated_and_not_live_evidence(tmp_path, monkeypatch):
    from src.agent.aiops import local_retrieval
    from src.agent.aiops.strategies.investigation import evidence_index
    original = local_retrieval._RUNBOOKS_DIR
    output = tmp_path / 'output'
    output.mkdir()
    documents = Path(__file__).resolve().parents[1] / 'docs/fixtures/windows-local-runbooks'
    # Fail if this isolated lookup accidentally reads the normal corpus.
    monkeypatch.setattr(local_retrieval, '_retrieve_kaggle', lambda *a, **k: [])
    monkeypatch.setattr(local_retrieval, '_retrieve_hf', lambda *a, **k: [])
    with local_runbook_retrieval(documents, output) as retrieve:
        context = retrieve('localapp 可用性异常')
        assert '手册不是现场事实' in context and 'downstream' in context
        assert local_retrieval._RUNBOOKS_DIR == documents.resolve()
        assert evidence_index({'raw_evidence': [('local runbook', json.dumps({
            'data_source': 'knowledge_base', 'content': context}))]}) == {}
    assert local_retrieval._RUNBOOKS_DIR == original
    trace = json.loads((output / 'knowledge_trace.json').read_text(encoding='utf-8'))
    assert trace['queries'][0]['context'] == context
    assert len(trace['queries'][0]['context_sha256']) == 64
    assert trace['sources'][0]['path'] == 'localapp-availability.md'
    assert not trace['vector_rag_evaluated']


def test_target_catalog_contains_allowed_query_names_without_credentials(tmp_path):
    from src.probe.windows.config import ProbeConfig, ServiceConfig, DependencyConfig
    cfg = ProbeConfig('test-target', 'ws://127.0.0.1:18767/probe/ws', tmp_path / 'secret-token',
        services={'localapp': ServiceConfig('TestApp', text_logs=('C:/logs/app.log',))},
        dependencies={'downstream': DependencyConfig('127.0.0.1', 18080, 'http')})
    text = target_catalog(cfg)
    data = json.loads(text)
    assert data['services']['localapp']['text_logs'] == ['C:/logs/app.log']
    assert data['dependencies']['downstream']['port'] == 18080
    assert 'secret-token' not in text and 'gateway_url' not in text
    assert 'token_file' not in text and 'tls_ca_file' not in text


def test_empty_runbook_directory_fails_before_evaluation(tmp_path):
    with pytest.raises(ValueError, match='no Markdown'):
        with local_runbook_retrieval(tmp_path, tmp_path):
            pytest.fail('empty corpus should not be used')


@pytest.mark.parametrize('url', [
    'http://example.com/mcp', 'https://127.0.0.1:9200/mcp',
    'http://user:secret@127.0.0.1:9200/mcp', 'http://127.0.0.1:9200/mcp?x=1',
    'http://127.0.0.1:9200/other',
])
def test_evaluation_knowledge_url_rejects_nonlocal_or_ambiguous_endpoints(url):
    with pytest.raises(SystemExit):
        parse_args(['--knowledge-mcp-url', url])


@pytest.mark.asyncio
async def test_evaluation_loads_both_tool_sets_and_closes_clients(tmp_path, monkeypatch):
    import src.agent.mcp_client as client
    from src.probe.evidence import PROBE_TOOL_OPERATIONS
    from scripts.evaluate_windows_probe import load_evaluation_tools
    token = tmp_path / 'token'
    token.write_text('test-token')
    cfg = SimpleNamespace(token_file=token, gateway_url='ws://127.0.0.1:2040/probe/ws')
    probe = [SimpleNamespace(name=name) for name in [*PROBE_TOOL_OPERATIONS, 'probe_list_evidence']]
    knowledge = SimpleNamespace(name='search_knowledge_base')
    load = AsyncMock(side_effect=[(probe, None), ([knowledge], None)])
    close = Mock()
    monkeypatch.setattr(client, 'load_tools_for_config', load)
    monkeypatch.setattr(client, 'close_client_for_config', close)
    async with load_evaluation_tools(cfg, 'http://127.0.0.1:9200/mcp') as tools:
        assert tools == [*probe, knowledge]
    assert close.call_count == 2
    knowledge_config = load.call_args_list[1].args[0]
    assert knowledge_config == {'knowledge': {'transport': 'streamable_http',
        'url': 'http://127.0.0.1:9200/mcp'}}


@pytest.mark.asyncio
async def test_evaluation_rejects_extra_knowledge_tools_before_any_call(tmp_path, monkeypatch):
    import src.agent.mcp_client as client
    from src.probe.evidence import PROBE_TOOL_OPERATIONS
    from scripts.evaluate_windows_probe import load_evaluation_tools
    token = tmp_path / 'token'
    token.write_text('test-token')
    cfg = SimpleNamespace(token_file=token, gateway_url='ws://127.0.0.1:2040/probe/ws')
    tools = [SimpleNamespace(name=name, ainvoke=AsyncMock())
        for name in [*PROBE_TOOL_OPERATIONS, 'probe_list_evidence']]
    extra = SimpleNamespace(name='probe_exec', ainvoke=AsyncMock())
    monkeypatch.setattr(client, 'load_tools_for_config', AsyncMock(side_effect=[
        (tools, None), ([extra], None)]))
    close = Mock()
    monkeypatch.setattr(client, 'close_client_for_config', close)
    with pytest.raises(RuntimeError, match='knowledge'):
        async with load_evaluation_tools(cfg, 'http://127.0.0.1:9200/mcp'):
            pytest.fail('unexpected tool accepted')
    assert close.call_count == 2
    extra.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_knowledge_trace_is_not_counted_as_live_host_evidence(tmp_path):
    from langchain_core.tools import StructuredTool
    from scripts.evaluate_windows_probe import trace_evaluation_tools
    async def search(query: str, kb_id: int = 14):
        return {'data_source': 'knowledge_base', 'results': [{'chunk_id': 'guide', 'content': query}]}
    tool = StructuredTool.from_function(coroutine=search, name='search_knowledge_base', description='Local guide')
    trace = []
    wrapped = trace_evaluation_tools([tool], 'windows-local-01', tmp_path, trace)
    result = await wrapped[0].ainvoke({'query': 'localapp'})
    assert result['data_source'] == 'knowledge_base'
    saved = json.loads((tmp_path / 'tool_trace.json').read_text(encoding='utf-8'))
    assert saved == trace and saved[0]['source'] == 'knowledge_base'
    assert saved[0]['validated_live_evidence'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('disabled', [False, True])
async def test_model_mode_wires_knowledge_without_sending_paid_requests(tmp_path, monkeypatch, disabled):
    import importlib
    import httpx
    from langchain_core.tools import StructuredTool
    from scripts.evaluate_windows_probe import run_model
    from src.settings import settings
    from src.probe.windows.config import ProbeConfig
    from src.agent.aiops import graph, planner, executor
    modules = [planner, executor, importlib.import_module('src.agent.aiops.strategies.investigation')]
    for module in modules:
        monkeypatch.setattr(module, 'create_agent_llm', module.create_agent_llm)
    for module in [planner, executor]:
        monkeypatch.setattr(module, 'load_agent_tools', module.load_agent_tools)
    monkeypatch.setattr(executor, '_tools_cache', {})
    monkeypatch.setattr(executor, '_tools_cache_at', {})
    for name in ['PROBE_ENABLED', 'PROBE_TARGET_ID', 'DIAGNOSTIC_TARGET_CATALOG',
            'PROBE_EVIDENCE_DIR', 'TERMCP_ENABLED', 'ENABLE_HITL', 'ENABLE_LLM_RETRY']:
        monkeypatch.setattr(settings, name, getattr(settings, name))
    async def reject_network(request):
        pytest.fail('offline orchestration must not send model requests')
    monkeypatch.setattr(httpx, 'AsyncHTTPTransport', lambda: httpx.MockTransport(reject_network))
    async def search(query: str, kb_id: int = 14):
        return {'data_source': 'knowledge_base', 'results': [{'chunk_id': 'guide', 'content': query}]}
    knowledge = StructuredTool.from_function(coroutine=search, name='search_knowledge_base', description='Local guide')
    closed = []
    class Service:
        async def execute(self, symptom, **kwargs):
            assert symptom == 'check localapp'
            assert json.loads(settings.DIAGNOSTIC_TARGET_CATALOG)['target_id'] == 'test-target'
            tools, error = await planner.load_agent_tools()
            if disabled:
                assert tools == [] and args.local_runbooks is None and args.knowledge_mcp_url is None
                yield {'type': 'complete', 'response': '未定位根因：knowledge disabled'}
                return
            assert error is None and tools[0].name == 'search_knowledge_base'
            await tools[0].ainvoke({'query': 'localapp'})
            yield {'type': 'complete', 'response': '未定位根因：offline orchestration only'}
        async def close(self):
            closed.append(True)
    monkeypatch.setattr(graph, 'AIOpsService', Service)
    args = SimpleNamespace(previous_cost=None, local_runbooks=None, symptom_file=tmp_path / 'symptom',
        knowledge_mcp_url='http://127.0.0.1:9200/mcp', knowledge_disabled=disabled)
    cfg = ProbeConfig('test-target', 'ws://127.0.0.1:18767/probe/ws', tmp_path / 'token')
    await run_model(args, cfg, tmp_path, [knowledge], 'check localapp')
    summary = json.loads((tmp_path / 'summary.json').read_text(encoding='utf-8'))
    assert summary['knowledge_mcp_calls'] == (0 if disabled else 1)
    assert summary['knowledge_mode'] == ('disabled' if disabled else 'local_bm25_mcp')
    assert summary['model_requests'] == 0 and summary['validated_live_returns'] == 0
    assert not summary['fault_location_evaluated'] and not summary['knowledge_base_evaluated']
    assert closed == [True] and read_cost_ledger(tmp_path / 'cost.json')['requests'] == []
