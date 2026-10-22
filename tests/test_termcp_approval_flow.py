from typing import TypedDict

import pytest
from unittest.mock import AsyncMock, MagicMock
from types import SimpleNamespace
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

from src.agent.aiops.termcp_tools import (
    _match_pending_request, TerminalProtocolError, TerminalApprovalPending,
)
import httpx
import asyncio
from langchain_core.tools import StructuredTool


class _State(TypedDict):
    value: str


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError("response lost"), asyncio.CancelledError()])
async def test_terminal_write_with_unknown_outcome_stops_without_retry(failure):
    from src.agent.aiops import termcp_tools as module
    calls = 0
    async def write(shell_id: str, text: str):
        nonlocal calls
        calls += 1
        raise failure
    tool = StructuredTool.from_function(coroutine=write, name="shell_input", description="stage command")
    token = module.terminal_scope.set("write-failure-test")
    try:
        module.register_shell_session("sh1", "s1")
        wrapped = module.wrap_termcp_tools([tool])[0]
        with pytest.raises(TerminalProtocolError, match="without replay"):
            await wrapped.ainvoke({"shell_id":"sh1", "text":"uptime"})
        assert calls == 1
    finally:
        module.clear_terminal_context("write-failure-test")
        module.terminal_scope.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("state,resolved_at,expected_status", [
    ("pending", None, 409), ("rejected", 500, 410), ("expired", 1000, 410),
    ("approved", 1000, 410), ("approved", 1100, 410),
    ("approved", 999, None),
])
async def test_terminal_verification_checks_decision_deadline(monkeypatch, state, resolved_at, expected_status):
    from src.agent.aiops import termcp_tools as module
    approval = {"session_id":"s1", "shell_id":"sh1", "request_id":"r1", "command":"uptime", "expires_at":1000}
    row = {"id":"r1", "session_id":"s1", "shell_id":"sh1", "source":"mcp",
           "text":"uptime", "keys":["enter"], "expires_at":1000, "state":state, "resolved_at":resolved_at}
    client_type = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"requests":[row]}))
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: client_type(transport=transport, **kwargs))
    # Approved before expiry remains valid even if the user returns after expiry.
    monkeypatch.setattr(module.time, "time", lambda: 0.5 if state == "pending" else 2.0)
    if expected_status is None:
        assert await module.verify_terminal_approval(approval) == row
    else:
        with pytest.raises(module.TerminalApprovalStatusError) as error:
            await module.verify_terminal_approval(approval)
        assert error.value.status_code == expected_status
        assert error.value.terminal == (state != "pending")


def test_termcp_pending_request_matches_only_new_exact_shell_command():
    before = {"requests": [{"id": "old", "shell_id": "sh-1", "text": "uptime"}]}
    after = {
        "requests": [
            {"id": "old", "shell_id": "sh-1", "source": "mcp", "state": "pending", "text": "uptime"},
            {"id": "new", "shell_id": "sh-1", "source": "mcp", "state": "pending", "text": " df -h ", "keys": ["enter"]},
        ]
    }

    result = _match_pending_request(before, after, "sh-1", " df -h ")

    assert result["id"] == "new"


def test_termcp_pending_request_rejects_ambiguous_matches():
    request = {"id": "1", "shell_id": "sh-1", "source": "mcp", "state": "pending", "text": "uptime", "keys": ["enter"]}
    with pytest.raises(TerminalProtocolError, match="uniquely match"):
        _match_pending_request({}, {"requests": [request, {**request, "id": "2"}]}, "sh-1", "uptime")


