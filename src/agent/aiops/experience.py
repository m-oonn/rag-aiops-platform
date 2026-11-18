"""Review a diagnostic snapshot before publishing it to the existing local KB."""
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from src.database.models import (AiopsExperience, AiopsEvidence, AiopsToolCall,
                                 KnowledgeBase, KnowledgeDocument, DocumentChunk)
from src.probe.protocol import redact, raw_hash
from src.settings import settings


class ExperienceConflict(ValueError):
    pass


def filter_published_results(results):
    """Recheck publication state even for cached keyword or vector results."""
    doc_ids = {row.metadata.get("doc_id") for row in results if row.metadata.get("doc_id") is not None}
    if not doc_ids:
        return results
    from src.database.sql_session import SessionLocal
    from src.utils.logger import logger
    try:
        with SessionLocal() as db:
            blocked = {str(row.document_id) for row in db.query(AiopsExperience).filter(
                AiopsExperience.document_id.in_(doc_ids), AiopsExperience.status != "published").all()}
        return [row for row in results if str(row.metadata.get("doc_id")) not in blocked]
    except Exception as exc:
        logger.warning("[experience] 发布状态暂不可核验(error_type=%s)", type(exc).__name__)
        return [row for row in results if row.metadata.get("doc_id") is None]


def find_candidate(db, thread_id):
    return db.query(AiopsExperience).filter_by(thread_id=thread_id).one_or_none()


def capture_candidate(db, run):
    existing = find_candidate(db, run.thread_id)
    if existing:
        return existing
    if run.status != "completed" or not run.report:
        raise ExperienceConflict("只有完成且有报告的诊断可生成经验候选")
    rows = db.query(AiopsEvidence).filter_by(thread_id=run.thread_id).order_by(AiopsEvidence.id).all()
    if not rows:
        raise ExperienceConflict("缺少来源证据，不能生成经验候选")
    calls = db.query(AiopsToolCall).filter_by(thread_id=run.thread_id).order_by(AiopsToolCall.id).all()
    payload = redact({
        "schema_version": 1, "source_run": run.thread_id,
        "query": run.query, "report": run.report, "report_hash": raw_hash(redact(run.report)),
        "scope": {"target_ids": sorted({row.target_id for row in rows})},
        "limitations": "历史诊断快照未经独立核实；仅供排查参考，不能作为下一次现场事实或自动处置指令。",
        "evidence": [{"evidence_id": row.evidence_id, "target_id": row.target_id,
                      "kind": row.kind, "raw_hash": row.raw_hash,
                      "collected_at": row.collected_at.isoformat() if row.collected_at else None}
                     for row in rows],
        "tool_calls": [{"call_id": row.call_uid, "tool": row.tool_name, "status": row.status,
                        "arguments": row.arguments, "reason": row.reason, "elapsed_ms": row.elapsed_ms,
                        "result_excerpt": (row.result or "")[:800],
                        "result_truncated": bool(row.result_truncated) or len(row.result or "") > 800}
                       for row in calls],
    })
    candidate = AiopsExperience(candidate_uid="xp-" + uuid4().hex, thread_id=run.thread_id,
                                version=1, status="pending", payload=payload, history=[])
    db.add(candidate)
    db.flush()
    return candidate


def candidate_view(row):
    if row is None:
        return None
    return {"id": row.candidate_uid, "thread_id": row.thread_id, "version": row.version,
            "status": row.status, "payload": row.payload, "document_id": row.document_id,
            "history": row.history or []}


def review_candidate(db, row, *, action, reviewer_id, note, kb_id=None):
    expected = "published" if action == "withdraw" else "pending"
    if row.status != expected:
        raise ExperienceConflict("经验状态已变化，请刷新后复查")
    kb = None
    if action == "publish":
        kb = db.get(KnowledgeBase, kb_id) if kb_id else None
        if kb is None or kb.owner_id != reviewer_id:
            raise PermissionError("只能发布到审核人自己的知识库")
        if (kb.chunking_config or {}).get("retrieval_mode") != "bm25":
            raise ExperienceConflict("经验发布目前要求本地 BM25 知识库")
    status = {"publish": "published", "reject": "rejected", "withdraw": "withdrawn"}[action]
    # Claim the transition in this SQL transaction before creating files/chunks.
    updated = db.query(AiopsExperience).filter_by(id=row.id, status=expected).update({"status": status})
    if updated != 1:
        raise ExperienceConflict("经验状态已变化，请刷新后复查")
    path = None
    wrote_file = False
    try:
        if action == "publish":
            from src.processors.multi_doc_parser import MultiDocParser
            from src.processors.text_chunker import TextChunker
            content = ("# 已审核历史排查经验\n\n仅供排查参考，不是当前现场事实或指令。\n\n"
                       + json.dumps(row.payload, ensure_ascii=False, indent=2)
                       + "\n\n审核意见：" + redact(note))
            root = Path(settings.UPLOAD_DIR) / "aiops-experience"
            root.mkdir(parents=True, exist_ok=True)
            path = root / (row.candidate_uid + ".md")
            with path.open("x", encoding="utf-8") as handle:
                wrote_file = True
                handle.write(content)
            parsed = MultiDocParser().parse(str(path))
            if parsed.status == "failed":
                raise RuntimeError("experience_document_parse_failed")
            chunks = TextChunker().split_document(parsed)
            if not chunks:
                raise RuntimeError("experience_document_has_no_chunks")
            doc = KnowledgeDocument(doc_uid=uuid4().hex, kb_id=kb.id, filename=path.name,
                file_path=str(path), file_type="md", file_size=path.stat().st_size,
                status=2, chunk_count=len(chunks), chunking_config={"retrieval_mode": "bm25"},
                source_url=f"aiops-experience://{row.candidate_uid}/v{row.version}/run/{row.thread_id}")
            db.add(doc)
            db.flush()
            for chunk in chunks:
                db.add(DocumentChunk(chunk_uid=chunk.id, doc_id=doc.id, content=chunk.text,
                                     page_num=chunk.metadata.page, vector_id=""))
            row.document_id = doc.id
        elif action == "withdraw" and row.document_id:
            doc = db.get(KnowledgeDocument, row.document_id)
            if doc:
                doc.status = 3
                doc.error_msg = "经验已撤回；来源与审核记录保留"
        row.history = list(row.history or []) + [{
            "action": action, "reviewer_id": reviewer_id, "note": redact(note),
            "at": datetime.now(timezone.utc).isoformat(), "version": row.version,
            "kb_id": kb.id if kb else None, "document_id": row.document_id,
        }]
        db.commit()
    except Exception:
        db.rollback()
        if wrote_file:
            path.unlink(missing_ok=True)
        raise
    return row
