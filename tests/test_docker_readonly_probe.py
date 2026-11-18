import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.probe.windows.config import load_config, ProbeConfigError
from src.probe.windows.collector import WindowsCollector
from src.probe.windows import docker_readonly
from src.probe.protocol import redact


def config(tmp_path, extra=''):
    path = tmp_path / 'probe.toml'
    path.write_text('''target_id="test"
gateway_url="ws://127.0.0.1:18769/probe/ws"
[services.web]
kind="docker"
docker_container="allowed-web-1"
docker_django=true
''' + extra, encoding='utf-8')
    return load_config(path)


def test_docker_cannot_execute_arbitrary_container_or_command(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout=b'{"Running":false,"Status":"exited","Pid":0}', stderr=b'')
    monkeypatch.setattr(docker_readonly.subprocess, 'run', run)
    collector = WindowsCollector(cfg)
    assert collector.services('web')['payload']['state'] == 'stopped'
    assert calls[0][-1] == 'allowed-web-1'
    with pytest.raises(ProbeConfigError):
        collector.services('other')
    with pytest.raises(ProbeConfigError):
        collector.text_logs('web', 'docker://other/stdout')
    with pytest.raises(ProbeConfigError):
        collector.collect('exec', {'command': 'anything'})
    assert len(calls) == 1


def test_docker_config_rejects_option_injection_and_unallowed_source(tmp_path):
    with pytest.raises(ProbeConfigError):
        config(tmp_path, '\n[dependencies.db]\nhost="postgres"\nport=5432\nsource_service="unknown"')
    path = tmp_path / 'invalid.toml'
    path.write_text('target_id="test"\ngateway_url="ws://127.0.0.1:1"\n[services.web]\nkind="docker"\ndocker_container="--privileged"')
    with pytest.raises(ProbeConfigError):
        load_config(path)


