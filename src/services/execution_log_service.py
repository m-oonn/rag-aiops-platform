"""Agent 执行记录写入服务。

提供低开销的同步写入，用于将每次 Agent/AIOps 诊断的执行记录持久化到数据库。

设计原则：
  - 同步、零异步、尽量轻（日志场景不需要 await）
  - write_xxx() 内部吞异常，不干扰主流程
  - 被调用方（agent_tool_service / aiops graph）仅在执行完成后调用一次
"""

from sqlalchemy.orm import Session

from src.database.models import AgentExecutionLog
from src.database.sql_session import SessionLocal
from src.utils.logger import logger


def write_agent_execution(
    agent_id: int,
    query: str,
    answer: str,
    tool_calls: list | None = None,
    degradation: str | None = None,
    latency_ms: int | None = None,
) -> None:
    """同步写一条 Agent 执行记录。内部吞异常。"""
    try:
        log = AgentExecutionLog(
            agent_id=agent_id,
            query=query[:5000],
            answer=answer[:10000],
            tool_calls=tool_calls or [],
            tool_count=len(tool_calls) if tool_calls else 0,
            degradation=degradation,
            latency_ms=latency_ms,
        )
        db: Session = SessionLocal()
        try:
            db.add(log)
            db.commit()
        finally:
            db.close()
    except Exception as e:
        logger.warning("[execution_log] 写入 Agent 执行记录失败: %s", e)
