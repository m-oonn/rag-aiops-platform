"""Candidate/review/publication/retrieval boundary; isolated SQL, no models."""
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import sessionmaker
from src.agent.aiops import run_store
from src.database.models import KnowledgeBase, KnowledgeDocument, DocumentChunk
from src.probe.protocol import evidence
from src.settings import settings

ROOT = "/api/v1/aiops/runs/experience-run/experience"


@pytest.fixture
def prepared(db, engine, test_user, monkeypatch, tmp_path):
    import src.database.sql_session as sql
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(run_store, "SessionLocal", factory)
    monkeypatch.setattr(sql, "SessionLocal", factory)
    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(settings, "PROBE_EVIDENCE_DIR", str(tmp_path / "evidence"))
    db.add(KnowledgeBase(id=901, kb_uid="reviewed", name="Reviewed experience",
        owner_id=test_user.id, chunking_config={"retrieval_mode": "bm25"}))
    db.add(KnowledgeBase(id=902, kb_uid="online", name="Online", owner_id=test_user.id))
    db.add(KnowledgeBase(id=903, kb_uid="foreign", name="Foreign", owner_id=999,
        chunking_config={"retrieval_mode": "bm25"}))
    db.commit()
    run_store.create_run("experience-run", test_user.id, "应用失败排查")
    raw = evidence(target_id="local", operation="dependency_probe",
        payload={"dependency": "downstream", "http": {"status": 503}})
    eid = run_store.add_evidence("experience-run", test_user.id, "local", "dependency_probe", raw)
    run_store.mark_completed("experience-run", "下游连接失败；仍须核查请求链，不能直接证明停止原因。")
    return {"eid": eid, "factory": factory}


def admin(db, user):
    user.role = "admin"
    db.commit()


def test_completion_creates_pending_candidate_without_retrievable_document(prepared, client, auth_headers, db):
    response = client.get(ROOT, headers=auth_headers)
    assert response.status_code == 200
    candidate = response.json()["experience"]
    assert candidate["status"] == "pending" and candidate["version"] == 1
    assert candidate["payload"]["scope"]["target_ids"] == ["local"]
    assert candidate["payload"]["evidence"][0]["evidence_id"] == prepared["eid"]
    assert candidate["payload"]["evidence"][0]["raw_hash"].startswith("sha256:")
    again = client.post(ROOT, headers=auth_headers)
    assert again.status_code == 200 and again.json()["experience"]["id"] == candidate["id"]
    assert db.query(KnowledgeDocument).count() == 0


def test_publish_uses_existing_bm25_and_remains_reference_material(prepared, client, auth_headers, test_user, db, monkeypatch):
    import importlib
    planner = importlib.import_module("src.agent.aiops.planner")
    admin(db, test_user)
    response = client.post(ROOT + "/review", headers=auth_headers,
        json={"action": "publish", "kb_id": 901, "note": "仅供排查连接失败，未确认停止原因。"})
    assert response.status_code == 200, response.text
    candidate = response.json()["experience"]
    assert candidate["status"] == "published"
    doc = db.get(KnowledgeDocument, candidate["document_id"])
    assert doc.status == 2 and doc.chunk_count > 0
    assert doc.chunking_config["retrieval_mode"] == "bm25"
    assert prepared["eid"] in Path(doc.file_path).read_text(encoding="utf-8")
    assert db.query(DocumentChunk).filter_by(doc_id=doc.id).count() == doc.chunk_count
    monkeypatch.setenv("ENABLE_EXPERIENCE_CONTEXT", "true")
    payload = json.loads(planner._retrieve_experience("下游连接失败", kb_ids=[901]))
    assert payload["data_source"] == "knowledge_base"
    assert "不是当前现场事实" in payload["purpose"]
    assert payload["results"][0]["source_url"].startswith("aiops-experience://")
    assert candidate["history"][0]["reviewer_id"] == test_user.id
    assert client.post(ROOT + "/review", headers=auth_headers,
        json={"action": "publish", "kb_id": 901, "note": "重复"}).status_code == 409


def test_review_enforces_admin_and_library_ownership(prepared, client, auth_headers, test_user, db):
    body = {"action": "publish", "kb_id": 901, "note": "审核"}
    assert client.post(ROOT + "/review", headers=auth_headers, json=body).status_code == 403
    admin(db, test_user)
    assert client.post(ROOT + "/review", headers=auth_headers, json={**body, "kb_id": 903}).status_code == 403
    assert client.post(ROOT + "/review", headers=auth_headers, json={**body, "kb_id": 902}).status_code == 409
    run_store.create_run("foreign-run", 999, "private")
    assert client.get(ROOT.replace("experience-run", "foreign-run"), headers=auth_headers).status_code == 404


