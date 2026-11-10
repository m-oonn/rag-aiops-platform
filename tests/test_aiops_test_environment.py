import json
from contextlib import ExitStack
from types import SimpleNamespace

import httpx
import pytest

from scripts.aiops_test_environment import (
    archive_round, check_environment_round, install_budget, product_environment, save,
)
from scripts.competing_hypothesis_fixture import CompetingFaultFixture
from scripts.verify_competing_hypothesis_scenario import write_scenario_files


@pytest.mark.integration
@pytest.mark.parametrize('fault,status', [('localapp_wrong_endpoint', 503),
    ('downstream_unreachable', 503), ('normal', 200)])
def test_real_request_after_reset_has_current_matching_logs_and_preserves_previous_round(tmp_path, fault, status):
    with CompetingFaultFixture(fault, tmp_path / 'business', stop_mode='request',
                              startup_configuration=True) as fixture:
        first = fixture.trigger_business_request()
        assert first['http_status'] == status
        assert set(first['log_times']) == {'edge', 'localapp'}
        requests = {}
        for service in ('edge', 'localapp'):
            requests[service] = next(json.loads(line) for line in
                (fixture.output / (service + '.log')).read_text().splitlines()
                if json.loads(line).get('request_id') == first['request_id'])
        edge_trace = requests['edge']['upstream_request']
        app_trace = requests['localapp']['upstream_request']
        assert edge_trace == {'timeout_seconds': 1.5, 'phase': 'completed',
            'connection_established': True, 'response_status': status}
        assert app_trace['timeout_seconds'] == 0.5
        if status == 503:
            assert app_trace['phase'] == 'connect'
            assert app_trace['connection_established'] is False
            assert 'response_status' not in app_trace
        else:
            assert app_trace['phase'] == 'completed'
            assert app_trace['connection_established'] is True
            assert app_trace['response_status'] == 200
        archive_round(tmp_path, fixture, {'round': 1, 'boundary': fixture.boundary})
        for service in ('edge', 'localapp'):
            assert first['request_id'] in (tmp_path / 'rounds/1' / (service + '.log')).read_text()
        fixture.reset('normal')
        second = fixture.trigger_business_request()
        assert second['request_id'] != first['request_id']
        assert second['http_status'] == 200
        assert all(value >= fixture.boundary for value in second['log_times'].values())
        assert first['request_id'] not in (fixture.output / 'edge.log').read_text()


def test_product_database_and_boundary_are_isolated_and_closed_environment_is_rejected(tmp_path):
    state = {'status': 'ready', 'round': 1, 'target_id': 'isolated', 'gateway_url': 'http://127.0.0.1:1/mcp'}
    save(tmp_path / 'environment.json', state)
    (tmp_path / 'token').write_text('test-only-token')
    env = product_environment(tmp_path)
    assert env['DATABASE_URL'] == 'sqlite:///' + (tmp_path / 'product/runs.sqlite').as_posix()
    assert env['AIOPS_CHECKPOINT_DB_PATH'] == str(tmp_path / 'product/checkpoints.sqlite')
    assert env['ENABLE_LLM_RETRY'] == env['TERMCP_ENABLED'] == 'false'
    assert check_environment_round(tmp_path, 1) == state
    state['round'] = 2
    save(tmp_path / 'environment.json', state)
    with pytest.raises(ValueError, match='changed round'):
        check_environment_round(tmp_path, 1)
    state['status'] = 'stopped'
    save(tmp_path / 'environment.json', state)
    with pytest.raises(ValueError, match='not ready'):
        product_environment(tmp_path)


@pytest.mark.parametrize('fault', ['localapp_wrong_endpoint', 'downstream_unreachable', 'normal'])
def test_shared_configuration_keeps_controller_answer_accurate(tmp_path, fault):
    fixture = CompetingFaultFixture(fault, tmp_path / 'business', startup_configuration=True)
    write_scenario_files(tmp_path, fixture, 8001, 'fixture-target', 'private-token', 'canary', 'endpoint')
    answer = json.loads((tmp_path / 'controller-only.json').read_text())
    assert answer['hidden_fault'] == fault
    expected = fixture.obsolete_port if fault == 'localapp_wrong_endpoint' else fixture.downstream_port
    assert answer['actual_loaded_port'] == expected
    from src.probe.windows.config import load_config
    config = load_config(tmp_path / 'config.toml')
    assert config.dependencies['localapp_upstream'].port == expected
    assert all('controller-only.json' not in path for service in config.services.values() for path in service.text_logs)


