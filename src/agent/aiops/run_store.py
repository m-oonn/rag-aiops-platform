"""AIOps 诊断运行/审批记录持久化（HITL 支撑）。

状态机：running → pending_review → approved / rejected → completed；异常 → failed。
同步 SQLite 写（快、幂等），异常只告警不阻断主流程（沿用项目降级约定）。
"""

import json
from typing import Optional

from src.database.models import AiopsApproval, AiopsRun, AiopsStepSnapshot, AiopsEvidence, ProbeTarget, ProbeSnapshot
from src.database.sql_session import Base, SessionLocal, engine
from src.utils.logger import logger
from src.probe.protocol import redact, raw_hash
from src.probe.storage import write_evidence_file
from src.settings import settings
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

# 幂等建表（与 main.py 启动时 Base.metadata.create_all 同模式）：
# 保证脚本/测试等未经过 FastAPI 启动的入口直连时新表也存在。
Base.metadata.create_all(bind=engine)

# 状态常量（与 aiops_runs.status 字段对齐）
STATUS_RUNNING = "running"
STATUS_PENDING_REVIEW = "pending_review"
STATUS_PENDING_TERMINAL = "pending_terminal"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


def _utc_datetime(value: datetime | None) -> datetime | None:
    """Normalize SQLite's naive datetime values to aware UTC datetimes."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime | None) -> str | None:
    normalized = _utc_datetime(value)
    return normalized.isoformat() if normalized else None


def _parse_utc(value) -> datetime | None:
    if isinstance(value, datetime):
        return _utc_datetime(value)
    if isinstance(value, str) and value.strip():
        try:
            return _utc_datetime(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _update_run(thread_id: str, *, required: bool = False, **fields) -> None:
    try:
        db = SessionLocal()
        try:
            updated = db.query(AiopsRun).filter(AiopsRun.thread_id == thread_id).update(fields)
            if required and updated != 1:
                raise RuntimeError("Persistent diagnostic run is missing")
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.warning("[run_store] 更新运行记录失败(thread=%s): %s", thread_id, e)
        if required:
            raise


def create_run(thread_id: str, user_id: Optional[int], query: str) -> None:
    try:
        db = SessionLocal()
        try:
            db.add(AiopsRun(
                thread_id=thread_id, user_id=user_id, query=query, status=STATUS_RUNNING,
            ))
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.warning("[run_store] 创建运行记录失败(thread=%s): %s", thread_id, e)
        raise


def mark_pending_review(thread_id: str, report: str) -> None:
    _update_run(thread_id, status=STATUS_PENDING_REVIEW, report=report)


def mark_pending_terminal(thread_id: str, approval: dict) -> None:
    _update_run(thread_id, required=True, status=STATUS_PENDING_TERMINAL, terminal_approval=approval)


def mark_approved(thread_id: str) -> None:
    _update_run(thread_id, status=STATUS_APPROVED)


def mark_rejected(thread_id: str) -> None:
    _update_run(thread_id, status=STATUS_REJECTED)


def mark_completed(thread_id: str, report: str) -> None:
    _update_run(thread_id, status=STATUS_COMPLETED, report=report)


def mark_failed(thread_id: str, error: str) -> None:
    _update_run(thread_id, status=STATUS_FAILED, report=error)


def add_approval(
    thread_id: str, reviewer_id: Optional[int], action: str, instruction: Optional[str]
) -> None:
    try:
        db = SessionLocal()
        try:
            run = db.query(AiopsRun).filter(AiopsRun.thread_id == thread_id).first()
            if not run:
                return
            db.add(AiopsApproval(
                run_id=run.id, reviewer_id=reviewer_id,
                action=action, instruction=instruction,
            ))
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.warning("[run_store] 记录审批失败(thread=%s): %s", thread_id, e)


def get_run(thread_id: str) -> Optional[AiopsRun]:
    try:
        db = SessionLocal()
        try:
            return db.query(AiopsRun).filter(AiopsRun.thread_id == thread_id).first()
        finally:
            db.close()
    except Exception as e:
        logger.warning("[run_store] 查询运行记录失败(thread=%s): %s", thread_id, e)
        return None


# ═══════════════════════════════════════════════════════════════
# 步级快照（B3：可回放/可审计；以 thread_id 为键，独立于 HITL run 记录）
# ═══════════════════════════════════════════════════════════════


def add_step_snapshot(thread_id: str, step_index: int, node: str, payload: dict) -> None:
    """落一条步级快照（best-effort：异常只告警，不阻断诊断主流程）。

    payload 由调用方给出 JSON-安全 dict；此处再兜底 default=str 防序列化失败。
    """
    try:
        db = SessionLocal()
        try:
            db.add(AiopsStepSnapshot(
                thread_id=thread_id,
                step_index=step_index,
                node=node,
                payload=json.dumps(payload or {}, ensure_ascii=False, default=str),
            ))
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.warning("[run_store] 记录步快照失败(thread=%s): %s", thread_id, e)


def list_step_snapshots(thread_id: str) -> list:
    """按序返回某诊断的步级快照（回放数据源）；失败返回空列表（不抛异常）。"""
    try:
        db = SessionLocal()
        try:
            rows = (
                db.query(AiopsStepSnapshot)
                .filter(AiopsStepSnapshot.thread_id == thread_id)
                .order_by(AiopsStepSnapshot.step_index.asc(), AiopsStepSnapshot.id.asc())
                .all()
            )
            out = []
            for r in rows:
                try:
                    payload = json.loads(r.payload) if r.payload else {}
                except (TypeError, ValueError):
                    payload = {}
                out.append({
                    "step_index": r.step_index,
                    "node": r.node,
                    "payload": payload,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                })
            return out
        finally:
            db.close()
    except Exception as e:
        logger.warning("[run_store] 查询步快照失败(thread=%s): %s", thread_id, e)
        return []


def upsert_probe_target(target_id: str, *, platform: str = "windows", hostname: str | None = None,
                        agent_version: str | None = None, capabilities: list | None = None,
                        status: str = "online", last_seen: datetime | None = None) -> None:
    """Persist only the hello summary; token/config never enters this table."""
    db = SessionLocal()
    try:
        row = db.query(ProbeTarget).filter(ProbeTarget.target_id == target_id).first()
        values = {"platform": platform, "hostname": hostname, "agent_version": agent_version,
                  "capabilities": capabilities or [], "status": status,
                  "last_seen": last_seen or datetime.now(timezone.utc)}
        if row:
            for key, value in values.items():
                setattr(row, key, value)
        else:
            db.add(ProbeTarget(target_id=target_id, **values))
        db.commit()
    finally:
        db.close()


def add_evidence(thread_id: str, user_id: int | None, target_id: str, kind: str,
                 raw: dict, *, source: str = "windows_probe", ttl_seconds: int = 180) -> str:
    """Write a redacted ledger row and protected raw file, returning evidence_id."""
    evidence_id = "ev-" + uuid4().hex
    safe = redact(raw)
    digest = raw.get("raw_hash") or raw_hash(raw.get("payload", raw))
    root = Path(settings.PROBE_EVIDENCE_DIR)
    raw_path = write_evidence_file(root, f"{evidence_id}.json",
                                   json.dumps(safe, ensure_ascii=False, default=str))
    collected_dt = _parse_utc(raw.get("collected_at")) or datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        db.add(AiopsEvidence(evidence_id=evidence_id, thread_id=thread_id, user_id=user_id,
                             target_id=target_id, source=source, kind=kind,
                             collected_at=collected_dt, summary_redacted=json.dumps(safe.get("payload", safe), ensure_ascii=False, default=str)[:4000],
                             raw_ref=str(raw_path), raw_hash=digest, fresh_until=collected_dt + timedelta(seconds=ttl_seconds)))
        db.commit()
    finally:
        db.close()
    return evidence_id


def list_evidence(thread_id: str, user_id: int | None = None) -> list[dict]:
    db = SessionLocal()
    try:
        query = db.query(AiopsEvidence).filter(AiopsEvidence.thread_id == thread_id)
        if user_id is not None:
            query = query.filter(AiopsEvidence.user_id == user_id)
        return [{"evidence_id": row.evidence_id, "thread_id": row.thread_id, "target_id": row.target_id,
                 "source": row.source, "kind": row.kind, "collected_at": _utc_iso(row.collected_at),
                 "summary": row.summary_redacted, "raw_hash": row.raw_hash,
                 "fresh": bool(_utc_datetime(row.fresh_until) and _utc_datetime(row.fresh_until) > datetime.now(timezone.utc)),
                 "raw_available": bool(row.raw_ref)} for row in query.order_by(AiopsEvidence.id.asc()).all()]
    finally:
        db.close()


def get_evidence(thread_id: str, evidence_id: str, user_id: int | None = None,
                 *, include_raw: bool = False) -> dict | None:
    db = SessionLocal()
    try:
        query = db.query(AiopsEvidence).filter(AiopsEvidence.thread_id == thread_id, AiopsEvidence.evidence_id == evidence_id)
        if user_id is not None:
            query = query.filter(AiopsEvidence.user_id == user_id)
        row = query.first()
        if not row:
            return None
        result = {"evidence_id": row.evidence_id, "thread_id": row.thread_id, "target_id": row.target_id,
                "source": row.source, "kind": row.kind, "collected_at": _utc_iso(row.collected_at),
                "summary": row.summary_redacted, "raw_hash": row.raw_hash,
                "fresh": bool(_utc_datetime(row.fresh_until) and _utc_datetime(row.fresh_until) > datetime.now(timezone.utc)), "raw_ref": row.raw_ref}
        if include_raw and row.raw_ref:
            try:
                result["raw"] = json.loads(Path(row.raw_ref).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                result["raw"] = None
        return result
    finally:
        db.close()


def get_probe_target(target_id: str) -> dict | None:
    db = SessionLocal()
    try:
        row = db.query(ProbeTarget).filter(ProbeTarget.target_id == target_id).first()
        if not row:
            return None
        last_seen = _utc_datetime(row.last_seen)
        stale = not last_seen or not -30 <= (datetime.now(timezone.utc) - last_seen).total_seconds() <= 180
        status = "stale" if row.status == "online" and stale else row.status
        return {"target_id": row.target_id, "platform": row.platform, "hostname": row.hostname,
                "agent_version": row.agent_version, "capabilities": row.capabilities or [],
                "status": status, "stale": stale, "last_seen": _utc_iso(row.last_seen)}
    finally:
        db.close()


def cleanup_expired_probe_snapshots() -> int:
    """Delete expired baselines without touching diagnostic evidence or raw files."""
    db = SessionLocal()
    try:
        deleted = db.query(ProbeSnapshot).filter(
            ProbeSnapshot.expires_at <= datetime.now(timezone.utc)
        ).delete(synchronize_session=False)
        db.commit()
        return deleted
    finally:
        db.close()


def save_probe_snapshot(target_id: str, kind: str, payload: dict, raw_hash_value: str) -> None:
    now = datetime.now(timezone.utc)
    collected_at = _parse_utc(payload.get("collected_at")) or now
    db = SessionLocal()
    try:
        db.add(ProbeSnapshot(target_id=target_id, kind=kind, collected_at=collected_at,
                             expires_at=collected_at + timedelta(hours=24), payload=redact(payload), raw_hash=raw_hash_value))
        db.query(ProbeSnapshot).filter(ProbeSnapshot.expires_at < now).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def list_probe_snapshots(target_id: str, *, limit: int = 50) -> list[dict]:
    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        rows = (db.query(ProbeSnapshot).filter(ProbeSnapshot.target_id == target_id,
                                                ProbeSnapshot.expires_at > now)
                .order_by(ProbeSnapshot.collected_at.desc()).limit(max(1, min(limit, 100))).all())
        return [{"target_id": row.target_id, "kind": row.kind,
                 "collected_at": _utc_iso(row.collected_at),
                 "payload": row.payload or {}, "raw_hash": row.raw_hash,
                 "fresh": bool(_utc_datetime(row.collected_at) and
                               -30 <= (now - _utc_datetime(row.collected_at)).total_seconds() <= 180)} for row in rows]
    finally:
        db.close()
