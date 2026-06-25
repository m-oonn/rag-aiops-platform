from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from typing import List, Optional, Any
from pydantic import BaseModel
from datetime import datetime

from src.database.sql_session import get_db
from src.database.models import Assistant, User, KnowledgeBase, Agent
from src.api.dependencies import get_current_user

router = APIRouter()

# Mock storage for versions until DB table is created
MOCK_VERSIONS = {} # {assistant_id: [AssistantVersion]}

class AssistantCreate(BaseModel):
    name: str
    description: Optional[str] = None
    llm_model: str = "qwen-max"
    temperature: float = 0.7
    system_prompt: Optional[str] = None
    greeting_message: Optional[str] = None # New: Opening remarks
    memory_config: Optional[dict] = {"enable": True, "window_size": 10}
    kb_ids: Optional[List[int]] = []
    rag_config: Optional[dict] = {"top_k": 5, "enable_rerank": True}
    tool_config: Optional[List[str]] = []
    agent_ids: Optional[List[int]] = []

class AssistantUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    llm_model: Optional[str] = None
    temperature: Optional[float] = None
    system_prompt: Optional[str] = None
    greeting_message: Optional[str] = None
    memory_config: Optional[dict] = None
    kb_ids: Optional[List[int]] = None
    rag_config: Optional[dict] = None
    tool_config: Optional[List[str]] = None
    agent_ids: Optional[List[int]] = None

class AssistantOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    llm_model: str
    temperature: float
    system_prompt: Optional[str]
    greeting_message: Optional[str]
    memory_config: Optional[dict]
    kb_ids: Optional[List[int]]
    rag_config: Optional[dict]
    tool_config: Optional[List[str]]
    agent_ids: Optional[List[int]]
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

@router.post("/", response_model=AssistantOut)
def create_assistant(
    assistant_in: AssistantCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Verify KBs exist and belong to user
    if assistant_in.kb_ids:
        kbs = db.query(KnowledgeBase).filter(KnowledgeBase.id.in_(assistant_in.kb_ids)).all()
        # Basic check, detailed ownership check can be added
        if len(kbs) != len(assistant_in.kb_ids):
             # Or just ignore invalid ones? Let's be strict
             pass 

    assistant = Assistant(
        name=assistant_in.name,
        description=assistant_in.description,
        user_id=current_user.id,
        llm_model=assistant_in.llm_model,
        temperature=assistant_in.temperature,
        system_prompt=assistant_in.system_prompt,
        greeting_message=assistant_in.greeting_message,
        memory_config=assistant_in.memory_config,
        kb_ids=assistant_in.kb_ids,
        rag_config=assistant_in.rag_config,
        tool_config=assistant_in.tool_config,
        agent_ids=assistant_in.agent_ids
    )
    db.add(assistant)
    db.commit()
    db.refresh(assistant)
    return assistant

@router.get("/", response_model=List[AssistantOut])
def list_assistants(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return db.query(Assistant).filter(Assistant.user_id == current_user.id).all()

@router.get("/{assistant_id}", response_model=AssistantOut)
def get_assistant(
    assistant_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    assistant = db.query(Assistant).filter(Assistant.id == assistant_id).first()
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")
    if assistant.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    return assistant

@router.put("/{assistant_id}", response_model=AssistantOut)
def update_assistant(
    assistant_id: int,
    assistant_in: AssistantUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    assistant = db.query(Assistant).filter(Assistant.id == assistant_id).first()
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")
    if assistant.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    update_data = assistant_in.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(assistant, field, value)
        
    db.commit()
    db.refresh(assistant)
    return assistant

class AssistantVersion(BaseModel):
    version: str
    config: dict
    created_at: datetime = None

@router.delete("/{assistant_id}")
def delete_assistant(
    assistant_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    assistant = db.query(Assistant).filter(Assistant.id == assistant_id).first()
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")
    if assistant.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    db.delete(assistant)
    db.commit()
    return {"message": "Assistant deleted"}

class AssistantVersion(BaseModel):
    version: str
    config: dict
    created_at: datetime = None

@router.post("/{assistant_id}/versions")
def create_assistant_version(
    assistant_id: int,
    version_data: dict = Body(...), # {version: "v1.0.1", config: {...}}
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Mock implementation until DB migration
    # In real world, we save to AssistantVersion table
    if assistant_id not in MOCK_VERSIONS:
        MOCK_VERSIONS[assistant_id] = []
    
    version_entry = {
        "version": version_data.get("version"),
        "config": version_data.get("config"),
        "created_at": datetime.now()
    }
    MOCK_VERSIONS[assistant_id].append(version_entry)
    
    return {"message": "Version saved (Mock)"}

@router.get("/{assistant_id}/versions")
def list_assistant_versions(
    assistant_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Mock return
    return MOCK_VERSIONS.get(assistant_id, [])
