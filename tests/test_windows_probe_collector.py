from pathlib import Path
import asyncio

import pytest

from src.probe.windows.collector import WindowsCollector
from src.probe.windows.config import ProbeConfigError, load_config, allowed_text_path
from scripts.windows_probe import _load_validated_config, run_probe
from scripts.windows_probe import _set_acl
import subprocess
import os
import sys
from dataclasses import replace
from unittest.mock import Mock


def _config(tmp_path: Path):
    log = tmp_path / "orders.log"
    log.write_text("one\ntwo\nthree\n", encoding="utf-8")
    path = tmp_path / "probe.toml"
    path.write_text(f'''
target_id = "windows-local-01"
gateway_url = "ws://127.0.0.1:18767/probe/ws"
token_file = '{str(tmp_path / 'token').replace("'", "''")}'
baseline_interval_seconds = 60
[services.orders]
service_name = "OrdersService"
process_names = ["orders.exe"]
log_channels = ["Application"]
log_providers = ["Orders"]
text_logs = ['{str(log).replace("'", "''")}']
[dependencies.database]
host = "127.0.0.1"
port = 1433
health_scheme = "http"
health_path = "/health"
''', encoding="utf-8")
    (tmp_path / "token").write_text("test-token", encoding="utf-8")
    return load_config(path), log


def test_config_allow_list_and_text_log_tail(tmp_path):
    cfg, log = _config(tmp_path)
    assert allowed_text_path(cfg, "orders", str(log))
    collector = WindowsCollector(cfg)
    result = collector.text_logs("orders", str(log), lines=2)
    assert result["operation"] == "text_logs"
    assert result["payload"]["lines"] == ["two", "three"]
    assert result["raw_hash"].startswith("sha256:")
    assert result["truncated"] is True


def test_process_application_does_not_query_windows_service_manager(tmp_path, monkeypatch):
    cfg, _ = _config(tmp_path)
    path = tmp_path / 'probe.toml'
    path.write_text(path.read_text(encoding='utf-8').replace('[services.orders]',
        '[services.orders]\nkind = "process"'), encoding='utf-8')
    cfg = load_config(path)
    manager = Mock(side_effect=AssertionError('process application must not access SCM'))
    monkeypatch.setitem(sys.modules, 'win32service', Mock(OpenSCManager=manager))
    collector = WindowsCollector(cfg)
    assert collector.inventory()['payload']['configured_services']['orders']['kind'] == 'process'
    result = collector.services('orders')['payload']
    assert result['state'] == 'not_applicable' and 'error' not in result
    manager.assert_not_called()


def test_service_kind_defaults_to_windows_service_and_rejects_unknown(tmp_path):
    cfg, _ = _config(tmp_path)
    assert cfg.services['orders'].kind == 'windows_service'
    path = tmp_path / 'probe.toml'
    path.write_text(path.read_text(encoding='utf-8').replace('[services.orders]',
        '[services.orders]\nkind = "shell"'), encoding='utf-8')
    with pytest.raises(ProbeConfigError, match='kind'):
        load_config(path)


def test_collector_redacts_text_before_hashing_and_leaving_target(tmp_path):
    from src.probe.evidence import validate_evidence
    cfg, log = _config(tmp_path)
    log.write_text('Authorization: Basic hidden-credential\nCookie: sid=hidden-credential\nconnection refused\n', encoding='utf-8')
    result = WindowsCollector(cfg).text_logs('orders', str(log))
    assert 'hidden-credential' not in str(result)
    assert 'connection refused' in str(result)
    assert validate_evidence(result, target_id=cfg.target_id) is result


def test_text_tail_does_not_read_whole_large_file(tmp_path, monkeypatch):
    cfg, log = _config(tmp_path)
    with log.open("wb") as handle:
        handle.seek(8 * 1024 * 1024)
        handle.write(b"\nlast line\n")
    monkeypatch.setattr(Path, "read_bytes", lambda self: pytest.fail("unbounded file read"))
    result = WindowsCollector(cfg).text_logs("orders", str(log), lines=1)
    assert result["payload"]["lines"] == ["last line"]
    assert result["truncated"] is True


