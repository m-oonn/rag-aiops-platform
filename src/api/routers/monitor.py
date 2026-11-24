from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional, Any
from pydantic import BaseModel, ConfigDict
from celery.result import AsyncResult
from src.worker.celery_app import celery_app
from src.database.sql_session import get_db
from src.database.models import KnowledgeDocument, User, KnowledgeBase, OpsWatchServiceState, OpsWatchIncident
from src.api.dependencies import get_current_user, require_admin
from sqlalchemy import desc
from datetime import datetime, timezone
from src.agent.aiops.run_store import _utc_datetime, _utc_iso
from src.settings import settings

router = APIRouter()


def _watch_state(state, enabled):
    now = datetime.now(timezone.utc)
    times = [_utc_datetime(value) for value in (state.last_observed_at, state.latest_sample_at)]
    stale = not enabled or any(value is None or not -5 <= (now - value).total_seconds()
                              <= settings.OPS_WATCH_STALE_AFTER_SECONDS for value in times)
    return {
        "service_name": state.service_name,
        "status": ("alerting" if state.active_incident_id else "unknown") if stale else state.status,
        "latest_observation": "unknown" if stale else state.latest_observation,
        "breach_count": 0 if stale else state.breach_count,
        "recovery_count": 0 if stale else state.recovery_count,
        "latest_value": None if stale else state.latest_value,
        "latest_sample_at": _utc_iso(state.latest_sample_at),
        "last_observed_at": _utc_iso(state.last_observed_at),
        "data_source": state.data_source,
        "last_error": ("监察未启用或样本已过期，等待新鲜观测" if stale else state.last_error),
        "active_incident_id": state.active_incident_id,
        "stale": stale,
    }


