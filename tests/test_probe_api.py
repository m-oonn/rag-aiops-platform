from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.orm import sessionmaker

from src.agent.aiops import run_store
from src.probe.protocol import evidence
from src.settings import settings


@pytest.fixture
def probe_run(engine, test_user, tmp_path, monkeypatch):
    monkeypatch.setattr(run_store, 'SessionLocal', sessionmaker(bind=engine))
    monkeypatch.setattr(settings, 'PROBE_EVIDENCE_DIR', str(tmp_path))
    thread_id = 'probe-api-' + uuid4().hex
    run_store.create_run(thread_id, test_user.id, 'read-only evidence API check')
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='services',
                   payload={'state': 'running', 'password': 'must-not-appear'})
    evidence_id = run_store.add_evidence(thread_id, test_user.id, settings.PROBE_TARGET_ID, 'services', raw)
    run_store.add_step_snapshot(thread_id, 0, 'executor', {'result': 'running'})
    return thread_id, evidence_id


def test_owner_sees_summary_without_raw(client, auth_headers, probe_run):
    thread_id, evidence_id = probe_run
    response = client.get(f'/api/v1/aiops/runs/{thread_id}/evidence', headers=auth_headers)
    assert response.status_code == 200
    assert response.json()['can_read_raw'] is False
    assert response.json()['total'] == 1
    item = client.get(f'/api/v1/aiops/runs/{thread_id}/evidence/{evidence_id}', headers=auth_headers).json()
    assert 'raw' not in item and 'raw_ref' not in item
    assert 'must-not-appear' not in response.text


def test_auditor_owner_can_read_redacted_raw(client, auth_headers, probe_run, test_user, db):
    thread_id, evidence_id = probe_run
    test_user.role = 'auditor'
    db.commit()
    response = client.get(f'/api/v1/aiops/runs/{thread_id}/evidence/{evidence_id}', headers=auth_headers)
    assert response.status_code == 200
    assert response.json()['raw']['payload']['password'] == '[REDACTED]'
    assert 'must-not-appear' not in response.text


@pytest.mark.parametrize('suffix', ['evidence', 'steps', 'evidence/{id}'])
def test_other_owner_cannot_read_run(client, auth_headers, probe_run, other_user, suffix):
    thread_id, evidence_id = probe_run
    run_store._update_run(thread_id, user_id=other_user.id)
    suffix = suffix.replace('{id}', evidence_id)
    response = client.get(f'/api/v1/aiops/runs/{thread_id}/{suffix}', headers=auth_headers)
    assert response.status_code == 404


def test_unregistered_target_and_unauthenticated_requests_are_rejected(client, auth_headers):
    assert client.get('/api/v1/aiops/targets/not-configured/status', headers=auth_headers).status_code == 404
    assert client.get('/api/v1/aiops/runs/no-run/evidence').status_code == 401


def test_run_details_only_loaded_after_owner_check(client, auth_headers, probe_run, other_user, monkeypatch):
    from src.api.routers.aiops import aiops_service
    details = {'diagnosis': None, 'investigation': {'candidates': [], 'events': [], 'next_check': 'check port'}}
    load = AsyncMock(return_value=details)
    monkeypatch.setattr(aiops_service, 'run_details', load)
    tid, _ = probe_run
    url = f'/api/v1/aiops/runs/{tid}'
    assert client.get(url).status_code == 401
    load.assert_not_awaited()
    result = client.get(url, headers=auth_headers)
    assert result.status_code == 200 and result.json()['investigation'] == details['investigation']
    load.assert_awaited_once_with(tid)
    load.reset_mock()
    run_store._update_run(tid, user_id=other_user.id)
    assert client.get(url, headers=auth_headers).status_code == 404
    load.assert_not_awaited()