def test_text_pattern_cannot_match_nested_directory_or_alternate_stream(tmp_path):
    cfg, _ = _config(tmp_path)
    service = replace(cfg.services["orders"], text_logs=(str(tmp_path / "*.log"),))
    cfg = replace(cfg, services={"orders": service})
    assert allowed_text_path(cfg, "orders", str(tmp_path / "normal.log"))
    assert not allowed_text_path(cfg, "orders", str(tmp_path / "nested" / "secret.log"))
    assert not allowed_text_path(cfg, "orders", str(tmp_path / "normal.log:secret.log"))


@pytest.mark.skipif(os.name != 'nt', reason='Windows short/long directory aliases')
def test_text_log_short_directory_alias_matches_opened_long_path(tmp_path):
    import win32api
    cfg, log = _config(tmp_path)
    short_parent = win32api.GetShortPathName(str(tmp_path))
    long_parent = str(tmp_path.resolve(strict=True))
    if short_parent.casefold() == long_parent.casefold():
        pytest.skip('8.3 directory aliases are disabled on this volume')
    cfg = replace(cfg, services={'orders': replace(cfg.services['orders'],
                  text_logs=(str(Path(short_parent) / '*.log'),))})
    assert allowed_text_path(cfg, 'orders', str(Path(long_parent) / log.name))
    result = WindowsCollector(cfg).text_logs('orders', str(Path(short_parent) / log.name))
    assert result['payload']['lines'] == ['one', 'two', 'three']
    assert not allowed_text_path(cfg, 'orders', str(Path(long_parent) / 'nested' / log.name))


@pytest.mark.skipif(os.name != 'nt', reason='Windows case-insensitive paths')
def test_text_log_windows_case_and_separators_preserve_allow_list(tmp_path):
    cfg, log = _config(tmp_path)
    requested = str(log).upper().replace('\\', '/')
    assert allowed_text_path(cfg, 'orders', requested)
    assert WindowsCollector(cfg).text_logs('orders', requested)['payload']['lines'] == ['one', 'two', 'three']
    for forbidden in (str(log) + ':secret', str(tmp_path / '..' / log.name),
                      '\\\\?\\' + str(log), '\\\\server\\share\\orders.log'):
        assert not allowed_text_path(cfg, 'orders', forbidden)


def test_text_log_junction_cannot_escape_allow_list(tmp_path):
    cfg, _ = _config(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.log").write_text("must not read", encoding="utf-8")
    link = tmp_path / "linked"
    if os.name == "nt":
        subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(link), str(outside)], check=True, capture_output=True)
    else:
        link.symlink_to(outside, target_is_directory=True)
    try:
        cfg = replace(cfg, services={"orders": replace(cfg.services["orders"], text_logs=(str(link / "*.log"),))})
        assert not allowed_text_path(cfg, 'orders', str(outside / 'secret.log'))
        with pytest.raises(ProbeConfigError):
            WindowsCollector(cfg).text_logs("orders", str(link / "secret.log"))
    finally:
        if os.name == "nt":
            os.rmdir(link)
        else:
            link.unlink()


def test_missing_log_directory_does_not_hide_later_allow_list_entry(tmp_path):
    cfg, log = _config(tmp_path)
    cfg = replace(cfg, services={'orders': replace(cfg.services['orders'],
                  text_logs=(str(tmp_path / 'missing' / '*.log'), str(log)))})
    assert allowed_text_path(cfg, 'orders', str(log))


@pytest.mark.parametrize("url", ["ws://192.168.1.2/probe/ws", "ws://example.com/probe/ws", "wss://user:secret@example.com/probe/ws", "wss:///probe/ws"])
def test_gateway_config_rejects_plaintext_remote_and_credentials(tmp_path, url):
    _config(tmp_path)
    path = tmp_path / "probe.toml"
    path.write_text(path.read_text(encoding="utf-8").replace("ws://127.0.0.1:18767/probe/ws", url), encoding="utf-8")
    with pytest.raises(ProbeConfigError):
        load_config(path)


