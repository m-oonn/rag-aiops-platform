from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks, Body
from sqlalchemy.orm import Session
from typing import List, Optional, Any, Dict
import shutil
import os
import re
from datetime import datetime
from pathlib import Path
from pydantic import BaseModel, ConfigDict
from fastapi.responses import StreamingResponse, FileResponse
import io

from src.database.sql_session import get_db
from src.database.models import KnowledgeBase, KnowledgeDocument, User, DocumentChunk, GeneratedQAPair
from src.utils.security import create_access_token
from src.settings import settings
from src.api.dependencies import get_current_user
from src.services.qa_generator import qa_generator
from src.worker.tasks import process_document_task, process_document
from src.services.storage import storage_service
from src.database.vector_db import MilvusClient
from src.utils.preview_utils import get_preview_response
from src.utils.logger import logger

router = APIRouter()
vector_db_client = MilvusClient()


def _try_celery_delay(doc_id: int):
    """尝试通过 Celery 分发任务；broker 不可用时 5s 内抛异常，由调用方降级。"""
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

    def _do_delay():
        return process_document_task.delay(doc_id)

    pool = ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(_do_delay)
        return future.result(timeout=5)
    finally:
        pool.shutdown(wait=False)

# --- Pydantic Models ---

class KBCreate(BaseModel):
    name: str
    description: Optional[str] = None
    is_public: bool = False
    chunking_config: Optional[Dict[str, Any]] = None # e.g. {"method": "recursive", "chunk_size": 300, "chunk_overlap": 50}

class KBUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_public: Optional[bool] = None
    chunking_config: Optional[Dict[str, Any]] = None

class KBOut(BaseModel):
    id: int
    kb_uid: str
    name: str
    description: Optional[str]
    is_public: bool
    chunking_config: Optional[Dict[str, Any]]
    created_at: datetime
    owner_id: int
    
    model_config = ConfigDict(from_attributes=True)

class DocumentOut(BaseModel):
    id: int
    doc_uid: str
    filename: str
    status: int
    chunk_count: int
    file_size: int
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

class QAPairOut(BaseModel):
    id: int
    question: str
    answer: str
    qa_type: str
    created_at: Any
    
    model_config = ConfigDict(from_attributes=True)

class QAPairCreate(BaseModel):
    question: str
    answer: str
    qa_type: str = "single_hop"
    
class QAPairUpdate(BaseModel):
    question: Optional[str] = None
    answer: Optional[str] = None
    qa_type: Optional[str] = None
    status: Optional[int] = None

class ChunkOut(BaseModel):
    id: int
    content: str
    page_num: Optional[int]
    
    model_config = ConfigDict(from_attributes=True)

MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB

ALLOWED_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".csv",
    ".pptx", ".ppt", ".md", ".html", ".htm", ".txt",
}


def sanitize_filename(filename: str) -> str:
    """清洗文件名，拒绝路径穿越并移除危险字符。"""
    if not filename:
        raise HTTPException(status_code=400, detail="Filename cannot be empty")

    # 拒绝任何包含路径分隔符或 .. 的文件名
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(
            status_code=400, detail="Invalid filename: path traversal detected"
        )

    # 仅保留基础名称，防止绝对路径
    base_name = Path(filename).name
    if not base_name or base_name in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid filename")

    # 移除剩余危险字符
    safe_name = re.sub(r'[\\/*?:"<>|]', "", base_name)
    return safe_name

# --- Endpoints ---

