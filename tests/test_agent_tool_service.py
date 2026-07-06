"""Agent MCP 工具执行服务的行为测试。

目标：不整体 mock execute_agent_query，而是 mock 外部依赖（LLM、工具加载），
验证 execute_agent_query 的真实决策、工具调用、降级逻辑正确。
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.database.models import Agent
from src.services.agent_tool_service import execute_agent_query


def _make_agent(**overrides) -> Agent:
    """构造一个内存中的 Agent 实例，不写入数据库。"""
    defaults = {
        "id": 1,
        "name": "Test Agent",
        "type": "function_call",
        "user_id": 1,
        "system_prompt": "You are a test assistant.",
        "tools_config": {"monitor": {"transport": "streamable_http", "url": "http://localhost/mcp"}},
        "execution_config": {"max_iterations": 3, "llm_timeout": 5.0, "tool_timeout": 5.0},
    }
    defaults.update(overrides)
    return Agent(**defaults)


def _make_fake_llm_with_tool_calls(tool_calls_sequence):
    """构造一个假 LLM，按顺序返回 tool_calls 或 content。

    tool_calls_sequence 是一个列表，每个元素是：
      - list: 带有 tool_calls 的响应
      - str: 最终答案字符串
    """
    fake_llm = MagicMock()
    call_iter = iter(tool_calls_sequence)

    async def _ainvoke(messages):
        item = next(call_iter)
        response = MagicMock()
        if isinstance(item, list):
            response.tool_calls = item
            response.content = ""
        else:
            response.tool_calls = []
            response.content = item
        return response

    fake_llm.ainvoke = _ainvoke

    def _bind_tools(tools):
        bound = MagicMock()
        bound.ainvoke = _ainvoke
        return bound

    fake_llm.bind_tools = _bind_tools
    return fake_llm


def _make_fake_tool(name: str, result: str, delay: float = 0.0):
    """构造一个支持 ainvoke 的假工具。"""
    tool = MagicMock()
    tool.name = name

    async def _ainvoke(args):
        if delay:
            await asyncio.sleep(delay)
        return result

    tool.ainvoke = AsyncMock(side_effect=_ainvoke)
    return tool


@pytest.mark.asyncio
async def test_execute_agent_query_calls_tool_and_returns_final_answer():
    """LLM 请求工具时，工具应被调用，最终答案来自 LLM 再决策。"""
    agent = _make_agent()
    fake_tool = _make_fake_tool("fake_tool", "tool result")
    fake_llm = _make_fake_llm_with_tool_calls([
        [{"id": "tc_1", "name": "fake_tool", "args": {}}],
        "final answer from llm",
    ])

    with patch("src.services.agent_tool_service.create_agent_llm", return_value=fake_llm):
        with patch("src.services.agent_tool_service.load_tools_for_config", return_value=([fake_tool], None)):
            result = await execute_agent_query(agent, "do something")

    assert result["query"] == "do something"
    assert result["answer"] == "final answer from llm"
    assert len(result["tool_calls"]) == 1
    assert result["tool_calls"][0]["name"] == "fake_tool"
    assert result["degradation"] is None
    fake_tool.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_agent_query_falls_back_to_plain_llm_when_tools_unavailable():
    """MCP 工具加载失败时，应降级为纯 LLM 问答，不抛异常给用户。"""
    agent = _make_agent()
    fake_llm = _make_fake_llm_with_tool_calls(["plain llm answer"])

    with patch("src.services.agent_tool_service.create_agent_llm", return_value=fake_llm):
        with patch("src.services.agent_tool_service.load_tools_for_config", return_value=([], "ConnectionError: MCP down")):
            result = await execute_agent_query(agent, "do something")

    assert result["query"] == "do something"
    assert result["answer"] == "plain llm answer"
    assert result["tool_calls"] == []
    assert result["degradation"] == "tools_unavailable"


@pytest.mark.asyncio
async def test_execute_agent_query_returns_service_unavailable_when_llm_unavailable():
    """Agent LLM 和降级 LLM 都不可用时，返回服务不可用提示。"""
    agent = _make_agent()

    with patch("src.services.agent_tool_service.create_agent_llm", side_effect=RuntimeError("no model")):
        with patch("src.services.agent_tool_service.LLMClient") as mock_llm_client_class:
            mock_llm_client_class.return_value.llm = None
            result = await execute_agent_query(agent, "do something")

    assert result["query"] == "do something"
    assert "LLM 服务暂不可用" in result["answer"]
    assert result["tool_calls"] == []
    assert result["degradation"] == "llm_fallback"


@pytest.mark.asyncio
async def test_execute_agent_query_executes_multiple_tool_calls_in_parallel():
    """一次 LLM 响应中的多个独立工具调用应并发执行，而非串行。"""
    agent = _make_agent()
    fake_tool_a = _make_fake_tool("tool_a", "result a", delay=0.1)
    fake_tool_b = _make_fake_tool("tool_b", "result b", delay=0.1)
    fake_llm = _make_fake_llm_with_tool_calls([
        [
            {"id": "tc_a", "name": "tool_a", "args": {}},
            {"id": "tc_b", "name": "tool_b", "args": {}},
        ],
        "final answer",
    ])

    start = time.monotonic()
    with patch("src.services.agent_tool_service.create_agent_llm", return_value=fake_llm):
        with patch("src.services.agent_tool_service.load_tools_for_config", return_value=([fake_tool_a, fake_tool_b], None)):
            result = await execute_agent_query(agent, "parallel task")
    elapsed = time.monotonic() - start

    assert result["answer"] == "final answer"
    assert len(result["tool_calls"]) == 2
    assert result["degradation"] is None
    assert elapsed < 0.15, f"tool calls appear sequential, elapsed={elapsed:.3f}s"
