"""AIOps 诊断事件契约（SSE 事件单一事实来源）。

背景（B4 事件契约显式化，借鉴 pi 的 AgentEvent 判别联合设计）：
诊断过程的 SSE 事件原散落在 graph.py::_format_event 与 execute()/resume() 中
手工拼 dict。本模块把「事件类型 + 字段结构 + 构造函数」集中为单一契约，供：
  - 产出：graph.py 调 make_*() 构造函数产出事件
  - 消费：前端 / 测试脚本 / 实验脚本按类型常量与字段定义读取
  - 文档：docs/aiops-events.md 与本模块一一对应

契约红线：JSON 字段与历史版本逐字段兼容（前端零改动）；本模块只做集中化，
不改变任何字段的名/值/默认语义。
"""

from typing import Any, Dict, List, Literal, TypedDict, Union, NotRequired

from src.agent.aiops.roles import ROLE_EXECUTOR, ROLE_PLANNER, ROLE_REPLANNER

# ── 事件类型常量（SSE payload["type"]）──────────────────────────
EVENT_PLAN = "plan"
EVENT_STEP_COMPLETE = "step_complete"
EVENT_STATUS = "status"
EVENT_DRAFT = "draft"
EVENT_REPORT = "report"
EVENT_PENDING_REVIEW = "pending_review"
EVENT_COMPLETE = "complete"
EVENT_ERROR = "error"
EVENT_EVIDENCE = "evidence"

EVENT_TYPES = (
    EVENT_PLAN,
    EVENT_STEP_COMPLETE,
    EVENT_STATUS,
    EVENT_DRAFT,
    EVENT_REPORT,
    EVENT_PENDING_REVIEW,
    EVENT_COMPLETE,
    EVENT_ERROR,
    EVENT_EVIDENCE,
)


# ── 类型定义（判别联合）────────────────────────────────────────


class PlanEvent(TypedDict):
    """planner 产出诊断计划。"""

    type: Literal["plan"]
    stage: Literal["plan_created"]
    role: str
    message: str
    plan: List[str]


class StepCompleteEvent(TypedDict):
    """executor 完成一步（含累计进度，供前端进度条）。"""

    type: Literal["step_complete"]
    stage: Literal["step_executed"]
    role: str
    message: str
    done: int
    total: int
    current_step: str
    remaining_steps: int


class StatusEvent(TypedDict, total=False):
    """节点进行中/继续执行的通用状态事件（字段随场景可变）。"""

    type: Literal["status"]
    stage: str
    role: str
    message: str
    remaining_steps: int


class DraftEvent(TypedDict):
    """HITL 开启时：报告草稿待审批。"""

    type: Literal["draft"]
    stage: Literal["draft_ready"]
    role: str
    message: str
    report: str


class ReportEvent(TypedDict):
    """非 HITL：最终诊断报告。"""

    type: Literal["report"]
    stage: Literal["final_report"]
    role: str
    message: str
    report: str
    diagnosis: NotRequired[dict]


class PendingReviewEvent(TypedDict):
    """HITL 挂起，等待人工审批。"""

    type: Literal["pending_review"]
    stage: Literal["pending_review"]
    thread_id: str
    message: str
    draft: str


class CompleteEvent(TypedDict, total=False):
    """诊断终态：报告 + 诊断元数据（假设空间/旁开支线/信念历史/证据源可用性）。"""

    type: Literal["complete"]
    stage: Literal["complete"]
    message: str
    response: str
    hypothesis_space: List[Dict[str, Any]]
    sidebar_branches: List[Dict[str, Any]]
    belief_history: List[Dict[str, Any]]
    evidence_source_availability: List[Dict[str, Any]]
    thread_id: str
    diagnosis: dict


class ErrorEvent(TypedDict):
    """错误事件（stage: error / validation_error / not_found）。"""

    type: Literal["error"]
    stage: str
    message: str