def test_old_event_ends_reverse_scan_and_missing_time_is_not_evidence(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace
    cfg, _ = _config(tmp_path)
    now = datetime.now(timezone.utc)
    event = lambda stamp: SimpleNamespace(TimeGenerated=stamp, SourceName="Orders", StringInserts=["hello"], EventID=1, EventType=1)
    api = Mock(EVENTLOG_BACKWARDS_READ=1, EVENTLOG_SEQUENTIAL_READ=2)
    api.ReadEventLog.side_effect = [[event(None), event(now), event(now - timedelta(days=2))], AssertionError("scanned past cutoff")]
    monkeypatch.setitem(sys.modules, "win32evtlog", api)
    result = WindowsCollector(cfg).event_logs("orders")
    assert len(result["payload"]["events"]) == 1
    assert "error" not in result["payload"]
    api.CloseEventLog.assert_called_once()


def test_isolated_worker_returns_real_inventory(tmp_path):
    from src.probe.windows.worker import collect_isolated
    _config(tmp_path)
    result = asyncio.run(collect_isolated(tmp_path / 'probe.toml', 'inventory', {}))
    assert result['operation'] == 'inventory'
    assert result['target_id'] == 'windows-local-01'


@pytest.mark.parametrize('stop', [False, True])
def test_isolated_worker_kills_timed_out_or_stopped_process(tmp_path, monkeypatch, stop):
    from src.probe.windows.worker import collect_isolated
    real_create = asyncio.create_subprocess_exec
    processes = []
    async def create(*args, **kwargs):
        child = await real_create(sys.executable, '-c', 'import time; time.sleep(60)', **kwargs)
        processes.append(child)
        return child
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', create)
    with pytest.raises(InterruptedError if stop else TimeoutError):
        asyncio.run(collect_isolated(tmp_path / 'probe.toml', 'resources', {}, lambda: stop, timeout=0.2))
    assert len(processes) == 1
    assert processes[0].returncode is not None


def test_text_log_path_traversal_is_rejected(tmp_path):
    cfg, _ = _config(tmp_path)
    with pytest.raises(ProbeConfigError):
        WindowsCollector(cfg).text_logs("orders", str(tmp_path / ".." / "secret.log"))


def test_collector_fixed_operations_do_not_expose_shell(tmp_path):
    cfg, _ = _config(tmp_path)
    collector = WindowsCollector(cfg)
    result = collector.processes("orders")
    assert result["operation"] == "processes"
    with pytest.raises(ProbeConfigError):
        collector.collect("exec", {"command": "whoami"})


def test_process_cpu_is_sampled_twice_with_one_shared_interval(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from src.probe.windows import collector as module
    cfg, _ = _config(tmp_path)
    samples = []
    first = SimpleNamespace(info={'pid': 101, 'name': 'orders.exe', 'cpu_percent': 0,
                                  'memory_info': SimpleNamespace(rss=8192)})
    second = SimpleNamespace(info={'pid': 102, 'name': 'orders.exe', 'cpu_percent': 0,
                                   'memory_info': SimpleNamespace(rss=4096)})
    first.cpu_percent = Mock(side_effect=[0, 37.5])
    second.cpu_percent = Mock(side_effect=[0, 12.5])
    monkeypatch.setattr(module.psutil, 'process_iter', lambda attrs: iter([first, second]))
    def sample_wait(seconds):
        assert first.cpu_percent.call_count == second.cpu_percent.call_count == 1
        samples.append(seconds)
    monkeypatch.setattr(module.time, 'sleep', sample_wait)
    result = WindowsCollector(cfg).processes('orders')['payload']
    assert [row['cpu_percent'] for row in result['processes']] == [37.5, 12.5]
    assert samples == [0.1]
    assert result['cpu_sample_interval_seconds'] == 0.1


@pytest.mark.parametrize('fail_on_first_read', [True, False])
def test_process_cpu_permission_failure_is_not_reported_as_zero(tmp_path, monkeypatch, fail_on_first_read):
    from types import SimpleNamespace
    from src.probe.windows import collector as module
    cfg, _ = _config(tmp_path)
    process = SimpleNamespace(info={'pid': 101, 'name': 'orders.exe', 'cpu_percent': 0,
                                    'memory_info': SimpleNamespace(rss=4096)},
                              cpu_percent=Mock(side_effect=module.psutil.AccessDenied(101)
                                  if fail_on_first_read else [0, module.psutil.AccessDenied(101)]))
    monkeypatch.setattr(module.psutil, 'process_iter', lambda attrs: iter([process]))
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)
    result = WindowsCollector(cfg).processes('orders')['payload']['processes'][0]
    assert result['cpu_percent'] is None
    assert result['cpu_error'] == 'AccessDenied'


def test_dependency_must_be_configured(tmp_path):
    cfg, _ = _config(tmp_path)
    with pytest.raises(ProbeConfigError):
        WindowsCollector(cfg).dependency_probe("unknown")


@pytest.mark.parametrize('sort_by', ['memory', 'cpu'])
def test_process_snapshot_selects_heavy_process_beyond_output_cap(tmp_path, monkeypatch, sort_by):
    from types import SimpleNamespace
    from src.probe.windows import collector as module
    cfg, _ = _config(tmp_path)
    processes = [SimpleNamespace(info={'pid': pid, 'name': 'orders.exe',
        'memory_info': SimpleNamespace(rss=pid * 1024)},
        cpu_percent=Mock(side_effect=[0, float(pid)])) for pid in range(1, 301)]
    monkeypatch.setattr(module.psutil, 'process_iter', lambda attrs: iter(processes))
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)
    result = WindowsCollector(cfg).collect('processes', {'sort_by': sort_by})
    payload = result['payload']
    assert len(payload['processes']) == 256
    assert payload['processes'][0]['pid'] == 300
    assert payload['matched_count'] == payload['inspected_count'] == 300
    assert payload['sort_by'] == sort_by
    assert result['truncated'] is True


