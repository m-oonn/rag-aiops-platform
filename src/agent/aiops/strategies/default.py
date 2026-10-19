"""默认 Replanner 策略：三决策 continue / replan / respond。

搬运自 src/agent/aiops/replanner.py 的当前实现，行为不变。
"""

from textwrap import dedent
from typing import Any, Dict, List

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from src.agent.aiops.state import PlanExecuteState
from src.agent.aiops.strategies.base import BaseReplanStrategy
from src.agent.aiops.structured import ainvoke_structured
from src.agent.aiops_llm import create_agent_llm
from src.agent.aiops.evidence_sources import format_knowledge_references
from src.agent.aiops.report_text import readable_tool_text
from src.utils.logger import logger

MAX_STEPS = 8
NO_REPLAN_AFTER = 5
_STEP_PREVIEW = 300


class Act(BaseModel):
    action: str = Field(
        description="下一步行动: 'continue'(继续) / 'replan'(调整计划) / 'respond'(出报告)"
    )
    new_steps: List[str] = Field(
        default_factory=list,
        description="action='replan' 时的新步骤列表(替换剩余计划)",
    )


class Response(BaseModel):
    response: str = Field(description="给用户的最终诊断报告(Markdown)")


replanner_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            dedent(
                """
                你是重新规划专家,根据已执行步骤决定下一步。三选一(按优先级):

                1. 'respond'【最高】信息已足够回答 → 立即出报告。自主调查时必须有现场证据
                   支持结论，并检查关键替代解释；不能仅因执行了若干步就结束。
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
                根据原始任务和已执行步骤的结果,生成最终诊断报告。

                报告的读者是**不懂技术的普通人**(业务同事、普通用户)。
                目标:让 TA 读完一眼就知道"现在什么情况、要不要管、下一步做什么"。

                写作要求:
                - 结论先行:开头第一段直接回答"现在到底是什么情况"——正常 / 有问题 /
                  暂时判断不了,一句话说清,不卖关子、不铺垫;
                - 说人话:用通顺的日常中文,像当面给朋友解释;必须出现的专业词
                  (如 HTTP 状态码、CPU、响应耗时)要顺手用括号解释一句
                  (例:"HTTP 200(表示网页能正常打开)");
                - **禁止出现**:工具/函数名(check_website、search_log 等)、参数写法
                  (url=…、deep=true)、代码块、JSON、文件路径、原始日志行、堆栈信息——
                  这些读者看不懂,必须转述成自然语言;
                - 数字要有解读:给出关键数据时说明它意味着什么
                  (例:"响应约 40 毫秒,打开速度很快");
                - 如实陈述:结论必须来自上面的检查数据,不编造;某项检查没做成的,用大白话
                  说清"哪项没查成、对结论有什么影响";结果没问题就大方说"一切正常、
                  无需处理",不要为了凑篇幅硬找问题;任务是对网址/网站做健康检查时,
                  按探测结果如实下结论(正常就写"网站正常"并附响应速度);
                - **数据可信度(硬约束)**: 只按结果里的**数据来源标记**判断真伪——
                  标注了"Mock演示数据/非真实"或"真实数据源不可用"的,说明该项**没拿到
                  真实数据**:不得当作根因的主要证据,不得引用其中具体的 CPU/内存数值或
                  日志堆栈内容,只能如实写"该项未取得真实数据(数据源未接入)",并说明
                  这对结论的限制;反之,标注为**真实数据源**(如 Elasticsearch)的指标/
                  日志就是**真实证据**,应当采用——**不得仅因日志里出现 OutOfMemoryError
                  等异常堆栈,就怀疑它是演示数据而弃用**;
                - 控制篇幅:能三句说清就别写十句,全文尽量不超过 600 字,宁可简短清楚、
                  不要又长又碎。

                报告结构(Markdown,可用标题/短段落/列表/表格):
                1. 标题 + 一句话结论(可加 ✅ / ⚠️ / ❌ 等直观标记);
                2. "我们检查了什么":2-4 条,列出这次检查了哪些方面;
                3. "发现了什么":关键数据与发现,每项都让读者看得懂;
                4. "建议怎么做":有问题给出具体、可执行的建议;没问题就写
                   "目前无需处理,保持关注即可"。
                """
            ).strip(),
        ),
        ("placeholder", "{messages}"),
    ]
)