class EvidenceEvent(TypedDict, total=False):
    type: Literal["evidence"]
    stage: Literal["evidence_collected"]
    evidence_id: str
    target_id: str
    kind: str
    source: str
    collected_at: str
    summary: str
    fresh: bool


DiagnosisEvent = Union[
    PlanEvent,
    StepCompleteEvent,
    StatusEvent,
    DraftEvent,
    ReportEvent,
    PendingReviewEvent,
    CompleteEvent,
    ErrorEvent,
    EvidenceEvent,
]


# ── 构造函数（graph.py 统一经此产出事件）────────────────────────


def make_plan_event(plan: List[str]) -> Dict[str, Any]:
    return {
        "type": EVENT_PLAN,
        "stage": "plan_created",
        "role": ROLE_PLANNER,
        "message": f"诊断计划已制定,共 {len(plan)} 步",
        "plan": plan,
    }


def make_step_complete_event(
    done: int, total: int, current_step: str, remaining_steps: int
) -> Dict[str, Any]:
    return {
        "type": EVENT_STEP_COMPLETE,
        "stage": "step_executed",
        "role": ROLE_EXECUTOR,
        "message": f"步骤完成 ({done}/{total})",
        "done": done,
        "total": total,
        "current_step": current_step,
        "remaining_steps": remaining_steps,
    }


def make_status_event(stage: str, role: str, message: str, **extra: Any) -> Dict[str, Any]:
    """通用状态事件；extra 允许追加场景字段（如 remaining_steps）。"""
    ev: Dict[str, Any] = {"type": EVENT_STATUS, "stage": stage, "role": role, "message": message}
    ev.update(extra)
    return ev


def make_draft_event(report: str) -> Dict[str, Any]:
    return {
        "type": EVENT_DRAFT,
        "stage": "draft_ready",
        "role": ROLE_REPLANNER,
        "message": "报告草稿已生成",
        "report": report,
    }


def make_report_event(report: str, diagnosis: dict | None = None) -> Dict[str, Any]:
    event = {
        "type": EVENT_REPORT,
        "stage": "final_report",
        "role": ROLE_REPLANNER,
        "message": "诊断报告已生成",
        "report": report,
    }
    if diagnosis is not None:
        event['diagnosis'] = diagnosis
    return event


def make_pending_review_event(thread_id: str, draft: str) -> Dict[str, Any]:
    return {
        "type": EVENT_PENDING_REVIEW,
        "stage": "pending_review",
        "thread_id": thread_id,
        "message": "报告草稿已生成, 等待人工审批",
        "draft": draft,
    }


def make_complete_event(
    response: str,
    *,
    thread_id: str | None = None,
    hypothesis_space: List | None = None,
    sidebar_branches: List | None = None,
    belief_history: List | None = None,
    evidence_source_availability: List | None = None,
    diagnosis: dict | None = None,
) -> Dict[str, Any]:
    event = {
        "type": EVENT_COMPLETE,
        "stage": "complete",
        "message": "诊断完成",
        "response": response,
        "hypothesis_space": hypothesis_space or [],
        "sidebar_branches": sidebar_branches or [],
        "belief_history": belief_history or [],
        "evidence_source_availability": evidence_source_availability or [],
    }
    if thread_id:
        event["thread_id"] = thread_id
    if diagnosis is not None:
        event['diagnosis'] = diagnosis
    return event


def make_error_event(message: str, stage: str = "error") -> Dict[str, Any]:
    return {"type": EVENT_ERROR, "stage": stage, "message": message}


def make_evidence_event(*, evidence_id: str, target_id: str, kind: str, source: str,
                        collected_at: str, summary: str, fresh: bool = True, raw_hash: str | None = None) -> Dict[str, Any]:
    return {"type": EVENT_EVIDENCE, "stage": "evidence_collected", "evidence_id": evidence_id,
            "target_id": target_id, "kind": kind, "source": source,
            "collected_at": collected_at, "summary": summary, "fresh": fresh}
