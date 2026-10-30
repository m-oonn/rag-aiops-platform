import pytest

from scripts.evaluate_windows_probe import classify_report, parse_args, mcp_url
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from scripts.evaluate_windows_probe import preflight
from scripts.evaluate_windows_probe import read_cost_ledger
from scripts.evaluate_windows_probe import local_runbook_retrieval, target_catalog
import json
from pathlib import Path


@pytest.mark.parametrize('options', [
    ['--knowledge-kb-id', '0'], ['--knowledge-query', ' '],
    ['--knowledge-kb-id', '15'],
    ['--knowledge-mcp-url', 'http://127.0.0.1:8105/mcp', '--knowledge-source', ' '],
    ['--knowledge-mcp-url', 'http://127.0.0.1:8105/mcp', '--knowledge-kb-id', '15', '--run-model'],
    ['--knowledge-mcp-url', 'http://127.0.0.1:8105/mcp', '--knowledge-kb-id', '15', '--knowledge-disabled']])
def test_knowledge_preflight_cli_rejects_invalid_or_ignored_scope(options):
    with pytest.raises(SystemExit):
        parse_args(options)


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', ['none', 'empty', 'wrong_library', 'missing_library', 'missing_page', 'empty_page', 'wrong_source', 'exception'])
async def test_knowledge_preflight_checks_actual_provenance_and_preserves_failures(tmp_path, mutation):
    from scripts.evaluate_windows_probe import knowledge_preflight
    payload = {'data_source': 'knowledge_base', 'kb_id': 15, 'results': [
        {'source': 'manual.pdf', 'page': 2, 'chunk_id': 'c1', 'content': 'guidance'}]}
    if mutation == 'empty': payload['results'] = []
    if mutation == 'wrong_library': payload['kb_id'] = 14
    if mutation == 'missing_library': payload.pop('kb_id')
    if mutation == 'missing_page': payload['results'][0].pop('page')
    if mutation == 'empty_page': payload['results'][0]['page'] = ''
    if mutation == 'wrong_source': payload['results'][0]['source'] = 'other.pdf'
    tool = SimpleNamespace(ainvoke=AsyncMock(return_value=payload,
        side_effect=RuntimeError('unavailable') if mutation == 'exception' else None))
    if mutation == 'none':
        result = await knowledge_preflight(tool, tmp_path, kb_id=15, query='应用异常', expected_source='manual.pdf')
        assert result['passed'] and result['fragments'][0]['kb_id'] == 15
    else:
        with pytest.raises((ValueError, RuntimeError)):
            await knowledge_preflight(tool, tmp_path, kb_id=15, query='应用异常', expected_source='manual.pdf')
    saved = json.loads((tmp_path / 'knowledge-preflight.json').read_text(encoding='utf-8'))
    assert saved['passed'] is (mutation == 'none')
    assert saved['autonomously_selected'] is False
    tool.ainvoke.assert_awaited_once_with({'query': '应用异常', 'kb_id': 15, 'top_k': 3})
    assert not (tmp_path / 'cost.json').exists()


@pytest.mark.asyncio
async def test_legacy_knowledge_preflight_keeps_default_query_and_library(tmp_path):
    from scripts.evaluate_windows_probe import knowledge_preflight
    tool = SimpleNamespace(ainvoke=AsyncMock(return_value={
        'data_source': 'knowledge_base', 'kb_id': 14, 'results': [
            {'source': 'localapp-availability.md', 'chunk_id': 'localapp-guide', 'page': 1, 'content': 'guide'}]}))
    result = await knowledge_preflight(tool, tmp_path)
    assert result['passed']
    tool.ainvoke.assert_awaited_once_with({'query': 'localapp availability', 'kb_id': 14, 'top_k': 3})


