from types import SimpleNamespace
from unittest.mock import Mock
from pathlib import Path
import json
import sqlite3
import subprocess
import sys
import pytest

from scripts import verify_windows_local_faults as module


def test_candidate_opportunity_profile_is_explicit_and_does_not_name_a_fault():
    assert module.symptom_text('neutral') == (
        '请只读检查配置中的 localapp 是否可用；自行核实入口、相关依赖和允许的日志，说明证据与无法确认的部分。'
    )
    prompt = module.symptom_text('candidate-opportunity')
    assert '仍合理的候选' in prompt and '具体、可执行且能区分解释的检查' in prompt
    assert '遇到可靠相反证据时改查其他解释' in prompt
    assert 'downstream_unreachable' not in prompt and 'application_config_error' not in prompt
    with pytest.raises(ValueError, match='unknown symptom profile'):
        module.symptom_text('unknown')


@pytest.mark.asyncio
@pytest.mark.parametrize('profile', ['neutral', 'candidate-opportunity'])
async def test_model_runner_passes_selected_symptom_profile_to_child(tmp_path, profile):
    captured = {}

    def launch(args, name):
        captured['args'] = args
        raise RuntimeError('launch intercepted')

    with pytest.raises(RuntimeError, match='launch intercepted'):
        await module.evaluate_model_case(tmp_path, 'downstream_unreachable', launch,
            symptom_profile=profile)

    args = captured['args']
    symptom_path = Path(args[args.index('--symptom-file') + 1])
    assert symptom_path.read_text(encoding='utf-8') == module.symptom_text(profile)