@pytest.mark.asyncio
async def test_product_model_transport_uses_reserved_body_blocks_unknown_and_binds_all_roles(tmp_path, monkeypatch):
    from src.settings import settings
    from scripts.evaluate_autonomous_investigation import EvaluationBudgetExceeded
    import src.agent.aiops_llm as models
    monkeypatch.setattr(settings, 'LLM_API_BASE', 'https://api.deepseek.com')
    monkeypatch.setattr(settings, 'LLM_FALLBACK_ENABLED', False)
    seen = []

    def respond(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': []})  # Missing usage must stop further sends.

    monkeypatch.setattr(httpx, 'AsyncHTTPTransport', lambda: httpx.MockTransport(respond))
    primary = SimpleNamespace(root_async_client=SimpleNamespace(), root_client=SimpleNamespace())
    fallback = SimpleNamespace(root_async_client=SimpleNamespace(), root_client=SimpleNamespace())
    monkeypatch.setattr(models, 'create_agent_llm', lambda **kwargs: SimpleNamespace(runnable=primary, fallbacks=[fallback]))
    previous = {'requests': [], 'reserved_cny': 0, 'limit_cny': 33.058792}
    ledger = tmp_path / 'previous.json'
    save(ledger, previous)
    args = SimpleNamespace(output=tmp_path, previous_cost=ledger, timeout_authorization=None)
    save(tmp_path / 'environment.json', {'status': 'ready', 'round': 1})
    with ExitStack() as stack:
        client = install_budget(args, stack)
        try:
            import importlib
            for name in ('planner', 'executor', 'strategies.investigation', 'strategies.default', 'reporting'):
                factory = importlib.import_module('src.agent.aiops.' + name).create_agent_llm
                factory()
                for leaf in (primary, fallback):
                    assert leaf.http_async_client is client and leaf.root_async_client._client is client
                    assert leaf.max_tokens == 4096 and leaf.max_retries == 0
            models.create_agent_llm()
            assert primary.http_async_client is client
            await client.post('https://api.deepseek.com/chat/completions', json={
                'model': 'deepseek-flash', 'max_completion_tokens': 9000, 'stream': True})
            assert seen == [{'model': 'deepseek-flash', 'max_tokens': 4096, 'stream': False}]
            with pytest.raises(EvaluationBudgetExceeded, match='unknown usage'):
                await client.post('https://api.deepseek.com/chat/completions', json={'model': 'deepseek-flash'})
            with pytest.raises(ValueError, match='endpoint outside'):
                await client.post('https://example.invalid/chat/completions', json={'model': 'deepseek-flash'})
            assert len(seen) == 1
            cost = json.loads((tmp_path / 'product-model/cost.json').read_text())
            assert len(cost['requests']) == 1 and cost['reserved_cny'] > 0
            assert cost['blocked_requests'][-1]['sent'] is False
            assert json.loads(ledger.read_text()) == previous
        finally:
            await client.aclose()
    with ExitStack() as stack:
        resumed = install_budget(args, stack)
        try:
            resumed_cost = json.loads((tmp_path / 'product-model/cost.json').read_text())
            assert len(resumed_cost['requests']) == 1
            assert resumed_cost['request_limits']['inherited_requests'] == 0
            with pytest.raises(EvaluationBudgetExceeded, match='unknown usage'):
                await resumed.post('https://api.deepseek.com/chat/completions', json={'model': 'deepseek-flash'})
        finally:
                await resumed.aclose()


@pytest.mark.asyncio
async def test_new_product_model_round_keeps_unknown_history_but_gets_fresh_five_cny_budget(tmp_path):
    previous = {
        'requests': [{'number': 1, 'model': 'deepseek-flash', 'reserved_cny': .1,
            'reservation_upper_cny': .1, 'pricing_verified': True, 'status': 'ReadTimeout',
            'error_type': 'ReadTimeout'}],
        'reserved_cny': .1, 'limit_cny': 5,
    }
    ledger = tmp_path / 'previous.json'
    save(ledger, previous)
    output = tmp_path / 'new-round'
    output.mkdir()
    save(output / 'environment.json', {'status': 'ready', 'round': 1})
    args = SimpleNamespace(output=output, previous_cost=ledger, timeout_authorization=None)
    with ExitStack() as stack:
        client = install_budget(args, stack)
        try:
            cost = json.loads((output / 'product-model/cost.json').read_text())
            assert cost['limit_cny'] == 5.1
            assert cost['reserved_cny'] == .1
            assert cost['requests'][0]['status'] == 'ReadTimeout'
        finally:
            await client.aclose()


@pytest.mark.asyncio
async def test_backend_restart_preserves_spend_and_original_unknown_baseline(tmp_path, monkeypatch):
    from scripts.evaluate_autonomous_investigation import EvaluationBudgetExceeded
    from src.settings import settings
    monkeypatch.setattr(settings, 'LLM_API_BASE', 'https://api.deepseek.com')
    monkeypatch.setattr(settings, 'LLM_FALLBACK_ENABLED', False)
    history = {'number': 1, 'reserved_cny': .1, 'status': 'ReadTimeout'}
    ledger = tmp_path / 'previous.json'
    save(ledger, {'requests': [history], 'reserved_cny': .1, 'limit_cny': .1})
    save(tmp_path / 'environment.json', {'status': 'ready', 'round': 1})
    args = SimpleNamespace(output=tmp_path, previous_cost=ledger, timeout_authorization=None)
    with ExitStack() as stack:
        client = install_budget(args, stack)
        await client.aclose()
    path = tmp_path / 'product-model/cost.json'
    cost = json.loads(path.read_text())
    cost['requests'].append({'number': 2, 'reserved_cny': 4.999, 'status': 'returned',
        'http_status': 200, 'usage': {'prompt_tokens': 1, 'completion_tokens': 1}})
    cost['reserved_cny'] = 5.099
    save(path, cost)
    with ExitStack() as stack:
        client = install_budget(args, stack)
        try:
            with pytest.raises(EvaluationBudgetExceeded) as error:
                await client.post('https://api.deepseek.com/chat/completions', json={'model': 'deepseek-flash'})
            assert error.value.reason_code == 'per_run_cost_limit'
            resumed = json.loads(path.read_text())
            assert resumed['request_limits']['inherited_requests'] == 1
            assert resumed['requests'][0] == history
            assert resumed['reserved_cny'] == pytest.approx(5.099)
        finally:
            await client.aclose()
    cost['requests'][0]['status'] = 'changed'
    save(path, cost)
    with ExitStack() as stack, pytest.raises(ValueError, match='original run baseline'):
        install_budget(args, stack)
