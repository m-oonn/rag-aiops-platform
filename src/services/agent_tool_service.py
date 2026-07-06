"""Agent MCP 工具加载与执行服务。

把 Agent.tools_config 里描述的 MCP 服务器转成可用工具，并通过 LLM 函数调用
完成单轮/多轮工具执行。设计目标：与现有 RAG/chat 架构保持一致的降级策略，
MCP 加载失败时不阻断主流程。

MCP 连接管理已统一迁移至 src/agent/mcp_client.py，本模块只做两件事：
  1) 调 mcp_client.load_tools_for_config() 加载工具
  2) LLM function calling 多轮工具执行
"""

import asyncio
from typing import Any, Optional

from langchain_core.tools import BaseTool
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from src.agent.mcp_client import load_tools_for_config
from src.database.models import Agent
from src.llm.llm_client import LLMClient
from src.agent.aiops_llm import create_agent_llm
from src.utils.logger import logger
from src.utils.tracing import trace_span
from src.services.execution_log_service import write_agent_execution

# 默认超时（秒）。可在 agent.execution_config 里按 Agent 覆盖。
_DEFAULT_MCP_LOAD_TIMEOUT = 10.0
_DEFAULT_TOOL_TIMEOUT = 30.0
_DEFAULT_LLM_TIMEOUT = 60.0
_DEFAULT_MAX_ITERATIONS = 5


async def _with_timeout(coro, timeout: float, description: str):
    """包装协程，增加超时保护。超时时抛出可读异常。"""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError as e:
        raise asyncio.TimeoutError(f"{description} 超时（{timeout}s）") from e


async def load_agent_tools(agent: Agent) -> tuple[list[BaseTool], Optional[str]]:
    """根据 Agent.tools_config 加载 MCP 工具。

    委托给 mcp_client.load_tools_for_config()，由统一封装管理连接缓存和降级。
    返回 (tools, error)，不向上抛异常。
    """
    tools_config = agent.tools_config
    if not tools_config:
        return [], None
    logger.info("Agent %s 加载 MCP 工具", agent.id)
    return await load_tools_for_config(tools_config, timeout=_DEFAULT_MCP_LOAD_TIMEOUT)


def _get_agent_llm(agent: Agent):
    """为 Agent 获取适合的 LLM 实例（ChatOpenAI compatible-mode）。

    优先使用 Agent 专属的 create_agent_llm()（支持 function calling），
    失败时降级到 RAG 路径的 LLMClient。
    """
    model = None
    temperature = 0.0
    if agent.llm_config and isinstance(agent.llm_config, dict):
        model = agent.llm_config.get("model")
        temperature = agent.llm_config.get("temperature", 0.0)

    try:
        return create_agent_llm(model=model, temperature=temperature)
    except Exception as e:
        logger.warning("create_agent_llm 失败，降级到 LLMClient: %s", e)
        llm_client = LLMClient()
        return llm_client.llm if llm_client.llm else None


def _get_execution_config(agent: Agent) -> dict:
    """读取 agent.execution_config，若不是字典则返回空字典。"""
    config = agent.execution_config
    return config if isinstance(config, dict) else {}


async def _execute_tool_calls(
    agent: Agent,
    tools: list[BaseTool],
    tool_calls: list[dict[str, Any]],
    tool_timeout: float,
) -> list[tuple[str, str, Any]]:
    """并发执行一批 tool_calls，返回 (tool_call_id, tool_name, result) 列表。

    独立的工具调用之间没有依赖，并发执行可以缩短多工具诊断链路耗时。
    """
    async def _run_one(tool_call: dict[str, Any]) -> tuple[str, str, Any]:
        tool_call_id = tool_call.get("id", "")
        tool_name = tool_call.get("name")
        tool_args = tool_call.get("args") or {}

        tool = next((t for t in tools if t.name == tool_name), None)
        if tool is None:
            return tool_call_id, tool_name, f"Tool {tool_name} not found."

        try:
            result = await _with_timeout(
                tool.ainvoke(tool_args),
                timeout=tool_timeout,
                description=f"Agent {agent.id} 调用 {tool_name}",
            )
            return tool_call_id, tool_name, result
        except Exception as e:
            logger.warning("Agent %s 调用工具 %s 失败: %s", agent.id, tool_name, e)
            return tool_call_id, tool_name, f"Error executing {tool_name}: {e}"

    return await asyncio.gather(*(_run_one(tc) for tc in tool_calls))


