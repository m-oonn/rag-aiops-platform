"""工具守卫层（tool_guards）单元测试。

三层覆盖：
  1. 单守卫行为（直接调 guard.apply）—— 等价于搬迁前内联在 executor 的四段确定性纠偏
  2. 守卫链（run_guards）—— 顺序、改写记录、停用开关、无关工具放行、不改调用方原参
  3. executor 接线（_run_single_tool）—— 守卫在真实调用点生效
"""

import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent.aiops.executor import _run_single_tool
from src.agent.aiops.tool_guards import (
    ChangeTimeAnchorGuard,
    GenericWordFilterGuard,
    GuardContext,
    MetricTimeAnchorGuard,
    TopicAlignmentGuard,
    run_guards,
)
from src.settings import settings

_FMT = "%Y-%m-%d %H:%M:%S"
_REAL_IDS = (
    "可用真实标识符(本步如需要,务必使用这些真实值调用工具):\n"
    "  topic_id = topic-003"
)


# ═══════════════ 单守卫行为 ═══════════════


class TestTopicAlignmentGuard:
    guard = TopicAlignmentGuard()

    def test_overrides_placeholder_with_real_topic(self):
        out = self.guard.apply(
            "search_log",
            {"topic_id": "log-topic-api-gateway-001"},
            GuardContext(real_ids=_REAL_IDS),
        )
        assert out is not None and out["topic_id"] == "topic-003"

    def test_same_value_no_rewrite(self):
        assert self.guard.apply(
            "search_log", {"topic_id": "topic-003"}, GuardContext(real_ids=_REAL_IDS)
        ) is None

    def test_no_real_ids_no_rewrite(self):
        assert self.guard.apply("search_log", {"topic_id": "t1"}, GuardContext()) is None

    def test_other_tool_no_rewrite(self):
        assert self.guard.apply(
            "query_cpu_metrics", {"topic_id": "t1"}, GuardContext(real_ids=_REAL_IDS)
        ) is None


class TestGenericWordFilterGuard:
    guard = GenericWordFilterGuard()

    def test_bare_generic_words_degrade_to_full_scan(self):
        out = self.guard.apply(
            "search_log",
            {"topic_id": "t", "query": "error OR exception OR timeout"},
            GuardContext(),
        )
        assert out is not None and "query" not in out and out["topic_id"] == "t"

    def test_specific_tokens_survive(self):
        out = self.guard.apply(
            "search_log", {"query": "connection refused OR exception"}, GuardContext()
        )
        assert out is not None and out["query"] == "connection refused"

    def test_field_scoped_clause_preserved(self):
        # 合法字段子句本身无改写（值原样保留）
        assert self.guard.apply(
            "search_log", {"query": "level:ERROR OR level:WARN"}, GuardContext()
        ) is None

    def test_clean_query_no_rewrite(self):
        assert self.guard.apply(
            "search_log", {"query": "connection refused"}, GuardContext()
        ) is None

    def test_query_absent_no_rewrite(self):
        assert self.guard.apply("search_log", {"topic_id": "t"}, GuardContext()) is None

    def test_other_tool_no_rewrite(self):
        assert self.guard.apply("site_probe", {"query": "error"}, GuardContext()) is None


class TestMetricTimeAnchorGuard:
    guard = MetricTimeAnchorGuard()

    def test_stale_window_reanchored_to_now(self):
        stale = (datetime.now() - timedelta(hours=3)).strftime(_FMT)
        out = self.guard.apply(
            "query_cpu_metrics", {"start_time": stale, "end_time": stale}, GuardContext()
        )
        assert out is not None
        end = datetime.strptime(out["end_time"], _FMT)
        assert abs((datetime.now() - end).total_seconds()) < 5

    def test_stale_window_keeps_intended_duration(self):
        now = datetime.now()
        out = self.guard.apply(
            "query_memory_metrics",
            {
                "start_time": (now - timedelta(hours=6)).strftime(_FMT),
                "end_time": (now - timedelta(hours=3)).strftime(_FMT),
            },
            GuardContext(),
        )
        assert out is not None
        s = datetime.strptime(out["start_time"], _FMT)
        e = datetime.strptime(out["end_time"], _FMT)
        assert abs((e - s) - timedelta(hours=3)) < timedelta(seconds=5)

    def test_fresh_window_kept(self):
        now = datetime.now()
        args = {
            "start_time": (now - timedelta(hours=1)).strftime(_FMT),
            "end_time": now.strftime(_FMT),
        }
        assert self.guard.apply("query_cpu_metrics", dict(args), GuardContext()) is None

    def test_other_tool_no_rewrite(self):
        assert self.guard.apply("search_log", {"start_time": "x"}, GuardContext()) is None


