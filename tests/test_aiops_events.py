"""诊断事件契约（events.py 构造函数 + graph._format_event）测试。

覆盖：
  1. 8 类事件的构造函数字段快照（契约基线）
  2. _format_event 各分支输出（plan/executor×3/replanner×3/未知节点）
  3. 关键默认值（complete 元数据缺省 []）

契约红线：字段结构与会话集中化前（2026-10-12 基线）逐字段一致。
"""

from src.agent.aiops.events import (
    EVENT_TYPES,
    make_complete_event,
    make_draft_event,
    make_error_event,
    make_pending_review_event,
    make_plan_event,
    make_report_event,
    make_status_event,
    make_step_complete_event,
)
from src.agent.aiops.graph import AIOpsService
from src.settings import settings


# ═══════════════ 构造函数字段快照 ═══════════════


class TestConstructors:
    def test_plan_event(self):
        ev = make_plan_event(["a", "b", "c"])
        assert ev == {
            "type": "plan",
            "stage": "plan_created",
            "role": "planner",
            "message": "诊断计划已制定,共 3 步",
            "plan": ["a", "b", "c"],
        }

    def test_step_complete_event(self):
        ev = make_step_complete_event(2, 5, "查日志", 3)
        assert ev == {
            "type": "step_complete",
            "stage": "step_executed",
            "role": "executor",
            "message": "步骤完成 (2/5)",
            "done": 2,
            "total": 5,
            "current_step": "查日志",
            "remaining_steps": 3,
        }

    def test_status_event_base(self):
        assert make_status_event("executor", "executor", "执行步骤中") == {
            "type": "status",
            "stage": "executor",
            "role": "executor",
            "message": "执行步骤中",
        }

    def test_status_event_with_extra(self):
        ev = make_status_event("replanner", "replanner", "准备生成报告", remaining_steps=2)
        assert ev["remaining_steps"] == 2
        assert set(ev.keys()) == {"type", "stage", "role", "message", "remaining_steps"}

    def test_draft_event(self):
        assert make_draft_event("草稿") == {
            "type": "draft",
            "stage": "draft_ready",
            "role": "replanner",
            "message": "报告草稿已生成",
            "report": "草稿",
        }

    def test_report_event(self):
        ev = make_report_event("报告")
        assert ev["type"] == "report" and ev["stage"] == "final_report" and ev["report"] == "报告"

    def test_pending_review_event(self):
        ev = make_pending_review_event("t-1", "草稿")
        assert ev == {
            "type": "pending_review",
            "stage": "pending_review",
            "thread_id": "t-1",
            "message": "报告草稿已生成, 等待人工审批",
            "draft": "草稿",
        }

    def test_complete_event_defaults(self):
        ev = make_complete_event("结论")
        assert ev["type"] == "complete" and ev["response"] == "结论"
        assert ev["hypothesis_space"] == []
        assert ev["sidebar_branches"] == []
        assert ev["belief_history"] == []
        assert ev["evidence_source_availability"] == []

    def test_complete_event_with_payload(self):
        ev = make_complete_event(
            "结论", hypothesis_space=[{"id": "h1"}], belief_history=[{"step": 1}]
        )
        assert ev["hypothesis_space"] == [{"id": "h1"}]
        assert ev["belief_history"] == [{"step": 1}]
        assert ev["sidebar_branches"] == []

    def test_error_event_stages(self):
        assert make_error_event("boom") == {"type": "error", "stage": "error", "message": "boom"}
        assert make_error_event("bad", stage="validation_error")["stage"] == "validation_error"
        assert make_error_event("gone", stage="not_found")["stage"] == "not_found"

    def test_event_types_constant_covers_all(self):
        assert set(EVENT_TYPES) == {
            "plan",
            "step_complete",
            "status",
            "draft",
            "report",
            "pending_review",
            "complete",
            "error",
            'evidence',
        }


# ═══════════════ _format_event 各分支 ═══════════════


class TestFormatEvent:
    def test_planner_branch(self):
        ev = AIOpsService._format_event("planner", {"plan": ["s1", "s2"]})
        assert ev["type"] == "plan" and ev["message"] == "诊断计划已制定,共 2 步"

    def test_executor_step_complete_with_progress(self):
        ev = AIOpsService._format_event(
            "executor",
            {
                "past_steps": [("步1", "结果")],
                "plan": ["剩1"],
                "_step_progress": {"done": 4, "total": 6},
            },
        )
        assert ev == {
            "type": "step_complete",
            "stage": "step_executed",
            "role": "executor",
            "message": "步骤完成 (4/6)",
            "done": 4,
            "total": 6,
            "current_step": "步1",
            "remaining_steps": 1,
        }

    def test_executor_step_complete_without_progress(self):
        ev = AIOpsService._format_event(
            "executor", {"past_steps": [("a", "r")], "plan": ["x", "y"]}
        )
        assert ev["done"] == 1 and ev["total"] == 3

    def test_executor_status_when_no_steps(self):
        ev = AIOpsService._format_event("executor", {})
        assert ev["type"] == "status" and ev["stage"] == "executor"

    def test_replanner_report_and_draft(self, monkeypatch):
        monkeypatch.setattr(settings, "ENABLE_HITL", False)
        ev = AIOpsService._format_event("replanner", {"response": "R"})
        assert ev["type"] == "report" and ev["report"] == "R"

        monkeypatch.setattr(settings, "ENABLE_HITL", True)
        ev = AIOpsService._format_event("replanner", {"response": "R"})
        assert ev["type"] == "draft" and ev["report"] == "R"

    def test_replanner_status_with_sidebar_note(self):
        ev = AIOpsService._format_event(
            "replanner",
            {
                "plan": ["x"],
                "sidebar_branches": [{"status": "running"}, {"status": "done"}],
            },
        )
        assert ev["type"] == "status"
        assert "旁开支线 1 条" in ev["message"]
        assert ev["remaining_steps"] == 1

    def test_unknown_node_status(self):
        ev = AIOpsService._format_event("weird", {})
        assert ev == {
            "type": "status",
            "stage": "weird",
            "role": "weird",
            "message": "weird 执行中",
        }
