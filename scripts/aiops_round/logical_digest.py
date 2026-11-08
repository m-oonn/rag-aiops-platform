"""Read-only: logical digests of the 036 run DBs + consistency vs pre-restart reads.

The restart changed `runs.sqlite-wal` / `checkpoints.sqlite` byte layout (SQLite WAL
checkpointing), so equality is proven at the row level instead of the byte level.
"""
import hashlib
import json
import sqlite3
from pathlib import Path
from rounddir import round_dir

D = round_dir()


def ro(name):
    return sqlite3.connect(f'file:{(D / name).as_posix()}?mode=ro', uri=True)


def digest(rows):
    blob = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


con = ro('product/runs.sqlite')
run = con.execute('select id, thread_id, user_id, query, status, report, terminal_approval, '
                  'degraded, created_at, updated_at from aiops_runs').fetchall()
ev = con.execute('select evidence_id, thread_id, user_id, target_id, source, kind, collected_at, '
                 'summary_redacted, raw_ref, raw_hash, fresh_until from aiops_evidence '
                 'order by evidence_id').fetchall()
snaps = con.execute('select id, target_id, kind, collected_at, raw_hash from probe_snapshots '
                    'order by id').fetchall()
targets = con.execute('select id, target_id, platform, hostname, agent_version, capabilities, status '
                      'from probe_targets order by id').fetchall()
users = con.execute('select id, username, role, is_active from users order by id').fetchall()
con.close()

con = ro('product/checkpoints.sqlite')
ck = con.execute('select thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, '
                 'length(checkpoint), length(metadata) from checkpoints order by checkpoint_id').fetchall()
writes = con.execute('select count(*) from writes').fetchone()[0]
con.close()

report = run[0][5] or ''
report_sha = hashlib.sha256(report.encode()).hexdigest()

# Pre-restart API reads recorded in acceptance-live.json / run-detail.json.
live = json.loads((D / 'acceptance-live.json').read_text(encoding='utf-8'))
access = {
    'report_sha256_matches_live': live.get('report_sha256') == report_sha,
    'live_report_sha256': live.get('report_sha256'),
    'evidence_total_matches_live': live.get('evidence_total') == len(ev),
    # 036/037/038 compare against 'confirmed_cause'; 039 legitimately ended as
    # localized_fault, so compare against the kind recorded in run-detail.json.
    'diagnosis_kind_matches_live': live.get('diagnosis_kind') == (
        json.loads((D / 'run-detail.json').read_text(encoding='utf-8'))
        .get('diagnosis', {}).get('kind')),
}

record = {
    'runs': {
        'rows': len(run),
        'status': run[0][4] if run else None,
        'thread_id': run[0][1] if run else None,
        'report_sha256': report_sha,
        'report_bytes': len(report.encode()),
        'created_at': run[0][8] if run else None,
        'updated_at': run[0][9] if run else None,
        'run_rows_digest': digest([list(r) for r in run]),
        'evidence_rows': len(ev),
        'evidence_digest': digest([list(r) for r in ev]),
        'evidence_ids': [r[0] for r in ev],
        'evidence_raw_hashes': [r[9] for r in ev],
        'probe_snapshots': len(snaps),
        'probe_snapshots_digest': digest([list(r) for r in snaps]),
        'probe_targets_digest': digest([list(r) for r in targets]),
        'users_digest': digest([list(r) for r in users]),
    },
    'checkpoints': {'rows': len(ck), 'digest': digest([list(r) for r in ck]), 'writes': writes},
    'vs_live_reads': access,
}
(D / 'logical-digest-after-restart.json').write_text(
    json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')

short = {k: v for k, v in record['runs'].items() if k not in ('evidence_ids', 'evidence_raw_hashes')}
print(json.dumps(short, ensure_ascii=False, indent=1))
print(json.dumps(record['checkpoints'], ensure_ascii=False))
print(json.dumps(access, ensure_ascii=False))
