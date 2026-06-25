"""Replanner 节点:评估已执行步骤,决定 continue / replan / respond。

三决策(按优先级):
  - respond: 信息足够,生成最终诊断报告(最高优先级,不追求完美);
  - continue: 剩余计划合理,继续执行;
  - replan: 原计划有严重问题,替换剩余步骤(最低优先级,严格限制)。

硬限制(防止无限循环,标准 Plan-Execute 教程做法):
  - past_steps >= MAX_STEPS(8): 强制 respond;
  - past_steps >= 5: 禁止 replan,只能 respond;
  - 新步骤数不超过当前剩余步骤数。
"""

from textwrap import dedent
from typing import Any, Dict, List

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from src.agent.aiops.state import PlanExecuteState
from src.agent.aiops.structured import ainvoke_structured
from src.agent.aiops_llm import create_agent_llm
from src.utils.logger import logger

MAX_STEPS = 8           # 总步数上限,超过强制出报告
NO_REPLAN_AFTER = 5     # 执行步数到此禁止 replan
_STEP_PREVIEW = 300     # 喂给 LLM 的单步结果截断长度


class Act(BaseModel):
    """重新规划的输出格式。"""

    action: str = Field(
        description="下一步行动: 'continue'(继续) / 'replan'(调整计划) / 'respond'(出报告)"
    )
    new_steps: List[str] = Field(
        default_factory=list,
        description="action='replan' 时的新步骤列表(替换剩余计划)",
    )


class Response(BaseModel):
    """最终诊断报告。"""

    response: str = Field(description="给用户的最终诊断报告(Markdown)")


replanner_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            dedent(
                """
                你是重新规划专家,根据已执行步骤决定下一步。三选一(按优先级):

                1. 'respond'【最高】信息已足够回答 → 立即出报告。已执行>=3且拿到关键信息、
                   或已执行>=5(无论结果)、或信息已满足任务,都应 respond。不要追求完美。
                2. 'continue'【次】剩余步骤确实必要才继续。
                3. 'replan'【最低,谨慎】原计划明显错误或漏关键步骤才用。新步骤数必须<=剩余步骤数。

                口诀: 优先结束 > 保持不变 > 调整计划;信息足够就响应。
                """
            ).strip(),
        ),
        ("placeholder", "{messages}"),
    ]
)

response_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            dedent(
                """
                根据原始任务和已执行步骤的结果,生成全面的最终诊断报告。要求:
                - 清晰、结构化,用 Markdown;
                - 基于实际数据,不编造;某步失败要诚实说明;
                - 给出根因分析和处理建议。
                """
            ).strip(),
        ),
        ("placeholder", "{messages}"),
    ]
)


def _format_steps(past_steps: list) -> str:
    return "\n".join(
        f"步骤: {step}\n结果: {str(result)[:_STEP_PREVIEW]}" for step, result in past_steps
    )


async def _generate_response(state: PlanExecuteState) -> Dict[str, Any]:
    """生成最终诊断报告。"""
    logger.info("[replanner] 生成最终报告...")
    input_text = state.get("input", "")
    past_steps = state.get("past_steps", [])
    history = "\n\n".join(
        f"### 步骤: {step}\n**结果:**\n{result}" for step, result in past_steps
    )

    llm = create_agent_llm(temperature=0)
    chain = response_prompt | llm.with_structured_output(Response)
    try:
        result = await ainvoke_structured(
            llm, Response, response_prompt,
            {
                "messages": [
                    ("user", f"原始任务: {input_text}"),
                    ("user", f"执行历史:\n{history}"),
                    ("user", "请基于以上信息生成全面的最终诊断报告"),
                ]
            }
        )
        final = result.response
        logger.info(f"[replanner] 报告生成完成,长度 {len(final)}")
        return {"response": final}
    except Exception:
        logger.exception("[replanner] 生成报告失败,用兜底")
        steps_md = "\n".join(f"- {s}: {str(r)[:200]}" for s, r in past_steps) or "无"
        return {
            "response": dedent(
                f"""
                # 诊断结果(降级)
                ## 原始任务
                {input_text}
                ## 已执行步骤
                {steps_md}
                ## 说明
                系统异常,无法生成完整报告,以上为已收集信息。
                """
            ).strip()
        }


async def replanner(state: PlanExecuteState) -> Dict[str, Any]:
    """重新规划节点:三决策。"""
    logger.info("=== Replanner:评估 ===")
    input_text = state.get("input", "")
    plan = state.get("plan", [])
    past_steps = state.get("past_steps", [])
    logger.info(f"[replanner] 剩余 {len(plan)} 步,已执行 {len(past_steps)} 步")

    # 硬限制:步数过多强制出报告
    if len(past_steps) >= MAX_STEPS:
        logger.warning(f"[replanner] 已执行 {len(past_steps)} 步,超上限,强制 respond")
        return await _generate_response(state)

    # 计划已空,出报告
    if not plan:
        logger.info("[replanner] 计划执行完毕,出报告")
        return await _generate_response(state)

    llm = create_agent_llm(temperature=0)
    try:
        act = await ainvoke_structured(
            llm, Act, replanner_prompt,
            {
                "messages": [
                    ("user", f"原始任务: {input_text}"),
                    ("user", f"已执行步骤:\n{_format_steps(past_steps)}"),
                    ("user", f"剩余计划: {', '.join(plan)}"),
                    ("user", f"提示: 已执行 {len(past_steps)} 步,优先考虑信息是否已足够 respond"),
                ]
            }
        )
        action = act.action
        new_steps = act.new_steps
        logger.info(f"[replanner] 决策: {action}")

        if action == "respond":
            return await _generate_response(state)

        if action == "replan":
            if len(past_steps) >= NO_REPLAN_AFTER:
                logger.warning(f"[replanner] 已执行 {len(past_steps)} 步,禁止 replan,强制 respond")
                return await _generate_response(state)
            if len(new_steps) > len(plan):
                logger.warning(f"[replanner] 新步骤数 {len(new_steps)}>剩余 {len(plan)},截断")
                new_steps = new_steps[: len(plan)]
            if new_steps:
                return {"plan": new_steps}
            logger.warning("[replanner] replan 但无新步骤,继续原计划")
            return {}

        # continue
        return {}

    except Exception:
        logger.exception("[replanner] 评估失败,继续原计划")
        return {}
