"""Read-only: inspect what the checkpoint store can reconstruct for the audit trail."""
import json
import sqlite3
from pathlib import Path
from rounddir import round_dir

D = round_dir()
con = sqlite3.connect(f'file:{(D / "product/checkpoints.sqlite").as_posix()}?mode=ro', uri=True)
con.row_factory = sqlite3.Row

print('--- checkpoints ---')
for r in con.execute('select checkpoint_id, parent_checkpoint_id, type, length(checkpoint) len, '
                     'metadata from checkpoints order by rowid'):
    meta = r['metadata']
    try:
        meta_obj = json.loads(meta) if meta else {}
        src = meta_obj.get('source') or meta_obj.get('step')
    except Exception:
        src = None
    print(' ', r['checkpoint_id'], '| parent', (r['parent_checkpoint_id'] or '-')[:8],
          '| type', r['type'], '| len', r['len'], '| source', src)

print('--- channels seen ---')
for r in con.execute('select channel, type, count(*) n from writes group by channel, type order by n desc'):
    print(' ', r['channel'], r['type'], r['n'])

print('--- latest write per interesting channel ---')
for ch in ('investigation', 'diagnosis', 'plan', 'records', 'messages'):
    row = con.execute('select length(value) len from writes where channel=? order by rowid desc limit 1',
                      (ch,)).fetchone()
    print(' ', ch, row['len'] if row else 'missing')
con.close()