@pytest.mark.asyncio
async def test_knowledge_scope_reaches_free_entry(tmp_path, monkeypatch):
    from scripts import evaluate_windows_probe as evaluation, windows_probe
    from src.probe.windows import config
    options = ['--knowledge-mcp-url', 'http://127.0.0.1:8105/mcp', '--knowledge-kb-id', '15',
        '--knowledge-query', '应用内部异常', '--knowledge-source', '02-application-errors.pdf',
        '--output-dir', str(tmp_path / 'output')]
    args = parse_args(options)
    monkeypatch.setattr(evaluation, 'parse_args', lambda: args)
    monkeypatch.setattr(windows_probe, '_set_acl', lambda path: None)
    cfg = SimpleNamespace(tls_ca_file=None)
    monkeypatch.setattr(config, 'load_config', lambda path: cfg)
    for name in ['DATABASE_URL', 'AIOPS_CHECKPOINT_DB_PATH', 'ENABLE_EXPERIENCE_CONTEXT']:
        monkeypatch.setenv(name, 'test-placeholder')
    free, paid = AsyncMock(), AsyncMock(side_effect=AssertionError('paid path forbidden'))
    monkeypatch.setattr(evaluation, 'preflight', free)
    monkeypatch.setattr(evaluation, 'run_model', paid)
    await evaluation.main()
    free.assert_awaited_once_with(cfg, (tmp_path / 'output').resolve(), args.knowledge_mcp_url,
        kb_id=15, query='应用内部异常', expected_source='02-application-errors.pdf')
    paid.assert_not_awaited()


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


@pytest.mark.asyncio
@pytest.mark.parametrize('reserved, status, usage', [
    (0.4, None, None), (0.4, 500, {'prompt_tokens': 3}),
    (0.4, 200, {}), (0.4, 200, ['not a usage object']),
    (0.4, 200, {'prompt_tokens': 3}),
    (0.4, 200, {'prompt_tokens': 3, 'completion_tokens': True}),
    (5, 200, {'prompt_tokens': 3}),
])
async def test_direct_model_resume_rejects_uncertain_or_exhausted_cost_before_setup(
        tmp_path, monkeypatch, reserved, status, usage):
    import httpx
    from scripts.evaluate_windows_probe import run_model
    prior = tmp_path / 'prior.json'
    value = {'limit_cny': 5, 'reserved_cny': reserved, 'requests': [
        {'number': 1, 'reserved_cny': reserved, 'http_status': status, 'usage': usage}]}
    prior.write_text(json.dumps(value))
    transport = Mock(side_effect=AssertionError('must reject before network setup'))
    monkeypatch.setattr(httpx, 'AsyncHTTPTransport', transport)
    args = SimpleNamespace(previous_cost=prior)
    with pytest.raises(RuntimeError, match='exhausted or uncertain cost'):
        await run_model(args, None, tmp_path, [])
    transport.assert_not_called()
    assert json.loads(prior.read_text()) == value
    assert not (tmp_path / 'cost.json').exists()


def test_settled_cost_can_be_loaded_for_resume_without_changing_history(tmp_path):
    value = {'limit_cny': 5, 'reserved_cny': 0.4, 'requests': [
        {'number': 1, 'reserved_cny': 0.4, 'http_status': 200, 'usage': {'prompt_tokens': 3, 'completion_tokens': 1}}]}
    prior = tmp_path / 'prior.json'
    prior.write_text(json.dumps(value))
    assert read_cost_ledger(prior, for_resume=True) == value


