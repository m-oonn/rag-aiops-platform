"""Read-only: rebuild the decision-audit trail and latest state from 036 checkpoints.

LangGraph stores checkpoint/write blobs with `ormsgpack` (installed) or msgpack; the
declared type is `msgpack`. We only need the JSON-compatible channel payloads, so we
decode defensively and skip anything that cannot be decoded.
"""
import json
from pathlib import Path

import ormsgpack
import sqlite3
from rounddir import round_dir

D = round_dir()


def decode(blob):
    if blob is None:
        return None
    if isinstance(blob, memoryview):
        blob = blob.tobytes()
    if isinstance(blob, (bytes, bytearray)):
        for fn in (ormsgpack.unpackb,):
            try:
                return fn(bytes(blob))
            except Exception:
                continue
        return {'__undecodable__': True, 'length': len(blob)}
    if isinstance(blob, str):
        try:
            return json.loads(blob)
        except Exception:
            return blob
    return blob


con = sqlite3.connect(f'file:{(D / "product/checkpoints.sqlite").as_posix()}?mode=ro', uri=True)
con.row_factory = sqlite3.Row

ckpts = []
for r in con.execute('select checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata '
                     'from checkpoints order by rowid'):
    ckpts.append({
        'checkpoint_id': r['checkpoint_id'],
        'parent_checkpoint_id': r['parent_checkpoint_id'],
        'type': r['type'],
        'checkpoint_bytes': len(r['checkpoint'] or b''),
        'metadata': decode(r['metadata']),
    })

channels = {}
for r in con.execute('select checkpoint_id, channel, type, value from writes order by rowid'):
    decoded = decode(r['value'])
    channels.setdefault(r['channel'], []).append({
        'checkpoint_id': r['checkpoint_id'],
        'type': r['type'],
        'decoded_kind': type(decoded).__name__,
        'preview': (json.dumps(decoded, ensure_ascii=False, default=str)[:400]
                    if not isinstance(decoded, dict) or len(json.dumps(decoded, default=str)) < 400
                    else json.dumps(decoded, ensure_ascii=False, default=str)[:400]),
    })
con.close()

diagnosis_writes = [w for w in channels.get('diagnosis', [])]
plan_writes = channels.get('plan', [])
steps = channels.get('_step_progress', [])
ev_events = channels.get('evidence_events', [])

record = {
    'checkpoints': ckpts,
    'channel_counts': {k: len(v) for k, v in sorted(channels.items())},
    'diagnosis_write_preview': diagnosis_writes,
    'plan_writes_preview': plan_writes[:3],
    'step_progress_preview': steps,
    'evidence_events_count': len(ev_events),
}
(D / 'ckpt-decoded.json').write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str),
                                     encoding='utf-8')
print(json.dumps(record['channel_counts'], ensure_ascii=False))
print('diagnosis preview:', json.dumps(diagnosis_writes, ensure_ascii=False)[:600])
print('step progress:', json.dumps(steps, ensure_ascii=False)[:600])