@router.post("/", response_model=KBOut)
def create_knowledge_base(
    kb_in: KBCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    import uuid
    kb = KnowledgeBase(
        kb_uid=str(uuid.uuid4()),
        name=kb_in.name,
        description=kb_in.description,
        is_public=kb_in.is_public,
        chunking_config=kb_in.chunking_config,
        owner_id=current_user.id
    )
    db.add(kb)
    db.commit()
    db.refresh(kb)
    return kb

@router.get("/", response_model=List[KBOut])
def list_knowledge_bases(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Return user's KBs and public KBs
    # For now just user's
    return db.query(KnowledgeBase).filter(KnowledgeBase.owner_id == current_user.id).all()

@router.delete("/{kb_id}")
def delete_knowledge_base(
    kb_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge Base not found")
    if kb.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Logic to delete KB:
    # 1. Delete Milvus vectors by kb_id
    # 2. Delete Documents (and chunks) via SQLAlchemy cascade
    # 3. Delete generated QAs via SQLAlchemy cascade
    # 4. Delete KB

    vector_db_client.delete_by_kb_id(kb.id)

    db.delete(kb)
    db.commit()
    return {"message": "Knowledge Base deleted"}

@router.get("/{kb_id}", response_model=KBOut)
def get_knowledge_base(
    kb_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge Base not found")
    if kb.owner_id != current_user.id and not kb.is_public:
         raise HTTPException(status_code=403, detail="Not authorized")
    return kb

@router.put("/{kb_id}", response_model=KBOut)
def update_knowledge_base(
    kb_id: int,
    kb_in: KBUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge Base not found")
    if kb.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    if kb_in.name is not None:
        kb.name = kb_in.name
    if kb_in.description is not None:
        kb.description = kb_in.description
    if kb_in.is_public is not None:
        kb.is_public = kb_in.is_public
    if kb_in.chunking_config is not None:
        kb.chunking_config = kb_in.chunking_config
        
    db.commit()
    db.refresh(kb)
    return kb

@router.post("/{kb_id}/upload")
def upload_document(
    kb_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge Base not found")
    if kb.owner_id != current_user.id:
         raise HTTPException(status_code=403, detail="Not authorized")

    import uuid
    doc_uid = str(uuid.uuid4())
    safe_filename = sanitize_filename(file.filename)

    # 前置文件类型白名单校验
    ext = Path(safe_filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext}. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    # 先读取并校验文件大小，再落盘
    file_content = file.file.read()
    file_size = len(file_content)
    if file_size > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large: {file_size} bytes exceeds limit of {MAX_UPLOAD_SIZE} bytes",
        )

    file_path = settings.UPLOAD_DIR / f"{doc_uid}_{safe_filename}"
    
    # Ensure directory exists (again, to be safe)
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    
    try:
        # Use absolute path explicitly
        abs_file_path = file_path.resolve()
        
        with open(abs_file_path, "wb") as buffer:
            buffer.write(file_content)
            
        if not os.path.exists(abs_file_path):
             raise Exception("File saved but not found on disk immediately.")
             
        # Try to upload to MinIO with correct content type and filename in metadata
        try:
            object_name = f"{doc_uid}_{safe_filename}"
            with open(abs_file_path, "rb") as f:
                content = f.read()
                # MinIO put_object supports metadata for Content-Disposition but presigned URL overrides it usually
                # But we can try setting content_type correctly
                storage_service.upload_file(object_name, content, file.content_type)
        except Exception as e:
            # Log error but don't fail the upload entirely? 
            # Or fail it because preview is required?
            # User wants preview, so maybe we should ensure it works.
            # But core functionality is RAG, so local file is more important.
            # Let's log and proceed, but maybe add a warning.
            print(f"Failed to upload to MinIO: {e}")
             
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")
        
    doc = KnowledgeDocument(
        doc_uid=doc_uid,
        kb_id=kb.id,
        filename=safe_filename,
        file_path=str(abs_file_path), # Store absolute path
        file_type=safe_filename.split('.')[-1],
        file_size=os.path.getsize(abs_file_path),
        chunk_count=0, # Initialize chunk count
        status=0 # Uploading
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    
    # Trigger Celery task
    try:
        task = _try_celery_delay(doc.id)
        doc.celery_task_id = task.id
        db.commit()
        return {"message": "File uploaded successfully", "doc_id": doc.id, "task_id": task.id}
    except Exception as e:
        # broker 不可用(demo 无 RabbitMQ):转后台同步处理,上传立即成功,前端轮询状态
        logger.warning(f"Celery broker 不可用,转同步处理 doc {doc.id}: {e}")
        background_tasks.add_task(process_document, doc.id)
        doc.celery_task_id = None
        db.commit()
        return {"message": "File uploaded (sync mode)", "doc_id": doc.id, "task_id": None}

@router.post("/documents/batch-retry")
def batch_retry_documents(
    doc_ids: List[int],
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    docs = db.query(KnowledgeDocument).filter(KnowledgeDocument.id.in_(doc_ids)).all()
    restarted = []
    for doc in docs:
        kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == doc.kb_id).first()
        if kb and kb.owner_id == current_user.id:
            doc.status = 0
            doc.error_msg = None
            db.commit()
            try:
                _try_celery_delay(doc.id)
            except Exception:
                background_tasks.add_task(process_document, doc.id)
            restarted.append(doc.id)

    return {"message": f"Restarted {len(restarted)} documents"}

@router.delete("/documents/batch-delete")
def batch_delete_documents(
    doc_ids: List[int],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    docs = db.query(KnowledgeDocument).filter(KnowledgeDocument.id.in_(doc_ids)).all()
    deleted = 0
    for doc in docs:
        kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == doc.kb_id).first()
        if kb and kb.owner_id == current_user.id:
            # Delete file
            if os.path.exists(doc.file_path):
                try:
                    os.remove(doc.file_path)
                except:
                    pass
            db.delete(doc)
            deleted += 1
            
    db.commit()
    return {"message": f"Deleted {deleted} documents"}

@router.post("/documents/{doc_id}/retry")
def retry_document(
    doc_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == doc.kb_id).first()
    if not kb or kb.owner_id != current_user.id:
         raise HTTPException(status_code=403, detail="Not authorized")

    if not os.path.exists(doc.file_path):
        raise HTTPException(status_code=400, detail="Original file not found on server")

    # Reset status
    doc.status = 0
    doc.error_msg = None
    db.commit()

    try:
        task = _try_celery_delay(doc.id)
        doc.celery_task_id = task.id
        db.commit()
        return {"message": "Retry started", "task_id": task.id}
    except Exception as e:
        logger.warning(f"Celery broker 不可用,转同步处理 doc {doc.id}: {e}")
        background_tasks.add_task(process_document, doc.id)
        doc.celery_task_id = None
        db.commit()
        return {"message": "Retry started (sync mode)", "task_id": None}

@router.get("/{kb_id}/documents", response_model=List[DocumentOut])
def list_documents(
    kb_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge Base not found")
    if kb.owner_id != current_user.id and not kb.is_public:
        raise HTTPException(status_code=403, detail="Not authorized")

    return db.query(KnowledgeDocument).filter(KnowledgeDocument.kb_id == kb_id).all()

@router.post("/documents/{doc_id}/generate-qa", response_model=List[QAPairOut])
def generate_qa_for_document(
    doc_id: int,
    num_pairs: int = 5,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Check permission
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == doc.kb_id).first()
    if kb.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    # Fetch chunks to get text
    chunks = db.query(DocumentChunk).filter(DocumentChunk.doc_id == doc_id).limit(10).all()
    if not chunks:
        # Fallback to reading file if no chunks (e.g. text file not yet processed)
        # But usually we process first.
        # For this demo, let's just use a placeholder text if empty
        combined_text = f"Document content for {doc.filename}"
    else:
        combined_text = "\n".join([c.content for c in chunks])
    
    # Use QA Generator
    pairs = qa_generator.generate_qa_pairs(combined_text, num_pairs)
    
    saved_pairs = []
    for p in pairs:
        qa = GeneratedQAPair(
            kb_id=kb.id,
            doc_id=doc.id,
            question=p.get("question", ""),
            answer=p.get("answer", ""),
            qa_type="single_hop",
            status=0 # Pending
        )
        db.add(qa)
        saved_pairs.append(qa)
        
    db.commit()
    for qa in saved_pairs:
        db.refresh(qa)
        
    return saved_pairs

from fastapi.responses import StreamingResponse
import io

@router.post("/documents/{doc_id}/qa-pairs", response_model=QAPairOut)
def create_qa_pair(
    doc_id: int,
    qa_in: QAPairCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
        
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == doc.kb_id).first()
    if kb.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    qa = GeneratedQAPair(
        kb_id=kb.id,
        doc_id=doc.id,
        question=qa_in.question,
        answer=qa_in.answer,
        qa_type=qa_in.qa_type,
        status=1, # Confirmed since manually created
        created_by=current_user.username
    )
    db.add(qa)
    db.commit()
    db.refresh(qa)
    return qa

@router.put("/qa-pairs/{qa_id}", response_model=QAPairOut)
def update_qa_pair(
    qa_id: int,
    qa_in: QAPairUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    qa = db.query(GeneratedQAPair).filter(GeneratedQAPair.id == qa_id).first()
    if not qa:
        raise HTTPException(status_code=404, detail="QA Pair not found")
        
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == qa.kb_id).first()
    if kb.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    if qa_in.question is not None:
        qa.question = qa_in.question
    if qa_in.answer is not None:
        qa.answer = qa_in.answer
    if qa_in.qa_type is not None:
        qa.qa_type = qa_in.qa_type
    if qa_in.status is not None:
        qa.status = qa_in.status
        
    db.commit()
    db.refresh(qa)
    return qa

@router.delete("/qa-pairs/{qa_id}")
def delete_qa_pair(
    qa_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    qa = db.query(GeneratedQAPair).filter(GeneratedQAPair.id == qa_id).first()
    if not qa:
        raise HTTPException(status_code=404, detail="QA Pair not found")
        
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == qa.kb_id).first()
    if kb.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    db.delete(qa)
    db.commit()
    return {"message": "QA Pair deleted"}

@router.get("/documents/{doc_id}/qa-pairs/download")
def download_qa_pairs(
    doc_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
        
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == doc.kb_id).first()
    if kb.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    qa_pairs = db.query(GeneratedQAPair).filter(GeneratedQAPair.doc_id == doc_id).all()
    
    # Generate Markdown content
    content = f"# QA Pairs for {doc.filename}\n\n"
    for i, qa in enumerate(qa_pairs, 1):
        content += f"## Question {i} ({qa.qa_type})\n\n"
        content += f"**Q:** {qa.question}\n\n"
        content += f"**A:** {qa.answer}\n\n"
        content += "---\n\n"
        
    # Create a stream
    stream = io.StringIO(content)
    
    response = StreamingResponse(iter([stream.getvalue()]), media_type="text/markdown")
    response.headers["Content-Disposition"] = f"attachment; filename=qa_pairs_{doc.filename}.md"
    return response

@router.get("/documents/{doc_id}/chunks", response_model=List[ChunkOut])
def get_document_chunks(
    doc_id: int,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
        
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == doc.kb_id).first()
    if kb.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    return db.query(DocumentChunk).filter(DocumentChunk.doc_id == doc_id).limit(limit).all()

@router.post("/documents/{doc_id}/reprocess")
def reprocess_document(
    doc_id: int,
    background_tasks: BackgroundTasks,
    config: Optional[Dict[str, Any]] = Body(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == doc.kb_id).first()
    if kb.owner_id != current_user.id:
         raise HTTPException(status_code=403, detail="Not authorized")

    if config:
        doc.chunking_config = config

    doc.status = 0 # Reset status to pending
    doc.error_msg = None
    db.commit()

    try:
        task = _try_celery_delay(doc.id)
        doc.celery_task_id = task.id
        db.commit()
        return {"message": "Reprocessing started", "doc_id": doc.id, "task_id": task.id}
    except Exception as e:
        logger.warning(f"Celery broker 不可用,转同步处理 doc {doc.id}: {e}")
        background_tasks.add_task(process_document, doc.id)
        doc.celery_task_id = None
        db.commit()
        return {"message": "Reprocessing started (sync mode)", "doc_id": doc.id, "task_id": None}

@router.get("/documents/{doc_id}/preview")
def preview_document(
    doc_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
        
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == doc.kb_id).first()
    if kb.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    file_path = doc.file_path
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found on server")
        
    return get_preview_response(file_path, doc.file_type)

@router.get("/documents/{doc_id}/qa-pairs", response_model=List[QAPairOut])
def get_document_qa_pairs(
    doc_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
        
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == doc.kb_id).first()
    if kb.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    return db.query(GeneratedQAPair).filter(GeneratedQAPair.doc_id == doc_id).all()