def test_explicit_budget_increase_preserves_prior_requests_and_new_ceiling(tmp_path):
    from scripts.evaluate_autonomous_investigation import PaidRequestBudget, EvaluationBudgetExceeded
    prior = tmp_path / 'prior.json'
    value = {'limit_cny': 5, 'reserved_cny': 5, 'requests': [
        {'number': 1, 'reserved_cny': 5, 'http_status': 200, 'usage': {'prompt_tokens': 3, 'completion_tokens': 1}}]}
    prior.write_text(json.dumps(value))
    with pytest.raises(RuntimeError):
        read_cost_ledger(prior, for_resume=True)
    saved = read_cost_ledger(prior, for_resume=True, limit_cny=5.11)
    budget = PaidRequestBudget(tmp_path, max_output_tokens=4096, limit_cny=5.11)
    budget.reserved, budget.ledger = saved['reserved_cny'], saved['requests']
    while True:
        try:
            budget.reserve({'model': 'deepseek-flash', 'max_tokens': 4096})
        except EvaluationBudgetExceeded:
            break
    result = read_cost_ledger(tmp_path / 'cost.json')
    assert 5 < result['reserved_cny'] <= 5.11 and result['limit_cny'] == 5.11
    assert result['requests'][0] == value['requests'][0]
    assert result['requests'][1]['number'] == 2
    assert json.loads(prior.read_text()) == value


@pytest.mark.parametrize('limit', ['nan', 'inf', '0', '-1'])
def test_cli_rejects_invalid_budget_limits(limit):
    with pytest.raises(SystemExit):
        parse_args(['--budget-limit-cny', limit])


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


@pytest.mark.parametrize(('reason_code', 'options', 'ledger', 'reserved'), [
    ('unpriced_model', {}, [], 0),
    ('max_requests', {'allow_unpriced_models': True, 'max_requests': 1},
        [{'number': 1, 'reserved_cny': 0, 'model': 'glm-5.3-flash'}], 0),
    ('per_run_cost_limit', {'run_limit_cny': 0.000001}, [], 0),
    ('cumulative_cost_limit', {'limit_cny': 0.000001}, [], 0),
])
def test_budget_rejection_reasons_are_distinct_and_not_counted_as_sent(
        tmp_path, reason_code, options, ledger, reserved):
    from scripts.evaluate_autonomous_investigation import PaidRequestBudget, EvaluationBudgetExceeded
    budget = PaidRequestBudget(tmp_path, **options)
    budget.ledger = list(ledger)
    budget.reserved = reserved
    before_requests = list(budget.ledger)
    body = {'model': 'glm-5.3-flash' if reason_code in {'unpriced_model', 'max_requests'} else 'deepseek-flash',
        'max_tokens': 64}

    with pytest.raises(EvaluationBudgetExceeded) as caught:
        budget.reserve(body)

    assert caught.value.reason_code == reason_code
    assert budget.ledger == before_requests
    saved = json.loads((tmp_path / 'cost.json').read_text(encoding='utf-8'))
    assert saved['requests'] == before_requests
    assert saved['blocked_requests'][-1] == {
        'request_number': len(before_requests) + 1, 'model': body['model'],
        'reason_code': reason_code, 'reason': str(caught.value), 'sent': False}


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
    assert parse_args(['--mechanism-group', 'G00']).run_model is False
    with pytest.raises(SystemExit):
        parse_args(['--mechanism-group', 'G99'])
    with pytest.raises(SystemExit):
        parse_args(['--mechanism-group', 'G00', '--knowledge-disabled'])


