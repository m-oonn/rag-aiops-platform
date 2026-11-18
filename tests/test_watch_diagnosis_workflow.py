"""System-run ownership and HITL handoff regressions; no model calls."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.orm import sessionmaker

from src.agent.aiops import continuous_monitor as monitor, run_store
from src.database.models import AiopsApproval, OpsWatchIncident


@pytest.fixture
def store(engine, monkeypatch):
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(run_store, "SessionLocal", factory)
    monkeypatch.setattr(monitor, "SessionLocal", factory)
    return factory


def incident(store, thread_id=None, status="pending"):
    with store() as db:
        db.add(OpsWatchIncident(incident_uid="watch-case", service_name="mall",
            opened_at=datetime.now(timezone.utc), evidence={}, diagnosis_status=status,
            diagnosis_thread_id=thread_id))
        db.commit()


def test_system_evidence_identity_requires_persisted_incident_link(store):
    from src.agent.aiops.evidence_reader import can_read_run_evidence
    run_store.create_run("system-run", None, "watch mall")
    assert not can_read_run_evidence("system-run", None)
    incident(store, "system-run")
    assert can_read_run_evidence("system-run", None)
    assert not can_read_run_evidence("system-run", 42)
    assert not can_read_run_evidence("missing", None)


@pytest.mark.asyncio
async def test_executor_offers_evidence_reader_to_linked_system_run(store, monkeypatch):
    import importlib
    module = importlib.import_module("src.agent.aiops.executor")
    run_store.create_run("system-run", None, "watch mall")
    incident(store, "system-run")
    monkeypatch.setattr(module, "_get_tools_cached", AsyncMock(return_value=([], None)))
    tools, _ = await module._get_tools_for_state({"thread_id": "system-run", "user_id": None,
        "autonomous_investigation": True})
    assert [tool.name for tool in tools] == ["read_run_evidence"]


def test_watch_binds_run_before_planning_and_preserves_review_draft(store, monkeypatch):
    import src.agent.aiops as package
    incident(store)

    async def execute(**kwargs):
        run_store.create_run("system-run", None, kwargs["user_input"])
        yield {"type": "status", "thread_id": "system-run"}
        with store() as db:
            assert db.query(OpsWatchIncident).one().diagnosis_thread_id == "system-run"
        run_store.mark_pending_review("system-run", "review me")
        yield {"type": "pending_review", "thread_id": "system-run", "draft": "review me"}

    monkeypatch.setattr(package, "aiops_service", SimpleNamespace(execute=execute))
    asyncio.run(monitor._diagnose_incident("watch-case", "mall", asyncio.Semaphore(1)))
    with store() as db:
        row = db.query(OpsWatchIncident).one()
        assert (row.diagnosis_status, row.diagnosis_report) == ("pending_review", "review me")
    run_store.mark_completed("system-run", "approved report")
    with store() as db:
        row = db.query(OpsWatchIncident).one()
        assert (row.diagnosis_status, row.diagnosis_report) == ("completed", "approved report")


def test_admin_reads_only_linked_system_run(store, client, test_user, auth_headers, db, monkeypatch):
    from src.api.routers import aiops
    monkeypatch.setattr(aiops.aiops_service, "run_details", AsyncMock(return_value={}))
    run_store.create_run("system-run", None, "watch mall")
    run_store.create_run("orphan-run", None, "unlinked")
    run_store.create_run("other-run", 999, "private")
    incident(store, "system-run")
    for suffix in ("", "/steps", "/evidence", "/tool-calls"):
        assert client.get("/api/v1/aiops/runs/system-run" + suffix, headers=auth_headers).status_code == 404
    test_user.role = "admin"
    db.commit()
    for suffix in ("", "/steps", "/evidence", "/tool-calls"):
        assert client.get("/api/v1/aiops/runs/system-run" + suffix, headers=auth_headers).status_code == 200
    for thread_id in ("orphan-run", "other-run"):
        assert client.get(f"/api/v1/aiops/runs/{thread_id}", headers=auth_headers).status_code == 404


def test_report_review_endpoint_keeps_review_and_terminal_separate(store, client, test_user,
        auth_headers, db, monkeypatch):
    from src.api.routers import aiops
    run_store.create_run("system-run", None, "watch mall")
    incident(store, "system-run")
    run_store.mark_pending_review("system-run", "draft")
    test_user.role = "admin"
    db.commit()
    decisions = []

    async def resume(thread_id, decision):
        decisions.append(decision)
        run_store.mark_completed(thread_id, "approved")
        yield {"type": "complete", "thread_id": thread_id, "response": "approved"}

    monkeypatch.setattr(aiops.aiops_service, "resume", resume)
    root = "/api/v1/aiops/runs/system-run"
    assert client.post(root + "/continue", headers=auth_headers).status_code == 409
    response = client.post(root + "/review", json={"action": "approve"}, headers=auth_headers)
    assert response.status_code == 200 and '"complete"' in response.text
    assert decisions == [{"action": "approve", "instruction": None, "reviewer_id": test_user.id}]
    assert client.post(root + "/review", json={"action": "approve"}, headers=auth_headers).status_code == 409
    with store() as session:
        assert session.query(OpsWatchIncident).one().diagnosis_report == "approved"


def test_system_reader_reads_real_stored_file_and_rejects_other_run(store, tmp_path, monkeypatch):
    from src.agent.aiops.evidence_reader import read_run_evidence
    from src.probe.protocol import evidence
    from src.settings import settings
    monkeypatch.setattr(settings, "PROBE_EVIDENCE_DIR", str(tmp_path / "evidence"))
    run_store.create_run("system-run", None, "watch mall")
    incident(store, "system-run")
    raw = evidence(target_id="local", operation="services", payload={"service": "mall", "state": "stopped"})
    eid = run_store.add_evidence("system-run", None, "local", "services", raw)
    assert "stopped" in read_run_evidence("system-run", None, eid)["excerpt"]
    run_store.create_run("other-system", None, "unlinked")
    with pytest.raises(PermissionError):
        read_run_evidence("other-system", None, eid)
    with pytest.raises(PermissionError):
        read_run_evidence("system-run", 42, eid)


@pytest.mark.asyncio
async def test_watch_report_resumes_after_service_restart_with_audit(store, tmp_path, monkeypatch):
    import importlib
    module = importlib.import_module("src.agent.aiops.graph")
    monkeypatch.setattr(module.settings, "ENABLE_HITL", True)
    monkeypatch.setattr(module.settings, "PROBE_ENABLED", False)
    monkeypatch.setattr(module.settings, "TERMCP_ENABLED", False)
    monkeypatch.setattr(module.settings, "AIOPS_CHECKPOINT_DB_PATH", str(tmp_path / "checkpoint.sqlite"))
    monkeypatch.setattr(module, "planner", AsyncMock(return_value={"plan": ["check"]}))
    execute = AsyncMock(return_value={"plan": [], "past_steps": [("check", "observed")]})
    monkeypatch.setattr(module, "executor", execute)
    strategy = SimpleNamespace(decide=AsyncMock(return_value={"response": "review draft"}))
    monkeypatch.setattr(module.AIOpsService, "_create_strategy", lambda self: strategy)
    incident(store)
    first = module.AIOpsService()
    try:
        async for event in first.execute("watch mall", persist_run=True):
            if event.get("thread_id"):
                with store() as db:
                    db.query(OpsWatchIncident).update({"diagnosis_thread_id": event["thread_id"]})
                    db.commit()
        tid = event["thread_id"]
        assert event["type"] == "pending_review"
    finally:
        await first.close()
    reopened = module.AIOpsService()
    try:
        events = [e async for e in reopened.resume(tid, {"action": "approve", "reviewer_id": 7})]
        assert events[-1]["type"] == "complete"
        assert execute.await_count == 1
        with store() as db:
            row = db.query(OpsWatchIncident).one()
            assert (row.diagnosis_status, row.diagnosis_report) == ("completed", "review draft")
            assert db.query(AiopsApproval).one().reviewer_id == 7
        again = [e async for e in reopened.resume(tid, {"action": "approve", "reviewer_id": 7})]
        assert again[-1]["type"] == "error"
        with store() as db:
            assert db.query(AiopsApproval).count() == 1
    finally:
        await reopened.close()
