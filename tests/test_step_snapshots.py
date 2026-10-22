"""步级快照（B3：run_store 扩展 + graph 挂点）测试。

- run_store 读写往返 / 排序 / 线程隔离 / 坏 payload 容错
- graph._stream_events 挂点（开关开/关）与 _snapshot_payload 摘要
"""

import time as _time

import pytest

from src.agent.aiops import run_store
from src.agent.aiops.graph import AIOpsService, _snapshot_payload
from src.database.models import AiopsStepSnapshot
from src.database.sql_session import SessionLocal
from src.settings import settings


def _fresh_thread() -> str:
    return f"test-snap-{_time.time_ns()}"


def _cleanup(thread_id: str) -> None:
    db = SessionLocal()
    try:
        db.query(AiopsStepSnapshot).filter(AiopsStepSnapshot.thread_id == thread_id).delete()
        db.commit()
    finally:
        db.close()


# ═══════════════ run_store 读写 ═══════════════


class TestRunStoreSnapshots:
    def test_add_and_list_roundtrip(self):
        tid = _fresh_thread()
        try:
            run_store.add_step_snapshot(tid, 0, "planner", {"plan": ["a", "b"]})
            run_store.add_step_snapshot(
                tid, 1, "executor", {"last_step": "a", "result_digest": "r"}
            )
            steps = run_store.list_step_snapshots(tid)
            assert [s["step_index"] for s in steps] == [0, 1]
            assert steps[0]["node"] == "planner"
            assert steps[0]["payload"] == {"plan": ["a", "b"]}
            assert steps[1]["payload"]["last_step"] == "a"
            assert steps[0]["created_at"]
        finally:
            _cleanup(tid)

    def test_empty_for_unknown_thread(self):
        assert run_store.list_step_snapshots("no-such-thread-xyz") == []

    def test_thread_isolation(self):
        t1, t2 = _fresh_thread(), _fresh_thread()
        try:
            run_store.add_step_snapshot(t1, 0, "planner", {"plan": ["x"]})
            assert len(run_store.list_step_snapshots(t1)) == 1
            assert run_store.list_step_snapshots(t2) == []
        finally:
            _cleanup(t1)
            _cleanup(t2)

    def test_non_json_payload_safe(self):
        tid = _fresh_thread()
        try:
            run_store.add_step_snapshot(tid, 0, "executor", {"obj": object()})
            steps = run_store.list_step_snapshots(tid)
            assert len(steps) == 1  # default=str 兜底，不炸
        finally:
            _cleanup(tid)

    def test_ordering_by_step_index(self):
        tid = _fresh_thread()
        try:
            run_store.add_step_snapshot(tid, 2, "replanner", {})
            run_store.add_step_snapshot(tid, 0, "planner", {})
            run_store.add_step_snapshot(tid, 1, "executor", {})
            steps = run_store.list_step_snapshots(tid)
            assert [s["step_index"] for s in steps] == [0, 1, 2]
        finally:
            _cleanup(tid)


# ═══════════════ payload 摘要 ═══════════════


class TestSnapshotPayload:
    def test_planner(self):
        assert _snapshot_payload("planner", {"plan": ["s1"]}) == {"plan": ["s1"]}

    def test_executor(self):
        p = _snapshot_payload("executor", {"past_steps": [("步骤", "结果" * 300)]})
        assert p["last_step"] == "步骤"
        assert len(p["result_digest"]) == 200

    def test_executor_without_steps(self):
        assert _snapshot_payload("executor", {}) == {}

    def test_replanner(self):
        p = _snapshot_payload("replanner", {"plan": ["x"], "response": "R" * 500})
        assert p["remaining_plan"] == ["x"]
        assert len(p["response_digest"]) == 200

    def test_unknown_node(self):
        assert _snapshot_payload("weird", {}) == {}


# ═══════════════ graph 挂点 ═══════════════


class _FakeGraph:
    """按 updates 流吐出节点事件，并提供分段终态。"""

    async def astream(self, input, config, stream_mode, interrupt_after=None):
        yield {"planner": {"plan": ["s1", "s2"]}}
        yield {"executor": {"past_steps": [("s1", "r1")], "plan": ["s2"]}}
        yield {"__interrupt__": ()}
        yield {"replanner": {"plan": [], "response": "done"}}

    async def aget_state(self, config):
        from types import SimpleNamespace
        return SimpleNamespace(next=())


class TestStreamEventsHook:
    @pytest.mark.asyncio
    async def test_snapshots_written_when_enabled(self, monkeypatch):
        monkeypatch.setattr(settings, "ENABLE_STEP_SNAPSHOTS", True)
        tid = _fresh_thread()
        try:
            service = AIOpsService.__new__(AIOpsService)  # 绕过 __init__（不建图）
            config = {"configurable": {"thread_id": tid}}
            events = [e async for e in service._stream_events(_FakeGraph(), config, {})]
            assert len(events) == 3  # __interrupt__ 被跳过
            steps = run_store.list_step_snapshots(tid)
            assert [s["node"] for s in steps] == ["planner", "executor", "replanner"]
            assert steps[0]["step_index"] == 0 and steps[2]["step_index"] == 2
        finally:
            _cleanup(tid)

    @pytest.mark.asyncio
    async def test_no_snapshots_when_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "ENABLE_STEP_SNAPSHOTS", False)
        tid = _fresh_thread()
        service = AIOpsService.__new__(AIOpsService)
        config = {"configurable": {"thread_id": tid}}
        events = [e async for e in service._stream_events(_FakeGraph(), config, {})]
        assert len(events) == 3
        assert run_store.list_step_snapshots(tid) == []