@pytest.mark.asyncio
@pytest.mark.parametrize('group', ['G00', 'G10', 'G01', 'G11'])
async def test_group_preflight_cannot_enter_paid_path(tmp_path, monkeypatch, group):
    from scripts import evaluate_windows_probe as evaluation
    from scripts import windows_probe
    from src.probe.windows import config
    from src.settings import settings
    output = tmp_path / 'output'
    args = evaluation.parse_args(['--mechanism-group', group, '--output-dir', str(output)])
    monkeypatch.setattr(evaluation, 'parse_args', lambda: args)
    monkeypatch.setattr(windows_probe, '_set_acl', lambda path: None)
    monkeypatch.setattr(config, 'load_config', lambda path: SimpleNamespace(tls_ca_file=None))
    for name in ['INVESTIGATION_HYPOTHESIS_PROTECTION', 'INVESTIGATION_CONTRADICTION_TRIGGER']:
        monkeypatch.setattr(settings, name, getattr(settings, name))
    for name in ['DATABASE_URL', 'AIOPS_CHECKPOINT_DB_PATH', 'ENABLE_EXPERIENCE_CONTEXT']:
        monkeypatch.setenv(name, 'test-placeholder')
    free = AsyncMock()
    paid = AsyncMock(side_effect=AssertionError('paid path reached'))
    monkeypatch.setattr(evaluation, 'preflight', free)
    monkeypatch.setattr(evaluation, 'run_model', paid)
    await evaluation.main()
    saved = json.loads((output / 'mechanism-preflight.json').read_text(encoding='utf-8'))
    assert saved['requested_group'] == group and saved['runtime_verified'] is False
    assert saved['model_calls'] == 0 and not (output / 'cost.json').exists()
    assert (saved['requested_config']['hypothesis_protection'], saved['requested_config']['contradiction_trigger']) == evaluation.MECHANISM_GROUPS[group]
    free.assert_awaited_once()
    paid.assert_not_awaited()


@pytest.mark.parametrize('mutation', ['none', 'initial', 'diagnosis', 'tracking', 'trace', 'missing', 'disabled_event'])
def test_mechanism_audit_uses_actual_state_and_fails_closed(mutation):
    from scripts.evaluate_windows_probe import audit_mechanisms
    import copy
    config = {'hypothesis_protection': False, 'contradiction_trigger': False, 'protection_steps': 2}
    tracking = {'config': dict(config), 'events': [], 'candidates': []}
    values = {'investigation_config': dict(config), 'investigation_memory': {'hypothesis_tracking': tracking},
        'diagnosis': {'mechanism_config': dict(config), 'mechanisms': copy.deepcopy(tracking)}}
    snapshots = [{'tracking': copy.deepcopy(tracking)}]
    if mutation == 'initial': values['investigation_config']['hypothesis_protection'] = True
    if mutation == 'diagnosis': values['diagnosis']['mechanism_config']['contradiction_trigger'] = True
    if mutation == 'tracking': tracking['config']['hypothesis_protection'] = True
    if mutation == 'trace': snapshots[0]['tracking']['config']['hypothesis_protection'] = True
    if mutation == 'missing': snapshots = []
    if mutation == 'disabled_event': tracking['events'].append({'kind': 'hypothesis_protected'})
    result = audit_mechanisms(config, values, snapshots)
    assert result['passed'] is (mutation == 'none')
    assert not result['mechanism_effectiveness_verified']


