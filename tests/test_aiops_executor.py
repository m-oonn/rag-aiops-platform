"""AIOps Executor 节点行为测试。

重点验证工具调用性能与正确性：
  - 多个独立工具调用应并发执行，而不是串行。
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent.aiops.executor import _run_tool_calls


def _make_fake_tool(name: str, delay: float):
    """构造一个会 sleep 一段时间的假工具，用来验证并发。"""
    tool = MagicMock()
    tool.name = name

    async def _ainvoke(args):
        await asyncio.sleep(delay)
        return f"{name}_result"

    tool.ainvoke = AsyncMock(side_effect=_ainvoke)
    return tool


@pytest.mark.asyncio
async def test_run_tool_calls_executes_independent_tools_in_parallel():
    """一次步骤中的多个独立工具调用应并发执行，总耗时接近最慢者。"""
    tool_a = _make_fake_tool("tool_a", 0.1)
    tool_b = _make_fake_tool("tool_b", 0.1)
    tool_map = {"tool_a": tool_a, "tool_b": tool_b}
    tool_calls = [
        {"id": "tc_a", "name": "tool_a", "args": {}},
        {"id": "tc_b", "name": "tool_b", "args": {}},
    ]

    start = time.monotonic()
    messages = await _run_tool_calls(tool_calls, tool_map)
    elapsed = time.monotonic() - start

    assert len(messages) == 2
    # 串行执行约 0.2s；并发应在 0.15s 内完成
    assert elapsed < 0.15, f"tool calls appear sequential, elapsed={elapsed:.3f}s"

    # 确保每个工具都被调用到了
    tool_a.ainvoke.assert_awaited_once()
    tool_b.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_tool_calls_keeps_order_and_handles_missing_tool():
    """返回的 ToolMessage 顺序应与输入一致，缺失工具给出友好提示。"""
    tool_a = _make_fake_tool("tool_a", 0.0)
    tool_map = {"tool_a": tool_a}
    tool_calls = [
        {"id": "tc_a", "name": "tool_a", "args": {}},
        {"id": "tc_missing", "name": "missing_tool", "args": {}},
    ]

    messages = await _run_tool_calls(tool_calls, tool_map)

    assert len(messages) == 2
    assert messages[0].tool_call_id == "tc_a"
    assert "tool_a_result" in messages[0].content
    assert messages[1].tool_call_id == "tc_missing"
    assert "不存在" in messages[1].content
