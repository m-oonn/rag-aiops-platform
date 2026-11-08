"""Read-only acceptance reader: authenticate, fetch run details + evidence, hash them.

Makes NO model calls: only POST /api/v1/auth/login/access-token and GET /api/v1/aiops/*.
The cost ledger and evidence files are hashed before and after so the caller can prove
that reading the persisted report creates zero new model requests.
"""
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import httpx
from rounddir import round_dir

D = round_dir()
phase = sys.argv[1] if len(sys.argv) > 1 else 'pre-restart'
out = D / f'acceptance-{phase}.json'
base = 'http://127.0.0.1:8200'

login = json.loads((D / 'login.json').read_text(encoding='utf-8'))
cost = D / 'product-model' / 'cost.json'
evdir = D / 'product' / 'evidence'
runs_db = D / 'product' / 'runs.sqlite'


def ledger():
    data = cost.read_bytes()
    body = json.loads(data)
    return {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
            'requests': len(body['requests']), 'reserved_cny': body['reserved_cny']}


def file_hashes():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(evdir.glob('*.json'))}


def thread_id_from_db():
    con = sqlite3.connect(f'file:{runs_db.as_posix()}?mode=ro', uri=True)
    try:
        return con.execute('select thread_id from aiops_runs order by id desc limit 1').fetchone()[0]
    finally:
        con.close()


before = {'ledger': ledger(), 'evidence_files': file_hashes()}
thread_id = thread_id_from_db()

with httpx.Client(base_url=base, timeout=60) as client:
    r = client.post('/api/v1/auth/login/access-token',
                    data={'username': login['username'], 'password': login['password']})
    r.raise_for_status()
    headers = {'Authorization': 'Bearer ' + r.json()['access_token']}
    detail = client.get(f'/api/v1/aiops/runs/{thread_id}', headers=headers)
    detail.raise_for_status()
    detail_body = detail.json()
    ev = client.get(f'/api/v1/aiops/runs/{thread_id}/evidence', headers=headers)
    ev.raise_for_status()
    ev_body = ev.json()
    first = ev_body['evidence'][0]['evidence_id'] if ev_body.get('evidence') else None
    item = None
    if first:
        i = client.get(f'/api/v1/aiops/runs/{thread_id}/evidence/{first}', headers=headers)
        item = {'evidence_id': first, 'status': i.status_code,
                'body': i.json() if i.status_code == 200 else i.text}
    owner_only = client.get(f'/api/v1/aiops/runs/{thread_id}/steps', headers=headers)
    steps = {'status': owner_only.status_code,
             'total': owner_only.json().get('total') if owner_only.status_code == 200 else None}

after = {'ledger': ledger(), 'evidence_files': file_hashes()}

diagnosis = detail_body.get('diagnosis') or {}
record = {
    'phase': phase,
    'thread_id': thread_id,
    'run_status': detail_body.get('status'),
    'report_sha256': hashlib.sha256((detail_body.get('report') or '').encode('utf-8')).hexdigest(),
    'report_bytes': len((detail_body.get('report') or '').encode('utf-8')),
    'diagnosis_kind': diagnosis.get('kind'),
    'root_cause_code': diagnosis.get('root_cause_code'),
    'confidence': diagnosis.get('confidence'),
    'diagnosis_keys': sorted(diagnosis.keys()),
    'investigation_keys': sorted((detail_body.get('investigation') or {}).keys()),
    'investigation_failure': detail_body.get('investigation_failure'),
    'steps': steps,
    'evidence_total': ev_body.get('total'),
    'can_read_raw': ev_body.get('can_read_raw'),
    'evidence_items': [
        {k: row.get(k) for k in ('evidence_id', 'kind', 'target_id', 'collected_at', 'summary')}
        for row in ev_body.get('evidence', [])
    ],
    'evidence_sample_item': item,
    'ledger_before': before['ledger'],
    'ledger_after': after['ledger'],
    'ledger_unchanged': before['ledger'] == after['ledger'],
    'evidence_files_before': before['evidence_files'],
    'evidence_files_after': after['evidence_files'],
    'evidence_files_unchanged': before['evidence_files'] == after['evidence_files'],
}
out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({k: record[k] for k in ('phase', 'thread_id', 'run_status', 'report_sha256',
                                        'diagnosis_kind', 'root_cause_code', 'evidence_total',
                                        'ledger_unchanged', 'evidence_files_unchanged')},
                 ensure_ascii=False))
print('requests:', record['ledger_before']['requests'], '->', record['ledger_after']['requests'])
print('written:', out)