@pytest.mark.parametrize('mutation', ['none', 'legacy', 'config', 'event', 'condition', 'candidate', 'proposal'])
def test_mechanism_audit_compares_public_projection_without_accepting_tampering(mutation):
    import copy
    from scripts.evaluate_windows_probe import audit_mechanisms
    from src.agent.aiops.strategies import investigation as inv

    config = {'hypothesis_protection': False, 'contradiction_trigger': False, 'protection_steps': 2}
    tracking = {'config': dict(config), 'events': [], 'candidates': [{
        'id': 'h-causal', 'explanation': '根因已确认是进程崩溃', 'status': 'active',
        'condition': {'operation': 'dependency_probe', 'object_name': 'db', 'field': 'tcp', 'expected': 'failed'},
        'proposal': {'explanation': '根因已确认是进程崩溃', 'status': 'unresolved',
                     'verification': 'causal_claim_unverified'}}]}
    public = copy.deepcopy(tracking) if mutation == 'legacy' else inv._public_tracking(tracking)
    if mutation == 'config': public['config']['protection_steps'] = 99
    if mutation == 'event': public['events'].append({'kind': 'invented'})
    if mutation == 'condition': public['candidates'][0]['condition']['expected'] = 'ok'
    if mutation == 'candidate': public['candidates'][0]['id'] = 'h-other'
    if mutation == 'proposal': public['candidates'][0]['proposal']['verification'] = 'predicate_verified'
    values = {'investigation_config': dict(config), 'investigation_memory': {'hypothesis_tracking': tracking},
              'diagnosis': {'mechanism_config': dict(config), 'mechanisms': public}}
    before = copy.deepcopy(values)

    result = audit_mechanisms(config, values, [{'tracking': copy.deepcopy(tracking)}])

    assert result['checks']['diagnosis_tracking'] is (mutation in {'none', 'legacy'})
    assert result['passed'] is (mutation in {'none', 'legacy'})
    assert values == before
    assert not result['mechanism_effectiveness_verified']


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
@pytest.mark.parametrize('full_catalog', [False, True])
async def test_evaluation_loads_both_tool_sets_and_closes_clients(tmp_path, monkeypatch, full_catalog):
    import src.agent.mcp_client as client
    from src.probe.evidence import PROBE_TOOL_OPERATIONS
    from scripts.evaluate_windows_probe import load_evaluation_tools
    from langchain_core.tools import StructuredTool
    token = tmp_path / 'token'
    token.write_text('test-token')
    cfg = SimpleNamespace(token_file=token, gateway_url='ws://127.0.0.1:2040/probe/ws')
    probe = [SimpleNamespace(name=name) for name in [*PROBE_TOOL_OPERATIONS, 'probe_list_evidence']]
    async def search(query: str, kb_id: int):
        """Isolated search endpoint with the real input contract."""
        return kb_id
    knowledge = StructuredTool.from_function(coroutine=search, name='search_knowledge_base')
    catalog = [knowledge, *([SimpleNamespace(name='list_knowledge_bases'),
        SimpleNamespace(name='get_document_info')] if full_catalog else [])]
    load = AsyncMock(side_effect=[(probe, None), (catalog, None)])
    close = Mock()
    monkeypatch.setattr(client, 'load_tools_for_config', load)
    monkeypatch.setattr(client, 'close_client_for_config', close)
    async with load_evaluation_tools(cfg, 'http://127.0.0.1:9200/mcp') as tools:
        assert tools[:-1] == probe
        assert tools[-1].name == knowledge.name
        assert tools[-1].args['kb_id']['enum'] == [14]
        with pytest.raises(PermissionError):
            await tools[-1].ainvoke({'query': 'x', 'kb_id': 1})
        assert await tools[-1].ainvoke({'query': 'x'}) == 14
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
@pytest.mark.parametrize('group', [None, 'G00', 'G10', 'G01', 'G11'])
@pytest.mark.parametrize('audit_passed', [False, True, 'not_assessed'])
async def test_model_mode_wires_knowledge_without_sending_paid_requests(tmp_path, monkeypatch, disabled, group, audit_passed):
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
            'PROBE_EVIDENCE_DIR', 'TERMCP_ENABLED', 'ENABLE_HITL', 'ENABLE_LLM_RETRY',
            'INVESTIGATION_HYPOTHESIS_PROTECTION', 'INVESTIGATION_CONTRADICTION_TRIGGER']:
        monkeypatch.setattr(settings, name, getattr(settings, name))
    async def reject_network(request):
        pytest.fail('offline orchestration must not send model requests')
    monkeypatch.setattr(httpx, 'AsyncHTTPTransport', lambda: httpx.MockTransport(reject_network))
    async def search(query: str, kb_id: int = 14):
        return {'data_source': 'knowledge_base', 'results': [{'chunk_id': 'guide', 'content': query}]}
    knowledge = StructuredTool.from_function(coroutine=search, name='search_knowledge_base', description='Local guide')
    closed = []
    from scripts import evaluate_windows_probe as evaluation
    audit = AsyncMock(return_value={'passed': audit_passed is not False,
        'behavior': {'status': 'not_assessed' if audit_passed == 'not_assessed' else 'passed'}})
    monkeypatch.setattr(evaluation, 'save_mechanism_audit', audit)
    class Service:
        async def execute(self, symptom, **kwargs):
            assert symptom == 'check localapp'
            if group:
                assert (settings.INVESTIGATION_HYPOTHESIS_PROTECTION,
                    settings.INVESTIGATION_CONTRADICTION_TRIGGER) == evaluation.MECHANISM_GROUPS[group]
            assert json.loads(settings.DIAGNOSTIC_TARGET_CATALOG)['target_id'] == 'test-target'
            tools, error = await planner.load_agent_tools()
            if disabled:
                assert tools == [] and args.local_runbooks is None and args.knowledge_mcp_url is None
                yield {'type': 'complete', 'response': '未定位根因：knowledge disabled'}
                return
            assert error is None and tools[0].name == 'search_knowledge_base'
            assert tools[0].args['kb_id']['enum'] == [14]
            await tools[0].ainvoke({'query': 'localapp'})
            yield {'type': 'complete', 'response': '未定位根因：offline orchestration only'}
        async def close(self):
            closed.append(True)
    monkeypatch.setattr(graph, 'AIOpsService', Service)
    args = SimpleNamespace(previous_cost=None, budget_limit_cny=10, local_runbooks=None, symptom_file=tmp_path / 'symptom',
        knowledge_mcp_url='http://127.0.0.1:9200/mcp', knowledge_disabled=disabled, mechanism_group=group)
    if not disabled:
        from scripts.knowledge_conditions import knowledge_conditions
        corpus = tmp_path / 'runbooks'
        corpus.mkdir()
        (corpus / 'localapp-availability.md').write_text('localapp guide', encoding='utf-8')
        args.local_runbooks = corpus
        args.knowledge_manifest = tmp_path / 'knowledge-manifest.json'
        args.knowledge_manifest.write_text(json.dumps(knowledge_conditions(corpus)), encoding='utf-8')
    cfg = ProbeConfig('test-target', 'ws://127.0.0.1:18767/probe/ws', tmp_path / 'token')
    if group and disabled:
        with pytest.raises(ValueError, match='knowledge conditions'):
            await run_model(args, cfg, tmp_path, [knowledge], 'check localapp')
        assert not (tmp_path / 'cost.json').exists()
        return
    if group and audit_passed is not True:
        with pytest.raises(RuntimeError, match='audit failed'):
            await run_model(args, cfg, tmp_path, [knowledge], 'check localapp')
    else:
        await run_model(args, cfg, tmp_path, [knowledge], 'check localapp')
    summary = json.loads((tmp_path / 'summary.json').read_text(encoding='utf-8'))
    assert summary['knowledge_mcp_calls'] == (0 if disabled else 1)
    assert summary['knowledge_mode'] == ('disabled' if disabled else 'local_bm25_mcp')
    assert summary['model_requests'] == 0 and summary['validated_live_returns'] == 0
    assert summary['limit_cny'] == read_cost_ledger(tmp_path / 'cost.json')['limit_cny'] == 10
    assert not summary['fault_location_evaluated'] and not summary['knowledge_base_evaluated']
    assert closed == [True] and read_cost_ledger(tmp_path / 'cost.json')['requests'] == []
    assert summary['mechanism_group'] == group
    assert summary['mechanism_audit']['passed'] is (audit_passed is not False)
    if not disabled:
        assert summary['knowledge_conditions']['passed'] and summary['knowledge_conditions']['phase'] == 'after'
        trace = json.loads((tmp_path / 'tool_trace.json').read_text(encoding='utf-8'))
        assert trace[0]['arguments'] == {'query': 'localapp', 'kb_id': 14}
    record = json.loads((tmp_path / 'evaluation-record.json').read_text(encoding='utf-8'))
    assert record['config']['knowledge_kb_ids'] == ([] if disabled else [14])
    audit.assert_awaited_once()
