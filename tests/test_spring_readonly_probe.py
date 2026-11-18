"""Synthetic Actuator responses exercise the tool chain, never live acceptance."""
import base64
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.probe.windows import docker_readonly, spring_readonly
from src.probe.windows.collector import WindowsCollector
from src.probe.windows.config import load_config, ProbeConfigError
from src.agent.aiops import registered_causes
from src.probe.protocol import evidence


def config(tmp_path):
    path = tmp_path / 'probe.toml'
    source = tmp_path / 'portal.yml'
    source.write_text('spring: {}', encoding='utf-8')
    path.write_text(f'''target_id="test"
gateway_url="ws://127.0.0.1:18769/probe/ws"
[services.portal]
kind="docker"
docker_container="allowed-portal-1"
docker_spring=true
spring_management_port=9001
config_file={json.dumps(str(source))}
config_keys=["spring.datasource.url","spring.data.redis.host","spring.data.redis.port"]
[dependencies.cache]
host="redis"
port=6379
source_service="portal"
probe_kind="spring_cache"
[dependencies.db]
host="mysql"
port=3306
source_service="portal"
probe_kind="spring_database"
''', encoding='utf-8')
    return load_config(path)


def source_documents():
    now = datetime.now(timezone.utc)
    identity = {'id': 'a' * 64, 'pid': 12, 'running': True,
                'started_at': (now - timedelta(minutes=2)).isoformat()}
    props = {'contexts': {'application': {'beans': {
        'cache': {'prefix': 'spring.data.redis', 'properties': {
            'host': 'redis', 'port': 6380, 'password': 'private-password'}},
        'datasource': {'prefix': 'spring.datasource.druid', 'properties': {
            'url': 'jdbc:mysql://mysql:3307/mall?password=private-query',
            'username': 'private-user', 'password': 'private-password'}}}}}}
    exchanges = {'exchanges': [{'timestamp': (now-timedelta(seconds=2)).isoformat(),
        'request': {'method': 'POST', 'uri': 'http://portal/order/generate?token=private-query',
                    'headers': {'Authorization': ['Bearer private-token']}, 'body': 'private-body'},
        'response': {'status': 500, 'headers': {'Set-Cookie': ['private-cookie']}},
        'principal': {'name': 'private-user'}, 'session': {'id': 'private-session'}}]}
    return identity, props, exchanges


def install_docker(monkeypatch, *, mutation=''):
    identity, props, exchanges = source_documents()
    calls = []
    def run(*args, **kwargs):
        calls.append((args, kwargs))
        if args[0] == 'inspect':
            value = dict(identity)
            if mutation == 'restart' and len(calls) > 1:
                value['pid'] += 1
            return json.dumps(value).encode()
        assert args[:5] == ('exec', '-i', 'allowed-portal-1', 'jshell', '--execution')
        code = kwargs['input'].decode()
        if 'PROBE_HTTP' in code:
            assert '127.0.0.1:9001/actuator/' in code
            assert 'setRequestMethod("GET")' in code and 'setInstanceFollowRedirects(false)' in code
            value = props if '/configprops' in code else exchanges if '/httpexchanges' in code else {
                'status': 'DOWN', 'details': {'error': 'connection failed password=private-password'}}
            if mutation == 'ambiguous' and '/configprops' in code:
                value['contexts']['other'] = value['contexts']['application']
            if mutation == 'masked' and '/configprops' in code:
                value['contexts']['application']['beans']['cache']['properties']['host'] = '******'
            status = 404 if mutation == 'disabled' else 200
            return f'PROBE_HTTP={status};'.encode() + base64.b64encode(json.dumps(value).encode()) + b'\n'
        assert 'socket.connect(' in code
        return b'PROBE_TCP=ok\n' if ',6379)' in code or ',3306)' in code else b'PROBE_TCP=failed\n'
    monkeypatch.setattr(docker_readonly, 'docker', run)
    return calls, identity, props, exchanges