@router.get("/watch/services")
def get_watch_services(
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Read persisted continuous-monitor state; this endpoint never starts the worker."""
    states = db.query(OpsWatchServiceState).order_by(OpsWatchServiceState.service_name).all()
    enabled = settings_watch_enabled()
    return {"enabled": enabled, "services": [_watch_state(state, enabled) for state in states]}


@router.get("/watch/incidents")
def get_watch_incidents(
    limit: int = 50,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    limit = min(max(limit, 1), 200)
    incidents = (db.query(OpsWatchIncident)
                 .order_by(desc(OpsWatchIncident.opened_at)).limit(limit).all())
    return [{
        "incident_id": incident.incident_uid,
        "service_name": incident.service_name,
        "status": incident.status,
        "opened_at": _utc_iso(incident.opened_at),
        "resolved_at": _utc_iso(incident.resolved_at),
        "diagnosis_status": incident.diagnosis_status,
        "diagnosis_thread_id": incident.diagnosis_thread_id,
    } for incident in incidents]


@router.get("/watch/incidents/{incident_id}")
def get_watch_incident(
    incident_id: str,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    incident = db.query(OpsWatchIncident).filter_by(incident_uid=incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="监察事件不存在")
    return {
        "incident_id": incident.incident_uid,
        "service_name": incident.service_name,
        "status": incident.status,
        "opened_at": _utc_iso(incident.opened_at),
        "resolved_at": _utc_iso(incident.resolved_at),
        "evidence": incident.evidence,
        "diagnosis_status": incident.diagnosis_status,
        "diagnosis_thread_id": incident.diagnosis_thread_id,
        "diagnosis_report": incident.diagnosis_report,
    }


def settings_watch_enabled() -> bool:
    from src.settings import settings
    return settings.OPS_WATCH_ENABLED

class QueueItem(BaseModel):
    task_id: Optional[str]
    doc_id: int
    filename: str
    kb_name: str
    status: str # PENDING, STARTED, RETRY, FAILURE, SUCCESS
    progress: Optional[int]
    message: Optional[str]
    created_at: Any

    model_config = ConfigDict(from_attributes=True)

class QueueStats(BaseModel):
    total_pending: int
    total_processing: int
    total_failed: int
    total_completed: int

@router.get("/", response_model=List[QueueItem])
def get_queue_status(
    status_filter: Optional[str] = None, # 'processing', 'pending', 'failed', 'completed'
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Fetch recent documents (e.g. last 100)
    query = db.query(KnowledgeDocument).join(KnowledgeBase).filter(KnowledgeBase.owner_id == current_user.id)
    
    if status_filter == 'processing':
        query = query.filter(KnowledgeDocument.status == 1)
    elif status_filter == 'pending':
        query = query.filter(KnowledgeDocument.status == 0)
    elif status_filter == 'failed':
        query = query.filter(KnowledgeDocument.status == 3)
    elif status_filter == 'completed':
        query = query.filter(KnowledgeDocument.status == 2)
        
    docs = query.order_by(desc(KnowledgeDocument.created_at)).limit(50).all()
    
    result = []
    for doc in docs:
        # 优先使用真实 Celery task_id；缺失时回退到 doc_id
        task_id = doc.celery_task_id or str(doc.id)

        # 若存在真实 task_id 且文档正在处理，可进一步查询 Celery 状态
        status_str = get_status_str(doc.status)
        progress = 0
        if doc.celery_task_id and doc.status == 1:
            try:
                async_result = AsyncResult(doc.celery_task_id, app=celery_app)
                celery_state = async_result.state
                status_str = celery_state
                if celery_state == "PENDING":
                    progress = 10
                elif celery_state == "STARTED":
                    progress = 50
                elif celery_state in ("SUCCESS", "FAILURE"):
                    progress = 100
            except Exception:
                pass
        elif doc.status == 1:
            progress = 50
        elif doc.status == 2:
            progress = 100

        item = QueueItem(
            task_id=task_id,
            doc_id=doc.id,
            filename=doc.filename,
            kb_name=doc.knowledge_base.name,
            status=status_str,
            progress=progress,
            message=doc.error_msg,
            created_at=doc.created_at,
        )

        result.append(item)

    return result

@router.get("/stats", response_model=QueueStats)
def get_queue_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    base_query = db.query(KnowledgeDocument).join(KnowledgeBase).filter(KnowledgeBase.owner_id == current_user.id)
    
    return QueueStats(
        total_pending=base_query.filter(KnowledgeDocument.status == 0).count(),
        total_processing=base_query.filter(KnowledgeDocument.status == 1).count(),
        total_failed=base_query.filter(KnowledgeDocument.status == 3).count(),
        total_completed=base_query.filter(KnowledgeDocument.status == 2).count()
    )

class BatchDeleteRequest(BaseModel):
    task_ids: List[str] # Actually we might need doc_ids if we don't have task_ids persistent

@router.delete("/tasks/{task_id}") # Using task_id as placeholder for doc_id since we mapped it loosely
def delete_task(
    task_id: str, # Interpreting as doc_id for now as per get_queue_status
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # In get_queue_status, we return task_id=None. Frontend needs to send doc_id or we fix backend to return doc_id as task_id
    # Let's assume frontend sends doc_id as task_id for now or we fix the model
    try:
        doc_id = int(task_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format")
        
    doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Task/Document not found")
        
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == doc.kb_id).first()
    if kb.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    # Delete doc
    db.delete(doc)
    db.commit()
    return {"message": "Deleted"}

@router.post("/tasks/batch-delete")
def batch_delete_tasks(
    req: BatchDeleteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    ids = []
    for tid in req.task_ids:
        if tid:
            try:
                ids.append(int(tid))
            except:
                pass
                
    if not ids:
        return {"message": "No valid IDs provided"}
        
    # Verify ownership implicitly by joining
    # But delete with join is tricky in some SQL dialects
    # Fetch first
    docs = db.query(KnowledgeDocument).filter(KnowledgeDocument.id.in_(ids)).all()
    count = 0
    for doc in docs:
        kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == doc.kb_id).first()
        if kb and kb.owner_id == current_user.id:
            db.delete(doc)
            count += 1
            
    db.commit()
    return {"message": f"Deleted {count} tasks"}

def get_status_str(status_code: int) -> str:
    mapping = {0: "PENDING", 1: "PROCESSING", 2: "SUCCESS", 3: "FAILURE"}
    return mapping.get(status_code, "UNKNOWN")
