"""A literal query can retrieve diagnostic lines without pretending history is complete."""
import json
from types import SimpleNamespace

import pytest

from src.probe.windows import docker_readonly
from src.probe.windows.collector import WindowsCollector
from src.probe.windows.config import ProbeConfigError
from src.agent.aiops.strategies import investigation as inv
from tests.test_docker_readonly_probe import config

def source(monkeypatch, rows):
    def observe(argv, **kwargs):
        limit = int(argv[argv.index('--tail') + 1])
        return SimpleNamespace(returncode=0, stdout=('\n'.join(rows[-limit:]) + '\n').encode(), stderr=b'')
    monkeypatch.setattr(docker_readonly.subprocess, 'run', observe)

def test_filter_retrieves_middle_exception_without_frames(tmp_path, monkeypatch):
    rows = [f'2026-11-16T01:00:00.000Z at frame {i}' for i in range(300)]
    rows[151] = '2026-11-16T01:00:00.000Z Caused by: java.net.ConnectException: Connection refused password=private'
    source(monkeypatch, rows)
    result = WindowsCollector(config(tmp_path)).text_logs('web', 'docker://allowed-web-1/stdout',
                                                         contains='Caused by:')
    body = result['payload']
    assert len(body['lines']) == 1 and 'ConnectException' in body['lines'][0]
    assert body['contains'] == 'Caused by:' and body['filtered_out_lines'] == 299
    assert body['covers_full_history'] is False
    assert not result.get('truncated') and 'private' not in json.dumps(result)

def test_filter_does_not_hide_saturated_source_window(tmp_path, monkeypatch):
    rows = ['2026-11-16T01:00:00.000Z frame'] * 1200
    rows[-100] = '2026-11-16T01:00:00.000Z Caused by: Failure'
    source(monkeypatch, rows)
    result = WindowsCollector(config(tmp_path)).text_logs('web', 'docker://allowed-web-1/stdout',
                                                         contains='Caused by:')
    assert result['truncated'] is True
    assert result['payload']['source_window_saturated'] is True

def test_identical_timestamps_keep_stack_order(tmp_path, monkeypatch):
    rows = ['2026-11-16T01:00:00.000Z RootException: outer',
            '2026-11-16T01:00:00.000Z Caused by: InnerException: inner']
    source(monkeypatch, rows)
    result = WindowsCollector(config(tmp_path)).text_logs('web', 'docker://allowed-web-1/stdout')
    assert result['payload']['lines'] == rows

def test_filter_is_part_of_query_identity():
    args = {'service': 'web', 'path': 'docker://allowed-web-1/stdout'}
    assert inv.probe_query_key('probe_text_log', args) != inv.probe_query_key(
        'probe_text_log', {**args, 'contains': 'Caused by:'})


def test_exception_beyond_json_prefix_has_an_exact_bound_citation():
    from tests.test_concrete_investigation_checks import state
    diagnostic = r'Caused by: ConnectException: 中文连接失败 at D:\logs\app.log'
    current = state(('text_logs', {'service': 'web', 'path': 'docker://allowed-web-1/stdout',
        'line_limit': 100, 'lines': ['at stack frame ' + str(i) for i in range(150)] + [diagnostic]}))
    records = inv.evidence_index(current)
    record = records['e1.1']
    quote = json.dumps(diagnostic, ensure_ascii=False)[1:-1]
    assert quote not in record['payload'][:2000]
    snippets = inv._citation_snippets(record)
    assert quote in snippets.values()
    assert all(value in record['payload'] for value in snippets.values())
    assert inv._valid_citations([inv.Citation(evidence_id='e1.1', quote=quote)], records)

@pytest.mark.parametrize('supported', [True, False])
def test_filter_requires_current_collector_capability(supported):
    from tests.test_concrete_investigation_checks import state
    from src.agent.aiops.probe_checks import arguments_error
    current = state(('inventory', {'configured_services': {'web': {
        'text_logs_available': True, 'text_log_contains_supported': supported,
        'text_logs': ['docker://allowed-web-1/stdout']}}}))
    error = arguments_error('probe_text_log', {'service': 'web',
        'path': 'docker://allowed-web-1/stdout', 'contains': 'Caused by:'}, current, inv.evidence_index(current))
    assert bool(error) is (not supported)

def test_filtered_file_logs_use_same_literal_and_scope_guard(tmp_path):
    from tests.test_windows_probe_collector import _config
    cfg, path = _config(tmp_path)
    path.write_text('frame\nCaused by: refused\nframe\n', encoding='utf-8')
    collector = WindowsCollector(cfg)
    result = collector.collect('text_logs', {'service': 'orders', 'path': str(path), 'contains': 'Caused by:'})
    assert result['payload']['lines'] == ['Caused by: refused']
    assert result['payload']['filtered_out_lines'] == 2
    with pytest.raises(ProbeConfigError):
        collector.text_logs('orders', str(tmp_path / 'secret.log'), contains='Caused by:')

@pytest.mark.asyncio
@pytest.mark.parametrize('confirmed', [True, False])
async def test_gateway_requires_collector_to_confirm_filter(monkeypatch, confirmed):
    from mcp_servers import probe_gateway
    from unittest.mock import AsyncMock
    payload = {'contains': 'Caused by:'} if confirmed else {}
    tool = AsyncMock(return_value={'payload': payload})
    monkeypatch.setattr(probe_gateway, '_tool', tool)
    if confirmed:
        await probe_gateway.probe_text_log.fn('web', 'docker://allowed-web-1/stdout', contains='Caused by:')
    else:
        with pytest.raises(ValueError, match='did not confirm'):
            await probe_gateway.probe_text_log.fn('web', 'docker://allowed-web-1/stdout', contains='Caused by:')
    assert tool.await_args.args[1]['contains'] == 'Caused by:'

@pytest.mark.parametrize('contains', [123, 'a' * 121, 'a\nb'])
def test_filter_rejects_invalid_input_before_docker(tmp_path, monkeypatch, contains):
    monkeypatch.setattr(docker_readonly.subprocess, 'run', lambda *a, **k: pytest.fail('must reject before execution'))
    with pytest.raises(ProbeConfigError):
        WindowsCollector(config(tmp_path)).text_logs('web', 'docker://allowed-web-1/stdout', contains=contains)
