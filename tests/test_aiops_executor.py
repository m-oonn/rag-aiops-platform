"""AIOps Executor 节点行为测试。

重点验证工具调用性能与正确性：
  - 多个独立工具调用应并发执行，而不是串行。
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent.aiops.executor import (
    _run_single_tool,
    _run_tool_calls,
)
from src.agent.aiops.tool_guards import _reanchor_change_time_window


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


# ── 变更查询时间窗锚定 ──────────────────────────────────────────────────
# 背景: search_changes 的窗口错位会查成"窗口内无变更",进而误判 h_change 矛盾、
# 把结论从正确的变更根因上带反 —— 故与指标工具同样做"贴近当前"的确定性纠偏。


def test_reanchor_change_time_window_defaults_to_last_hour():
    """0/0(未给窗口)应锚定为"最近 1 小时"的毫秒时间戳。"""
    now_ms = int(time.time() * 1000)
    args = {"service_name": "order-service", "start_time": 0, "end_time": 0}

    _reanchor_change_time_window("search_changes", args)

    assert isinstance(args["end_time"], int) and isinstance(args["start_time"], int)
    assert abs(args["end_time"] - now_ms) < 5000  # 右端贴近当前
    assert abs((args["end_time"] - args["start_time"]) - 3600 * 1000) < 5000  # 时长 1 小时


def test_reanchor_change_time_window_preserves_intended_duration():
    """给了"旧但合理"的窗口时,右端对齐当前、保留原时长。"""
    now_ms = int(time.time() * 1000)
    three_h = 3 * 3600 * 1000
    args = {"start_time": now_ms - 5 * 3600 * 1000, "end_time": now_ms - 2 * 3600 * 1000}

    _reanchor_change_time_window("search_changes", args)

    assert abs(args["end_time"] - now_ms) < 5000
    assert abs((args["end_time"] - args["start_time"]) - three_h) < 5000


def test_reanchor_change_time_window_keeps_fresh_window():
    """窗口右端已贴近当前时不应改动(避免无谓漂移)。"""
    now_ms = int(time.time() * 1000)
    args = {"start_time": now_ms - 3600 * 1000, "end_time": now_ms - 60 * 1000}
    before = dict(args)

    _reanchor_change_time_window("search_changes", args)

    assert args == before


def test_reanchor_change_time_window_handles_garbage():
    """字符串/非法时间戳按缺失处理,退化为最近 1 小时。"""
    args = {"start_time": "2026-10-10 09:00:00", "end_time": None}

    _reanchor_change_time_window("search_changes", args)

    assert isinstance(args["start_time"], int) and isinstance(args["end_time"], int)
    assert abs((args["end_time"] - args["start_time"]) - 3600 * 1000) < 5000


@pytest.mark.asyncio
async def test_run_single_tool_anchors_change_window():
    """search_changes 经 _run_single_tool 时应被锚定(验证调用点接线)。"""
    captured = {}

    async def _ainvoke(args):
        captured.update(args)
        return "ok"

    tool = MagicMock()
    tool.name = "search_changes"
    tool.ainvoke = AsyncMock(side_effect=_ainvoke)

    tc = {"id": "tc_change", "name": "search_changes",
          "args": {"service_name": "order-service", "start_time": 0, "end_time": 0}}
    await _run_single_tool(tc, {"search_changes": tool})

    now_ms = int(time.time() * 1000)
    assert abs(captured["end_time"] - now_ms) < 5000
    assert abs((captured["end_time"] - captured["start_time"]) - 3600 * 1000) < 5000
