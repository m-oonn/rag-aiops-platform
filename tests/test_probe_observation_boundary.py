import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from langchain_core.tools import StructuredTool
from scripts.verify_probe_observation_boundary import verify_boundary_rounds
from scripts import verify_windows_local_faults as controller
from src.probe.protocol import evidence, utc_now


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [None, 'reset', 'stale_log', 'transport', 'empty_log', 'wrong_target', 'next_round_transport'])
async def test_boundary_rounds_use_reset_and_preserve_failed_trace(tmp_path, failure):
    log = tmp_path / 'app.log'
    log.write_text(json.dumps({'at': utc_now(), 'status': 200}) + '\n')
    resets = []
    dependency_calls = 0
    async def dependency(dependency: str):
        nonlocal dependency_calls
        dependency_calls += 1
        if failure == 'next_round_transport' and dependency_calls == 3:
            raise RuntimeError('next round unavailable')
        return evidence(target_id='t', operation='dependency_probe', payload={'dependency': dependency})
    async def text(service: str, path: str, lines: int):
        if failure == 'transport':
            raise RuntimeError('transport unavailable')
        return evidence(target_id='other' if failure == 'wrong_target' else 't', operation='text_logs', payload={'lines': log.read_text().splitlines()})
    tools = {name: StructuredTool.from_function(coroutine=fn, name=name, description='test')
        for name, fn in [('probe_dependency_probe', dependency), ('probe_text_log', text)]}
    async def reset(case):
        resets.append(case)
        if failure == 'reset':
            raise RuntimeError('reset failed')
        if failure != 'stale_log':
            log.write_text('' if failure == 'empty_log' else json.dumps({'at': utc_now(), 'status': 200}) + '\n')
    output = tmp_path / 'boundary'
    if failure:
        with pytest.raises((RuntimeError, ValueError, AssertionError)):
            await verify_boundary_rounds(tools, 't', output, log, reset)
    else:
        result = await verify_boundary_rounds(tools, 't', output, log, reset)
        assert result['rounds'] == 2 and result['evidence_count'] == 6
    report = json.loads((output / 'report.json').read_text())
    assert report['status'] == ('failed' if failure else 'passed')
    assert report['ended_at'] and report['model_calls'] == 0
    if failure == 'next_round_transport':
        assert len(report['rounds']) == 1 and report['rounds'][0]['status'] == 'passed'
    assert len(resets) == (0 if failure in {'transport', 'wrong_target'} else 1 if failure else 2)
    trace = json.loads((output / 'round-0/tool_trace.json').read_text())
    assert trace[0]['status'] == 'failed' and trace[0]['validated_live_evidence'] is False
    if failure not in {'transport', 'wrong_target'}:
        assert trace[0]['result'] and (output / 'round-0/pre-reset.log').exists()


@pytest.mark.parametrize('listener_failure', [False, True])
def test_cleanup_continues_after_stop_failure_and_never_claims_released_when_unknown(monkeypatch, listener_failure):
    processes = [SimpleNamespace(pid=i, poll=Mock(return_value=0 if i == 1 else None)) for i in [1, 2, 3]]
    calls = []
    def stop(process):
        calls.append(process.pid)
        if process.pid == 3:
            raise OSError('stop failed')
    monkeypatch.setattr(controller, 'stop', stop)
    def listeners(ports):
        if listener_failure:
            raise OSError('cannot inspect')
        return [{'port': 12345, 'pid': 3}]
    monkeypatch.setattr(controller, 'listening_rows', listeners)
    result = controller.cleanup_owned(processes, [12345])
    assert calls == [3, 2, 1]
    assert result['owned_processes_stopped'] is False and result['ports_released'] is False
    assert len(result['cleanup_errors']) == (2 if listener_failure else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', [None, 'http_status', 'body', 'dependency', 'downstream',
    'log_status', 'log_detail', 'foreign_pid', 'unverified_reset'])
async def test_fault_windows_match_current_controller_facts_and_processes(tmp_path, failure):
    log = tmp_path / 'app.log'
    log.write_text(json.dumps({'at': utc_now(), 'pid': 10, 'status': 200, 'detail': 'healthy'}) + '\n')
    current = {'case': 'normal', 'index': -1}
    resets = []
    scenarios = ('normal', 'downstream_unreachable', 'application_error') * 4 + ('normal',)
    statuses = {'normal': 200, 'downstream_unreachable': 503, 'application_error': 500}
    details = {'normal': 'healthy', 'downstream_unreachable': 'upstream connection failed', 'application_error': 'request failed'}
    bodies = {'normal': 'healthy', 'downstream_unreachable': 'temporarily unavailable', 'application_error': 'request failed'}
    async def dependency(dependency: str):
        case = current['case']
        status = statuses[case] if dependency == 'localapp' else None if case == 'downstream_unreachable' else 200
        body = bodies[case] if dependency == 'localapp' else 'healthy'
        if current['index'] == 2:
            if failure == 'http_status' and dependency == 'localapp':
                status = 200
            if failure == 'downstream' and dependency == 'downstream':
                status = None
            if failure == 'body':
                body = 'wrong response'
        return evidence(target_id='t', operation='dependency_probe', payload={
            'dependency': 'other' if failure == 'dependency' and current['index'] == 2 else dependency,
            'tcp': 'failed' if status is None else 'ok', 'http': {'status': status, 'body_prefix': body}})
    async def text(service: str, path: str, lines: int):
        return evidence(target_id='t', operation='text_logs', payload={'lines': log.read_text().splitlines()})
    tools = {name: StructuredTool.from_function(coroutine=fn, name=name, description='test')
        for name, fn in [('probe_dependency_probe', dependency), ('probe_text_log', text)]}
    async def reset(case):
        resets.append(case)
        current.update(case=case, index=len(resets) - 1)
        pid = 100 + len(resets)
        row = {'at': utc_now(), 'pid': pid, 'status': statuses[case], 'detail': details[case]}
        if len(resets) == 3:
            if failure == 'log_status': row['status'] = 200
            if failure == 'log_detail': row['detail'] = 'healthy'
            if failure == 'foreign_pid': row['pid'] = pid - 1
        log.write_text(json.dumps(row) + '\n')
        return {'case': case, 'passed': not (failure == 'unverified_reset' and len(resets) == 3),
            'app': {'http_status': statuses[case], 'body': bodies[case]},
            'downstream': {'http_status': None if case == 'downstream_unreachable' else 200, 'body': 'healthy'},
            'app_pids': [pid], 'downstream_pids': [] if case == 'downstream_unreachable' else [pid + 100]}
    output = tmp_path / 'boundary'
    if failure:
        with pytest.raises(AssertionError):
            await verify_boundary_rounds(tools, 't', output, log, reset, scenarios)
    else:
        result = await verify_boundary_rounds(tools, 't', output, log, reset, scenarios)
        assert result['rounds'] == 13 and result['evidence_count'] == 52
    report = json.loads((output / 'report.json').read_text())
    assert report['status'] == ('failed' if failure else 'passed')
    assert resets == list(scenarios[:3] if failure else scenarios)
    assert [row['status'] for row in report['rounds']] == (['passed', 'passed', 'failed'] if failure else ['passed'] * 13)
    assert all(row['old_log_rejected'] and row['old_observation_rejected'] for row in report['rounds'])
    assert report['model_calls'] == 0 and report['ended_at']