def test_real_disposable_cases_are_independently_checked_and_recovered(tmp_path):
    ports = [module.free_port()]
    while len(ports) < 2:
        port = module.free_port()
        if port not in ports:
            ports.append(port)
    app_port, dep_port = ports
    mode, dep_mode, log = tmp_path / 'app.mode', tmp_path / 'dep.mode', tmp_path / 'app.log'
    mode.write_text('normal')
    dep_mode.write_text('normal')
    owned = []
    def launch(port, mode_file, downstream=None, wait=True):
        args = [sys.executable, str(Path(module.__file__).resolve()), '--serve', str(port),
            '--mode-file', str(mode_file), '--log', str(log)]
        if downstream is not None:
            args += ['--downstream', str(downstream)]
        process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        owned.append(process)
        if wait:
            module.wait_listener(port, process)
        return process
    def verify(case, app, dep, blocker=None):
        return module.verify_case_state(tmp_path, case, app, dep, app_port, dep_port, log, blocker)
    try:
        dep = launch(dep_port, dep_mode)
        app = launch(app_port, mode, dep_port)
        assert verify('normal', app, dep)['passed']
        mode.write_text('application_error')
        assert verify('application_error', app, dep)['passed']
        assert verify('missing_evidence', app, dep)['passed']
        mode.write_text('normal')
        module.stop(dep)
        assert verify('downstream_unreachable', app, dep)['passed']
        unavailable_response = module.get_local(app_port)
        dep = launch(dep_port, dep_mode)
        assert verify('normal', app, dep)['passed']
        mode.write_text(json.dumps({'max_attempts': 'invalid'}))
        assert verify('application_config_error', app, dep)['passed']
        assert module.get_local(app_port) == unavailable_response == (503, 'temporarily unavailable')
        assert module.get_local(dep_port) == (200, 'healthy')
        with pytest.raises(RuntimeError, match='state verification failed'):
            verify('downstream_unreachable', app, dep)
        # Valid configuration takes the normal application path again.
        mode.write_text(json.dumps({'max_attempts': 3}))
        assert verify('normal', app, dep)['passed']
        mode.write_text('normal')
        module.stop(app)
        assert verify('application_exit', app, dep)['passed']
        blocker = launch(app_port, dep_mode)
        app = launch(app_port, mode, dep_port, wait=False)
        assert app.wait(timeout=10) != 0
        assert verify('port_conflict', app, dep, blocker)['passed']
        module.stop(blocker)
        app = launch(app_port, mode, dep_port)
        assert verify('normal', app, dep)['passed']
        # An unsuccessful injection must never proceed to a model run.
        with pytest.raises(RuntimeError, match='state verification failed'):
            verify('downstream_unreachable', app, dep)
    finally:
        for process in reversed(owned):
            module.stop(process)
    assert all(p.poll() is not None for p in owned)
    assert module.listening_rows(ports) == []
    rows = [json.loads(line) for line in (tmp_path / 'controller-observations.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(rows) == 12 and rows[-1]['passed'] is False
    assert all(row['agent_evidence'] is False for row in rows)


@pytest.mark.parametrize('mutation', ['wrong_body', 'missing_body', 'wrong_log', 'wrong_pid', 'wrong_error_type'])
def test_config_error_requires_generic_response_and_current_application_log(tmp_path, monkeypatch, mutation):
    app = SimpleNamespace(pid=111, poll=lambda: None)
    dep = SimpleNamespace(pid=222, poll=lambda: None)
    body = 'invalid configuration' if mutation == 'wrong_body' else 'temporarily unavailable'
    def get_local(port):
        if port == 23001 and mutation == 'missing_body':
            raise OSError('test application unavailable')
        return (503, body) if port == 23001 else (200, 'healthy')
    monkeypatch.setattr(module, 'get_local', get_local)
    monkeypatch.setattr(module, 'listening_rows', lambda ports: [{'port': 23001, 'pid': 111}, {'port': 23002, 'pid': 222}])
    monkeypatch.setattr(module.psutil, 'Process', lambda pid: SimpleNamespace(children=lambda **kw: []))
    log = tmp_path / 'app.log'
    log.write_text(json.dumps({'pid': 999 if mutation == 'wrong_pid' else 111, 'status': 503,
        'detail': 'request failed' if mutation == 'wrong_log' else 'invalid max_attempts configuration',
        'error_type': 'TypeError' if mutation == 'wrong_error_type' else 'ValueError'}))
    with pytest.raises(RuntimeError, match='state verification failed'):
        module.verify_case_state(tmp_path, 'application_config_error', app, dep, 23001, 23002, log)
    row = json.loads((tmp_path / 'controller-observations.jsonl').read_text())
    assert not row['passed']
    assert not row['checks']['generic_response' if mutation in {'wrong_body', 'missing_body'} else 'application_log']


@pytest.mark.asyncio
async def test_failed_injection_prevents_model_start_and_preserves_failure(tmp_path, monkeypatch):
    changes = []
    async def set_case(case):
        changes.append(case)
        if case != 'normal':
            raise RuntimeError('state verification failed')
    model = Mock()
    monkeypatch.setattr(module, 'evaluate_model_case', model)
    with pytest.raises(RuntimeError, match='state verification failed'):
        await module.evaluate_blind_cases(tmp_path, Mock(), set_case, suite=['application_error'])
    model.assert_not_called()
    controller = json.loads((tmp_path / 'blind-controller.json').read_text(encoding='utf-8'))
    assert changes == ['application_error', 'normal']
    assert controller['failure']['exception_type'] == 'RuntimeError'
    assert controller['injections'] == []
    assert controller['recovery'] == 'normal_restored'


def test_foreign_listener_fails_even_when_http_is_healthy(tmp_path, monkeypatch):
    app = SimpleNamespace(pid=111, poll=lambda: None)
    dep = SimpleNamespace(pid=222, poll=lambda: None)
    monkeypatch.setattr(module, 'get_local', lambda port: (200, 'healthy'))
    monkeypatch.setattr(module, 'listening_rows', lambda ports: [
        {'port': 23001, 'pid': 999}, {'port': 23002, 'pid': 222}])
    monkeypatch.setattr(module.psutil, 'Process', lambda pid: SimpleNamespace(children=lambda **kwargs: []))
    with pytest.raises(RuntimeError, match='state verification failed'):
        module.verify_case_state(tmp_path, 'normal', app, dep, 23001, 23002, tmp_path / 'app.log')
    snapshot = json.loads((tmp_path / 'controller-observations.jsonl').read_text(encoding='utf-8'))
    assert snapshot['checks']['http_states']
    assert not snapshot['checks']['app_listener']


@pytest.mark.asyncio
async def test_recovery_failure_is_recorded_without_losing_investigation_failure(tmp_path, monkeypatch):
    async def set_case(case):
        if case == 'normal':
            raise RuntimeError('recovery failed')
    async def fail(*args, **kwargs):
        raise ValueError('investigation failed')
    monkeypatch.setattr(module, 'evaluate_model_case', fail)
    with pytest.raises(RuntimeError, match='recovery failed'):
        await module.evaluate_blind_cases(tmp_path, Mock(), set_case, suite=['application_error'])
    controller = json.loads((tmp_path / 'blind-controller.json').read_text(encoding='utf-8'))
    assert controller['failure']['exception_type'] == 'ValueError'
    assert controller['recovery'] == 'failed'
    assert controller['recovery_error'] == 'RuntimeError'


def test_stop_waits_for_owned_child_before_launcher(monkeypatch):
    child = Mock()
    parent = Mock()
    parent.poll.return_value = None
    monkeypatch.setattr(module.psutil, 'Process', lambda pid: SimpleNamespace(children=lambda **_: [child]))
    wait = Mock(side_effect=[([child], []), ([], [])])
    monkeypatch.setattr(module.psutil, 'wait_procs', wait)
    module.stop(parent)
    child.terminate.assert_called_once()
    parent.terminate.assert_called_once()
    parent.wait.assert_called_once_with(timeout=5)
    child.kill.assert_not_called()


def test_listener_check_excludes_time_wait_and_unrelated_ports(monkeypatch):
    def conn(port, state, pid):
        return SimpleNamespace(status=state, pid=pid, laddr=SimpleNamespace(port=port))
    monkeypatch.setattr(module.psutil, 'net_connections', lambda **_: [
        conn(23000, 'TIME_WAIT', None), conn(23001, 'LISTEN', 71), conn(23002, 'LISTEN', 72)])
    assert module.listening_rows([23000, 23001]) == [{'port': 23001, 'pid': 71}]


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['none', 'process', 'budget', 'unknown_cost', 'lost_previous', 'missing_complete', 'isolation_lost'])
@pytest.mark.parametrize('group', [None, 'G00', 'G10', 'G01', 'G11'])
@pytest.mark.parametrize('limit', [5, 10])
async def test_model_runner_inherits_budget_and_fails_closed(tmp_path, monkeypatch, failure, group, limit):
    from scripts import evaluation_record
    def audit(*args, **kwargs):
        import hashlib
        symptom_file = next(Path(args[0]).parent.glob('symptom-*.txt'))
        return {'passed': True, 'this_run_cost': {'requests': 1}, 'comparison_config': {
            'symptom_sha256': hashlib.sha256(symptom_file.read_bytes()).hexdigest()}}
    monkeypatch.setattr(evaluation_record, 'audit_evaluation', audit)
    previous = {'limit_cny': 5, 'reserved_cny': 0.4, 'requests': [
        {'number': 1, 'reserved_cny': 0.4, 'http_status': 200, 'usage': {'prompt_tokens': 3, 'completion_tokens': 1}}]}
    prior = tmp_path / 'prior.json'
    prior.write_text(json.dumps(previous))
    launches = []
    def launch(args, name):
        launches.append(args)
        assert '--run-model' in args and args[args.index('--previous-cost') + 1] == str(prior)
        symptom = Path(args[args.index('--symptom-file') + 1]).read_text(encoding='utf-8')
        assert symptom == '请只读检查配置中的 localapp 是否可用；自行核实入口、相关依赖和允许的日志，说明证据与无法确认的部分。'
        assert 'downstream_unreachable' not in ' '.join(args)
        assert float(args[args.index('--budget-limit-cny') + 1]) == limit
        if group:
            assert args[args.index('--mechanism-group') + 1] == group
        assert args[args.index('--knowledge-mcp-url') + 1] == 'http://127.0.0.1:9200/mcp'
        output = Path(args[args.index('--output-dir') + 1])
        output.mkdir()
        assert 'downstream_unreachable' not in str(output)
        summary = {'budget_stopped': failure == 'budget', 'execution_error': None,
            'error_events': 0, 'has_final_report': True, 'report_kind': 'unlocated',
            'mechanism_group': group, 'mechanism_audit': {'passed': True}}
        if group:
            from scripts.evaluate_windows_probe import MECHANISM_GROUPS
            protection, trigger = MECHANISM_GROUPS[group]
            config = {'hypothesis_protection': protection, 'contradiction_trigger': trigger, 'protection_steps': 2}
            summary['mechanism_audit'].update(actual_config=config, expected_config=config)
        (output / 'summary.json').write_text(json.dumps(summary))
        (output / 'events.json').write_text(json.dumps([{'type': 'complete', 'response': 'fixture report'}]))
        if failure == 'missing_complete':
            (output / 'events.json').write_text('[]')
        row = {'number': 2, 'reserved_cny': 0.2, 'http_status': 200, 'usage': {'prompt_tokens': 4, 'completion_tokens': 1}}
        cost = {'limit_cny': limit, 'reserved_cny': 0.6, 'requests': [*previous['requests'], row]}
        if failure == 'unknown_cost':
            row.pop('usage')
        if failure == 'lost_previous':
            cost = {'limit_cny': 5, 'reserved_cny': 0.2, 'requests': [{**row, 'number': 1}]}
        (output / 'cost.json').write_text(json.dumps(cost))
        return SimpleNamespace(wait=lambda: 1 if failure == 'process' else 0)
    if failure in {'none', 'missing_complete'}:
        result = await module.evaluate_model_case(tmp_path, 'downstream_unreachable', launch, prior,
            knowledge_url='http://127.0.0.1:9200/mcp', mechanism_group=group, budget_limit_cny=limit)
        assert result['reserved_cny'] == 0.6 and result['cumulative_requests'] == 2
        assert result['workflow_completed'] is (failure == 'none')
        if failure == 'missing_complete':
            assert result['status'] == 'failed'
        assert not result['diagnostic_correctness_verified']
    else:
        with pytest.raises((RuntimeError, ValueError)):
            await module.evaluate_model_case(tmp_path, 'downstream_unreachable', launch, prior,
                knowledge_url='http://127.0.0.1:9200/mcp', mechanism_group=group, budget_limit_cny=limit,
                isolate_history=failure == 'isolation_lost')
    assert len(launches) == 1


@pytest.mark.asyncio
async def test_uncertain_prior_cost_prevents_starting_another_model_process(tmp_path):
    prior = tmp_path / 'cost.json'
    prior.write_text(json.dumps({'limit_cny': 5, 'reserved_cny': 0.4,
        'requests': [{'number': 1, 'reserved_cny': 0.4, 'status': 'reserved'}]}))
    launch = Mock()
    with pytest.raises(RuntimeError, match='uncertain cost'):
        await module.evaluate_model_case(tmp_path, 'downstream_unreachable', launch, prior)
    launch.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('mutation', ['wrong_group', 'failed', 'wrong_config', 'missing_config'])
async def test_controller_rejects_mislabeled_or_unverified_mechanism_result(tmp_path, mutation):
    def launch(args, name):
        output = Path(args[args.index('--output-dir') + 1])
        output.mkdir()
        config = {'hypothesis_protection': False, 'contradiction_trigger': False, 'protection_steps': 2}
        audit = {'passed': mutation != 'failed', 'actual_config': dict(config), 'expected_config': dict(config)}
        if mutation == 'wrong_config':
            audit['actual_config']['hypothesis_protection'] = True
        if mutation == 'missing_config':
            audit.pop('actual_config')
        (output / 'summary.json').write_text(json.dumps({
            'mechanism_group': 'G11' if mutation == 'wrong_group' else 'G00', 'mechanism_audit': audit}))
        return SimpleNamespace(wait=lambda: 0)
    with pytest.raises(RuntimeError, match='mechanism audit failed'):
        await module.evaluate_model_case(tmp_path, 'normal', launch, mechanism_group='G00')


@pytest.mark.asyncio
@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('limit', [5, 10])
async def test_blind_controller_randomizes_order_preserves_cost_and_restores(tmp_path, monkeypatch, reverse, limit):
    changes, seen = [], []
    reset_times = []
    class Shuffle:
        def shuffle(self, rows):
            if reverse:
                rows.reverse()
    monkeypatch.setattr(module.secrets, 'SystemRandom', Shuffle)
    async def set_case(case):
        from scripts.evaluation_record import utc_now
        reset_times.append(utc_now())
        changes.append(case)
    async def run(out, case, launch, previous, knowledge_url=None, budget_limit_cny=5,
                  isolate_history=False, observation_not_before=None):
        assert knowledge_url == 'http://127.0.0.1:9200/mcp'
        assert budget_limit_cny == limit
        injection = json.loads((tmp_path / 'blind-controller.json').read_text())['injections'][-1]
        assert isolate_history is True
        assert observation_not_before == injection['observation_not_before']
        assert observation_not_before <= injection['injected_at']
        assert observation_not_before <= reset_times[-1]
        seen.append((case, previous))
        return {'status': 'passed', 'workflow_completed': True,
            'cost_file': str(tmp_path / (str(len(seen)) + '.json'))}
    monkeypatch.setattr(module, 'evaluate_model_case', run)
    await module.evaluate_blind_cases(tmp_path, Mock(), set_case, knowledge_url='http://127.0.0.1:9200/mcp',
        budget_limit_cny=limit)
    assert seen[0][0] == ('downstream_unreachable' if reverse else 'normal')
    assert {row[0] for row in seen} == {'normal', 'downstream_unreachable'}
    assert seen[0][1] is None and seen[1][1] == tmp_path / '1.json'
    assert changes == [seen[0][0], seen[1][0], 'normal']
    assert reset_times[0] <= reset_times[1]


@pytest.mark.asyncio
async def test_blind_controller_forwards_per_run_cost_cap(tmp_path, monkeypatch):
    calls = []

    async def set_case(case):
        return None

    async def run(*args, **kwargs):
        calls.append(kwargs)
        return {'status': 'passed', 'workflow_completed': True,
            'cost_file': str(tmp_path / 'cost.json')}

    monkeypatch.setattr(module, 'evaluate_model_case', run)
    await module.evaluate_blind_cases(tmp_path, Mock(), set_case, suite=['downstream_unreachable'],
        run_budget_cny=0.25)

    assert len(calls) == 1
    assert calls[0]['run_budget_cny'] == 0.25


@pytest.mark.asyncio
@pytest.mark.parametrize('isolate,cap', [(False, None), (True, None), (False, 0.1)])
async def test_model_child_history_isolation_is_independent_of_money_cap(tmp_path, isolate, cap):
    boundary = '2026-10-29T00:00:00+00:00'
    captured = []
    def launch(args, name):
        captured.append(args)
        assert ('--isolate-history' in args) is (isolate or cap is not None)
        assert args[args.index('--observation-not-before') + 1] == boundary
        assert ('--run-budget-cny' in args) is (cap is not None)
        raise RuntimeError('offline launch intercepted')
    with pytest.raises(RuntimeError, match='offline launch intercepted'):
        await module.evaluate_model_case(tmp_path, 'downstream_unreachable', launch,
            isolate_history=isolate, run_budget_cny=cap, observation_not_before=boundary)
    assert len(captured) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('status,completed', [('failed', True), ('passed', False)])
async def test_blind_controller_stops_on_returned_failed_gates_and_keeps_result(tmp_path, monkeypatch, status, completed):
    changes, calls = [], []
    async def set_case(case):
        changes.append(case)
    async def run(*args, **kwargs):
        calls.append(kwargs)
        return {'status': status, 'workflow_completed': completed, 'cost_file': 'unused'}
    monkeypatch.setattr(module, 'evaluate_model_case', run)
    with pytest.raises(RuntimeError, match='failed mechanical gates'):
        await module.evaluate_blind_cases(tmp_path, Mock(), set_case)
    saved = json.loads((tmp_path / 'blind-controller.json').read_text())
    assert len(calls) == len(saved['results']) == 1
    assert len(changes) == 2 and changes[-1] == 'normal'
    assert saved['results'][0]['status'] == status
    assert saved['failure']['exception_type'] == 'RuntimeError'
    assert saved['recovery'] == 'normal_restored'


@pytest.mark.asyncio
async def test_blind_controller_failure_stops_later_cases_and_restores(tmp_path, monkeypatch):
    changes, calls = [], []
    async def set_case(case):
        changes.append(case)
    async def fail(out, case, launch, previous, knowledge_url=None, **options):
        calls.append(case)
        raise RuntimeError('uncertain cost')
    monkeypatch.setattr(module, 'evaluate_model_case', fail)
    with pytest.raises(RuntimeError, match='uncertain cost'):
        await module.evaluate_blind_cases(tmp_path, Mock(), set_case)
    assert len(calls) == 1
    assert changes == [calls[0], 'normal']


@pytest.mark.parametrize('mutation', [None, 'wrong_target', 'foreign_id', 'invented_quote', 'unsafe_tool'])
def test_mechanical_review_checks_trace_without_claiming_causal_correctness(tmp_path, mutation):
    diagnosis = {'version': 1, 'kind': 'localized_fault', 'target_id': 'windows-local-01',
        'evidence': [{'evidence_id': 'ev-123', 'quote': 'failed'}]}
    trace = [{'tool': 'probe_dependency_probe', 'validated_live_evidence': True,
              'evidence_id': 'ev-123',
              'result': {'payload': {'tcp': 'failed'}}}]
    if mutation == 'wrong_target': diagnosis['target_id'] = 'other'
    if mutation == 'foreign_id': diagnosis['evidence'][0]['evidence_id'] = 'ev-other'
    if mutation == 'invented_quote': diagnosis['evidence'][0]['quote'] = 'database crashed'
    if mutation == 'unsafe_tool': trace[0]['tool'] = 'probe_exec'
    (tmp_path / 'events.json').write_text(json.dumps([{'type': 'evidence', 'evidence_id': 'ev-123'}]))
    (tmp_path / 'tool_trace.json').write_text(json.dumps(trace))
    result = module.review_model_artifacts(tmp_path, 'downstream_unreachable', {'diagnosis': diagnosis})
    assert result['passed'] is (mutation is None)
    assert result['causal_correctness_proven'] is False and result['manual_verdict'] == 'pending'


@pytest.mark.parametrize('failure_location', ['none', 'summary', 'event'])
def test_failure_marker_prevents_workflow_completion_even_with_report(tmp_path, failure_location):
    summary = {'has_final_report': True, 'diagnosis': {'version': 1, 'kind': 'unlocated',
        'target_id': 'windows-local-01'}}
    events = [{'type': 'complete', 'response': '未定位根因：offline fixture'}]
    if failure_location == 'summary':
        summary.update(workflow_completed=False, investigation_failure={'code': 'model_request_failed'})
    if failure_location == 'event':
        events[0]['investigation_failure'] = {'code': 'model_request_failed'}
    (tmp_path / 'events.json').write_text(json.dumps(events))
    (tmp_path / 'tool_trace.json').write_text('[]')
    result = module.review_model_artifacts(tmp_path, 'downstream_unreachable', summary)
    assert result['workflow_status'] == ('completed' if failure_location == 'none' else 'incomplete')
    assert result['causal_correctness_proven'] is False


@pytest.mark.parametrize('mutation', [None, 'missing_row', 'missing_file', 'tampered', 'wrong_id', 'corrupt_db'])
def test_mechanical_review_reads_quotes_from_persisted_evidence(tmp_path, mutation):
    from src.probe.protocol import evidence, raw_hash
    diagnosis = {'version': 1, 'kind': 'localized_fault', 'target_id': 'windows-local-01',
        'evidence': [{'evidence_id': 'ev-log', 'quote': '"status": 503, "body": "upstream"'}]}
    (tmp_path / 'events.json').write_text(json.dumps([{'type': 'evidence', 'evidence_id': 'ev-log'}]))
    (tmp_path / 'tool_trace.json').write_text(json.dumps([
        {'tool': 'probe_text_log', 'validated_live_evidence': True,
         'result': {'payload': {'status': 503, 'body': 'upstream'}}}]))
    raw = tmp_path / 'evidence' / 'ev-log.json'
    raw.parent.mkdir()
    saved = evidence(target_id='windows-local-01', operation='text_logs',
        payload={'status': 503, 'body': 'upstream'})
    digest = raw_hash(saved['payload'])
    if mutation == 'tampered':
        saved['payload']['changed'] = True
    if mutation != 'missing_file':
        raw.write_text(json.dumps(saved, ensure_ascii=False))
    with sqlite3.connect(tmp_path / 'runs.sqlite') as db:
        db.execute('create table aiops_evidence (evidence_id text, raw_ref text, raw_hash text)')
        if mutation != 'missing_row':
            db.execute('insert into aiops_evidence values (?, ?, ?)',
                ('ev-other' if mutation == 'wrong_id' else 'ev-log', str(raw), digest))
        db.commit()
    if mutation == 'corrupt_db':
        (tmp_path / 'runs.sqlite').write_bytes(b'not a database')
    result = module.review_model_artifacts(tmp_path, 'downstream_unreachable', {'diagnosis': diagnosis})
    assert result['gates']['quotes_observed'] is (mutation is None)
    assert result['passed'] is (mutation is None)
