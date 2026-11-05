import json
import psutil
import pytest

from scripts.competing_hypothesis_fixture import CompetingFaultFixture, UNAVAILABLE_BODY
from src.probe.windows.collector import WindowsCollector
from src.probe.windows.config import DependencyConfig, ProbeConfig, ServiceConfig


@pytest.mark.parametrize('stop_mode', ['terminate', 'request'])
def test_downstream_stop_evidence_is_readable_and_reset_does_not_reuse_it(tmp_path, stop_mode):
    from src.probe.evidence import validate_observation_window, EvidenceValidationError
    from scripts.verify_competing_hypothesis_scenario import assert_answer_isolated

    with CompetingFaultFixture('normal', tmp_path, stop_mode=stop_mode) as fixture:
        collector = WindowsCollector(ProbeConfig(
            target_id='competing-fault-test', gateway_url='ws://127.0.0.1:1/probe/ws', token_file=None,
            services={'downstream': ServiceConfig(service_name='', kind='process',
                process_names=(psutil.Process().name(),), process_args=fixture.process_identity('downstream'),
                text_logs=(str(tmp_path / 'downstream.log'),))}))
        boundary = fixture.reset('downstream_unreachable')
        process = fixture.processes['downstream']
        assert process.poll() is not None
        raw = collector.text_logs('downstream', str(tmp_path / 'downstream.log'), lines=100)
        validate_observation_window(raw, boundary)
        events = [json.loads(line) for line in raw['payload']['lines']]
        assert_answer_isolated(raw, 'private-answer-canary')
        if stop_mode == 'request':
            event, = events
            assert event['event'] == 'shutdown_requested'
            assert event['pid'] in fixture.process_pids['downstream'] and event['at'] >= boundary
            assert event['stop_request']['initiator'] == 'unknown'
        else:
            assert events == []
        assert collector.processes('downstream')['payload']['matched_count'] == 0
        next_boundary = fixture.reset('normal')
        with pytest.raises(EvidenceValidationError):
            validate_observation_window(raw, next_boundary)
        assert not (tmp_path / 'downstream.log').read_text()
        assert not (tmp_path / 'downstream.stop').exists()
        assert fixture.observe_controller_side()['downstream']['http_status'] == 200
    assert fixture.cleanup_result == {'remaining_listener_ports': [], 'cleanup_errors': []}


def test_stop_mode_rejects_unknown_values():
    with pytest.raises(ValueError, match='stop mode'):
        CompetingFaultFixture('normal', stop_mode='unknown')


def test_same_downstream_outage_has_distinct_real_application_cause_logs(tmp_path):
    from src.probe.evidence import validate_observation_window, EvidenceValidationError
    with CompetingFaultFixture('normal', tmp_path, stop_mode='request') as fixture:
        collector = WindowsCollector(ProbeConfig(
            target_id='competing-fault-test', gateway_url='ws://127.0.0.1:1/probe/ws', token_file=None,
            services={'downstream': ServiceConfig(service_name='', kind='process',
                process_names=(psutil.Process().name(),), process_args=fixture.process_identity('downstream'),
                text_logs=(str(tmp_path / 'downstream.log'),))}))
        observations = []
        for fault in ('downstream_unreachable', 'downstream_bind_failed'):
            boundary = fixture.reset(fault)
            controller = fixture.observe_controller_side()
            raw = collector.text_logs('downstream', str(tmp_path / 'downstream.log'), lines=100)
            validate_observation_window(raw, boundary)
            event, = [json.loads(line) for line in raw['payload']['lines']]
            assert event['at'] >= boundary and event['pid'] in fixture.process_pids['downstream']
            assert controller['edge']['body'] == UNAVAILABLE_BODY.decode() and controller['edge']['http_status'] == 503
            assert controller['downstream']['tcp'] == 'failed'
            assert not collector.ports(local_port=fixture.downstream_port, listening_only=True)['payload']['ports']
            assert collector.processes('downstream')['payload']['matched_count'] == 0
            observations.append(raw)
            if fault == 'downstream_bind_failed':
                assert event['error'] == 'bind_failed' and event['errno'] and event['port'] == fixture.downstream_port
                assert fixture.processes['downstream'].returncode != 0
            else:
                assert event['event'] == 'shutdown_requested' and fixture.processes['downstream'].returncode == 0
        boundary = fixture.reset('normal')
        for raw in observations:
            with pytest.raises(EvidenceValidationError):
                validate_observation_window(raw, boundary)
        assert all(fixture.observe_controller_side()[name]['http_status'] == 200
            for name in ('edge', 'localapp', 'downstream'))
    assert fixture.cleanup_result == {'remaining_listener_ports': [], 'cleanup_errors': []}


