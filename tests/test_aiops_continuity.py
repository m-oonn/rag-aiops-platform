"""AIOps continuity contracts; isolated SQL and fake model events only."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import sessionmaker

from src.agent.aiops import run_store
from src.api.routers import aiops
from src.settings import settings


@pytest.fixture
def store(engine, monkeypatch, tmp_path):
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(run_store, "SessionLocal", factory)
    monkeypatch.setattr(settings, "PROBE_EVIDENCE_DIR", str(tmp_path / "evidence"))
    return factory


@pytest.mark.parametrize("query", ["", " \n\t", "x" * 12001], ids=["empty", "blank", "oversize"])
def test_invalid_input_is_rejected_before_stream_creation(query):
    with pytest.raises(ValidationError):
        aiops.AIOpsRequest(query=query)


@pytest.mark.parametrize("session_id", ["a/b", "a" * 129, "../escape"], ids=["slash", "oversize", "path"])
def test_session_prefix_cannot_create_unreadable_run_ids(session_id):
    with pytest.raises(ValidationError):
        aiops.AIOpsRequest(query="故障", session_id=session_id)


@pytest.mark.asyncio
async def test_run_reread_returns_original_input_and_server_times(store, test_user, monkeypatch):
    run_store.create_run("reread", test_user.id, "原始故障描述")
    monkeypatch.setattr(aiops.aiops_service, "run_details", AsyncMock(return_value={"diagnosis": None}))
    result = await aiops.get_run_status("reread", test_user)
    assert result["query"] == "原始故障描述"
    assert result["created_at"].endswith("+00:00")
    assert result["updated_at"].endswith("+00:00")


@pytest.mark.asyncio
async def test_checkpoint_read_failure_preserves_durable_report(store, test_user, monkeypatch):
    run_store.create_run("checkpoint-error", test_user.id, "故障")
    run_store.mark_completed("checkpoint-error", "持久化报告")
    monkeypatch.setattr(aiops.aiops_service, "run_details", AsyncMock(side_effect=OSError("offline")))
    result = await aiops.get_run_status("checkpoint-error", test_user)
    assert result["report"] == "持久化报告"
    assert result["details_status"] == "unavailable"


@pytest.mark.asyncio
async def test_api_always_uses_persisted_runs(monkeypatch, test_user):
    arguments = []
    async def fake_execute(**kwargs):
        arguments.append(kwargs)
        yield {"type": "complete", "thread_id": "persisted", "response": "ok"}
    monkeypatch.setattr(aiops.aiops_service, "execute", fake_execute)
    response = await aiops.diagnose_stream(aiops.AIOpsRequest(query="故障"), test_user)
    async for _ in response.body_iterator:
        pass
    assert arguments[0]["persist_run"] is True


def test_database_unavailability_is_not_not_found(client, auth_headers, monkeypatch):
    monkeypatch.setattr(run_store, "SessionLocal", lambda: (_ for _ in ()).throw(OSError("offline")))
    result = client.get("/api/v1/aiops/runs/unavailable", headers=auth_headers)
    assert result.status_code == 503


def test_finished_run_drops_obsolete_terminal_approval(store):
    run_store.create_run("old-approval", 1, "故障")
    run_store.mark_pending_terminal("old-approval", {"request_id": "old"})
    run_store.mark_completed("old-approval", "报告")
    assert run_store.get_run("old-approval").terminal_approval is None


def test_required_state_write_failure_does_not_report_success(monkeypatch):
    monkeypatch.setattr(run_store, "SessionLocal", lambda: (_ for _ in ()).throw(OSError("offline")))
    with pytest.raises(OSError):
        run_store.mark_pending_review("unavailable", "草稿")


def test_expired_evidence_from_the_future_is_not_fresh(store):
    from src.probe.protocol import evidence
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    raw = evidence(target_id="t", operation="inventory", payload={}, collected_at=future)
    eid = run_store.add_evidence("future", 1, "t", "inventory", raw)
    assert run_store.list_evidence("future", 1)[0]["fresh"] is False
    assert run_store.get_evidence("future", eid, 1)["fresh"] is False


def test_raw_file_tampering_is_explicit_in_the_evidence_view(store):
    import json
    from pathlib import Path
    from src.probe.protocol import evidence
    raw = evidence(target_id="t", operation="inventory", payload={"count": 1})
    eid = run_store.add_evidence("raw-tamper", 1, "t", "inventory", raw)
    row = run_store.get_evidence("raw-tamper", eid, 1)
    Path(row["raw_ref"]).write_text(json.dumps({**raw, "payload": {"count": 999}}), encoding="utf-8")
    result = run_store.get_evidence("raw-tamper", eid, 1, include_raw=True)
    assert result["raw"] is None
    assert result["raw_status"] == "integrity_failed"


def test_knowledge_reference_can_locate_a_chunk_after_the_first_page(client, auth_headers, db, test_user):
    from src.database.models import KnowledgeBase, KnowledgeDocument, DocumentChunk
    kb = KnowledgeBase(kb_uid="reference-kb", name="reference", owner_id=test_user.id)
    db.add(kb)
    db.flush()
    doc = KnowledgeDocument(doc_uid="reference-doc", kb_id=kb.id, filename="reference.md", file_path="unused", file_type="md", status=2)
    db.add(doc)
    db.flush()
    db.add_all([DocumentChunk(chunk_uid=f"reference-{i}", doc_id=doc.id, content=f"段落{i}", vector_id="") for i in range(101)])
    db.commit()
    result = client.get(f"/api/v1/knowledge-bases/documents/{doc.id}/chunks?chunk_uid=reference-100&limit=1", headers=auth_headers)
    assert result.status_code == 200
    assert [row["chunk_uid"] for row in result.json()] == ["reference-100"]
