import hashlib
import json
from dataclasses import replace

import pytest

from src.probe.windows.collector import WindowsCollector
from src.probe.windows.config import ProbeConfig, ProbeConfigError, ServiceConfig, load_config


def configured(tmp_path, content):
    source = tmp_path / 'app.json'
    source.write_text(content, encoding='utf-8')
    config = ProbeConfig('windows-local-01', 'ws://127.0.0.1:9000/probe/ws', tmp_path / 'token',
        services={'entry': ServiceConfig('', kind='process', config_file=str(source),
                                        config_keys=('max_attempts', 'password', 'absent'))})
    return config, source


def test_snapshot_reads_only_configured_keys_and_preserves_source_hash(tmp_path):
    cfg, source = configured(tmp_path, json.dumps({'max_attempts': 'invalid',
        'password': 'hidden-secret', 'private_other': 'must-not-return'}))
    collector = WindowsCollector(cfg)
    result = collector.collect('configuration', {'service': 'entry'})
    body = result['payload']
    assert result['operation'] == 'configuration'
    assert body['path'] == str(source.resolve())
    assert body['values'] == {'max_attempts': 'invalid', 'password': '[REDACTED]'}
    assert body['missing_keys'] == ['absent']
    assert body['source_sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert body['modified_at_ns'] == source.stat().st_mtime_ns
    assert 'hidden-secret' not in str(result) and 'must-not-return' not in str(result)
    assert collector.inventory()['payload']['configured_services']['entry']['configuration_available']
    with pytest.raises(ProbeConfigError):
        collector.configuration('not-configured')
    with pytest.raises(ProbeConfigError):
        collector.collect('configuration', {'service': 'entry', 'path': str(tmp_path / 'other')})


@pytest.mark.parametrize('content,error', [('not json', 'invalid_json_object'),
    ('[]', 'invalid_json_object'), ('x' * 17000, 'configuration_too_large')])
def test_bad_or_large_configuration_returns_no_values(tmp_path, content, error):
    cfg, _ = configured(tmp_path, content)
    result = WindowsCollector(cfg).configuration('entry')
    assert result['payload']['error'] == error
    assert 'values' not in result['payload']


def test_snapshot_requires_explicit_configuration_allowlist(tmp_path):
    cfg, _ = configured(tmp_path, '{}')
    cfg = replace(cfg, services={'entry': ServiceConfig('', kind='process')})
    assert WindowsCollector(cfg).configuration('entry')['payload']['error'] == 'configuration_not_configured'


def test_configuration_file_and_keys_load_together_and_reject_wildcards(tmp_path):
    cfg, source = configured(tmp_path, '{}')
    path = tmp_path / 'probe.toml'
    base = "target_id = 'windows-local-01'\ngateway_url = 'ws://127.0.0.1:9000/probe/ws'\n[services.entry]\n"
    valid = f"config_file = '{source.as_posix()}'\nconfig_keys = ['max_attempts']\n"
    path.write_text(base + valid, encoding='utf-8')
    loaded = load_config(path)
    assert loaded.services['entry'].config_keys == ('max_attempts',)
    for invalid in [valid.replace('app.json', '*.json'),
                    f"config_file = '{source.as_posix()}'\n", "config_keys = ['max_attempts']\n"]:
        path.write_text(base + invalid, encoding='utf-8')
        with pytest.raises(ProbeConfigError):
            load_config(path)


def test_snapshot_checks_opened_handle_before_reading(tmp_path, monkeypatch):
    import builtins
    cfg, source = configured(tmp_path, '{}')
    outside = tmp_path / 'private.json'
    outside.write_text('{"max_attempts": "must-not-read"}', encoding='utf-8')
    real_open = builtins.open
    monkeypatch.setattr(builtins, 'open', lambda path, *args, **kwargs:
        real_open(outside if str(path) == str(source) else path, *args, **kwargs))
    with pytest.raises(ProbeConfigError, match='outside'):
        WindowsCollector(cfg).configuration('entry')


@pytest.mark.asyncio
async def test_gateway_configuration_schema_and_forwarded_arguments(monkeypatch):
    from unittest.mock import AsyncMock
    from mcp_servers import probe_gateway as gateway
    request = AsyncMock(return_value={'payload': {'values': {'max_attempts': 'invalid'}}})
    monkeypatch.setattr(gateway, '_tool', request)
    assert set(gateway.probe_config_snapshot.parameters['properties']) == {'service'}
    assert gateway.probe_config_snapshot.parameters['required'] == ['service']
    await gateway.probe_config_snapshot.fn(service='entry')
    request.assert_awaited_once_with('configuration', {'service': 'entry'})
