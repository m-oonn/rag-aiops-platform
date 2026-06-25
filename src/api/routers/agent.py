from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from typing import List, Optional, Any
from pydantic import BaseModel
from datetime import datetime

from src.database.sql_session import get_db
from src.database.models import Agent, User
from src.api.dependencies import get_current_user

router = APIRouter()

class AgentCreate(BaseModel):
    name: str
    description: Optional[str] = None
    type: str = "function_call"
    
    # New Config Fields
    system_prompt: Optional[str] = None
    tools_config: Optional[dict] = None
    knowledge_config: Optional[dict] = None
    memory_config: Optional[dict] = None
    reasoning_config: Optional[dict] = None
    security_config: Optional[dict] = None
    interaction_config: Optional[dict] = None
    llm_config: Optional[dict] = None
    execution_config: Optional[dict] = None
    
    # Legacy
    config: Optional[dict] = {}

class AgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    
    system_prompt: Optional[str] = None
    tools_config: Optional[dict] = None
    knowledge_config: Optional[dict] = None
    memory_config: Optional[dict] = None
    reasoning_config: Optional[dict] = None
    security_config: Optional[dict] = None
    interaction_config: Optional[dict] = None
    llm_config: Optional[dict] = None
    execution_config: Optional[dict] = None
    
    config: Optional[dict] = None

class AgentOut(BaseModel):
    id: int
    name: str
    description: Optional[str]
    type: str
    
    system_prompt: Optional[str]
    tools_config: Optional[dict]
    knowledge_config: Optional[dict]
    memory_config: Optional[dict]
    reasoning_config: Optional[dict]
    security_config: Optional[dict]
    interaction_config: Optional[dict]
    llm_config: Optional[dict]
    execution_config: Optional[dict]
    
    config: Optional[dict]
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

@router.post("/", response_model=AgentOut)
def create_agent(
    agent_in: AgentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    agent = Agent(
        name=agent_in.name,
        description=agent_in.description,
        type=agent_in.type,
        user_id=current_user.id,
        
        system_prompt=agent_in.system_prompt,
        tools_config=agent_in.tools_config,
        knowledge_config=agent_in.knowledge_config,
        memory_config=agent_in.memory_config,
        reasoning_config=agent_in.reasoning_config,
        security_config=agent_in.security_config,
        interaction_config=agent_in.interaction_config,
        llm_config=agent_in.llm_config,
        execution_config=agent_in.execution_config,
        
        config=agent_in.config
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent

@router.get("/", response_model=List[AgentOut])
def list_agents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return db.query(Agent).filter(Agent.user_id == current_user.id).all()

@router.get("/{agent_id}", response_model=AgentOut)
def get_agent(
    agent_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    return agent

@router.put("/{agent_id}", response_model=AgentOut)
def update_agent(
    agent_id: int,
    agent_in: AgentUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    update_data = agent_in.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(agent, field, value)
        
    db.commit()
    db.refresh(agent)
    return agent

@router.delete("/{agent_id}")
def delete_agent(
    agent_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    db.delete(agent)
    db.commit()
    return {"message": "Agent deleted"}
