from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional, Any
from pydantic import BaseModel, ConfigDict, Field, field_validator
import uuid
import json

from sse_starlette.sse import EventSourceResponse
from starlette.concurrency import run_in_threadpool, iterate_in_threadpool

from src.database.sql_session import get_db, SessionLocal
from src.database.models import ChatSession, ChatInteraction, User, KnowledgeBase, Assistant, Agent
from src.services.rag_service import RAGService
from src.services.memory_service import MemorySystem
from src.api.dependencies import get_current_user
from src.utils.logger import logger

router = APIRouter()
rag_service = RAGService()
memory_system = MemorySystem()

class ChatRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    kb_id: Optional[int] = None # Deprecated/Override
    assistant_id: Optional[int] = None # New: Select Assistant
    top_k: int = Field(5, ge=1, le=50)
    llm_model: Optional[str] = None  # 前端手动切换模型，None 则用 Assistant 默认或全局默认

    @field_validator("llm_model")
    @classmethod
    def validate_llm_model(cls, v: str | None) -> str | None:
        """安全最佳实践: 校验 llm_model 在白名单内，防止注入任意模型名。"""
        if v is None:
            return v
        from src.settings import settings
        allowed = [m.strip() for m in settings.AVAILABLE_MODELS.split(",")]
        if v not in allowed:
            raise ValueError(f"不支持的模型: {v}，可用模型: {', '.join(allowed)}")
        return v

class ChatResponse(BaseModel):
    session_id: str
    query: str
    answer: str
    source_documents: List[Any]

class SessionOut(BaseModel):
    id: int
    session_uid: str
    title: Optional[str]
    created_at: Any
    assistant_id: Optional[int]
    
    model_config = ConfigDict(from_attributes=True)

class MessageOut(BaseModel):
    query: str
    answer: str
    created_at: Any

    model_config = ConfigDict(from_attributes=True)