def test_logs_are_bounded_redacted_and_provenanced(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    monkeypatch.setattr(docker_readonly.subprocess, 'run', lambda *a, **k:
        SimpleNamespace(returncode=0, stdout=b'2026-11-15T01:00:00Z normal\n',
            stderr=b'2026-11-15T01:00:01Z password=hidden for user "private"\n'))
    value = WindowsCollector(cfg).text_logs('web', 'docker://allowed-web-1/stdout', lines=1)
    assert value['truncated'] is True
    assert 'hidden' not in json.dumps(value) and 'private' not in json.dumps(value)
    assert value['payload']['path'] == 'docker://allowed-web-1/stdout'
    assert value['raw_hash'].startswith('sha256:')


def test_stopped_configuration_projects_public_endpoints_without_credentials(tmp_path, monkeypatch):
    calls = []
    def observe(*args, **kwargs):
        calls.append(args)
        if args[0] == 'exec':
            raise ProbeConfigError('Docker observation unavailable')
        return json.dumps(['POSTGRES_HOST=db', 'POSTGRES_PORT=5433', 'POSTGRES_PASSWORD=private',
            'REDIS_CART_CONFIG=redis://person:private@cache:6380/4', 'SECRET_KEY=private']).encode()
    monkeypatch.setattr(docker_readonly, 'docker', observe)
    value = docker_readonly.configuration(config(tmp_path).service('web'))
    assert value['source'] == 'container_start_environment'
    assert value['values']['POSTGRES_PORT'] == '5433'
    assert value['values']['REDIS_CART_CONFIG'] == {'host':'cache','port':6380,'database':'/4'}
    assert 'private' not in json.dumps(value) and 'person' not in json.dumps(value)
    assert calls[-1][-1] == 'allowed-web-1'


def test_authentication_error_username_is_redacted_at_shared_boundary():
    result = redact({'http': {'body_prefix': 'password authentication failed for user "private-account"'}})
    assert 'private-account' not in json.dumps(result)
    assert 'authentication failed' in result['http']['body_prefix']


def test_long_log_window_keeps_header_and_tail_with_explicit_gap(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    rows = ['2026-11-15T01:00:00Z ConnectionException password=private']
    rows += [f'2026-11-15T01:00:{i:02d}Z stack frame {i}' for i in range(1, 15)]
    rows += ['2026-11-15T01:00:15Z request failed']
    monkeypatch.setattr(docker_readonly, 'MAX_TEXT_BYTES', 240)
    monkeypatch.setattr(docker_readonly.subprocess, 'run', lambda *a, **k:
        SimpleNamespace(returncode=0, stdout=('\n'.join(rows) + '\n').encode(), stderr=b''))

    value = WindowsCollector(cfg).text_logs('web', 'docker://allowed-web-1/stdout', lines=20)

    payload = value['payload']
    assert 'ConnectionException' in payload['lines'][0]
    assert payload['lines'][-1] == rows[-1]
    assert 'private' not in json.dumps(value)
    assert len('\n'.join(payload['lines']).encode()) <= 240
    assert payload['omitted_middle_lines'] == len(rows) - len(payload['lines'])
    assert payload['selection'] == 'head_and_tail'
    assert payload['covers_full_history'] is False
    assert value['truncated'] is True


def test_spring_configuration_projects_registered_public_values_only(tmp_path, monkeypatch):
    source = tmp_path / 'portal.yml'
    source.write_text('''spring:
  datasource:
    url: jdbc:mysql://mysql:3306/mall?useUnicode=true
    password: never-return-this
  data:
    redis:
      host: redis
      port: 6379
server:
  port: 8323
''', encoding='utf-8')
    extra = f'''\n[services.portal]
kind="docker"
docker_container="allowed-portal-1"
docker_spring=true
config_file={json.dumps(str(source))}
config_keys=["spring.datasource.url", "spring.data.redis.host", "spring.data.redis.port", "server.port"]
'''
    cfg = config(tmp_path, extra).service('portal')
    def observe(*args):
        if args[:3] == ('inspect', '--type', 'container') and args[3] == '--format':
            if '{{json .Mounts}}' in args[4]:
                return json.dumps([{'Destination': '/app/local.yml', 'Source': str(source), 'RW': False}]).encode()
            if '{{json .Config.Cmd}}' in args[4]:
                return json.dumps(['java', '-jar', '/app/app.jar', '--spring.config.additional-location=file:/app/local.yml']).encode()
        raise AssertionError(args)
    monkeypatch.setattr(docker_readonly, 'docker', observe)

    result = docker_readonly.configuration(cfg)

    assert result['source'] == 'mounted_spring_config_snapshot'
    assert result['runtime_effective_values_confirmed'] is False
    assert result['mount_matches_registered_file'] is True
    assert result['mount_read_only'] is True
    assert result['startup_config_argument_present'] is True
    assert result['values']['spring.datasource.url'] == {'host': 'mysql', 'port': 3306, 'database': 'mall'}
    assert result['values']['server.port'] == 8323
    assert 'never-return-this' not in json.dumps(result)
    assert 'useUnicode' not in json.dumps(result)


def test_long_stack_keeps_start_of_bounded_source_window(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    rows = ['2026-11-15T01:00:00.000Z RedisConnectionFailureException password=private']
    rows += [f'2026-11-15T01:00:00.{i:03d}Z stack frame {i}' for i in range(1, 301)]
    calls = []
    def observe(argv, **kwargs):
        calls.append(argv)
        limit = int(argv[argv.index('--tail') + 1])
        return SimpleNamespace(returncode=0, stdout=('\n'.join(rows[-limit:]) + '\n').encode(), stderr=b'')
    monkeypatch.setattr(docker_readonly.subprocess, 'run', observe)

    result = WindowsCollector(cfg).text_logs('web', 'docker://allowed-web-1/stdout', lines=100)

    payload = result['payload']
    assert 'RedisConnectionFailureException' in payload['lines'][0]
    assert payload['lines'][-1] == rows[-1]
    assert len(payload['lines']) <= 100
    assert payload['omitted_middle_lines'] == len(rows) - len(payload['lines'])
    assert payload['source_line_limit'] == 1001
    assert payload['selection'] == 'head_and_tail'
    assert result['truncated'] is True and payload['covers_full_history'] is False
    assert 'private' not in json.dumps(result)


def test_spring_container_dependency_probe_uses_fixed_jshell_tcp_check(tmp_path, monkeypatch):
    source = tmp_path / 'portal.yml'
    source.write_text('server: {port: 8323}\n', encoding='utf-8')
    cfg = config(tmp_path, f'''\n[services.portal]
kind="docker"
docker_container="allowed-portal-1"
docker_spring=true
config_file={json.dumps(str(source))}
config_keys=["server.port"]
[dependencies.mysql]
host="mysql"
port=3306
source_service="portal"
''')
    calls = []
    def observe(*args, **kwargs):
        calls.append((args, kwargs))
        return b'PROBE_TCP=ok;elapsed_ms=3.4\n'
    monkeypatch.setattr(docker_readonly, 'docker', observe)

    result = docker_readonly.dependency(cfg, cfg.dependency('mysql'))

    assert result['tcp'] == 'ok'
    assert result['elapsed_ms'] == 3.4
    assert result['source_service'] == 'portal'
    assert calls[0][0][:5] == ('exec', '-i', 'allowed-portal-1', 'jshell', '--execution')
    assert 'mysql' in calls[0][1]['input'].decode()


def test_spring_probe_allowlist_rejects_secret_and_arbitrary_keys(tmp_path):
    source = tmp_path / 'portal.yml'
    source.write_text('spring: {}\n', encoding='utf-8')
    base = f'''target_id="test"\ngateway_url="ws://127.0.0.1:18769/probe/ws"
[services.portal]
kind="docker"
docker_container="allowed-portal-1"
docker_spring=true
config_file={json.dumps(str(source))}
'''
    secret = tmp_path / 'secret.toml'
    secret.write_text(base + 'config_keys=["spring.datasource.password"]\n', encoding='utf-8')
    arbitrary = tmp_path / 'arbitrary.toml'
    arbitrary.write_text(base + 'config_keys=["management.endpoint.env.enabled"]\n', encoding='utf-8')

    with pytest.raises(ProbeConfigError):
        load_config(secret)
    with pytest.raises(ProbeConfigError):
        load_config(arbitrary)


def test_tcp_failure_is_not_reported_as_an_application_query(monkeypatch, capsys):
    import socket
    import sys
    monkeypatch.setattr(sys, 'argv', ['probe', json.dumps(dict(host='db', port=5432,
        source_service='web', probe_kind='tcp', cache_alias='default'))])
    def unavailable(*args, **kwargs):
        raise OSError('unreachable')
    monkeypatch.setattr(socket, 'create_connection', unavailable)
    exec(docker_readonly.NETWORK, {})
    result = json.loads(capsys.readouterr().out)
    assert result['tcp'] == 'failed'
    assert 'query' not in result


@pytest.mark.parametrize('resource', ['../secret', '/etc/passwd', 'a//b', 'a/../b', 'a\\b'])
def test_static_resources_cannot_escape_registration(tmp_path, resource):
    with pytest.raises(ProbeConfigError):
        config(tmp_path, '\nstatic_resources=' + json.dumps([resource]))


def test_static_mount_observation_checks_registered_resource_without_reading_contents(tmp_path, monkeypatch):
    source = tmp_path / 'static'
    source.mkdir()
    (source / 'shop.css').write_text('private contents are not evidence')
    cfg = config(tmp_path, '\nstatic_resources=["shop.css"]\nexpected_static_mounts={"/lab/static"=' + json.dumps(str(source)) + '}')
    calls = []
    def observe(*args, **kwargs):
        calls.append(args)
        if args[0] == 'exec':
            assert json.loads(args[-1]) == ['shop.css']
            return b'{"static_files":{"shop.css":{"found":false}},"static_directories":["/lab/static"]}'
        return json.dumps([{'Destination': '/lab/static', 'Source': str(tmp_path / 'empty')},
                           {'Destination': '/other', 'Source': 'unregistered'}]).encode()
    monkeypatch.setattr(docker_readonly, 'docker', observe)
    value = WindowsCollector(cfg).configuration('web')['payload']
    mount = value['static_mounts'][0]
    assert mount['registered_resources_present'] == {'shop.css': True}
    assert mount['actual_source'] != mount['registered_source']
    assert 'private contents' not in json.dumps(value) and 'unregistered' not in json.dumps(value)
    assert len(calls) == 2
    inventory = WindowsCollector(cfg).inventory()['payload']['configured_services']['web']
    assert inventory['static_resources'] == ['shop.css']
    assert inventory['static_mount_destinations'] == ['/lab/static']
