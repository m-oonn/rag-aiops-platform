"""Read-only: prove the post-restart DB churn is only the probe heartbeat.

Takes a per-table row digest, waits ~75 s, takes it again, and diffs.
Diagnosis content (run row, evidence, checkpoints) must stay identical.
"""
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from rounddir import round_dir

D = round_dir()


def digest(rows):
    blob = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


QUERIES = {
    'aiops_runs': 'select id, thread_id, user_id, query, status, report, terminal_approval, '
                  'degraded, created_at, updated_at from aiops_runs',
    'aiops_evidence': 'select evidence_id, thread_id, user_id, target_id, source, kind, '
                      'collected_at, summary_redacted, raw_ref, raw_hash, fresh_until, created_at '
                      'from aiops_evidence order by evidence_id',
    'probe_snapshots': 'select id, target_id, kind, collected_at, raw_hash from probe_snapshots order by id',
    'probe_targets': 'select id, target_id, status, last_seen, updated_at from probe_targets order by id',
    'users': 'select id, username, role, is_active from users order by id',
}
CK_QUERIES = {
    'checkpoints': 'select thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, '
                   'length(checkpoint), length(metadata) from checkpoints order by checkpoint_id',
    'writes': 'select thread_id, checkpoint_ns, checkpoint_id, task_id, task_path, idx, channel, type, '
              'length(value) from writes order by checkpoint_id, idx',
}


def snapshot():
    out = {}
    con = sqlite3.connect(f'file:{(D / "product/runs.sqlite").as_posix()}?mode=ro', uri=True)
    for table, sql in QUERIES.items():
        rows = con.execute(sql).fetchall()
        out[table] = {'rows': len(rows), 'digest': digest([list(r) for r in rows])}
    con.close()
    con = sqlite3.connect(f'file:{(D / "product/checkpoints.sqlite").as_posix()}?mode=ro', uri=True)
    for table, sql in CK_QUERIES.items():
        rows = con.execute(sql).fetchall()
        out[f'checkpoints.{table}'] = {'rows': len(rows), 'digest': digest([list(r) for r in rows])}
    con.close()
    cost = json.loads((D / 'product-model/cost.json').read_text(encoding='utf-8'))
    out['cost'] = {'ledger_rows': len(cost['requests']),
                   'ledger_sha256': hashlib.sha256(
                       (D / 'product-model/cost.json').read_bytes()).hexdigest()}
    return out


first = snapshot()
time.sleep(75)
second = snapshot()

changed = {k: {'before': first[k], 'after': second[k]}
           for k in first if first[k] != second[k]}
unchanged = [k for k in first if first[k] == second[k]]

record = {
    'interval_seconds': 75,
    'changed': changed,
    'unchanged': unchanged,
    'verdict': {
        'diagnosis_content_stable': all(
            first[k] == second[k]
            for k in ('aiops_runs', 'aiops_evidence', 'checkpoints.checkpoints',
                      'checkpoints.writes', 'users', 'cost')),
        'churn_tables': sorted(changed),
        'churn_is_probe_heartbeat_only': set(changed) <= {'probe_snapshots', 'probe_targets'},
    },
}
(D / 'heartbeat-drift.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(record['verdict'], ensure_ascii=False, indent=1))
print('changed:', json.dumps(changed, ensure_ascii=False))
print('unchanged:', unchanged)
