"""Read-only observer for a real round. Never writes to the environment."""
import json
import sqlite3
from pathlib import Path
from rounddir import inherited_baseline, inherited_reserved, round_dir

D = round_dir()
PM = D / 'product-model'
INHERITED = inherited_baseline()
INHERITED_RESERVED = inherited_reserved()

cost = json.loads((PM / 'cost.json').read_text(encoding='utf-8'))
rows = cost['requests']
new = [r for r in rows[INHERITED:]]
print('ledger requests:', len(rows), 'reserved:', cost['reserved_cny'], 'limit:', cost['limit_cny'])
print('new rows:', len(new), 'projected new spend:', round(cost['reserved_cny'] - INHERITED_RESERVED, 6))
blocked = cost.get('blocked_requests') or []
print('blocked total:', len(blocked))
for b in blocked:
    print('  blocked:', json.dumps(b, ensure_ascii=False)[:300])
settled = [r for r in new if r.get('status') != 'reserved']
print('settled new rows:', len(settled), 'last status:', new[-1].get('status') if new else None)
print('new models:', sorted({r.get('model') for r in new}))
print('new rows with usage:', sum(1 for r in new if (r.get('usage') or {}).get('total_tokens') is not None))
print('new rows unpriced:', [r['number'] for r in new if not r.get('pricing_verified')])

inputs = PM / 'model-inputs'
print('model-inputs files:', len(list(inputs.glob('*.json'))) if inputs.exists() else 0)

trace_path = D / 'product' / 'tool_trace.json'
if trace_path.exists():
    trace = json.loads(trace_path.read_text(encoding='utf-8'))
    print('tool calls:', len(trace))
    for row in trace:
        print('  ', row.get('tool'), row.get('status'), row.get('validated_live_evidence'),
              json.dumps(row.get('arguments'), ensure_ascii=False)[:160])

for name in ('product/runs.sqlite', 'product/checkpoints.sqlite'):
    p = D / name
    if not p.exists():
        print(name, 'MISSING')
        continue
    con = sqlite3.connect(f'file:{p.as_posix()}?mode=ro', uri=True)
    tables = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
    print(name, 'tables:', tables)
    for t in tables:
        try:
            print('   ', t, 'rows', con.execute('select count(*) from ' + t).fetchone()[0])
        except Exception as exc:
            print('   ', t, 'err', exc)
    if 'aiops_runs' in tables:
        for row in con.execute('select id, thread_id, status, length(report), created_at, updated_at from aiops_runs'):
            print('   run:', row)
    con.close()
