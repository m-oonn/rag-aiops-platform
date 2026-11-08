"""Read-only: inspect `past_steps` / `investigation_memory` / `evidence_events` payloads
to see whether an audit trail can be reconstructed from persisted checkpoints."""
import json
import sqlite3
from pathlib import Path

import ormsgpack
from rounddir import round_dir

D = round_dir()
con = sqlite3.connect(f'file:{(D / "product/checkpoints.sqlite").as_posix()}?mode=ro', uri=True)
con.row_factory = sqlite3.Row


def decode(blob):
    if blob is None:
        return None
    if isinstance(blob, memoryview):
        blob = blob.tobytes()
    if isinstance(blob, (bytes, bytearray)):
        try:
            return ormsgpack.unpackb(bytes(blob))
        except Exception as exc:  # pragma: no cover
            return {'__undecodable__': str(exc)}
    return blob


for channel in ('past_steps', 'investigation_memory', 'autonomous_investigation',
                'investigation_config', 'target_resolution', 'response'):
    rows = list(con.execute('select checkpoint_id, value from writes where channel=? order by rowid',
                            (channel,)))
    print(f'=== {channel} ({len(rows)} writes) ===')
    last = decode(rows[-1]['value']) if rows else None
    text = json.dumps(last, ensure_ascii=False, default=str) if last is not None else 'None'
    print(text[:1200])
    print()
con.close()
