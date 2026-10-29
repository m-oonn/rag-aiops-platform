import hashlib
import json

import pytest

from scripts.summarize_mechanism_runs import GROUPS, summarize


@pytest.fixture
def artifacts(tmp_path):
    source, audits = tmp_path / 'source', tmp_path / 'audits'
    source.mkdir()
    audits.mkdir()
    manifest = []
    def save(path, value):
        path.write_text(json.dumps(value), encoding='utf-8')
    for index, (group, switches) in enumerate(GROUPS.items()):
        name = 'mechanisms-case-' + group
        directory = source / name
        directory.mkdir()
        config = dict(zip(('hypothesis_protection', 'contradiction_trigger'), switches))
        config['protection_steps'] = 2
        tid = 'thread-' + group
        manifest.append({'case': 'case', 'group': group, 'thread_id': tid, 'config': config})
        steps = ['check'] * (index + 1)
        events = [{'type': 'step_complete', 'current_step': step} for step in steps]
        events.append({'type': 'complete', 'thread_id': tid, 'response': 'unknown',
                       'diagnosis': {'kind': 'unlocated', 'mechanism_config': config}})
        save(directory / 'events.json', events)
        save(directory / 'calls.json', [{'tool': 'probe_inventory'}] + [{'tool': 'probe_dependency_probe'}] * len(steps))
        save(directory / 'mechanism_trace.json', {'thread_id': tid, 'executed_steps': steps,
            'audit': {'expected_config': config, 'actual_config': config}})
        (directory / 'checkpoints.sqlite').write_bytes(b'trusted-local-fixture')
        for phase in ('before', 'after'):
            save(directory / ('knowledge-conditions-' + phase + '.json'),
                 {'passed': True, 'actual_sha256': 'same-knowledge', 'expected_sha256': 'same-knowledge'})
        executions = [{'tool': 'probe_inventory', 'status': 'success'}] + [
            {'tool': 'probe_dependency_probe', 'arguments': {'dependency': 'db'},
             'status': 'success', 'elapsed_ms': 10} for _ in steps]
        hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
                  (directory / 'mechanism_trace.json', directory / 'checkpoints.sqlite')}
        save(audits / (name + '.json'), {'sample': name, 'source_sha256': hashes, 'source_unchanged': True,
            'decision_boundaries_matched': True, 'execution_records': executions, 'behavior': {
                'status': 'passed', 'executed_changes': {'protection': int(switches[0]), 'contradiction': int(switches[1])},
                'blocked_events': int(switches[1]), 'opportunities': {'protection': 1, 'contradiction': 1},
                'candidate_correctness': 'pending_manual_review'}})
    save(source / 'live-mechanism-groups.json', manifest)
    return source, audits, tmp_path / 'output'


def test_summary_distinguishes_partial_timing_pending_reviews_and_real_deltas(artifacts):
    source, audits, output = artifacts
    result = summarize(source, audits, output)
    assert result['passed'] and result['source_unchanged']
    assert result['human_reviewed'] == result['model_calls_this_summary'] == result['new_observations'] == 0
    assert result['diagnostic_accuracy'] is None
    assert result['reported_kind_counts'] == {'unlocated': 4}
    assert result['workflow_counts'] == {'completed': 4}
    for index, row in enumerate(result['runs']):
        assert row['tool_attempts'] == index + 2
        assert row['timed_tool_calls'] == index + 1
        assert row['recorded_tool_elapsed_ms'] == 10 * (index + 1)
        assert row['total_duration_ms'] is None and row['model_cost_cny'] is None
        assert row['vs_G00']['tool_attempt_delta'] == index
        assert row['vs_G00']['executor_step_delta'] == index
        assert not row['vs_G00']['causal_overhead_estimated']
        assert row['diagnosis_review'] == 'pending'
    assert (output / 'summary.md').is_file()
    with pytest.raises(FileExistsError):
        summarize(source, audits, output)


@pytest.mark.parametrize('mutation', ['missing_events', 'missing_group', 'duplicate', 'changed_source',
    'wrong_group', 'tool_mismatch', 'invalid_duration', 'knowledge_mismatch', 'behavior_failed'])
