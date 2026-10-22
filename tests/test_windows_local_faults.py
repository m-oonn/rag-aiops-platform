from types import SimpleNamespace
from unittest.mock import Mock
from pathlib import Path
import json
import sqlite3
import pytest

from scripts import verify_windows_local_faults as module


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
@pytest.mark.parametrize('failure', ['none', 'process', 'budget', 'unknown_cost', 'lost_previous'])
async def test_model_runner_inherits_budget_and_fails_closed(tmp_path, failure):
    previous = {'limit_cny': 5, 'reserved_cny': 0.4, 'requests': [
        {'number': 1, 'reserved_cny': 0.4, 'http_status': 200, 'usage': {'prompt_tokens': 3}}]}
    prior = tmp_path / 'prior.json'
    prior.write_text(json.dumps(previous))
    launches = []
    def launch(args, name):
        launches.append(args)
        assert '--run-model' in args and args[args.index('--previous-cost') + 1] == str(prior)
        assert args[args.index('--knowledge-mcp-url') + 1] == 'http://127.0.0.1:9200/mcp'
        output = Path(args[args.index('--output-dir') + 1])
        output.mkdir()
        assert 'downstream_unreachable' not in str(output)
        summary = {'budget_stopped': failure == 'budget', 'execution_error': None,
            'error_events': 0, 'has_final_report': True, 'report_kind': 'unlocated'}
        (output / 'summary.json').write_text(json.dumps(summary))
        row = {'number': 2, 'reserved_cny': 0.2, 'http_status': 200, 'usage': {'prompt_tokens': 4}}
        cost = {'limit_cny': 5, 'reserved_cny': 0.6, 'requests': [*previous['requests'], row]}
        if failure == 'unknown_cost':
            row.pop('usage')
        if failure == 'lost_previous':
            cost = {'limit_cny': 5, 'reserved_cny': 0.2, 'requests': [{**row, 'number': 1}]}
        (output / 'cost.json').write_text(json.dumps(cost))
        return SimpleNamespace(wait=lambda: 1 if failure == 'process' else 0)
    if failure == 'none':
        result = await module.evaluate_model_case(tmp_path, 'downstream_unreachable', launch, prior,
            knowledge_url='http://127.0.0.1:9200/mcp')
        assert result['reserved_cny'] == 0.6 and result['cumulative_requests'] == 2
        assert result['workflow_completed'] and not result['diagnostic_correctness_verified']
    else:
        with pytest.raises((RuntimeError, ValueError)):
            await module.evaluate_model_case(tmp_path, 'downstream_unreachable', launch, prior,
                knowledge_url='http://127.0.0.1:9200/mcp')
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
@pytest.mark.parametrize('reverse', [False, True])
async def test_blind_controller_randomizes_order_preserves_cost_and_restores(tmp_path, monkeypatch, reverse):
    changes, seen = [], []
    class Shuffle:
        def shuffle(self, rows):
            if reverse:
                rows.reverse()
    monkeypatch.setattr(module.secrets, 'SystemRandom', Shuffle)
    async def set_case(case):
        changes.append(case)
    async def run(out, case, launch, previous, knowledge_url=None):
        assert knowledge_url == 'http://127.0.0.1:9200/mcp'
        seen.append((case, previous))
        return {'cost_file': str(tmp_path / (str(len(seen)) + '.json'))}
    monkeypatch.setattr(module, 'evaluate_model_case', run)
    await module.evaluate_blind_cases(tmp_path, Mock(), set_case, knowledge_url='http://127.0.0.1:9200/mcp')
    assert seen[0][0] == ('downstream_unreachable' if reverse else 'normal')
    assert {row[0] for row in seen} == {'normal', 'downstream_unreachable'}
    assert seen[0][1] is None and seen[1][1] == tmp_path / '1.json'
    assert changes == [seen[0][0], seen[1][0], 'normal']


@pytest.mark.asyncio
async def test_blind_controller_failure_stops_later_cases_and_restores(tmp_path, monkeypatch):
    changes, calls = [], []
    async def set_case(case):
        changes.append(case)
    async def fail(out, case, launch, previous, knowledge_url=None):
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