async def execute_agent_query(
    agent: Agent,
    query: str,
    llm_client: Optional[LLMClient] = None,
) -> dict[str, Any]:
    async with trace_span("execute_agent_query", agent_id=agent.id):
        agent_llm = _get_agent_llm(agent)
    if agent_llm is None:
        _write_log(agent.id, query, "LLM 服务暂不可用，请稍后重试。", None, "llm_fallback")
        return {
            "query": query,
            "answer": "LLM 服务暂不可用，请稍后重试。",
            "tool_calls": [],
            "degradation": "llm_fallback",
        }

    exec_config = _get_execution_config(agent)
    max_iterations = exec_config.get("max_iterations", _DEFAULT_MAX_ITERATIONS)
    llm_timeout = exec_config.get("llm_timeout", _DEFAULT_LLM_TIMEOUT)
    tool_timeout = exec_config.get("tool_timeout", _DEFAULT_TOOL_TIMEOUT)

    system_prompt = agent.system_prompt or "You are a helpful assistant."
    if "Markdown" not in system_prompt and "markdown" not in system_prompt:
        system_prompt += "\n\n请使用 Markdown 格式输出回答，合理使用标题、列表、加粗、代码块等排版。"

    # 加载 MCP 工具
    tools, error = await load_agent_tools(agent)

    if error or not tools:
        if error:
            logger.info("Agent %s 工具加载失败，降级为纯 LLM 问答", agent.id)
        try:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=query),
            ]
            response = await _with_timeout(
                agent_llm.ainvoke(messages),
                timeout=llm_timeout,
                description=f"Agent {agent.id} LLM 降级调用",
            )
            answer = response.content if hasattr(response, "content") else str(response)
        except Exception as e:
            logger.error("Agent %s 纯 LLM 降级也失败: %s", agent.id, e)
            answer = "抱歉，工具服务暂时不可用，请稍后重试。"

        _write_log(agent.id, query, answer, None, "tools_unavailable")
        return {
            "query": query,
            "answer": answer,
            "tool_calls": [],
            "degradation": "tools_unavailable",
        }

    # 工具可用 → function calling 多轮执行
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=query),
    ]

    llm_with_tools = agent_llm.bind_tools(tools)
    try:
        response = await _with_timeout(
            llm_with_tools.ainvoke(messages),
            timeout=llm_timeout,
            description=f"Agent {agent.id} LLM 决策",
        )
    except Exception as e:
        logger.error("Agent %s LLM 决策失败: %s", agent.id, e)
        _write_log(agent.id, query, "模型决策时出错，请稍后重试。", None, "llm_fallback")
        return {
            "query": query,
            "answer": "模型决策时出错，请稍后重试。",
            "tool_calls": [],
            "degradation": "llm_fallback",
        }

    executed_tool_calls: list[dict[str, Any]] = []
    any_tool_failed = False
    for _ in range(max_iterations):
        if not response.tool_calls:
            break

        for tc in response.tool_calls:
            executed_tool_calls.append({
                "name": tc.get("name"),
                "args": tc.get("args") or {},
            })

        results = await _execute_tool_calls(
            agent, tools, response.tool_calls, tool_timeout
        )

        for _, tool_name, tool_result in results:
            if isinstance(tool_result, str) and tool_result.startswith("Error executing"):
                any_tool_failed = True

        messages.append(response)
        for tool_call_id, tool_name, tool_result in results:
            messages.append(ToolMessage(
                content=str(tool_result),
                tool_call_id=tool_call_id,
            ))

        try:
            response = await _with_timeout(
                llm_with_tools.ainvoke(messages),
                timeout=llm_timeout,
                description=f"Agent {agent.id} LLM 再决策",
            )
        except Exception as e:
            logger.error("Agent %s LLM 再决策失败: %s", agent.id, e)
            _write_log(agent.id, query, "模型再决策时出错，请稍后重试。", executed_tool_calls, "llm_fallback")
            return {
                "query": query,
                "answer": "模型再决策时出错，请稍后重试。",
                "tool_calls": executed_tool_calls,
                "degradation": "llm_fallback",
            }

    degradation = "tools_partial" if any_tool_failed else None
    _write_log(agent.id, query, response.content, executed_tool_calls, degradation)
    return {
        "query": query,
        "answer": response.content,
        "tool_calls": executed_tool_calls,
        "degradation": degradation,
    }


def _write_log(agent_id: int, query: str, answer: str, tool_calls: list | None, degradation: str | None) -> None:
    """同步写执行日志，内部吞异常。"""
    try:
        write_agent_execution(
            agent_id=agent_id, query=query, answer=answer,
            tool_calls=tool_calls, degradation=degradation,
        )
    except Exception as e:
        logger.warning("[execute_agent_query] write_agent_execution 失败: %s", e)
