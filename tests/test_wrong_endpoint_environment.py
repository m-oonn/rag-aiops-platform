import hashlib
import json

import psutil
import pytest

from scripts.competing_hypothesis_fixture import CompetingFaultFixture
from scripts.verify_windows_local_faults import get_local
from src.probe.evidence import validate_observation_window
from src.probe.windows.collector import WindowsCollector
from src.probe.windows.config import ProbeConfig, ServiceConfig


def test_controller_business_request_precedes_first_log_snapshot(tmp_path):
    with CompetingFaultFixture('localapp_wrong_endpoint', tmp_path, stop_mode='request') as fixture:
        checks = fixture.observe_controller_side()
        assert checks['edge']['http_status'] == 503
        assert checks['downstream']['http_status'] == 200
        collector = WindowsCollector(ProbeConfig('endpoint-test', 'ws://127.0.0.1:1/probe/ws', None,
            services={'localapp': ServiceConfig('', kind='process', text_logs=(str(tmp_path / 'localapp.log'),))}))
        saved = collector.text_logs('localapp', str(tmp_path / 'localapp.log'), lines=100)
        events = [json.loads(line) for line in saved['payload']['lines']]
        business = [row for row in events if row.get('path') == '/api/availability']
        assert business and all(row['upstream']['port'] == fixture.obsolete_port for row in business)
        edge = [json.loads(line) for line in (tmp_path / 'edge.log').read_text().splitlines()]
        assert any(row.get('request_id') == business[0]['request_id'] for row in edge)
        original = json.dumps(saved, sort_keys=True)
        get_local(fixture.edge_port, path='/api/availability', request_id='later-business-request')
        assert 'later-business-request' in (tmp_path / 'localapp.log').read_text()
        assert json.dumps(saved, sort_keys=True) == original
        assert 'later-business-request' not in original


@pytest.mark.integration
def test_wrong_endpoint_is_loaded_once_and_repair_requires_restart(tmp_path):
    with CompetingFaultFixture('localapp_wrong_endpoint', tmp_path, stop_mode='request') as fixture:
        collector = WindowsCollector(ProbeConfig(
            'endpoint-test', 'ws://127.0.0.1:1/probe/ws', None,
            services={'localapp': ServiceConfig('', kind='process',
                process_names=(psutil.Process().name(),), process_args=fixture.process_identity('localapp'),
                text_logs=(str(tmp_path / 'localapp.log'),),
                config_file=str(fixture.connection_config), config_keys=('downstream_port',))}))
        assert get_local(fixture.edge_port) == (503, 'temporarily unavailable')
        assert get_local(fixture.downstream_port) == (200, 'healthy')
        assert collector.processes('localapp')['payload']['matched_count'] >= 1
        snapshot = collector.configuration('localapp')['payload']
        assert snapshot['values'] == {'downstream_port': fixture.obsolete_port}
        raw = collector.text_logs('localapp', str(tmp_path / 'localapp.log'), lines=100)
        validate_observation_window(raw, fixture.boundary)
        events = [json.loads(line) for line in raw['payload']['lines']]
        startup, = [row for row in events if row.get('event') == 'service_started']
        failed = [row for row in events if row.get('detail') == 'upstream connection failed']
        assert startup['configuration']['source_sha256'] == snapshot['source_sha256']
        assert startup['upstream']['port'] == fixture.obsolete_port
        assert failed and all(row['upstream']['port'] == fixture.obsolete_port for row in failed)
        assert all(row['error_type'] and 'errno' in row for row in failed)
        assert all(row['pid'] in fixture.process_pids['localapp'] for row in failed)
        before_hash = hashlib.sha256((tmp_path / 'localapp.log').read_bytes()).hexdigest()
        original_process = fixture.processes['localapp']
        downstream_process = fixture.processes['downstream']
        fixture.repair_endpoint(restart=False)
        assert collector.configuration('localapp')['payload']['values']['downstream_port'] == fixture.downstream_port
        assert get_local(fixture.edge_port)[0] == 503
        fixture.repair_endpoint(restart=True)
        assert fixture.processes['localapp'] is not original_process and original_process.poll() == 0
        assert fixture.processes['downstream'] is downstream_process and downstream_process.poll() is None
        assert all(get_local(port)[0] == 200 for port in
            (fixture.edge_port, fixture.localapp_port, fixture.downstream_port))
        events = [json.loads(line) for line in (tmp_path / 'localapp.log').read_text().splitlines()]
        assert any(row.get('event') == 'service_exited' for row in events)
        assert any(row.get('event') == 'service_started' and row['upstream']['port'] == fixture.downstream_port
            for row in events)
        assert before_hash != hashlib.sha256((tmp_path / 'localapp.log').read_bytes()).hexdigest()
        assert failed[0] in events  # Applying repair must not overwrite the fault evidence.
    assert fixture.cleanup_result == {'remaining_listener_ports': [], 'cleanup_errors': []}


@pytest.mark.integration
def test_same_business_symptom_can_distinguish_wrong_endpoint_from_stopped_downstream(tmp_path):
    with CompetingFaultFixture('localapp_wrong_endpoint', tmp_path, stop_mode='request') as fixture:
        wrong = get_local(fixture.edge_port, path='/api/availability')
        assert wrong == (503, 'temporarily unavailable')
        assert get_local(fixture.downstream_port, path='/api/availability')[0] == 200
        assert json.loads(fixture.connection_config.read_text())['downstream_port'] != fixture.downstream_port
        fault_log = (tmp_path / 'localapp.log').read_text()
        fixture.reset('downstream_unreachable')
        stopped = get_local(fixture.edge_port, path='/api/availability')
        assert stopped == wrong
        assert json.loads(fixture.connection_config.read_text())['downstream_port'] == fixture.downstream_port
        assert fixture.processes['downstream'].poll() == 0
        events = [json.loads(line) for line in (tmp_path / 'downstream.log').read_text().splitlines()]
        assert any(row.get('event') == 'shutdown_requested' for row in events)
        assert 'upstream connection failed' in fault_log
    assert fixture.cleanup_result == {'remaining_listener_ports': [], 'cleanup_errors': []}
