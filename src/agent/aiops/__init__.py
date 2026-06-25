"""运维诊断 Agent(Plan-Execute-Replan,简历版/甲)。

图结构:
    START -> planner -> executor -> replanner --(continue)--> executor
                                          |
                                          +--(respond/计划空)--> END

stream_mode="updates" 逐节点产出增量,封装成 SSE 事件给前端实时展示诊断过程。
"""

from src.agent.aiops.graph import AIOpsService, aiops_service
from src.agent.aiops.state import PlanExecuteState

__all__ = ["AIOpsService", "aiops_service", "PlanExecuteState"]
