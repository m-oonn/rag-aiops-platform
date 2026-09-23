"""HITL 人工审批节点（人在回路）。

在 replanner 决定 respond 后、正式输出报告前中断，等待人工审批：
  - approve：直接输出草稿报告（response 已就绪）→ END；
  - reject + instruction：携带人工补充指令回到 executor 重新诊断；
  - reject 无指令：按"补充更多诊断信息"兜底。

中断机制：langgraph.types.interrupt() 挂起图并持久化到 checkpointer，
审批端点用 Command(resume=decision) 恢复（见 graph.AIOpsService.resume）。
"""

from typing import Any, Dict

from langgraph.types import interrupt

from src.agent.aiops.state import PlanExecuteState
from src.utils.logger import logger

# reject 后新计划的兜底步骤
_FALLBACK_PLAN = ["补充更多诊断信息", "交叉验证当前假设"]


def build_human_review_node():
    """构造 HITL 审批节点函数（适配 LangGraph 异步节点）。"""

    async def human_review(state: PlanExecuteState) -> Dict[str, Any]:
        """审批节点：挂起等待人工决策，恢复后决定输出或重诊。"""
        draft = state.get("response") or ""
        logger.info("=== [role=human_review] 报告草稿已生成, 等待人工审批 ===")

        # 挂起：图在此持久化，resume 时该调用返回人工决策
        decision = interrupt({"type": "pending_review", "draft": draft})

        action = decision.get("action") if isinstance(decision, dict) else None
        instruction = ""
        if isinstance(decision, dict):
            instruction = (decision.get("instruction") or "").strip()

        if action == "approve":
            logger.info("[human_review] 审批通过, 输出报告")
            return {}

        # reject：带回人工补充指令（若有）重新诊断
        if instruction:
            new_plan = [f"根据人工反馈补充验证: {instruction}"]
        else:
            new_plan = list(_FALLBACK_PLAN)
        # 保留原计划中未执行的步骤作为补充（respond 时 plan 可能非空）
        remaining = [s for s in (state.get("plan") or []) if s not in new_plan]
        merged = (new_plan + remaining)[:6]
        logger.info("[human_review] 审批驳回, 回到 executor: %s", merged)
        return {"plan": merged, "response": ""}

    return human_review