def test_collector_reads_bound_fields_and_existing_failed_request_without_replay(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    calls, _, _, _ = install_docker(monkeypatch)
    collector = WindowsCollector(cfg)
    value = collector.configuration('portal')
    dep = collector.dependency_probe('cache')
    requests = collector.text_logs('portal', 'docker://allowed-portal-1/http-exchanges')
    assert value['payload']['source'] == 'running_spring_configprops'
    assert value['payload']['runtime_effective_values_confirmed'] is False
    assert value['payload']['bound_configuration_confirmed'] is True
    assert value['payload']['values']['spring.datasource.url']['port'] == 3307
    assert dep['payload']['tcp'] == 'failed' and dep['payload']['registered_tcp'] == 'ok'
    assert dep['payload']['query'] == 'unknown'
    assert dep['payload']['health_query'] == 'failed'
    assert dep['payload']['health_endpoint_binding_confirmed'] is False
    event, = [json.loads(line) for line in requests['payload']['lines']]
    assert event['method'] == 'POST' and event['status'] == 500 and event['path'] == '/order/generate'
    assert 'private-' not in json.dumps([value, dep, requests])
    assert any('/httpexchanges' in row[1].get('input', b'').decode() for row in calls)
    assert 'http-exchanges' in collector.inventory()['payload']['configured_services']['portal']['text_logs'][1]


@pytest.mark.parametrize('mutation', ['disabled', 'ambiguous', 'masked', 'restart'])
def test_unverified_runtime_never_falls_back_to_mounted_file(tmp_path, monkeypatch, mutation):
    cfg = config(tmp_path)
    install_docker(monkeypatch, mutation=mutation)
    with pytest.raises(ProbeConfigError):
        WindowsCollector(cfg).configuration('portal')


@pytest.mark.parametrize('mutation', ['old', 'future', 'previous_start', 'malformed'])
def test_recorded_request_time_is_not_refreshed_by_collecting_it_again(tmp_path, monkeypatch, mutation):
    cfg = config(tmp_path)
    _, identity, _, exchanges = install_docker(monkeypatch)
    if mutation == 'previous_start':
        exchanges['exchanges'][0]['timestamp'] = (datetime.fromisoformat(identity['started_at'])-timedelta(seconds=1)).isoformat()
    else:
        exchanges['exchanges'][0]['timestamp'] = ('invalid' if mutation == 'malformed' else
            (datetime.now(timezone.utc)+timedelta(seconds=30 if mutation == 'future' else -190)).isoformat())
    value = WindowsCollector(cfg).text_logs('portal', 'docker://allowed-portal-1/http-exchanges')
    assert not value['payload']['lines']


@pytest.mark.parametrize('boundary', ['absolute', 'offset', 'relative'])
def test_recorded_requests_respect_the_configured_scenario_boundary(tmp_path, monkeypatch, boundary):
    from dataclasses import replace
    cfg = config(tmp_path)
    _, identity, _, exchanges = install_docker(monkeypatch)
    now = datetime(2026, 11, 16, 6, 0, tzinfo=timezone.utc)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(spring_readonly, 'datetime', Clock)
    identity['started_at'] = (now-timedelta(minutes=10)).isoformat()
    start = now-timedelta(seconds=30)
    since = {'absolute': start.isoformat(), 'offset': start.astimezone(
        timezone(timedelta(hours=8))).isoformat(), 'relative': '30s'}[boundary]
    cfg.services['portal'] = replace(cfg.service('portal'), log_since=since)
    template = exchanges['exchanges'][0]
    exchanges['exchanges'] = [dict(template, timestamp=(start+timedelta(seconds=seconds)).isoformat())
                              for seconds in (-1, 0, 1)]

    result = WindowsCollector(cfg).text_logs('portal', 'docker://allowed-portal-1/http-exchanges')

    assert [json.loads(row)['at'] for row in result['payload']['lines']] == [
        start.isoformat(), (start+timedelta(seconds=1)).isoformat()]
    assert result['payload']['since'] == since
    assert result['payload']['window_start'] == start.isoformat()


@pytest.mark.parametrize('since', ['2026-99-99T00:00:00Z', '2026-11-16T00:00:00.000'])
def test_recorded_requests_reject_invalid_or_timezone_free_boundaries(tmp_path, monkeypatch, since):
    from dataclasses import replace
    cfg = config(tmp_path)
    install_docker(monkeypatch)
    cfg.services['portal'] = replace(cfg.service('portal'), log_since=since)
    with pytest.raises(ProbeConfigError, match='time boundary'):
        WindowsCollector(cfg).text_logs('portal', 'docker://allowed-portal-1/http-exchanges')


@pytest.mark.parametrize('mutation', ['', 'snapshot', 'missing_business', 'healthy_business',
    'other_target', 'other_start', 'binding', 'loaded_endpoint', 'reference_failed', 'truncated'])
def test_spring_cooccurrence_never_confirms_a_configuration_cause(tmp_path, monkeypatch, mutation):
    cfg = config(tmp_path)
    install_docker(monkeypatch)
    collector = WindowsCollector(cfg)
    rows = {'config': collector.configuration('portal'), 'dep': collector.dependency_probe('cache'),
            'requests': collector.text_logs('portal', 'docker://allowed-portal-1/http-exchanges')}
    if mutation == 'snapshot': rows['config']['payload']['source'] = 'mounted_spring_config_snapshot'
    if mutation == 'missing_business': del rows['requests']
    if mutation == 'healthy_business':
        event = json.loads(rows['requests']['payload']['lines'][0]); event['status'] = 200
        rows['requests']['payload']['lines'] = [json.dumps(event)]
    if mutation == 'other_target': rows['requests']['target_id'] = 'outside'
    if mutation == 'other_start': rows['requests']['payload']['runtime_identity']['pid'] += 1
    if mutation == 'binding': rows['dep']['payload']['binding_hash'] = 'other'
    if mutation == 'loaded_endpoint': rows['dep']['payload']['port'] = 6390
    if mutation == 'reference_failed': rows['dep']['payload']['registered_tcp'] = 'failed'
    if mutation == 'truncated': rows['requests']['truncated'] = True
    records = {key: {'payload': json.dumps(raw)} for key, raw in rows.items()}
    scope = {'status': 'resolved', 'allowed_services': ['portal', 'redis'],
             'dependency_services': {'cache': 'redis'}}
    chains = registered_causes.configuration_chains(records, scope)
    # A bound Bean, health failure and arbitrary POST500 do not prove causality.
    assert chains == []


def test_recorded_post_failure_cannot_supply_a_missing_dependency_link(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    _, _, props, _ = install_docker(monkeypatch)
    props['contexts']['application']['beans']['cache']['properties']['port'] = 6379
    monkeypatch.setattr(spring_readonly, '_tcp', lambda *args: 'failed')
    collector = WindowsCollector(cfg)
    stopped = evidence(target_id='test', operation='services', payload={
        'service': 'redis', 'kind': 'docker', 'state': 'stopped',
        'network_aliases': ['redis'], 'exposed_tcp_ports': [6379],
        'finished_at': (datetime.now(timezone.utc)-timedelta(seconds=10)).isoformat()})
    rows = [stopped, collector.dependency_probe('cache'),
            collector.text_logs('portal', 'docker://allowed-portal-1/http-exchanges')]
    records = {str(i): {'payload': json.dumps(raw)} for i, raw in enumerate(rows)}
    scope = {'status': 'resolved', 'allowed_services': ['portal', 'redis'],
             'dependency_services': {'cache': 'redis'}}
    chains = registered_causes.stopped_service_chains(records, scope)
    # An unrelated recorded request cannot supply the missing dependency link.
    assert chains == []
    del records['2']
    assert registered_causes.stopped_service_chains(records, scope) == []


@pytest.mark.parametrize('port', [True, 0, -1, 65536, '9001'])
def test_management_registration_rejects_invalid_ports(tmp_path, port):
    config(tmp_path)
    path = tmp_path / 'probe.toml'
    path.write_text(path.read_text(encoding='utf-8').replace(
        'spring_management_port=9001', 'spring_management_port=' + json.dumps(port)), encoding='utf-8')
    with pytest.raises(ProbeConfigError):
        load_config(path)


def test_invalid_bound_endpoint_fails_with_a_safe_error(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    _, _, props, _ = install_docker(monkeypatch)
    props['contexts']['application']['beans']['datasource']['properties']['url'] = (
        'jdbc:mysql://private-user:private-password@mysql:invalid/mall')
    with pytest.raises(ProbeConfigError, match='public runtime field is invalid') as caught:
        WindowsCollector(cfg).configuration('portal')
    assert 'private-' not in str(caught.value)


def test_health_result_is_separate_from_endpoint_query_and_survives_context(tmp_path, monkeypatch):
    from src.agent.aiops.strategies import investigation as inv
    from src.agent.aiops.observations import dependency_healthy
    from src.settings import settings
    monkeypatch.setattr(settings, 'PROBE_TARGET_ID', 'test')
    cfg = config(tmp_path)
    install_docker(monkeypatch)
    collector = WindowsCollector(cfg)
    rows = [collector.configuration('portal'), collector.dependency_probe('db'),
            collector.text_logs('portal', 'docker://allowed-portal-1/http-exchanges')]
    body = rows[1]['payload']
    assert body['health_query'] == 'failed' and body['query'] == 'unknown'
    assert not dependency_healthy(body)
    current = {'raw_evidence': [('constructed tool result', json.dumps(row)) for row in rows],
        'target_resolution': {'status': 'resolved', 'target_id': 'test',
            'allowed_services': ['portal', 'redis'], 'allowed_dependencies': ['db'],
            'dependency_services': {'db': 'redis'}}}
    # Unrelated observations must not push the source limitations out of context.
    current['raw_evidence'] += [('resource', json.dumps(evidence(target_id='test',
        operation='resources', payload={'sample': i}))) for i in range(10)]
    records = inv.evidence_index(current)
    context = inv.investigation_context(current, records)
    assert context['e1.1']['observation_contract']['runtime_effective_values_confirmed'] is False
    assert context['e2.1']['observation_contract']['health_endpoint_binding_confirmed'] is False
    assert context['e2.1']['observation_contract']['health_query'] == 'failed'
    assert context['e3.1']['observation_contract']['source'] == 'spring_http_exchanges'
    assert any('尚未证明' in note for note in inv.log_observation_notes(records, current))
    assert 'private-' not in json.dumps(context)


@pytest.mark.asyncio
async def test_recorded_post_observation_passes_the_real_executor_without_a_model(tmp_path, monkeypatch):
    import importlib
    from unittest.mock import AsyncMock, Mock
    from langchain_core.tools import StructuredTool
    from src.settings import settings
    from src.agent.aiops.strategies import investigation as inv
    monkeypatch.setattr(settings, 'PROBE_TARGET_ID', 'test')
    ex = importlib.import_module('src.agent.aiops.executor')
    cfg = config(tmp_path)
    calls, _, _, _ = install_docker(monkeypatch)
    collector = WindowsCollector(cfg)
    async def read(service: str, path: str):
        return collector.text_logs(service, path)
    tool = StructuredTool.from_function(coroutine=read, name='probe_text_log', description='read existing records')
    monkeypatch.setattr(ex, '_get_tools_for_state', AsyncMock(return_value=([tool], None)))
    model = Mock(side_effect=AssertionError('no model in offline transport regression'))
    monkeypatch.setattr(ex, 'create_agent_llm', model)
    args = {'service': 'portal', 'path': 'docker://allowed-portal-1/http-exchanges'}
    current = {'autonomous_investigation': True, 'investigation_tools': [{'name': tool.name}],
        'past_steps': [], 'raw_evidence': [('inventory', json.dumps(collector.inventory()))],
        'investigation_memory': {'next_check': 'read recorded business request',
            'next_tools': [tool.name], 'next_arguments': {tool.name: args}},
        'target_resolution': {'status': 'resolved', 'target_id': 'test',
            'allowed_services': ['portal'], 'allowed_dependencies': []}}
    _, raw = await ex._run_step('read recorded business request', current)
    current['raw_evidence'].append(('read recorded business request', raw))
    records = inv.evidence_index(current)
    found = [json.loads(r['payload'])['payload'] for r in records.values()
        if r['provenance']['operation'] == 'text_logs']
    assert len(found) == 1
    assert json.loads(found[0]['lines'][0])['status'] == 500
    assert found[0]['runtime_identity']['pid'] == 12
    assert inv.execution_checks(current)[0]['status'] == 'success'
    model.assert_not_called()
    assert all('setRequestMethod("POST")' not in kw.get('input', b'').decode() for _, kw in calls)
