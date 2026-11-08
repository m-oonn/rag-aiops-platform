"""Read-only: dump the full diagnosis JSON for the 036 run over the official read API.

Only POST /api/v1/auth/login/access-token + GET /api/v1/aiops/* are used, so this makes
zero model calls (the cost ledger is hashed before and after to prove it).
"""
import hashlib
import json
import sqlite3
from pathlib import Path

import httpx
from rounddir import round_dir

D = round_dir()
cost = D / 'product-model' / 'cost.json'
ledger_before = hashlib.sha256(cost.read_bytes()).hexdigest()
body_before = json.loads(cost.read_text(encoding='utf-8'))
n_before = len(body_before['requests'])

con = sqlite3.connect(f'file:{(D / "product/runs.sqlite").as_posix()}?mode=ro', uri=True)
thread_id = con.execute('select thread_id from aiops_runs order by id desc limit 1').fetchone()[0]
con.close()

login = json.loads((D / 'login.json').read_text(encoding='utf-8'))
with httpx.Client(base_url='http://127.0.0.1:8200', timeout=60) as client:
    token = client.post('/api/v1/auth/login/access-token',
                        data={'username': login['username'], 'password': login['password']}
                        ).json()['access_token']
    detail = client.get(f'/api/v1/aiops/runs/{thread_id}',
                        headers={'Authorization': 'Bearer ' + token})
    detail.raise_for_status()
    payload = detail.json()

(D / 'run-detail.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

body_after = json.loads(cost.read_text(encoding='utf-8'))
print('ledger bytes unchanged:', hashlib.sha256(cost.read_bytes()).hexdigest() == ledger_before,
      '| requests', n_before, '->', len(body_after['requests']))

diag = payload.get('diagnosis') or {}
print('kind:', diag.get('kind'), '| code:', diag.get('root_cause_code'))
print('target:', diag.get('target_id'), '| version:', diag.get('version'))
print('scope:', json.dumps(diag.get('scope'), ensure_ascii=False)[:500])
print('evidence n:', len(diag.get('evidence') or []))
print('mechanisms:', json.dumps(diag.get('mechanisms'), ensure_ascii=False)[:600])
print('mechanism_config:', json.dumps(diag.get('mechanism_config'), ensure_ascii=False)[:500])
print('validation_issues:', json.dumps(diag.get('validation_issues'), ensure_ascii=False)[:1200])
print('observation_conflicts:', json.dumps(diag.get('observation_conflicts'), ensure_ascii=False)[:600])
print('contradictions:', json.dumps(diag.get('contradictions'), ensure_ascii=False)[:600])
print('unresolved:', json.dumps(diag.get('unresolved_questions'), ensure_ascii=False)[:600])
print('stop_reason:', diag.get('stop_reason'))
print('alternatives:', len(diag.get('alternatives') or []))
for a in (diag.get('alternatives') or []):
    print('  -', a.get('status'), '|', (a.get('explanation') or '')[:100])
inv = payload.get('investigation') or {}
print('investigation candidates:', len(inv.get('candidates') or []),
      '| check_progress:', len(inv.get('check_progress') or []),
      '| events:', len(inv.get('events') or []))
print('blocked_reason:', inv.get('blocked_reason'))
