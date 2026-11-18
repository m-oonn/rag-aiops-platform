"""AIOps Executor 节点行为测试。

重点验证工具调用性能与正确性：
  - 多个独立工具调用应并发执行，而不是串行。
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent.aiops.executor import (
    _forced_search_log,
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
async def test_run_tool_calls_executes_independent_tools_in_parallel(monkeypatch):
    """一次步骤中的多个独立工具调用应并发执行，总耗时接近最慢者。"""
    tool_a = _make_fake_tool("tool_a", 0.1)
    tool_b = _make_fake_tool("tool_b", 0.1)
    tool_map = {"tool_a": tool_a, "tool_b": tool_b}
    monkeypatch.setattr("src.agent.aiops.executor.run_store.start_tool_call",
                        lambda *args: f"audit-{args[5]}")
    monkeypatch.setattr("src.agent.aiops.executor.run_store.finish_tool_call", lambda *args, **kwargs: True)
    tool_calls = [
        {"id": "tc_a", "name": "tool_a", "args": {}},
        {"id": "tc_b", "name": "tool_b", "args": {}},
    ]

    start = time.monotonic()
    messages = await _run_tool_calls(tool_calls, tool_map,
        state={"thread_id": "parallel-run", "user_id": 1, "past_steps": []})
    elapsed = time.monotonic() - start

    assert len(messages) == 2
    # 串行执行约 0.2s；并发应在 0.15s 内完成
    assert elapsed < 0.15, f"tool calls appear sequential, elapsed={elapsed:.3f}s"

    # 确保每个工具都被调用到了
    tool_a.ainvoke.assert_awaited_once()
    tool_b.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_tool_calls_keeps_order_and_handles_missing_tool(monkeypatch):
    """返回的 ToolMessage 顺序应与输入一致，缺失工具给出友好提示。"""
    tool_a = _make_fake_tool("tool_a", 0.0)
    tool_map = {"tool_a": tool_a}
    monkeypatch.setattr("src.agent.aiops.executor.run_store.start_tool_call",
                        lambda *args: f"audit-{args[5]}")
    monkeypatch.setattr("src.agent.aiops.executor.run_store.finish_tool_call", lambda *args, **kwargs: True)
    tool_calls = [
        {"id": "tc_a", "name": "tool_a", "args": {}},
        {"id": "tc_missing", "name": "missing_tool", "args": {}},
    ]

    messages = await _run_tool_calls(tool_calls, tool_map,
        state={"thread_id": "ordered-run", "user_id": 1, "past_steps": []})

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
    await _run_single_tool(tc, {"search_changes": tool},
                           state={"thread_id": "change-window-test", "user_id": 1})

    now_ms = int(time.time() * 1000)
    assert abs(captured["end_time"] - now_ms) < 5000
    assert abs((captured["end_time"] - captured["start_time"]) - 3600 * 1000) < 5000


@pytest.mark.asyncio
@pytest.mark.parametrize("raises, expected_status", [(False, "success"), (True, "failed")])
async def test_run_single_tool_persists_call_and_outcome(monkeypatch, raises, expected_status):
    from importlib import import_module

    executor_module = import_module("src.agent.aiops.executor")
    started = []
    finished = []
    monkeypatch.setattr(executor_module.run_store, "start_tool_call",
                        lambda *args: started.append(args) or "tc-persisted")
    monkeypatch.setattr(executor_module.run_store, "finish_tool_call",
                        lambda call_uid, **kwargs: finished.append((call_uid, kwargs)) or True)
    tool = MagicMock()
    tool.name = "tool_a"
    tool.ainvoke = AsyncMock(side_effect=RuntimeError("backend unavailable") if raises else None,
                             return_value="observed result")
    state = {"thread_id": "audit-run", "user_id": 7, "past_steps": [("previous", "done")]}

    message = await _run_single_tool({
        "id": "call-1", "name": "tool_a", "args": {"service": "mall"},
    }, {"tool_a": tool}, state=state, step="check mall service")

    assert started[0][:6] == ("audit-run", 7, 1, "check mall service", "call-1", "tool_a")
    assert started[0][6]["proposed"] == {"service": "mall"}
    assert finished[0][0] == "tc-persisted"
    assert finished[0][1]["status"] == expected_status
    assert finished[0][1]["elapsed_ms"] >= 0
    assert message.artifact["status"] == expected_status


def test_blocked_tool_proposal_is_persisted(monkeypatch):
    from importlib import import_module

    executor_module = import_module("src.agent.aiops.executor")
    started = []
    finished = []
    monkeypatch.setattr(executor_module.run_store, "start_tool_call",
                        lambda *args: started.append(args) or "tc-blocked")
    monkeypatch.setattr(executor_module.run_store, "finish_tool_call",
                        lambda call_uid, **kwargs: finished.append((call_uid, kwargs)) or True)

    executor_module._record_blocked_tool_call(
        "probe_text_log", {"service": "mall"}, "call-2",
        {"thread_id": "audit-run", "user_id": 7, "past_steps": []},
        "read mall logs", "service_outside_business_scope",
    )

    assert started[0][5] == "probe_text_log"
    assert started[0][6]["proposed"] == {"service": "mall"}
    assert finished == [("tc-blocked", {
        "status": "blocked", "reason": "service_outside_business_scope",
        "result": {"blocked": True, "reason": "service_outside_business_scope"}, "elapsed_ms": 0,
    })]


@pytest.mark.asyncio
async def test_run_single_tool_fails_closed_when_audit_cannot_start(monkeypatch):
    from importlib import import_module

    executor_module = import_module("src.agent.aiops.executor")
    monkeypatch.setattr(executor_module.run_store, "start_tool_call", lambda *args: None)
    tool = _make_fake_tool("tool_a", 0)
    message = await _run_single_tool({
        "id": "call-3", "name": "tool_a", "args": {},
    }, {"tool_a": tool}, state={"thread_id": "audit-run", "user_id": 7})

    tool.ainvoke.assert_not_awaited()
    assert message.artifact["status"] == "unavailable"
    assert message.artifact["reason"] == "tool_call_audit_unavailable"


@pytest.mark.asyncio
async def test_forced_log_fallback_uses_the_same_persisted_tool_path(monkeypatch):
    from importlib import import_module

    executor_module = import_module("src.agent.aiops.executor")
    started = []
    finished = []
    monkeypatch.setattr(executor_module.run_store, "start_tool_call",
                        lambda *args: started.append(args) or "tc-fallback")
    monkeypatch.setattr(executor_module.run_store, "finish_tool_call",
                        lambda call_uid, **kwargs: finished.append((call_uid, kwargs)) or True)
    tool = _make_fake_tool("search_log", 0)

    result = await _forced_search_log(
        {"search_log": tool}, "topic_id = topic-123", [],
        state={"thread_id": "audit-run", "user_id": 7, "past_steps": []},
        step="search error logs",
    )

    assert result == "search_log_result"
    assert started[0][5] == "search_log"
    assert started[0][6]["proposed"]["topic_id"] == "topic-123"
    assert finished[0][1]["status"] == "success"


@pytest.mark.asyncio
async def test_run_single_tool_refuses_unscoped_diagnostic_state(monkeypatch):
    from importlib import import_module

    executor_module = import_module("src.agent.aiops.executor")
    tool = _make_fake_tool("tool_a", 0)
    message = await _run_single_tool({
        "id": "call-no-thread", "name": "tool_a", "args": {},
    }, {"tool_a": tool}, state={"user_id": 7, "past_steps": []})

    tool.ainvoke.assert_not_awaited()
    assert message.artifact["reason"] == "tool_call_audit_context_missing"


@pytest.mark.asyncio
async def test_run_single_tool_aborts_when_result_cannot_be_recorded(monkeypatch):
    from importlib import import_module

    executor_module = import_module("src.agent.aiops.executor")
    monkeypatch.setattr(executor_module.run_store, "start_tool_call", lambda *args: "tc-persisted")
    monkeypatch.setattr(executor_module.run_store, "finish_tool_call", lambda *args, **kwargs: False)
    tool = _make_fake_tool("tool_a", 0)

    with pytest.raises(executor_module.run_store.ToolCallAuditError):
        await _run_single_tool({
            "id": "call-finish-failed", "name": "tool_a", "args": {},
        }, {"tool_a": tool}, state={"thread_id": "audit-run", "user_id": 7})

    tool.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_step_does_not_swallow_audit_persistence_failure(monkeypatch):
    from importlib import import_module
    from types import SimpleNamespace
    from langchain_core.messages import AIMessage

    executor_module = import_module("src.agent.aiops.executor")
    tool = MagicMock()
    tool.name = "query_metrics"
    tool.description = "query metrics"
    tool.ainvoke = AsyncMock(return_value={"cpu": 12})
    monkeypatch.setattr(executor_module, "_get_tools_for_state",
                        AsyncMock(return_value=([tool], None)))
    monkeypatch.setattr(executor_module, "create_agent_llm",
                        lambda **kwargs: SimpleNamespace(bind_tools=lambda _: object()))
    monkeypatch.setattr(executor_module, "ainvoke_with_retry", AsyncMock(return_value=AIMessage(
        content="", tool_calls=[{"id": "metric-1", "name": "query_metrics", "args": {}}])))
    monkeypatch.setattr(executor_module.run_store, "start_tool_call", lambda *args: "tc-persisted")
    monkeypatch.setattr(executor_module.run_store, "finish_tool_call", lambda *args, **kwargs: False)

    with pytest.raises(executor_module.run_store.ToolCallAuditError):
        await executor_module._run_step("check CPU", {
            "thread_id": "audit-run", "user_id": 7, "past_steps": [],
        })

    tool.ainvoke.assert_awaited_once()
