import json
import sqlite3
from datetime import datetime, timezone

import pytest
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from scripts.replay_aiops_decision import replay
from src.probe.protocol import evidence
from src.settings import settings


@pytest.fixture(params=['legacy', 'product'])
def historical_run(tmp_path, request):
    source = tmp_path / 'original'
    source.mkdir()
    product_layout = request.param == 'product'
    data_directory = source / 'product' if product_layout else source
    data_directory.mkdir(exist_ok=True)
    target_id = 'historical-target' if product_layout else settings.PROBE_TARGET_ID
    root = data_directory / 'evidence'
    root.mkdir()
    when = datetime.now(timezone.utc).isoformat()
    raw = evidence(target_id=target_id, operation='dependency_probe',
        payload={'dependency': 'db', 'tcp': 'failed'}, collected_at=when)
    path = root / 'ev-test.json'
    path.write_text(json.dumps(raw), encoding='utf-8')
    if product_layout:
        (source / 'result-summary.json').write_text(json.dumps({
            'thread_id': 'run-1', 'diagnosis_kind': 'unlocated'}), encoding='utf-8')
        (source / 'environment.json').write_text(json.dumps({'target_id': target_id}), encoding='utf-8')
    else:
        (source / 'summary.json').write_text(json.dumps({
            'thread_id': 'run-1', 'diagnosis': {'kind': 'unlocated'}}), encoding='utf-8')
    state = {'input': 'application unavailable', 'response': 'original report',
        'diagnosis': {'target_id': target_id, 'kind': 'unlocated'},
        'raw_evidence': [('check', json.dumps(raw))],
        'evidence_events': [{'evidence_id': 'ev-test', 'target_id': raw['target_id'],
            'collected_at': when, 'kind': raw['operation'], 'raw_hash': raw['raw_hash']}],
        'investigation_memory': {'hypothesis': 'dependency unavailable', 'blocked_reason': 'no more checks'}}
    kind, blob = JsonPlusSerializer().dumps_typed({'ts': when, 'channel_values': state})
    with sqlite3.connect(data_directory / 'checkpoints.sqlite') as db:
        db.execute('CREATE TABLE checkpoints (thread_id TEXT, checkpoint_ns TEXT, checkpoint_id TEXT, type TEXT, checkpoint BLOB)')
        db.execute('INSERT INTO checkpoints VALUES (?, ?, ?, ?, ?)', ('run-1', '', '1', kind, blob))
    with sqlite3.connect(data_directory / 'runs.sqlite') as db:
        db.execute('CREATE TABLE aiops_evidence (thread_id TEXT, evidence_id TEXT, raw_ref TEXT, raw_hash TEXT)')
        db.execute('INSERT INTO aiops_evidence VALUES (?, ?, ?, ?)', ('run-1', 'ev-test', str(path), raw['raw_hash']))
    return source, tmp_path / 'replayed', path, data_directory


def test_replay_uses_historical_time_shared_decision_and_preserves_originals(historical_run):
    source, output, _, _ = historical_run
    before = {p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()}
    result = replay(source, output)
    assert result['original_kind'] == 'unlocated'
    assert result['replayed_kind'] == 'localized_fault'
    assert result['model_calls'] == result['new_observations'] == 0
    assert result['autonomous_model_success_proven'] is False
    assert result['original_artifacts_unchanged'] is True
    assert result['diagnosis']['evidence'][0]['evidence_id'] == 'ev-test'
    assert before == {p.relative_to(source): p.read_bytes() for p in source.rglob('*') if p.is_file()}
    assert (output / 'replay.json').is_file()


@pytest.mark.parametrize('mutation', ['tampered', 'other_run', 'incomplete', 'inside_source', 'existing_output'])
def test_replay_rejects_invalid_or_unsafe_artifacts(historical_run, mutation):
    source, output, path, data_directory = historical_run
    if mutation == 'tampered':
        raw = json.loads(path.read_text(encoding='utf-8'))
        raw['payload']['tcp'] = 'ok'
        path.write_text(json.dumps(raw), encoding='utf-8')
    elif mutation == 'other_run':
        with sqlite3.connect(data_directory / 'runs.sqlite') as db:
            db.execute("UPDATE aiops_evidence SET thread_id = 'other'")
    elif mutation == 'incomplete':
        with sqlite3.connect(data_directory / 'checkpoints.sqlite') as db:
            kind, blob = db.execute('SELECT type, checkpoint FROM checkpoints').fetchone()
            serializer = JsonPlusSerializer()
            checkpoint = serializer.loads_typed((kind, blob))
            checkpoint['channel_values']['response'] = ''
            kind, blob = serializer.dumps_typed(checkpoint)
            db.execute('UPDATE checkpoints SET type = ?, checkpoint = ?', (kind, blob))
    elif mutation == 'inside_source':
        output = source / 'replay'
    else:
        output.mkdir()
    with pytest.raises(ValueError):
        replay(source, output)
    assert not (output / 'replay.json').exists()
