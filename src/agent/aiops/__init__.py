"""运维诊断 Agent(Plan-Execute-Replan,简历版/甲)。

图结构:
    START -> planner -> executor -> replanner --(continue)--> executor
                                          |
                                          +--(respond/计划空)--> END

stream_mode="updates" 逐节点产出增量,封装成 SSE 事件给前端实时展示诊断过程。
"""

__all__ = ["AIOpsService", "aiops_service", "PlanExecuteState"]


def __getattr__(name):
    # Gateway persistence must remain usable without loading the agent runtime.
    if name in {"AIOpsService", "aiops_service"}:
        from src.agent.aiops.graph import AIOpsService, aiops_service
        return {"AIOpsService": AIOpsService, "aiops_service": aiops_service}[name]
    if name == "PlanExecuteState":
        from src.agent.aiops.state import PlanExecuteState
        return PlanExecuteState
    raise AttributeError(name)
