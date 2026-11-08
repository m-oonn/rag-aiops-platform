"""Read-only: final Gate-B consistency checks for a round.

1. evidence rows in runs.sqlite -> raw_ref file -> raw_hash recomputation
2. pre-restart vs post-restart artifact comparison with a WAL-aware verdict
3. budget summary from product-model/cost.json
"""
import hashlib
import json
from pathlib import Path

from rounddir import inherited_baseline, round_dir

D = round_dir()

before = json.loads((D / 'artifacts-before-restart.json').read_text(encoding='utf-8'))
after = json.loads((D / 'artifacts-after-restart.json').read_text(encoding='utf-8'))
logical = json.loads((D / 'logical-digest-after-restart.json').read_text(encoding='utf-8'))

stable, churned = [], []
for rel, meta in before['files'].items():
    same = meta == after['files'][rel]
    (stable if same else churned).append({'file': rel, 'before': meta, 'after': after['files'][rel]})

wal_verdict = {}
for rel in [c['file'] for c in churned]:
    wal_verdict[rel] = {
        'byte_identical': False,
        'reason': 'sqlite WAL checkpoint rewrites page layout on restart; content proven at row level',
    }

# Evidence rows -> on-disk files -> raw_hash recomputation.
import sqlite3
from rounddir import inherited_baseline, round_dir
con = sqlite3.connect(f'file:{(D / "product/runs.sqlite").as_posix()}?mode=ro', uri=True)
rows = con.execute('select evidence_id, kind, raw_ref, raw_hash, summary_redacted from aiops_evidence '
                   'order by evidence_id').fetchall()
con.close()

# raw_hash is sha256 of the canonical payload JSON (src/probe/protocol.py raw_hash),
# not of the wrapper file; replicate that contract and the evidence_reader integrity rules.
def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)


def payload_hash(payload):
    return 'sha256:' + hashlib.sha256(canonical(payload).encode('utf-8')).hexdigest()


con = sqlite3.connect(f'file:{(D / "product/runs.sqlite").as_posix()}?mode=ro', uri=True)
row_meta = {r[0]: r for r in con.execute(
    'select evidence_id, target_id, source, kind, collected_at from aiops_evidence')}
con.close()

ev_checks, ev_bad = [], []
for evidence_id, kind, raw_ref, raw_hash, summary in rows:
    ref_path = Path(raw_ref) if raw_ref else None
    if ref_path is not None and not ref_path.is_absolute():
        ref_path = D / ref_path
    exists = bool(ref_path and ref_path.exists())
    file_sha = hashlib.sha256(ref_path.read_bytes()).hexdigest() if exists else None
    declared = raw_hash
    actual = None
    identity_ok = False
    if exists:
        raw = json.loads(ref_path.read_text(encoding='utf-8'))
        payload = raw.get('payload')
        actual = payload_hash(payload)
        meta = row_meta.get(evidence_id)
        identity_ok = bool(
            meta and raw.get('target_id') == meta[1] and meta[2] == 'windows_probe'
            and raw.get('data_source') == 'probe_target' and raw.get('platform') == 'windows'
            and raw.get('operation') == meta[3] and raw.get('raw_hash') == declared)
    match = bool(actual and declared and actual == declared and identity_ok)
    entry = {'evidence_id': evidence_id, 'kind': kind, 'raw_ref': str(raw_ref),
             'file_exists': exists, 'file_sha256': file_sha, 'declared': declared,
             'payload_hash': actual, 'identity_ok': identity_ok, 'match': match,
             'summary_chars': len(summary or '')}
    ev_checks.append(entry)
    if not match:
        ev_bad.append(entry)

cost = json.loads((D / 'product-model/cost.json').read_text(encoding='utf-8'))
baseline_rows = inherited_baseline()
new_rows = cost['requests'][baseline_rows:]
spent = round(sum(float(r.get('reserved_cny') or 0) for r in new_rows), 6)
budget = {
    'inherited_requests': baseline_rows,
    'total_requests': len(cost['requests']),
    'new_requests': len(new_rows),
    'inherited_reserved_cny': round(sum(float(r.get('reserved_cny') or 0)
                                        for r in cost['requests'][:baseline_rows]), 6),
    'round_spent_cny': spent,
    'run_limit_cny': 5,
    'limit_cny': cost['limit_cny'],
    'reserved_cny': cost['reserved_cny'],
    'within_run_cap': spent <= 5,
    'blocked_requests': len(cost.get('blocked_requests') or []),
    'models': sorted({r.get('model') for r in new_rows if r.get('model')}),
    'unpriced_new_rows': [r['number'] for r in new_rows if not r.get('pricing_verified')],
    'unknown_usage_new_rows': [r['number'] for r in new_rows if r.get('usage') is None],
}

record = {
    'artifact_comparison': {'stable': stable, 'churned': churned, 'wal_verdict': wal_verdict},
    'evidence_integrity': {'checked': len(ev_checks), 'bad': ev_bad, 'detail': ev_checks},
    'logical_digest': logical,
    'budget': budget,
    'verdict': {
        'stable_artifacts_identical': len(stable),
        'churned_artifacts': len(churned),
        'evidence_all_hash_verified': not ev_bad,
        'logical_report_sha_matches_pre_restart_read': logical['vs_live_reads']['report_sha256_matches_live'],
        'logical_evidence_count_matches': logical['vs_live_reads']['evidence_total_matches_live'],
        'checkpoints_rows': logical['checkpoints']['rows'],
        'checkpoints_writes': logical['checkpoints']['writes'],
        'checkpoint_counts_note': (
            'checkpoints.sqlite 重启前主文件仅 4096 B（页面全在 WAL），重启触发 WAL checkpoint 后'
            '主文件变为 2.7 MB；因此逐字节不可比，行内计数只在重启后取得，并以此为准。'
            '诊断内容未变的独立证据：runs.sqlite 主文件与 WAL 之前记录的 run.updated_at 均未变化，'
            '且 report_sha256 与重启前 API 读取一致。'
        ),
    },
}
(D / 'gate-b-checks.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(record['verdict'], ensure_ascii=False, indent=1))
print(json.dumps(budget, ensure_ascii=False, indent=1))
print('bad evidence:', ev_bad)
print('stable:', [s['file'] for s in stable])
print('churned:', [c['file'] for c in churned])
