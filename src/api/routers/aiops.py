"""运维诊断 Agent 的独立 SSE 端点(简历版)。

为什么独立端点、不接进 chat/rag_service:
  - rag_service.query() 已改为 async,但 Plan-Execute-Replan 图仍需要独立 async 流式控制;
  - 诊断过程要实时推给前端(计划→逐步执行→报告),SSE 最自然;
  - 解耦: 运维诊断自成一路,不动现有 RAG 链路,demo 时单独展示。
"""

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from src.agent.aiops import aiops_service
from src.api.dependencies import get_current_user
from src.database.models import User
from src.utils.logger import logger
from src.utils.metrics import (
    AIOPS_DIAGNOSIS_TOTAL,
    AIOPS_DIAGNOSIS_DURATION,
    AIOPS_ACTIVE_DIAGNOSES,
)
import time

router = APIRouter()


class AIOpsRequest(BaseModel):
    """诊断请求。"""

    query: str                      # 故障现象 / 诊断任务描述
    session_id: str | None = None   # 会话 ID(用于 checkpointer 隔离)


@router.post("")
async def diagnose_stream(
    request: AIOpsRequest,
    current_user: User = Depends(get_current_user),
):
    """故障诊断(流式 SSE)。

    事件流(event: message, data: JSON):
      {type: plan}          计划已制定
      {type: step_complete} 每步执行完成
      {type: report}        最终报告
      {type: complete}      诊断结束(带完整 response)
      {type: error}         出错
    """
    session_id = request.session_id or "default"
    start_time = time.time()
    AIOPS_ACTIVE_DIAGNOSES.inc()
    final_result = "failed"  # 默认值,出错时记录

    async def event_generator():
        nonlocal final_result
        try:
            async for event in aiops_service.execute(
                user_input=request.query, session_id=session_id
            ):
                yield {
                    "event": "message",
                    "data": json.dumps(event, ensure_ascii=False),
                }
                if event.get("type") == "complete":
                    final_result = "success"
                    break
                if event.get("type") == "error":
                    final_result = "failed"
                    break
        except Exception as e:
            logger.error(f"[aiops] SSE 流异常: {e}", exc_info=True)
            yield {
                "event": "message",
                "data": json.dumps(
                    {"type": "error", "stage": "exception", "message": f"诊断异常: {e}"},
                    ensure_ascii=False,
                ),
            }
        finally:
            # Prometheus 业务指标:诊断结果 + 耗时 + 活跃数
            duration = time.time() - start_time
            AIOPS_DIAGNOSIS_TOTAL.labels(result=final_result).inc()
            AIOPS_DIAGNOSIS_DURATION.observe(duration)
            AIOPS_ACTIVE_DIAGNOSES.dec()
            logger.info(f"[aiops] 诊断结束 result={final_result} duration={duration:.2f}s")

    return EventSourceResponse(event_generator())
