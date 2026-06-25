"""Planner 节点:制定诊断计划。

流程:
  1. 用 VectorRetriever 查一次知识库,捞相关排查经验(best-effort,查不到不报错);
  2. 加载 MCP 工具(指标/日志)列表,供 LLM 制定计划时参考用哪个工具;
  3. with_structured_output(Plan) 强制 LLM 输出步骤列表。

参考 OnCall app/agent/aiops/planner.py,改用 ChatOpenAI(compatible-mode) + 现有
VectorRetriever(不引 OnCall 的 vector_store_manager)。
"""

from textwrap import dedent
from typing import Any, Dict, List

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from src.agent.aiops.state import PlanExecuteState
from src.agent.aiops.tools import load_agent_tools
from src.agent.aiops.structured import ainvoke_structured
from src.agent.aiops_llm import create_agent_llm
from src.retrieval.vector_retriever import VectorRetriever
from src.settings import settings
from src.utils.logger import logger

# 经验检索捞几条;太多会撑爆 prompt。
_EXPERIENCE_TOP_K = 3


class Plan(BaseModel):
    """计划输出格式。"""

    steps: List[str] = Field(
        description="完成诊断所需的步骤,按顺序执行,每步说明用哪个工具(若需要)及参数。"
    )


planner_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            dedent(
                """
                你是一个专家级运维诊断规划者,负责把故障诊断任务拆成可执行的步骤。

                可用工具列表(制定计划时参考,实际调用由执行器负责):
                {tools_description}

                {experience_context}

                请为给定任务创建简单、逐步的计划。要求:
                - 每步逻辑独立,明确用哪个工具(如需)及参数;
                - 步骤之间有清晰依赖;
                - 若有相关经验文档,参考其中的排查方法;
                - 步骤要具体可操作,不要空泛。
                """
            ).strip(),
        ),
        ("placeholder", "{messages}"),
    ]
)


def _format_tools(tools: list) -> str:
    """把工具列表格式化成 名称: 描述 的多行文本。"""
    if not tools:
        return "(当前无可用工具)"
    return "\n".join(f"- {t.name}: {t.description}" for t in tools)


def _retrieve_experience(query: str) -> str:
    """查知识库捞排查经验。best-effort: 任何失败都返回空串,不阻断诊断。"""
    try:
        retriever = VectorRetriever()
        results = retriever.retrieve(query, top_k=_EXPERIENCE_TOP_K)
        if not results:
            return ""
        parts = [f"【经验 {i}】{r.text}" for i, r in enumerate(results, 1)]
        block = "\n".join(parts)
        return dedent(
            f"""
            ## 相关排查经验
            以下是从知识库检索到的经验,请参考:
            {block}
            ---
            """
        ).strip()
    except Exception as e:
        logger.warning(f"[planner] 经验检索失败(忽略): {e}")
        return ""


async def planner(state: PlanExecuteState) -> Dict[str, Any]:
    """规划节点:据输入生成诊断步骤列表。"""
    logger.info("=== Planner:制定诊断计划 ===")
    input_text = state.get("input", "")

    try:
        experience_context = _retrieve_experience(input_text)
        tools, err = await load_agent_tools()
        if err:
            logger.warning(f"[planner] MCP 工具加载失败: {err}")
        tools_description = _format_tools(tools)

        llm = create_agent_llm(temperature=0)
        result = await ainvoke_structured(llm, Plan, planner_prompt, {
            "messages": [("user", input_text)],
            "tools_description": tools_description,
            "experience_context": experience_context,
        })
        steps = result.steps
        logger.info(f"[planner] 计划已生成,共 {len(steps)} 步")
        return {"plan": steps}

    except Exception as e:
        logger.error(f"[planner] 生成计划失败,用默认计划: {e}", exc_info=True)
        return {"plan": ["收集相关指标和日志", "分析数据定位问题", "生成诊断报告"]}
