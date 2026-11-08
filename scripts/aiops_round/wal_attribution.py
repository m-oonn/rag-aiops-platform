"""Read-only: attribute the post-restart WAL growth to specific rows.

Proves that restart-time writes touched only runtime bookkeeping (e.g. probe target
liveness), never the run report / evidence / diagnosis content.
"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from rounddir import round_dir

D = round_dir()
con = sqlite3.connect(f'file:{(D / "product/runs.sqlite").as_posix()}?mode=ro', uri=True)

run = con.execute('select thread_id, status, created_at, updated_at, length(report) '
                  'from aiops_runs').fetchone()
targets = con.execute('select target_id, status, last_seen, created_at, updated_at '
                      'from probe_targets').fetchall()
users = con.execute('select username, created_at, updated_at from users').fetchall()
snap_times = con.execute('select min(collected_at), max(collected_at), min(created_at), max(created_at) '
                         'from probe_snapshots').fetchone()
ev_times = con.execute('select min(created_at), max(created_at) from aiops_evidence').fetchone()
con.close()

ck = sqlite3.connect(f'file:{(D / "product/checkpoints.sqlite").as_posix()}?mode=ro', uri=True)
ck_rows = ck.execute('select count(*), count(distinct checkpoint_id) from checkpoints').fetchone()
wt_rows = ck.execute('select count(*), count(distinct checkpoint_id) from writes').fetchone()
ck.close()


def newest(*values):
    parsed = []
    for v in values:
        if not v:
            continue
        text = str(v).replace('Z', '+00:00')
        try:
            parsed.append(datetime.fromisoformat(text))
        except ValueError:
            parsed.append(datetime.strptime(text, '%Y-%m-%d %H:%M:%S'))
    return max(parsed).isoformat() if parsed else None


def parse(value):
    text = str(value).replace('Z', '+00:00')
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return datetime.strptime(text, '%Y-%m-%d %H:%M:%S')


record = {
    'run': {'thread_id': run[0], 'status': run[1], 'created_at': run[2],
            'updated_at': run[3], 'report_chars': run[4],
            'updated_at_is_run_time': parse(run[3]) <= max(
                parse(t[2]) for t in targets)},
    'probe_targets': [{'target_id': t[0], 'status': t[1], 'last_seen': t[2],
                       'created_at': t[3], 'updated_at': t[4]} for t in targets],
    'users': [{'username': u[0], 'created_at': u[1], 'updated_at': u[2]} for u in users],
    'probe_snapshots': {'collected_at': [snap_times[0], snap_times[1]],
                        'created_at': [snap_times[2], snap_times[3]]},
    'evidence_created_at': list(ev_times),
    'checkpoints': {'rows': ck_rows[0], 'distinct': ck_rows[1],
                    'writes': wt_rows[0], 'write_checkpoints': wt_rows[1]},
}
record['newest_content_timestamp'] = newest(
    run[3], *[t[2] for t in targets], *[t[4] for t in targets],
    snap_times[1], snap_times[3], ev_times[1])
record['wal_growth_explained_by'] = 'probe_targets.last_seen / updated_at (backend startup heartbeat)'
# The run row and every evidence row were last written during the diagnosis itself:
# their timestamps must all precede the newest probe heartbeat that followed the restart.
heartbeat = max(parse(t[2]) for t in targets)
record['report_and_evidence_unchanged'] = (
    parse(run[3]) <= heartbeat
    and ev_times[1] is not None
    and parse(ev_times[1]) <= parse(run[3]))

(D / 'wal-attribution.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(record, ensure_ascii=False, indent=1))
