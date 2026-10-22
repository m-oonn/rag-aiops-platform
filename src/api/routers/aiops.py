"""运维诊断 Agent 的独立 SSE 端点(简历版)。

为什么独立端点、不接进 chat/rag_service:
  - rag_service.query() 已改为 async,但 Plan-Execute-Replan 图仍需要独立 async 流式控制;
  - 诊断过程要实时推给前端(计划→逐步执行→报告),SSE 最自然;
  - 解耦: 运维诊断自成一路,不动现有 RAG 链路,demo 时单独展示。
"""

import json
import re
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from src.agent.aiops import aiops_service, run_store
from src.api.dependencies import get_current_user
from src.database.models import User
from src.agent.aiops.termcp_tools import TerminalApprovalStatusError, verify_terminal_approval
from src.settings import settings
from src.utils.logger import logger
from src.utils.metrics import (
    AIOPS_DIAGNOSIS_TOTAL,
    AIOPS_DIAGNOSIS_DURATION,
    AIOPS_ACTIVE_DIAGNOSES,
)

router = APIRouter()


class AIOpsRequest(BaseModel):
    """诊断请求。"""

    query: str                      # 故障现象 / 诊断任务描述
    session_id: str | None = None   # 会话 ID(用于 checkpointer 隔离)
    terminal_enabled: bool = False


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
    if request.terminal_enabled and not settings.TERMCP_ENABLED:
        raise HTTPException(status_code=503, detail="受控终端诊断尚未启用")
    start_time = time.time()
    AIOPS_ACTIVE_DIAGNOSES.inc()
    final_result = "failed"  # 默认值,出错时记录

    # ── token 计量（2026-10-09 新增）──────────────────────────────
    # 设计: 服务端持久启用（几乎零成本——只是在 LLM 调用上挂一个回调),
    #      诊断结束后把本次消耗(含折算费用)推给前端/测试脚本;
    #      前端据此展示"本次诊断消耗",测试脚本据此记录真实损耗。
    from src.utils.token_meter import start_meter, stop_meter
    meter = start_meter()

    async def event_generator():
        nonlocal final_result
        try:
            async for event in aiops_service.execute(
                user_input=request.query, session_id=session_id,
                user_id=current_user.id,
                terminal_enabled=request.terminal_enabled,
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

            # 推送本次 token 消耗（独立事件类型,前端可选择性展示）
            try:
                m = stop_meter() or meter
                usage = m.as_dict()
                usage["elapsed_s"] = round(duration, 2)
                logger.info(
                    "[aiops] 本次消耗: %s 次LLM调用, 入 %s / 出 %s tokens, 约 ¥%.4f, 耗时 %.1fs",
                    usage.get("llm_calls"), usage.get("input_tokens"),
                    usage.get("output_tokens"), usage.get("cost_cny_estimated", 0), duration,
                )
                yield {
                    "event": "message",
                    "data": json.dumps({"type": "usage", **usage}, ensure_ascii=False),
                }
            except Exception as ue:
                logger.warning(f"[aiops] token 计量汇总失败(不影响诊断): {ue}")

    return EventSourceResponse(event_generator())


def _owned_run(thread_id: str, user: User):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", thread_id):
        raise HTTPException(status_code=400, detail="thread_id 非法")
    run = run_store.get_run(thread_id)
    if not run or run.user_id != user.id:
        raise HTTPException(status_code=404, detail="诊断不存在")
    return run


@router.get("/runs/{thread_id}")
async def get_run_status(thread_id: str, current_user: User = Depends(get_current_user)):
    run = _owned_run(thread_id, current_user)
    approval = run.terminal_approval if isinstance(run.terminal_approval, dict) else None
    return {
        "thread_id": run.thread_id,
        "status": run.status,
        "report": run.report,
        "terminal_approval": approval,
        "termcp_ui_url": settings.TERMCP_UI_URL if approval else None,
        'diagnosis': await aiops_service.run_diagnosis(thread_id),
    }


@router.post("/runs/{thread_id}/continue")
async def continue_run(thread_id: str, current_user: User = Depends(get_current_user)):
    run = _owned_run(thread_id, current_user)
    if run.status == run_store.STATUS_PENDING_TERMINAL:
        try:
            await verify_terminal_approval(run.terminal_approval or {})
        except TerminalApprovalStatusError as exc:
            if exc.terminal:
                run_store.mark_failed(thread_id, str(exc))
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        decision = {"action": "approve"}
    elif run.status == run_store.STATUS_PENDING_REVIEW:
        raise HTTPException(status_code=409, detail="此诊断等待的不是 Termcp 命令审批")
    else:
        raise HTTPException(status_code=409, detail="诊断当前不处于可续跑状态")

    async def event_generator():
        async for event in aiops_service.resume(thread_id, decision):
            yield {"event": "message", "data": json.dumps(event, ensure_ascii=False)}

    return EventSourceResponse(event_generator())


@router.get("/runs/{thread_id}/steps")
async def get_run_steps(
    thread_id: str,
    current_user: User = Depends(get_current_user),
):
    """诊断步级快照（B3：回放/审计数据源）。

    快照由 AIOpsService 在图执行时落库（ENABLE_STEP_SNAPSHOTS 开启时）；
    未开启或无记录时返回空列表。
    """
    _owned_run(thread_id, current_user)
    steps = run_store.list_step_snapshots(thread_id)
    return {"thread_id": thread_id, "total": len(steps), "steps": steps}


@router.get("/runs/{thread_id}/evidence")
async def get_run_evidence(thread_id: str, current_user: User = Depends(get_current_user)):
    """Return the redacted evidence ledger for an owned run."""
    _owned_run(thread_id, current_user)
    rows = run_store.list_evidence(thread_id, current_user.id)
    return {"thread_id": thread_id, "total": len(rows), "evidence": rows,
            "can_read_raw": getattr(current_user, "role", "user") in {"admin", "auditor"}}


@router.get("/runs/{thread_id}/evidence/{evidence_id}")
async def get_run_evidence_item(thread_id: str, evidence_id: str, current_user: User = Depends(get_current_user)):
    _owned_run(thread_id, current_user)
    if not re.fullmatch(r"ev-[A-Za-z0-9]{16,80}", evidence_id):
        raise HTTPException(status_code=400, detail="evidence_id 非法")
    is_auditor = getattr(current_user, "role", "user") in {"admin", "auditor"}
    row = run_store.get_evidence(thread_id, evidence_id, current_user.id, include_raw=is_auditor)
    if not row:
        raise HTTPException(status_code=404, detail="证据不存在")
    # Raw file paths remain hidden from normal operators.  Audit/admin users
    # can use the protected reference through the separately secured store.
    if not is_auditor:
        row.pop("raw_ref", None)
    return row


@router.get("/targets/{target_id}/status")
async def get_probe_target_status(target_id: str, current_user: User = Depends(get_current_user)):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", target_id):
        raise HTTPException(status_code=400, detail="target_id 非法")
    if target_id != settings.PROBE_TARGET_ID:
        raise HTTPException(status_code=404, detail="目标不存在")
    status = run_store.get_probe_target(target_id)
    if not status:
        raise HTTPException(status_code=404, detail="目标尚未注册")
    return status
