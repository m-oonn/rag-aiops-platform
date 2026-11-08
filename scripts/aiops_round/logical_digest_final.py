"""Read-only: final logical digest after the environment was stopped, compared with
the post-restart digest captured while the backend was running."""
import hashlib
import json
import sqlite3
from pathlib import Path
from rounddir import round_dir

D = round_dir()


def digest(rows):
    blob = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


con = sqlite3.connect(f'file:{(D / "product/runs.sqlite").as_posix()}?mode=ro', uri=True)
run = con.execute('select id, thread_id, user_id, query, status, report, terminal_approval, '
                  'degraded, created_at, updated_at from aiops_runs').fetchall()
ev = con.execute('select evidence_id, thread_id, user_id, target_id, source, kind, collected_at, '
                 'summary_redacted, raw_ref, raw_hash, fresh_until from aiops_evidence '
                 'order by evidence_id').fetchall()
targets = con.execute('select id, target_id, platform, hostname, agent_version, capabilities, status, '
                      'last_seen, updated_at from probe_targets order by id').fetchall()
users = con.execute('select id, username, role, is_active from users order by id').fetchall()
con.close()
ck = sqlite3.connect(f'file:{(D / "product/checkpoints.sqlite").as_posix()}?mode=ro', uri=True)
ckrows = ck.execute('select thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, '
                    'length(checkpoint), length(metadata) from checkpoints order by checkpoint_id').fetchall()
writes = ck.execute('select count(*) from writes').fetchone()[0]
ck.close()

report = run[0][5] or ''
final = {
    'run_status': run[0][4],
    'thread_id': run[0][1],
    'report_sha256': hashlib.sha256(report.encode()).hexdigest(),
    'report_bytes': len(report.encode()),
    'run_rows_digest': digest([list(r) for r in run]),
    'evidence_rows': len(ev),
    'evidence_digest': digest([list(r) for r in ev]),
    'probe_targets': [{'target_id': t[1], 'status': t[6], 'last_seen': t[7]} for t in targets],
    'users_digest': digest([list(r) for r in users]),
    'checkpoints': {'rows': len(ckrows), 'digest': digest([list(r) for r in ckrows]), 'writes': writes},
}

prev = json.loads((D / 'logical-digest-after-restart.json').read_text(encoding='utf-8'))
comparison = {
    'report_sha256_identical': prev['runs']['report_sha256'] == final['report_sha256'],
    'run_rows_digest_identical': prev['runs']['run_rows_digest'] == final['run_rows_digest'],
    'evidence_digest_identical': prev['runs']['evidence_digest'] == final['evidence_digest'],
    'evidence_rows_identical': prev['runs']['evidence_rows'] == final['evidence_rows'],
    'checkpoints_digest_identical': prev['checkpoints']['digest'] == final['checkpoints']['digest'],
    'checkpoints_rows_identical': prev['checkpoints']['rows'] == final['checkpoints']['rows'],
    'writes_identical': prev['checkpoints']['writes'] == final['checkpoints']['writes'],
    'users_digest_identical': prev['runs']['users_digest'] == final['users_digest'],
    'probe_target_status_now': final['probe_targets'],
}
record = {'final': final, 'comparison': comparison,
          'all_diagnosis_content_identical': all(v for k, v in comparison.items()
                                                if k not in ('probe_target_status_now',))}
(D / 'logical-digest-final.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(record['comparison'], ensure_ascii=False, indent=1))
print('all identical:', record['all_diagnosis_content_identical'])