def test_summary_keeps_rows_and_rejects_inconsistent_inputs(artifacts, mutation):
    source, audits, output = artifacts
    directory = source / 'mechanisms-case-G11'
    path = audits / 'mechanisms-case-G11.json'
    audit = json.loads(path.read_text())
    manifest = json.loads((source / 'live-mechanism-groups.json').read_text())
    if mutation == 'missing_events':
        (directory / 'events.json').unlink()
    if mutation == 'missing_group':
        manifest.pop()
    if mutation == 'duplicate':
        manifest.append(manifest[-1])
    if mutation == 'changed_source':
        (directory / 'checkpoints.sqlite').write_bytes(b'changed')
    if mutation == 'wrong_group':
        manifest[-1]['config']['hypothesis_protection'] = False
    if mutation == 'tool_mismatch':
        audit['execution_records'][-1]['tool'] = 'wrong-tool'
    if mutation == 'invalid_duration':
        audit['execution_records'][-1]['elapsed_ms'] = -1
    if mutation == 'knowledge_mismatch':
        (directory / 'knowledge-conditions-after.json').write_text(json.dumps({'passed': True, 'actual_sha256': 'changed'}))
    if mutation == 'behavior_failed':
        audit['behavior']['status'] = 'failed'
    path.write_text(json.dumps(audit))
    (source / 'live-mechanism-groups.json').write_text(json.dumps(manifest))
    result = summarize(source, audits, output)
    assert not result['passed']
    assert result['run_count'] == (4 if mutation == 'missing_group' else len(manifest))
    assert result['runs'][-1]['diagnosis_review'] == 'pending'


@pytest.mark.parametrize('mutation', ['unlisted_failure', 'missing_manifest', 'missing_audit'])
def test_failed_directories_are_not_silently_omitted(artifacts, mutation):
    source, audits, output = artifacts
    if mutation == 'unlisted_failure':
        (source / 'mechanisms-interrupted-G11').mkdir()
    if mutation == 'missing_manifest':
        (source / 'live-mechanism-groups.json').unlink()
    if mutation == 'missing_audit':
        (audits / 'mechanisms-case-G11.json').unlink()
    result = summarize(source, audits, output)
    assert not result['passed']
    assert result['run_count'] == (5 if mutation == 'unlisted_failure' else 4)
    if mutation == 'missing_audit':
        assert result['runs'][-1]['workflow_status'] == 'completed'
        assert result['runs'][-1]['behavior_status'] == 'not_assessed'


@pytest.mark.parametrize('mutation', ['no_complete', 'empty_report', 'error'])
def test_incomplete_is_retained_and_not_called_completed(artifacts, mutation):
    source, audits, output = artifacts
    path = source / 'mechanisms-case-G11/events.json'
    events = json.loads(path.read_text())
    if mutation == 'no_complete':
        events.pop()
    if mutation == 'empty_report':
        events[-1]['response'] = ' '
    if mutation == 'error':
        events.append({'type': 'error'})
    path.write_text(json.dumps(events))
    result = summarize(source, audits, output)
    assert result['workflow_counts'] == {'completed': 3, 'incomplete': 1}
    assert result['run_count'] == 4
    assert result['runs'][-1]['diagnosis_review'] == 'pending'


def test_legacy_manifest_without_config_still_requires_trace_and_report_agreement(artifacts):
    source, audits, output = artifacts
    path = source / 'live-mechanism-groups.json'
    manifest = json.loads(path.read_text())
    for row in manifest:
        row.pop('config')
    path.write_text(json.dumps(manifest))
    result = summarize(source, audits, output)
    assert result['passed']
    assert all(r['manifest_config_present'] is False for r in result['runs'])


@pytest.mark.parametrize('duration', [None, 0, float('nan'), True])
def test_missing_and_invalid_timing_are_not_silently_replaced_with_zero(artifacts, duration):
    source, audits, output = artifacts
    path = audits / 'mechanisms-case-G00.json'
    audit = json.loads(path.read_text())
    audit['execution_records'][-1]['elapsed_ms'] = duration
    path.write_text(json.dumps(audit))
    result = summarize(source, audits, output)
    row = result['runs'][0]
    assert row['total_duration_ms'] is None
    if duration is None:
        assert row['recorded_tool_elapsed_ms'] is None and row['timed_tool_calls'] == 0
    elif type(duration) is int:
        assert row['recorded_tool_elapsed_ms'] == 0 and row['timed_tool_calls'] == 1
    else:
        assert not result['passed']
        assert 'invalid tool elapsed_ms' in row['issues']


def test_failed_tools_are_counted_even_when_workflow_reports_completion(artifacts):
    source, audits, output = artifacts
    path = audits / 'mechanisms-case-G11.json'
    audit = json.loads(path.read_text())
    audit['execution_records'][-1]['status'] = 'failed'
    path.write_text(json.dumps(audit))
    result = summarize(source, audits, output)
    row = result['runs'][-1]
    assert row['workflow_status'] == 'completed'
    assert row['failed_tools'] == 1 and row['successful_tools'] == row['tool_attempts'] - 1
    assert not result['passed'] and row['vs_G00']['tool_attempt_delta'] is None
