"""Verify real evidence through production routes/auth using a copied run DB.

Uses in-process ASGI HTTP; does not claim a deployed server/browser check.
No dependency overrides, model calls or changes to the source database.
"""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def verify(source: Path):
    source = source.resolve()
    summary = json.loads((source / 'summary.json').read_text(encoding='utf-8'))
    runs = [item for item in summary['cases'] if item['case'].startswith('fixed_model_graph_')]
    assert len(runs) == 2 and all(item['status'] == 'passed' for item in runs)
    output = source / ('api-verification-' + uuid4().hex)
    output.mkdir()
    from scripts.windows_probe import _set_acl
    if os.name == 'nt':
        _set_acl(output)
    source_db = sqlite3.connect((source / 'ledger.sqlite').as_uri() + '?mode=ro', uri=True)
    destination = sqlite3.connect(output / 'api.sqlite')
    try:
        source_db.backup(destination)
    finally:
        destination.close()
        source_db.close()
    os.environ['DATABASE_URL'] = 'sqlite:///' + (output / 'api.sqlite').as_posix()
    os.environ['SECRET_KEY'] = uuid4().hex + uuid4().hex
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.api.routers.aiops import router
    from src.database.sql_session import SessionLocal
    from src.database.models import User
    from src.utils.security import create_access_token
    from src.settings import settings
    from src.probe.evidence import validate_evidence
    from datetime import datetime, timezone
    assert settings.DATABASE_URL == os.environ['DATABASE_URL']
    db = SessionLocal()
    try:
        for uid, role in [(1, 'user'), (2, 'user'), (3, 'auditor')]:
            assert db.get(User, uid) is None, 'not an isolated test database'
            db.add(User(id=uid, username='local-api-test-' + str(uid),
                email=f'local-api-test-{uid}@example.invalid', password_hash='login-disabled-test',
                role=role, is_active=True))
        db.commit()
    finally:
        db.close()
    app = FastAPI()
    app.include_router(router, prefix='/api/v1/aiops')
    checks = []
    headers = {uid: {'Authorization': 'Bearer ' + create_access_token(uid)} for uid in (1, 2, 3)}
    with TestClient(app) as client:
        for run in runs:
            tid = run['thread_id']
            base = '/api/v1/aiops/runs/' + tid
            assert client.get(base + '/evidence').status_code == 401
            assert client.get(base + '/evidence', headers=headers[2]).status_code == 404
            assert client.get(base + '/evidence', headers=headers[3]).status_code == 404
            response = client.get(base + '/evidence', headers=headers[1])
            assert response.status_code == 200
            ledger = response.json()
            assert ledger['total'] == 4 and ledger['can_read_raw'] is False
            for item in ledger['evidence']:
                eid = item['evidence_id']
                path = base + '/evidence/' + eid
                assert client.get(path, headers=headers[2]).status_code == 404
                normal = client.get(path, headers=headers[1])
                assert normal.status_code == 200
                assert 'raw' not in normal.json() and 'raw_ref' not in normal.json()
                assert item['target_id'] == summary['target_id']
            checks.append({'case': run['case'], 'owner_summary_count': 4,
                           'unauthenticated': 401, 'other_user': 404, 'other_auditor': 404})
        db = SessionLocal()
        try:
            db.get(User, 1).role = 'auditor'
            db.commit()
        finally:
            db.close()
        raw_count = 0
        for run in runs:
            base = '/api/v1/aiops/runs/' + run['thread_id'] + '/evidence'
            ledger = client.get(base, headers=headers[1]).json()
            assert ledger['can_read_raw'] is True
            for item in ledger['evidence']:
                response = client.get(base + '/' + item['evidence_id'], headers=headers[1])
                assert response.status_code == 200
                raw = response.json()['raw']
                # Historical audit: validate at collection time, not as live facts.
                when = datetime.fromisoformat(raw['collected_at'].replace('Z', '+00:00'))
                validate_evidence(raw, target_id=summary['target_id'], now=when)
                assert raw['raw_hash'] == item['raw_hash']
                raw_count += 1
        assert client.get('/api/v1/aiops/targets/not-registered/status', headers=headers[1]).status_code == 404
    result = {'ok': True, 'checked_at': datetime.now(timezone.utc).isoformat(), 'checks': checks,
        'auditor_owner_raw_count': raw_count, 'model_calls': 0, 'source_modified': False,
        'transport': 'in-process ASGI HTTP with production router, JWT auth and database dependency',
        'browser_or_deployed_server_verified': False, 'evidence_is_historical': True}
    (output / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'output': str(output), **result}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    verify(parser.parse_args().source)
