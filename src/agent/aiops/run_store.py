"""AIOps 诊断运行/审批记录持久化（HITL 支撑）。

状态机：running → pending_review → approved / rejected → completed；异常 → failed。
同步 SQLite 写（快、幂等），异常只告警不阻断主流程（沿用项目降级约定）。
"""

from typing import Optional

from src.database.models import AiopsApproval, AiopsRun
from src.database.sql_session import Base, SessionLocal, engine
from src.utils.logger import logger

# 幂等建表（与 main.py 启动时 Base.metadata.create_all 同模式）：
# 保证脚本/测试等未经过 FastAPI 启动的入口直连时新表也存在。
Base.metadata.create_all(bind=engine)

# 状态常量（与 aiops_runs.status 字段对齐）
STATUS_RUNNING = "running"
STATUS_PENDING_REVIEW = "pending_review"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"


def _update_run(thread_id: str, **fields) -> None:
    try:
        db = SessionLocal()
        try:
            db.query(AiopsRun).filter(AiopsRun.thread_id == thread_id).update(fields)
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.warning("[run_store] 更新运行记录失败(thread=%s): %s", thread_id, e)


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


def mark_pending_review(thread_id: str, report: str) -> None:
    _update_run(thread_id, status=STATUS_PENDING_REVIEW, report=report)


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
