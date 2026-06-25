"""Executor 节点:执行计划中的下一个步骤。

用 LangGraph 的 ToolNode 自动处理工具调用:
  1. LLM bind_tools 后决定是否调工具;
  2. 有 tool_calls 则 ToolNode 执行,结果回填再让 LLM 总结;
  3. 无 tool_calls 则直接用 LLM 输出。
执行完移除该步、把 (步骤, 结果) 追加进 past_steps。
"""

from typing import Any, Dict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import ToolNode

from src.agent.aiops.state import PlanExecuteState
from src.agent.aiops.tools import load_agent_tools
from src.agent.aiops_llm import create_agent_llm
from src.utils.logger import logger

_EXECUTOR_SYSTEM = """你是运维诊断执行器,负责执行单个诊断步骤。

对每个步骤:
1. 理解步骤目标;
2. 若已指定工具就用指定工具,否则选合适工具;
3. 调用工具获取真实数据;
4. 返回执行结果。

注意:
- 工具调用失败要说明原因,不要编造数据;
- 只返回实际获取的信息,结果要清晰准确;
- 专注当前步骤,不考虑其他任务。"""


async def executor(state: PlanExecuteState) -> Dict[str, Any]:
    """执行节点:执行 plan[0],结果写入 past_steps。"""
    logger.info("=== Executor:执行步骤 ===")
    plan = state.get("plan", [])
    if not plan:
        logger.info("[executor] 计划为空,跳过")
        return {}

    task = plan[0]
    logger.info(f"[executor] 当前步骤: {task}")

    try:
        tools, err = await load_agent_tools()
        if err:
            logger.warning(f"[executor] MCP 工具加载失败: {err}")

        llm = create_agent_llm(temperature=0)
        llm_with_tools = llm.bind_tools(tools) if tools else llm
        messages = [
            SystemMessage(content=_EXECUTOR_SYSTEM),
            HumanMessage(content=f"请执行以下诊断步骤: {task}"),
        ]

        llm_response = await llm_with_tools.ainvoke(messages)

        if getattr(llm_response, "tool_calls", None):
            logger.info(f"[executor] 检测到 {len(llm_response.tool_calls)} 个工具调用")
            tool_node = ToolNode(tools)
            messages.append(llm_response)
            tool_result = await tool_node.ainvoke({"messages": messages})
            messages.extend(tool_result["messages"])
            final = await llm_with_tools.ainvoke(messages)
            result = final.content
        else:
            logger.info("[executor] 未调用工具,直接返回 LLM 输出")
            result = llm_response.content

        result = result if isinstance(result, str) else str(result)
        logger.info(f"[executor] 步骤完成,结果长度 {len(result)}")
        return {"plan": plan[1:], "past_steps": [(task, result)]}

    except Exception as e:
        logger.error(f"[executor] 执行步骤失败: {e}", exc_info=True)
        return {"plan": plan[1:], "past_steps": [(task, f"执行失败: {e}")]}