class TestChangeTimeAnchorGuard:
    guard = ChangeTimeAnchorGuard()

    def test_zero_window_defaults_to_last_hour(self):
        out = self.guard.apply(
            "search_changes",
            {"service_name": "order-service", "start_time": 0, "end_time": 0},
            GuardContext(),
        )
        assert out is not None
        now_ms = int(time.time() * 1000)
        assert abs(out["end_time"] - now_ms) < 5000
        assert abs((out["end_time"] - out["start_time"]) - 3600 * 1000) < 5000

    def test_fresh_window_kept(self):
        now_ms = int(time.time() * 1000)
        args = {"start_time": now_ms - 3600 * 1000, "end_time": now_ms - 60 * 1000}
        assert self.guard.apply("search_changes", dict(args), GuardContext()) is None

    def test_other_tool_no_rewrite(self):
        assert self.guard.apply(
            "query_cpu_metrics", {"start_time": 0, "end_time": 0}, GuardContext()
        ) is None


# ═══════════════ 守卫链（run_guards）═══════════════


class TestRunGuardsChain:
    def test_chain_applies_in_order_and_records(self):
        gr = run_guards(
            "search_log",
            {"topic_id": "log-topic-001", "query": "error OR timeout"},
            GuardContext(real_ids=_REAL_IDS),
        )
        assert gr.guards_applied == ("topic_alignment", "generic_filter")
        assert gr.rewritten["topic_id"] == "topic-003"
        assert "query" not in gr.rewritten
        assert gr.original["topic_id"] == "log-topic-001"  # 原始参数保留（审计）

    def test_unrelated_tool_passes_untouched(self):
        args = {"url": "https://example.com/"}
        gr = run_guards("site_probe", dict(args))
        assert gr.action == "pass" and gr.guards_applied == ()
        assert gr.rewritten == args

    def test_caller_args_not_mutated(self):
        args = {"topic_id": "log-topic-001", "query": "error OR timeout"}
        gr = run_guards("search_log", args, GuardContext(real_ids=_REAL_IDS))
        assert args == {"topic_id": "log-topic-001", "query": "error OR timeout"}
        assert gr.original == args

    def test_disabled_guard_skipped(self, monkeypatch):
        monkeypatch.setattr(settings, "DISABLED_TOOL_GUARDS", "generic_filter")
        gr = run_guards("search_log", {"query": "error OR timeout"})
        assert gr.action == "pass"
        assert gr.rewritten["query"] == "error OR timeout"

    def test_disabled_guard_does_not_affect_others(self, monkeypatch):
        monkeypatch.setattr(settings, "DISABLED_TOOL_GUARDS", "generic_filter")
        gr = run_guards(
            "search_log",
            {"topic_id": "placeholder", "query": "error OR timeout"},
            GuardContext(real_ids=_REAL_IDS),
        )
        assert gr.guards_applied == ("topic_alignment",)


# ═══════════════ executor 接线 ═══════════════


@pytest.mark.asyncio
async def test_run_single_tool_applies_guard_chain():
    """search_log 经 _run_single_tool 时应完成 topic 对齐 + query 净化。"""
    captured = {}

    async def _ainvoke(args):
        captured.update(args)
        return "ok"

    tool = MagicMock()
    tool.name = "search_log"
    tool.ainvoke = AsyncMock(side_effect=_ainvoke)

    tc = {
        "id": "tc_1",
        "name": "search_log",
        "args": {"topic_id": "log-topic-api-gateway-001", "query": "error OR exception OR timeout"},
    }
    await _run_single_tool(tc, {"search_log": tool}, real_ids=_REAL_IDS)

    assert captured["topic_id"] == "topic-003"
    assert "query" not in captured
