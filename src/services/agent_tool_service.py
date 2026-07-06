"""Agent MCP 工具加载与执行服务。

把 Agent.tools_config 里描述的 MCP 服务器转成可用工具，并通过 LLM 函数调用
完成单轮/多轮工具执行。设计目标：与现有 RAG/chat 架构保持一致的降级策略，
MCP 加载失败时不阻断主流程。

本版本改进：
  - 按 tools_config 缓存 MultiServerMCPClient，避免每次执行都重建连接。
  - 支持一次 LLM 响应中多个 tool_calls 并发执行。
  - 对 MCP 加载、工具调用、LLM 调用增加超时控制。
  - max_iterations 等参数可从 agent.execution_config 读取。
"""

import asyncio
import json
from typing import Any, Optional

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from src.database.models import Agent
from src.llm.llm_client import LLMClient
from src.agent.aiops_llm import create_agent_llm
from src.utils.logger import logger

# 默认超时（秒）。可在 agent.execution_config 里按 Agent 覆盖。
_DEFAULT_MCP_LOAD_TIMEOUT = 10.0
_DEFAULT_TOOL_TIMEOUT = 30.0
_DEFAULT_LLM_TIMEOUT = 60.0
_DEFAULT_MAX_ITERATIONS = 5

# 按 tools_config 缓存 MCP client，减少重复建连。
# key = json.dumps(tools_config, sort_keys=True)
_agent_mcp_clients: dict[str, MultiServerMCPClient] = {}


def _tools_config_key(tools_config: dict) -> str:
    """把 tools_config 转成可哈希的字符串 key，用于 client 缓存。"""
    return json.dumps(tools_config, sort_keys=True, ensure_ascii=False)


async def _with_timeout(coro, timeout: float, description: str):
    """包装协程，增加超时保护。超时时抛出可读异常。"""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError as e:
        raise asyncio.TimeoutError(f"{description} 超时（{timeout}s）") from e


async def load_agent_tools(agent: Agent) -> tuple[list[BaseTool], Optional[str]]:
    """根据 Agent.tools_config 加载 MCP 工具。

    返回 (tools, error)。无 tools_config 或 MCP 不可用时返回空列表和错误信息，
    不向上抛异常，避免炸掉整条调用链。

    同一 tools_config 会复用已创建的 MultiServerMCPClient，避免重复建连。
    """
    tools_config = agent.tools_config
    if not tools_config:
        return [], None

    cache_key = _tools_config_key(tools_config)
    try:
        client = _agent_mcp_clients.get(cache_key)
        if client is None:
            logger.info("Agent %s 创建新的 MultiServerMCPClient", agent.id)
            client = MultiServerMCPClient(tools_config)
            _agent_mcp_clients[cache_key] = client

        tools = await _with_timeout(
            client.get_tools(),
            timeout=_DEFAULT_MCP_LOAD_TIMEOUT,
            description=f"Agent {agent.id} 加载 MCP 工具",
        )
        logger.info("Agent %s 加载 %d 个 MCP 工具", agent.id, len(tools))
        return tools, None
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        logger.error("Agent %s 加载 MCP 工具失败: %s", agent.id, error_msg)
        # 加载失败时清掉缓存，下次重试会重新建连
        _agent_mcp_clients.pop(cache_key, None)
        return [], error_msg


def close_agent_tool_client(tools_config: dict) -> None:
    """关闭指定 tools_config 对应的 MCP client（若存在）。"""
    cache_key = _tools_config_key(tools_config)
    client = _agent_mcp_clients.pop(cache_key, None)
    if client is not None:
        try:
            # 部分版本的 MultiServerMCPClient 可能没有 close 方法
            close_fn = getattr(client, "close", None) or getattr(client, "aclose", None)
            if close_fn is not None:
                asyncio.create_task(close_fn())
                logger.info("已关闭 tools_config 对应的 MCP client")
        except Exception as e:
            logger.warning("关闭 MCP client 时出错: %s", e)


def close_all_agent_tool_clients() -> None:
    """关闭所有缓存的 MCP client。适合应用退出时调用。"""
    for cache_key in list(_agent_mcp_clients.keys()):
        tools_config = json.loads(cache_key)
        close_agent_tool_client(tools_config)


def _get_agent_llm(agent: Agent):
    """为 Agent 获取适合的 LLM 实例（ChatOpenAI compatible-mode）。

    优先使用 Agent 专属的 create_agent_llm()（支持 function calling），
    失败时降级到 RAG 路径的 LLMClient。
    """
    # 从 agent.llm_config 读取模型配置（如果有）
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
    """执行 Agent 的一次查询：加载工具 -> LLM 决策 -> 调用工具 -> 返回结果。

    降级链：
      1. 工具加载成功 → LLM function calling 多轮工具执行
      2. 工具加载失败 → 使用 Agent system_prompt 做纯 LLM 问答（不返回错误信息给用户）
      3. LLM 也不可用 → 返回服务不可用提示
    """
    # 获取 Agent 专用 LLM（ChatOpenAI compatible-mode，支持 function calling）
    agent_llm = _get_agent_llm(agent)
    if agent_llm is None:
        return {
            "query": query,
            "answer": "LLM 服务暂不可用，请稍后重试。",
            "tool_calls": [],
        }

    exec_config = _get_execution_config(agent)
    max_iterations = exec_config.get("max_iterations", _DEFAULT_MAX_ITERATIONS)
    llm_timeout = exec_config.get("llm_timeout", _DEFAULT_LLM_TIMEOUT)
    tool_timeout = exec_config.get("tool_timeout", _DEFAULT_TOOL_TIMEOUT)

    system_prompt = agent.system_prompt or "You are a helpful assistant."
    # Ensure Markdown output instruction is appended if not already present
    if "Markdown" not in system_prompt and "markdown" not in system_prompt:
        system_prompt += "\n\n请使用 Markdown 格式输出回答，合理使用标题、列表、加粗、代码块等排版。"

    # 加载 MCP 工具
    tools, error = await load_agent_tools(agent)

    if error or not tools:
        # 工具不可用 → 降级为纯 LLM 问答（用 system_prompt 引导）
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

        return {
            "query": query,
            "answer": answer,
            "tool_calls": [],
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
        return {
            "query": query,
            "answer": "模型决策时出错，请稍后重试。",
            "tool_calls": [],
        }

    executed_tool_calls: list[dict[str, Any]] = []
    for _ in range(max_iterations):
        if not response.tool_calls:
            break

        # 记录本次迭代所有工具调用
        for tc in response.tool_calls:
            executed_tool_calls.append({
                "name": tc.get("name"),
                "args": tc.get("args") or {},
            })

        # 并发执行所有 tool_calls
        results = await _execute_tool_calls(
            agent, tools, response.tool_calls, tool_timeout
        )

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
            return {
                "query": query,
                "answer": "模型再决策时出错，请稍后重试。",
                "tool_calls": executed_tool_calls,
            }

    return {
        "query": query,
        "answer": response.content,
        "tool_calls": executed_tool_calls,
    }