@pytest.mark.asyncio
async def test_sqlite_checkpointer_resumes_interrupt_after_reopen(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite"

    async def approval_gate(state: _State):
        decision = interrupt({"value": state["value"]})
        return {"value": f"{state['value']}:{decision['action']}"}

    workflow = StateGraph(_State)
    workflow.add_node("approval_gate", approval_gate)
    workflow.set_entry_point("approval_gate")
    workflow.add_edge("approval_gate", END)
    config = {"configurable": {"thread_id": "pending-run"}}

    first_context = AsyncSqliteSaver.from_conn_string(str(db_path))
    first_saver = await first_context.__aenter__()
    await first_saver.setup()
    first_graph = workflow.compile(checkpointer=first_saver)
    async for _ in first_graph.astream({"value": "diagnostic"}, config, stream_mode="updates"):
        pass
    assert (await first_graph.aget_state(config)).next == ("approval_gate",)
    await first_context.__aexit__(None, None, None)

    second_context = AsyncSqliteSaver.from_conn_string(str(db_path))
    second_saver = await second_context.__aenter__()
    await second_saver.setup()
    second_graph = workflow.compile(checkpointer=second_saver)
    updates = []
    async for event in second_graph.astream(
        Command(resume={"action": "approve"}), config, stream_mode="updates"
    ):
        updates.append(event)
    assert updates == [{"approval_gate": {"value": "diagnostic:approve"}}]
    assert (await second_graph.aget_state(config)).next == ()
    await second_context.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_aiops_service_restarts_and_reads_approved_output_without_replaying(monkeypatch, tmp_path):
    import src.agent.aiops.graph as module
    from src.settings import settings

    monkeypatch.setattr(settings, "TERMCP_ENABLED", True)
    monkeypatch.setattr(settings, "ENABLE_HITL", False)
    monkeypatch.setattr(settings, "ENABLE_DYNAMIC_CLASSIFICATION", False)
    monkeypatch.setattr(settings, "AIOPS_CHECKPOINT_DB_PATH", str(tmp_path / "aiops.sqlite"))
    records = {}
    def create(thread, user, query):
        records[thread] = SimpleNamespace(status="running", user_id=user, terminal_approval=None)
    def pending(thread, approval):
        records[thread].status = "pending_terminal"
        records[thread].terminal_approval = approval
    monkeypatch.setattr(module.run_store, "create_run", create)
    monkeypatch.setattr(module.run_store, "mark_pending_terminal", pending)
    monkeypatch.setattr(module.run_store, "get_run", lambda thread: records.get(thread))
    monkeypatch.setattr(module.run_store, "mark_completed", lambda thread, report: setattr(records[thread], "status", "completed"))
    monkeypatch.setattr(module.run_store, "mark_failed", MagicMock())
    monkeypatch.setattr(module, "planner", AsyncMock(return_value={"plan": ["inspect CPU"]}))
    terminal_executor = AsyncMock(return_value={"terminal_approval": {
        "session_id": "session1", "shell_id": "shell1", "request_id": "req1",
        "command": "uptime", "expires_at": 2000000, "step": "inspect CPU",
    }})
    monkeypatch.setattr(module, "executor", terminal_executor)
    monkeypatch.setattr(module, "verify_terminal_approval", AsyncMock(return_value={"state": "approved"}))
    strategy = SimpleNamespace(decide=AsyncMock(return_value={"response": "CPU normal"}))
    output_tool = SimpleNamespace(name="shell_output", ainvoke=AsyncMock(return_value="load average 0.1"))
    monkeypatch.setattr("src.agent.aiops.executor._get_tools_cached", AsyncMock(return_value=([output_tool], None)))
    monkeypatch.setattr(module.AIOpsService, "_create_strategy", lambda self: strategy)

    service1 = module.AIOpsService()
    events1 = [e async for e in service1.execute("inspect", user_id=12, terminal_enabled=True)]
    assert events1[-1]["type"] == "pending_terminal_approval"
    thread_id = events1[-1]["thread_id"]
    await service1.close()
    service2 = module.AIOpsService()
    try:
        events2 = [e async for e in service2.resume(thread_id, {"action": "approve"})]
        assert events2[-1]["type"] == "complete"
        assert events2[-1]["response"] == "CPU normal"
        assert terminal_executor.await_count == 1
        output_tool.ainvoke.assert_awaited_once_with({"shell_id": "shell1", "timeout": 1})
        step, raw = strategy.decide.await_args.args[0]["raw_evidence"][0]
        assert step == "inspect CPU"
        evidence = __import__("json").loads(raw)
        assert evidence["data_source"] == "termcp_approved_target"
        assert evidence["output"] == "load average 0.1"
        assert evidence["approval_request_id"]
        repeated = [e async for e in service2.resume(thread_id, {"action": "approve"})]
        assert repeated[-1]["type"] == "error"
        assert output_tool.ainvoke.await_count == 1
    finally:
        await service2.close()