def _battlefield_summary(
    input_text: str, past_steps: list, plan: list, max_steps: int, no_replan_after: int,
) -> str:
    done = len(past_steps)
    remain = len(plan)
    lines = [
        "## 当前战场状态",
        f"- 原始任务: {input_text[:200]}",
        f"- 进度: 已执行 {done} 步, 剩余 {remain} 步 (上限 {max_steps} 步)",
    ]
    if done >= no_replan_after:
        lines.append(f"- ⚠️ 已执行 {done} 步 >= {no_replan_after}, 禁止 replan, 只能 continue 或 respond")

    for i, (step, result) in enumerate(past_steps, 1):
        summary = readable_tool_text(str(result))[:200].replace("\n", " ")
        lines.append(f"- [已完成 {i}] {step[:120]}")
        lines.append(f"  结果摘要: {summary}")

    if remain:
        next_up = plan[0][:120]
        lines.append(f"- 下一步: {next_up}")
        if len(plan) > 1:
            lines.append(f"- 之后还有 {len(plan) - 1} 步: {' → '.join(s[:40] for s in plan[1:4])}")

    return "\n".join(lines)


async def _generate_response(state: PlanExecuteState) -> Dict[str, Any]:
    logger.info("[replanner] 生成最终报告...")
    input_text = state.get("input", "")
    past_steps = state.get("past_steps", [])
    history = "\n\n".join(
        f"### 步骤: {step}\n**结果:**\n{readable_tool_text(result)}" for step, result in past_steps
    )

    llm = create_agent_llm(temperature=0)
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
        final += format_knowledge_references(state.get("raw_evidence"))
        logger.info(f"[replanner] 报告生成完成,长度 {len(final)}")
        return {"response": final}
    except Exception:
        logger.exception("[replanner] 生成报告失败,用兜底")
        steps_md = "\n".join(f"- {s}: {readable_tool_text(r)[:200]}" for s, r in past_steps) or "无"
        return {
            "response": dedent(
                f"""
                # 诊断结果

                ## 本次检查的任务
                {input_text}

                ## 已完成的检查
                {steps_md}

                ## 说明
                抱歉,自动整理完整报告时出了点问题,以上是目前已收集到的信息。
                """
            ).strip() + format_knowledge_references(state.get("raw_evidence"))
        }


class DefaultReplanStrategy(BaseReplanStrategy):
    """默认 replan 策略：简单的三决策 + 硬限制。

    这是当前生产使用的策略。Phase 3 的 DynamicClassificationStrategy
    将替代此策略注入 AIOpsService。
    """

    async def decide(self, state: PlanExecuteState) -> Dict[str, Any]:
        logger.info("=== [role=replanner] DefaultReplanStrategy:评估 ===")
        input_text = state.get("input", "")
        plan = state.get("plan", [])
        past_steps = state.get("past_steps", [])
        logger.info(f"[replanner] 剩余 {len(plan)} 步,已执行 {len(past_steps)} 步")

        autonomous = bool(state.get("autonomous_investigation"))
        if len(past_steps) >= MAX_STEPS and not autonomous:
            logger.warning(f"[replanner] 已执行 {len(past_steps)} 步,超上限,强制 respond")
            return await _generate_response(state)

        if not plan:
            logger.info("[replanner] 计划执行完毕,出报告")
            return await _generate_response(state)

        llm = create_agent_llm(temperature=0)
        try:
            summary = _battlefield_summary(input_text, past_steps, plan, MAX_STEPS, NO_REPLAN_AFTER)
            act = await ainvoke_structured(
                llm, Act, replanner_prompt,
                {
                    "messages": [
                        ("user", summary),
                        ("user", "请根据以上战场状态决定下一步行动"),
                    ]
                }
            )
            action = act.action
            new_steps = act.new_steps
            logger.info(f"[replanner] 决策: {action}")

            if action == "respond":
                return await _generate_response(state)

            if action == "replan":
                if len(past_steps) >= NO_REPLAN_AFTER and not autonomous:
                    logger.warning(f"[replanner] 已执行 {len(past_steps)} 步,禁止 replan,强制 respond")
                    return await _generate_response(state)
                if len(new_steps) > len(plan):
                    logger.warning(f"[replanner] 新步骤数 {len(new_steps)}>剩余 {len(plan)},截断")
                    new_steps = new_steps[: len(plan)]
                if new_steps:
                    return {"plan": new_steps}
                logger.warning("[replanner] replan 但无新步骤,继续原计划")
                return {}

            return {}

        except Exception:
            logger.exception("[replanner] 评估失败,继续原计划")
            return {}