@pytest.mark.parametrize('mutation', [None, 'zero_exit', 'wrong_error', 'wrong_port', 'unknown_errno', 'wrong_pid'])
def test_bind_failure_must_match_real_failure_and_independent_process_identity(tmp_path, monkeypatch, mutation):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from scripts import competing_hypothesis_fixture as module
    fixture = CompetingFaultFixture('normal', tmp_path)
    event = {'pid': 202, 'error': 'bind_failed', 'errno': 10048, 'port': fixture.downstream_port}
    if mutation == 'wrong_error': event['error'] = 'unrelated_failure'
    if mutation == 'wrong_port': event['port'] += 1
    if mutation == 'unknown_errno': event['errno'] = 99999
    if mutation == 'wrong_pid': event['pid'] = 303
    process = Mock(pid=101, returncode=0 if mutation == 'zero_exit' else 1)
    process.poll.side_effect = [None, process.returncode]
    def launch(*args, **kwargs):
        (tmp_path / 'downstream.log').write_text(json.dumps(event), encoding='utf-8')
        return process
    monkeypatch.setattr(module.subprocess, 'Popen', launch)
    monkeypatch.setattr(module.psutil, 'Process', lambda pid: SimpleNamespace(
        children=lambda recursive: [SimpleNamespace(pid=202)]))
    try:
        if mutation:
            with pytest.raises(RuntimeError, match='expected application bind failure'):
                fixture._start('downstream', expect_bind_failure=True)
        else:
            fixture._start('downstream', expect_bind_failure=True)
            assert fixture.process_pids['downstream'] == {101, 202}
    finally:
        for handle in fixture._handles:
            handle.close()


@pytest.mark.parametrize('failure', ['timeout', 'nonzero_exit'])
def test_failed_stop_request_cannot_silently_become_a_terminate_sample(tmp_path, monkeypatch, failure):
    import subprocess
    from unittest.mock import Mock
    from scripts import competing_hypothesis_fixture as module

    fixture = CompetingFaultFixture('normal', tmp_path, stop_mode='request')
    process = Mock(returncode=1)
    if failure == 'timeout':
        process.wait.side_effect = subprocess.TimeoutExpired('owned test process', 5)
    monkeypatch.setattr(fixture, '_start', lambda name: fixture.processes.update({name: process}))
    force_stop = Mock()
    monkeypatch.setattr(module, 'stop', force_stop)
    with pytest.raises(subprocess.TimeoutExpired if failure == 'timeout' else RuntimeError):
        fixture.reset('downstream_unreachable')
    assert (tmp_path / 'downstream.stop').exists()
    force_stop.assert_not_called()


def probe_observations(fixture):
    config = ProbeConfig(
        target_id="competing-fault-test",
        gateway_url="ws://127.0.0.1:1/probe/ws",
        token_file=None,
        services={"localapp": ServiceConfig(service_name="", kind="process")},
        dependencies={
            "edge": DependencyConfig("127.0.0.1", fixture.edge_port, "http"),
            "downstream": DependencyConfig("127.0.0.1", fixture.downstream_port),
        },
    )
    collector = WindowsCollector(config)
    return {
        "edge": collector.dependency_probe("edge"),
        "downstream": collector.dependency_probe("downstream"),
        "localapp_port": collector.ports(local_port=fixture.localapp_port, listening_only=True),
    }