@router.post("/", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # 0. Resolve Assistant & Configuration
    assistant = None
    kb_ids = []
    
    if request.assistant_id:
        assistant = db.query(Assistant).filter(Assistant.id == request.assistant_id).first()
        if not assistant:
             raise HTTPException(status_code=404, detail="Assistant not found")
        # Optional: check ownership or public
        if assistant.user_id != current_user.id:
             raise HTTPException(status_code=403, detail="Not authorized for this assistant")
        
        # Load config from assistant
        kb_ids = assistant.kb_ids or []
    elif request.kb_id:
        # Legacy/Direct KB mode
        kb_ids = [request.kb_id]
    
    # 1. Validate KBs (if any)
    valid_kb_ids = []
    if kb_ids:
        kbs = db.query(KnowledgeBase).filter(KnowledgeBase.id.in_(kb_ids)).all()
        for kb in kbs:
            if kb.owner_id == current_user.id or kb.is_public:
                valid_kb_ids.append(kb.id)
    
    # 2. Manage Session
    session_uid = request.session_id
    if not session_uid:
        session_uid = str(uuid.uuid4())
        chat_session = ChatSession(
            session_uid=session_uid,
            user_id=current_user.id,
            assistant_id=request.assistant_id,
            title=request.query[:50]  # Simple title generation
        )
        db.add(chat_session)
        db.commit()
        db.refresh(chat_session)
    else:
        chat_session = db.query(ChatSession).filter(ChatSession.session_uid == session_uid).first()
        if not chat_session:
            chat_session = ChatSession(
                session_uid=session_uid,
                user_id=current_user.id,
                assistant_id=request.assistant_id,
                title=request.query[:50]
            )
            db.add(chat_session)
            db.commit()
            db.refresh(chat_session)
        
        if chat_session.user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not authorized to access this session")

    # 3. Pre-load linked Agents if any
    agents = []
    if assistant and assistant.agent_ids:
        agents = db.query(Agent).filter(Agent.id.in_(assistant.agent_ids)).all()

    # Pass assistant config if available
    # Model resolution order: request.llm_model (前端手动切换) > assistant.llm_model (助手默认) > global default
    resolved_model = request.llm_model or (assistant.llm_model if assistant else None)
    assistant_config = {
        "llm_model": resolved_model,  # None means use global default
        "temperature": assistant.temperature if assistant else 0.7,
        "system_prompt": assistant.system_prompt if assistant else None,
        "memory_config": assistant.memory_config if assistant else None,
        "rag_config": assistant.rag_config if assistant else None,
        "tool_config": assistant.tool_config if assistant else None,
        "agent_ids": assistant.agent_ids if assistant else None,
        "agents": agents,
    }

    result = await rag_service.query(
        query_text=request.query,
        top_k=request.top_k,
        session_id=session_uid,
        kb_ids=valid_kb_ids, # Pass list of IDs
        assistant_config=assistant_config
    )
    
    # 4. Save Interaction
    interaction = ChatInteraction(
        session_id=chat_session.id,
        kb_id=valid_kb_ids[0] if valid_kb_ids else None, # Store primary KB or None
        query=request.query,
        answer=result["answer"],
        retrieved_docs=result.get("source_documents"), # JSON field
        metrics={} # Placeholder for metrics
    )
    db.add(interaction)
    db.commit()
    
    return ChatResponse(
        session_id=session_uid,
        query=request.query,
        answer=result["answer"],
        source_documents=result.get("source_documents", [])
    )

def _resolve_plain_session(request: ChatRequest, current_user: User, db: Session) -> ChatSession:
    """纯聊天会话解析: 复用 chat() 的 session_uid 创建/查找逻辑(assistant_id 恒为 None)。"""
    session_uid = request.session_id
    if session_uid:
        chat_session = db.query(ChatSession).filter(ChatSession.session_uid == session_uid).first()
        if chat_session:
            if chat_session.user_id != current_user.id:
                raise HTTPException(status_code=403, detail="Not authorized to access this session")
            return chat_session

    chat_session = ChatSession(
        session_uid=session_uid or str(uuid.uuid4()),
        user_id=current_user.id,
        assistant_id=None,
        title=request.query[:50]
    )
    db.add(chat_session)
    db.commit()
    db.refresh(chat_session)
    return chat_session

def _save_chat_interaction(session_db_id: int, query_text: str, answer: str) -> None:
    """保存一条 ChatInteraction(同步 DB 操作,供 run_in_threadpool 丢线程池)。"""
    db = SessionLocal()
    try:
        interaction = ChatInteraction(
            session_id=session_db_id,
            kb_id=None,
            query=query_text,
            answer=answer,
            retrieved_docs=[],
            metrics={},
        )
        db.add(interaction)
        db.commit()
    finally:
        db.close()


@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """纯聊天流式端点(无知识库/助手)。逐 token 推送 SSE。

    带 assistant_id / kb_id 的 RAG 路径仍走同步 POST /chat/,不经过这里。

    async 端点 + iterate_in_threadpool: 把同步阻塞的 LLM stream 推到线程池,
    不阻塞 asyncio 事件循环,SSE 帧才能被及时发送到浏览器。
    """
    chat_session = _resolve_plain_session(request, current_user, db)
    session_uid = chat_session.session_uid
    session_db_id = chat_session.id
    query_text = request.query
    stream_model = request.llm_model  # 前端手动切换的模型，None 则用全局默认

    async def event_generator():
        full_answer = ""
        try:
            # 取短期记忆拼 context
            history = memory_system.get_short_term_memory(session_uid, limit=10)
            context = ""
            if history:
                history_str = "\n".join(
                    f"{m['role']}: {m['content']}" for m in history
                )
                context = f"历史对话:\n{history_str}"

            # iterate_in_threadpool: 同步生成器的每次 next() 在线程池执行,
            # 不阻塞 asyncio 事件循环 → SSE 帧实时发出,浏览器可增量渲染。
            async for token in iterate_in_threadpool(
                rag_service.llm_client.generate_general_response_stream(
                    query_text, context, model=stream_model
                )
            ):
                full_answer += token
                yield {
                    "event": "message",
                    "data": json.dumps(
                        {"type": "token", "content": token}, ensure_ascii=False
                    ),
                }

            # 收尾: 更新短期记忆 + 落库(同步操作丢线程池)
            memory_system.add_short_term_memory(session_uid, "user", query_text)
            memory_system.add_short_term_memory(session_uid, "assistant", full_answer)
            await run_in_threadpool(
                _save_chat_interaction, session_db_id, query_text, full_answer
            )

            yield {
                "event": "message",
                "data": json.dumps(
                    {"type": "done", "session_id": session_uid}, ensure_ascii=False
                ),
            }
        except Exception as e:
            logger.error(f"[chat/stream] SSE 流异常: {e}", exc_info=True)
            yield {
                "event": "message",
                "data": json.dumps(
                    {"type": "error", "message": f"聊天异常: {e}"}, ensure_ascii=False
                ),
            }

    return EventSourceResponse(event_generator())

@router.get("/sessions", response_model=List[SessionOut])
def list_sessions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return db.query(ChatSession).filter(ChatSession.user_id == current_user.id).order_by(ChatSession.created_at.desc()).all()

@router.get("/sessions/{session_id}/messages", response_model=List[MessageOut])
def get_session_messages(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    chat_session = db.query(ChatSession).filter(ChatSession.session_uid == session_id).first()
    if not chat_session:
        raise HTTPException(status_code=404, detail="Session not found")
    if chat_session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    return db.query(ChatInteraction).filter(ChatInteraction.session_id == chat_session.id).order_by(ChatInteraction.created_at.asc()).all()

@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    chat_session = db.query(ChatSession).filter(ChatSession.session_uid == session_id).first()
    if not chat_session:
        raise HTTPException(status_code=404, detail="Session not found")
    if chat_session.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    # Delete interactions first
    db.query(ChatInteraction).filter(ChatInteraction.session_id == chat_session.id).delete()
    db.delete(chat_session)
    db.commit()
    
    # Clear short term memory from Redis
    try:
        memory_system.clear_short_term_memory(session_id)
    except Exception as e:
        print(f"Error clearing memory: {e}")
    
    return {"message": "Session deleted"}

@router.delete("/sessions")
def batch_delete_sessions(
    session_ids: List[str], # List of session_uids
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    sessions = db.query(ChatSession).filter(ChatSession.session_uid.in_(session_ids)).all()
    deleted_count = 0
    
    for session in sessions:
        if session.user_id == current_user.id:
            db.query(ChatInteraction).filter(ChatInteraction.session_id == session.id).delete()
            db.delete(session)
            deleted_count += 1
            
    db.commit()
    return {"message": f"Deleted {deleted_count} sessions"}