def test_rejection_is_retained_and_never_published(prepared, client, auth_headers, test_user, db):
    admin(db, test_user)
    response = client.post(ROOT + "/review", headers=auth_headers, json={"action": "reject", "note": "证据不足"})
    assert response.status_code == 200
    assert response.json()["experience"]["status"] == "rejected"
    assert db.query(KnowledgeDocument).count() == 0
    assert client.post(ROOT + "/review", headers=auth_headers,
        json={"action": "publish", "kb_id": 901, "note": "重试"}).status_code == 409


def test_withdrawal_stays_out_of_retrieval_even_after_document_reprocess(prepared, client, auth_headers, test_user, db, monkeypatch):
    from src.retrieval.knowledge_bm25 import retrieve_knowledge_bm25
    from src.retrieval.hybrid_retriever import HybridRetriever
    import mcp_servers.rag_server as rag
    from src.database.local_vector_store import LocalVectorStore
    monkeypatch.setattr(LocalVectorStore, "get_all_chunks", lambda self: [])
    admin(db, test_user)
    response = client.post(ROOT + "/review", headers=auth_headers,
        json={"action": "publish", "kb_id": 901, "note": "审核"})
    assert response.status_code == 200
    doc_id = response.json()["experience"]["document_id"]
    assert retrieve_knowledge_bm25(db, 901, "下游连接失败")
    hybrid = HybridRetriever(vector_retriever=Mock(retrieve=Mock(return_value=[])))
    assert hybrid.retrieve("下游连接失败", kb_ids=[901])
    response = client.post(ROOT + "/review", headers=auth_headers, json={"action": "withdraw", "note": "结论需补证"})
    assert response.status_code == 200
    candidate = response.json()["experience"]
    assert candidate["status"] == "withdrawn" and candidate["version"] == 1
    assert [row["action"] for row in candidate["history"]] == ["publish", "withdraw"]
    doc = db.get(KnowledgeDocument, doc_id)
    doc.status = 2
    db.commit()
    assert retrieve_knowledge_bm25(db, 901, "下游连接失败") == []
    assert hybrid.retrieve("下游连接失败", kb_ids=[901]) == []
    assert "error" in rag.get_document_info.fn(doc_id)
    from src.models.vector import SearchResult
    from src.agent.aiops.experience import filter_published_results
    cached_vector = SearchResult(id="cached", text="下游连接失败", score=1,
                                 metadata={"doc_id": str(doc_id)})
    assert filter_published_results([cached_vector]) == []
    assert "仍须核查" in run_store.get_run("experience-run").report


def test_publication_failure_keeps_pending_and_rolls_back_document(prepared, client, auth_headers, test_user, db, monkeypatch):
    from src.processors.text_chunker import TextChunker
    admin(db, test_user)
    monkeypatch.setattr(TextChunker, "split_document", Mock(side_effect=RuntimeError("chunker failed")))
    response = client.post(ROOT + "/review", headers=auth_headers,
        json={"action": "publish", "kb_id": 901, "note": "审核"})
    assert response.status_code == 503
    assert client.get(ROOT, headers=auth_headers).json()["experience"]["status"] == "pending"
    assert db.query(KnowledgeDocument).count() == 0
    assert not list(Path(settings.UPLOAD_DIR).rglob("*.md"))


def test_missing_evidence_cannot_be_promoted_to_experience(prepared, client, auth_headers, test_user):
    run_store.create_run("no-evidence", test_user.id, "unknown")
    run_store.mark_completed("no-evidence", "unsourced")
    response = client.post(ROOT.replace("experience-run", "no-evidence"), headers=auth_headers)
    assert response.status_code == 409


def test_published_draft_redacts_secrets_and_keeps_call_history(prepared, client, auth_headers, test_user, db):
    from src.database.models import AiopsExperience
    db.query(AiopsExperience).delete()
    db.commit()
    cid = run_store.start_tool_call("experience-run", test_user.id, 0, "read config", "call-1", "probe_configuration",
                                   {"password": "never-publish", "service": "app"})
    assert run_store.finish_tool_call(cid, status="blocked", reason="outside_scope", result="token=never-publish", elapsed_ms=4)
    run_store.mark_completed("experience-run", "连接失败 token=never-publish")
    response = client.get(ROOT, headers=auth_headers)
    assert "never-publish" not in response.text
    call = response.json()["experience"]["payload"]["tool_calls"][0]
    assert call["call_id"] == cid and call["status"] == "blocked" and call["elapsed_ms"] == 4


def test_publication_state_read_failure_does_not_return_cached_sql_content(prepared, monkeypatch):
    import src.database.sql_session as sql
    from src.agent.aiops.experience import filter_published_results
    from src.models.vector import SearchResult
    monkeypatch.setattr(sql, "SessionLocal", Mock(side_effect=RuntimeError("database unavailable")))
    sql_result = SearchResult(id="sql", text="cached", score=1, metadata={"doc_id": 1})
    external = SearchResult(id="external", text="local runbook", score=1, metadata={})
    assert filter_published_results([sql_result, external]) == [external]
