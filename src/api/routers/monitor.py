from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional, Any
from pydantic import BaseModel
from celery.result import AsyncResult
from src.worker.celery_app import celery_app
from src.database.sql_session import get_db
from src.database.models import KnowledgeDocument, User, KnowledgeBase
from src.api.dependencies import get_current_user
from sqlalchemy import desc

router = APIRouter()

class QueueItem(BaseModel):
    task_id: Optional[str]
    doc_id: int
    filename: str
    kb_name: str
    status: str # PENDING, STARTED, RETRY, FAILURE, SUCCESS
    progress: Optional[int]
    message: Optional[str]
    created_at: Any
    
    class Config:
        from_attributes = True

class QueueStats(BaseModel):
    total_pending: int
    total_processing: int
    total_failed: int
    total_completed: int

@router.get("/", response_model=List[QueueItem])
def get_queue_status(
    status_filter: Optional[str] = None, # 'processing', 'pending', 'failed'
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
        
    docs = query.order_by(desc(KnowledgeDocument.created_at)).limit(50).all()
    
    result = []
    for doc in docs:
        # Try to get task info if available? 
        # We don't store task_id in DB currently, so we rely on doc status
        # Ideally we should store task_id in KnowledgeDocument
        
        item = QueueItem(
            task_id=str(doc.id), # Use doc_id as task_id for now
            doc_id=doc.id,
            filename=doc.filename,
            kb_name=doc.knowledge_base.name,
            status=get_status_str(doc.status),
            progress=0, # Placeholder
            message=doc.error_msg,
            created_at=doc.created_at
        )
        
        # If processing, maybe we can't get real-time celery progress without task_id
        # But for now status from DB is good enough for "queue view"
        if doc.status == 1:
             item.progress = 50 # processing
        elif doc.status == 2:
             item.progress = 100
        
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