def test_process_snapshot_exact_cap_is_not_truncated_and_empty_filter_is_not_global(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from src.probe.windows import collector as module
    cfg, _ = _config(tmp_path)
    processes = [SimpleNamespace(info={'pid': pid, 'name': 'other.exe',
        'memory_info': None}, cpu_percent=Mock(side_effect=module.psutil.AccessDenied(pid)))
        for pid in range(256)]
    monkeypatch.setattr(module.psutil, 'process_iter', lambda attrs: iter(processes))
    result = WindowsCollector(cfg).processes()
    assert not result.get('truncated', False)
    assert result['payload']['memory_unavailable_count'] == 256
    assert result['payload']['cpu_unavailable_count'] == 256
    if os.name == 'nt':
        idle = next(row for row in result['payload']['processes'] if row['pid'] == 0)
        assert idle['cpu_role'] == 'idle_time_not_workload'
    cfg = replace(cfg, services={'orders': replace(cfg.services['orders'], process_names=())})
    assert WindowsCollector(cfg).processes('orders')['payload']['processes'] == []


def test_process_snapshot_rejects_unrecognized_sort_without_collecting(tmp_path, monkeypatch):
    from src.probe.windows import collector as module
    cfg, _ = _config(tmp_path)
    monkeypatch.setattr(module.psutil, 'process_iter', lambda *_: pytest.fail('invalid query was collected'))
    with pytest.raises(ProbeConfigError):
        WindowsCollector(cfg).collect('processes', {'sort_by': 'command'})


@pytest.mark.parametrize('status, body', [(200, b'healthy'), (503, b'database unavailable'),
                                       (503, b'x' * 2048), (302, b'redirect blocked')])
def test_dependency_http_preserves_status_bounds_body_and_does_not_redirect(tmp_path, status, body):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from src.probe.evidence import validate_evidence
    cfg, _ = _config(tmp_path)
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(status)
            if status == 302:
                self.send_header('Location', '/must-not-follow')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    cfg = replace(cfg, dependencies={'database': replace(cfg.dependencies['database'],
                  port=server.server_address[1])})
    try:
        result = WindowsCollector(cfg).dependency_probe('database')
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    assert requests == ['/health']
    assert result['payload']['tcp'] == 'ok'
    http = result['payload']['http']
    assert http['status'] == status
    assert http['body_prefix'] == body[:1024].decode()
    assert http['truncated'] is (len(body) > 1024)
    assert bool(result.get('truncated')) is (len(body) > 1024)
    assert validate_evidence(result, target_id=cfg.target_id) is result


def test_port_filter_finds_listener_after_unrelated_connections(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from src.probe.evidence import validate_evidence
    cfg, _ = _config(tmp_path)
    def connection(port, status='ESTABLISHED', pid=9):
        return SimpleNamespace(family=2, type=1, status=status,
            laddr=SimpleNamespace(ip='127.0.0.1', port=port), raddr=(), pid=pid)
    rows = [connection(10000 + index) for index in range(300)]
    rows += [connection(23456, 'LISTEN', None)]
    monkeypatch.setattr('src.probe.windows.collector.psutil.net_connections', lambda **_: rows)
    result = WindowsCollector(cfg).collect('ports', {'local_port': 23456, 'listening_only': True})
    assert len(result['payload']['ports']) == 1
    assert result['payload']['ports'][0]['local']['port'] == 23456
    assert result['payload']['ports'][0]['pid'] is None
    assert result['payload']['local_port'] == 23456
    assert result['payload']['listening_only'] is True
    assert result['payload']['matched_count'] == 1
    assert not result.get('truncated')
    validate_evidence(result, target_id=cfg.target_id)


@pytest.mark.parametrize('count,truncated', [(2, False), (3, True)])
def test_port_truncation_counts_matching_rows(tmp_path, monkeypatch, count, truncated):
    from types import SimpleNamespace
    cfg, _ = _config(tmp_path)
    row = SimpleNamespace(family=2, type=1, status='LISTEN',
        laddr=SimpleNamespace(ip='127.0.0.1', port=23456), raddr=(), pid=9)
    monkeypatch.setattr('src.probe.windows.collector.psutil.net_connections', lambda **_: [row] * count)
    result = WindowsCollector(cfg).ports(limit=2, local_port=23456, listening_only=True)
    assert len(result['payload']['ports']) == 2
    assert bool(result.get('truncated')) == truncated


@pytest.mark.parametrize('params', [{'local_port': 0}, {'local_port': True},
    {'local_port': 65536}, {'local_port': '80'}, {'listening_only': 'false'}])
def test_port_filters_rejected_before_collection(tmp_path, monkeypatch, params):
    cfg, _ = _config(tmp_path)
    monkeypatch.setattr('src.probe.windows.collector.psutil.net_connections',
        lambda **_: pytest.fail('invalid filters reached collection'))
    with pytest.raises(ValueError):
        WindowsCollector(cfg).collect('ports', params)


def test_inventory_exposes_allowed_log_queries_without_credentials(tmp_path):
    cfg, log = _config(tmp_path)
    payload = WindowsCollector(cfg).inventory()['payload']
    assert payload['configured_services']['orders']['service_name'] == 'OrdersService'
    assert payload['configured_services']['orders']['text_logs'] == list(cfg.services['orders'].text_logs)
    assert payload['configured_dependencies'] == ['database']
    assert str(log) in payload['configured_services']['orders']['text_logs']
    assert 'test-token' not in str(payload)


def test_naive_event_time_is_local_time_converted_to_utc():
    from datetime import datetime, timezone
    from src.probe.windows.collector import _safe_dt
    local = datetime(2026, 10, 17, 10, 23, 12)
    converted = datetime.fromisoformat(_safe_dt(local).replace('Z', '+00:00'))
    assert converted.timestamp() == local.timestamp()
    assert converted.tzinfo == timezone.utc


def test_probe_loop_honors_stop_callback_before_connecting(tmp_path, monkeypatch):
    _, _ = _config(tmp_path)
    monkeypatch.setenv("RAG_AIOPS_PROBE_CONFIG", str(tmp_path / "probe.toml"))
    asyncio.run(run_probe(lambda: True))


def test_install_preflight_rejects_empty_token_before_service_changes(tmp_path, monkeypatch):
    _config(tmp_path)
    (tmp_path / "token").write_text("", encoding="utf-8")
    monkeypatch.setenv("RAG_AIOPS_PROBE_CONFIG", str(tmp_path / "probe.toml"))
    with pytest.raises(ProbeConfigError, match="token file is empty"):
        _load_validated_config()


def test_acl_failure_is_not_ignored(tmp_path, monkeypatch):
    def fail(command, **kwargs):
        assert kwargs["check"] is True
        assert "*S-1-5-19:(OI)(CI)RX" in command
        raise subprocess.CalledProcessError(5, ["icacls"])
    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        _set_acl(tmp_path)


@pytest.mark.skipif(__import__('os').name != 'nt', reason='Windows installer API')
def test_installer_registers_protected_runtime_and_config(tmp_path, monkeypatch):
    import scripts.windows_probe as installer
    import win32service
    import win32serviceutil
    cfg, _ = _config(tmp_path)
    monkeypatch.setenv('RAG_AIOPS_PROBE_CONFIG', str(tmp_path / 'probe.toml'))
    monkeypatch.setattr(installer, 'DEFAULT_CONFIG_DIR', tmp_path / 'deployment')
    monkeypatch.setattr(installer, '_set_acl', lambda *args, **kwargs: None)
    host = tmp_path / 'deployment' / 'runtime' / 'pythonservice.exe'
    monkeypatch.setattr(installer, '_deploy_runtime', lambda path: host)
    def missing(name):
        raise win32service.error(1060, 'QueryServiceStatus', 'missing')
    monkeypatch.setattr(win32serviceutil, 'QueryServiceStatus', missing)
    calls = []
    monkeypatch.setattr(win32serviceutil, 'InstallService', lambda *args, **kwargs: calls.append((args, kwargs)))
    options = []
    monkeypatch.setattr(win32serviceutil, 'SetServiceCustomOption', lambda *args: options.append(args))
    assert installer.install_service() == 0
    assert calls[0][0][0] == 'src.probe.windows.service.ProbeService'
    assert calls[0][1]['exeName'] == str(host)
    assert calls[0][1]['userName'] == r'NT AUTHORITY\LocalService'
    assert options[0][1:] == ('ConfigPath', str((tmp_path / 'probe.toml').resolve()))


@pytest.mark.skipif(os.name != 'nt', reason='Windows service API')
def test_upgrade_restores_original_runtime_when_start_fails(tmp_path, monkeypatch):
    import scripts.windows_probe as installer
    import win32service
    import win32serviceutil
    _config(tmp_path)
    monkeypatch.setenv('RAG_AIOPS_PROBE_CONFIG', str(tmp_path / 'probe.toml'))
    monkeypatch.setattr(installer, 'DEFAULT_CONFIG_DIR', tmp_path)
    old = str(tmp_path / 'old' / 'pythonservice.exe')
    monkeypatch.setattr(installer, '_deploy_runtime', lambda path: tmp_path / 'new' / 'pythonservice.exe')
    monkeypatch.setattr(win32service, 'OpenSCManager', lambda *args: 1)
    monkeypatch.setattr(win32service, 'OpenService', lambda *args: 2)
    monkeypatch.setattr(win32service, 'CloseServiceHandle', lambda *args: None)
    monkeypatch.setattr(win32service, 'QueryServiceConfig', lambda *args: (0, 0, 0, old, None, 0, None, r'NT AUTHORITY\LocalService'))
    monkeypatch.setattr(win32serviceutil, 'GetServiceCustomOption', lambda *args: str(tmp_path / 'probe.toml'))
    states = iter([win32service.SERVICE_RUNNING, win32service.SERVICE_STOPPED])
    monkeypatch.setattr(win32serviceutil, 'QueryServiceStatus', lambda *args: (0, next(states)))
    monkeypatch.setattr(win32serviceutil, 'StopService', lambda *args: None)
    monkeypatch.setattr(win32serviceutil, 'WaitForServiceStatus', lambda *args: None)
    calls = []
    monkeypatch.setattr(win32service, 'ChangeServiceConfig', lambda *args: calls.append(args[4]))
    start = Mock(side_effect=[RuntimeError('new runtime failed'), None])
    monkeypatch.setattr(win32serviceutil, 'StartService', start)
    with pytest.raises(RuntimeError, match='new runtime failed'):
        installer.upgrade_service()
    assert calls[-1] == old
    assert len(calls) == 2
    assert start.call_count == 2

