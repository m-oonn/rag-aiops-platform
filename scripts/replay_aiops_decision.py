"""Read-only replay of trusted local evaluation artifacts; no model or tool calls."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def replay(directory, output):
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
    from src.agent.aiops.strategies.investigation import (
        InvestigationDecision, decide_from_evidence, evidence_index, _payloads,
    )
    from src.probe.evidence import validate_evidence
    from src.probe.protocol import redact
    from src.settings import settings

    directory, output = Path(directory).resolve(strict=True), Path(output).resolve()
    if output.exists() or output == directory or directory in output.parents:
        raise ValueError('replay output must be a new directory outside the original run')
    watched = {}

    def read(path):
        content = path.read_bytes()
        watched[path] = hashlib.sha256(content).hexdigest()
        return content

    summary_path = directory / 'summary.json'
    original = json.loads(read(summary_path))
    for name in ('checkpoints.sqlite', 'runs.sqlite'):
        read(directory / name)
    with sqlite3.connect((directory / 'checkpoints.sqlite').as_uri() + '?mode=ro', uri=True) as db:
        rows = db.execute('SELECT thread_id, type, checkpoint FROM checkpoints WHERE checkpoint_ns = ? ORDER BY checkpoint_id DESC', ('',)).fetchall()
    if not rows or len({row[0] for row in rows}) != 1:
        raise ValueError('expected exactly one historical investigation')
    thread_id, encoding, blob = rows[0]
    checkpoint = JsonPlusSerializer().loads_typed((encoding, blob))
    state = checkpoint['channel_values']
    if not state.get('response') or not state.get('diagnosis'):
        raise ValueError('incomplete investigation has no final decision to replay')
    when = datetime.fromisoformat(checkpoint['ts'].replace('Z', '+00:00'))
    proposal = (state.get('investigation_memory') or {}).get('model_suggestion') or state['investigation_memory']
    proposed = InvestigationDecision.model_validate(proposal)
    target_id = state['diagnosis']['target_id']
    if target_id != settings.PROBE_TARGET_ID:
        raise ValueError('historical target differs from configured target')
    with sqlite3.connect((directory / 'runs.sqlite').as_uri() + '?mode=ro', uri=True) as db:
        ledger = db.execute('SELECT evidence_id, raw_ref, raw_hash FROM aiops_evidence WHERE thread_id = ?', (thread_id,)).fetchall()
    saved = {}
    for evidence_id, raw_ref, digest in ledger:
        path = Path(raw_ref).resolve(strict=True)
        if path.parent != (directory / 'evidence').resolve() or path.name != evidence_id + '.json':
            raise ValueError('evidence path does not belong to this run')
        value = json.loads(read(path))
        validate_evidence(value, target_id=target_id, now=datetime.fromisoformat(value['collected_at'].replace('Z', '+00:00')))
        if value['raw_hash'] != digest:
            raise ValueError('ledger hash mismatch')
        saved[evidence_id] = value
    events = state.get('evidence_events') or []
    for event in events:
        value = saved.get(event.get('evidence_id'))
        if value is None or any(event.get(key) != value[key] for key in ('target_id', 'collected_at', 'raw_hash')) or event.get('kind') != value['operation']:
            raise ValueError('checkpoint evidence identity does not match this ledger')
    for _, raw in state.get('raw_evidence', []):
        values = list(_payloads(raw))
        if not values:
            values = [item for line in str(raw).splitlines() for item in _payloads(line)]
        for value in values:
            if value.get('data_source') == 'probe_target' and value not in saved.values():
                raise ValueError('checkpoint observation is absent from the evidence ledger')
    records = evidence_index(state, now=when)
    update = decide_from_evidence(state, proposed, records)
    if 'diagnosis' not in update:
        raise ValueError('historical proposal still requires an executable check; not a final replay')
    result = {
        'mode': 'historical_rule_replay', 'model_calls': 0, 'new_observations': 0,
        'autonomous_model_success_proven': False, 'thread_id': thread_id,
        'historical_validation_time': checkpoint['ts'],
        'original_kind': original.get('diagnosis', {}).get('kind'),
        'model_proposed_level': proposed.conclusion_level,
        'replayed_kind': update['diagnosis']['kind'],
        'validated_current_records_at_that_time': len(records),
        'diagnosis': update['diagnosis'], 'investigation_memory': update['investigation_memory'],
        'original_artifacts_unchanged': all(hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in watched.items()),
        'input_file_sha256': {str(path.relative_to(directory)): digest for path, digest in watched.items()},
    }
    if not result['original_artifacts_unchanged']:
        raise ValueError('source artifacts changed during replay')
    output.mkdir(parents=True, exist_ok=False)
    (output / 'replay.json').write_text(json.dumps(redact(result), ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'report.txt').write_text(update['response'], encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = args.output or ROOT / 'runtime' / ('decision-replay-' + uuid4().hex)
    result = replay(args.directory, output)
    print(json.dumps({key: result[key] for key in ('mode', 'original_kind', 'model_proposed_level', 'replayed_kind', 'model_calls', 'original_artifacts_unchanged')}, ensure_ascii=False))
    print('OUTPUT=' + str(output))