def test_competing_faults_have_same_edge_symptom_and_distinct_controller_checks():
    observations = {}
    cleanup = []
    for fault in ("localapp_unavailable", "downstream_unreachable"):
        fixture = CompetingFaultFixture(fault)
        with fixture:
            observations[fault] = fixture.observe_controller_side()
        cleanup.append(fixture.cleanup_result)

    localapp_fault = observations["localapp_unavailable"]
    downstream_fault = observations["downstream_unreachable"]
    assert (localapp_fault["edge"]["http_status"], localapp_fault["edge"]["body"]) == (503, UNAVAILABLE_BODY.decode())
    assert (downstream_fault["edge"]["http_status"], downstream_fault["edge"]["body"]) == (503, UNAVAILABLE_BODY.decode())
    assert localapp_fault["localapp"]["tcp"] == "failed"
    assert localapp_fault["downstream"]["http_status"] == 200
    assert downstream_fault["localapp"]["http_status"] == 503
    assert downstream_fault["downstream"]["tcp"] == "failed"
    assert localapp_fault["source"] == downstream_fault["source"] == "controller_fixture_check_not_agent_evidence"
    assert cleanup == [{"remaining_listener_ports": [], "cleanup_errors": []}] * 2


def test_existing_probe_collector_distinguishes_fault_conditions_without_answer_leak():
    results = {}
    for fault in ("localapp_unavailable", "downstream_unreachable"):
        with CompetingFaultFixture(fault) as fixture:
            results[fault] = probe_observations(fixture)

    localapp_fault = results["localapp_unavailable"]
    downstream_fault = results["downstream_unreachable"]
    for result in (localapp_fault, downstream_fault):
        assert result["edge"]["payload"]["http"]["status"] == 503
        assert "hidden_fault" not in json.dumps(result)
        assert all(item["target_id"] == "competing-fault-test" for item in result.values())
    assert localapp_fault["localapp_port"]["payload"]["ports"] == []
    assert localapp_fault["downstream"]["payload"]["tcp"] == "ok"
    assert downstream_fault["localapp_port"]["payload"]["ports"]
    assert downstream_fault["downstream"]["payload"]["tcp"] == "failed"


def test_independent_process_identity_and_recovery_use_the_same_topology():
    with CompetingFaultFixture("localapp_unavailable") as fixture:
        collector = WindowsCollector(ProbeConfig(
            target_id="competing-fault-test", gateway_url="ws://127.0.0.1:1/probe/ws", token_file=None,
            services={name: ServiceConfig(service_name="", kind="process",
                process_names=(psutil.Process().name(),), process_args=fixture.process_identity(name))
                for name in ("edge", "localapp", "downstream")}))
        assert collector.processes("localapp")["payload"]["matched_count"] == 0
        assert collector.processes("downstream")["payload"]["matched_count"] >= 1
        edge_pids = {row["pid"] for row in collector.processes("edge")["payload"]["processes"]}
        assert edge_pids
        fixture.reset("downstream_unreachable")
        app_pids = {row["pid"] for row in collector.processes("localapp")["payload"]["processes"]}
        assert app_pids and app_pids.isdisjoint(edge_pids)
        assert collector.processes("downstream")["payload"]["matched_count"] == 0
        assert {row["pid"] for row in collector.processes("edge")["payload"]["processes"]} == edge_pids
        fixture.reset("normal")
        assert all(row["http_status"] == 200 for name, row in fixture.observe_controller_side().items()
                   if name in {"edge", "localapp", "downstream"})
    assert fixture.cleanup_result == {"remaining_listener_ports": [], "cleanup_errors": []}
    assert all(process.poll() is not None for process in fixture.owned)
