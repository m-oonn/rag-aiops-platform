"""运维 Agent 三角色语义化定义（L2：图内多角色协同正名）。

Plan-Execute-Replan 图的三个节点即三个协作角色：规划 / 执行 / 重规划。
共享 PlanExecuteState（past_steps 累加、证据池全局共享）即角色间协同的事实载体。
事件与日志统一携带 ROLE_* 常量，供前端展示与论文表述引用。
"""

ROLE_PLANNER = "planner"
ROLE_EXECUTOR = "executor"
ROLE_REPLANNER = "replanner"

ROLE_LABELS = {
    ROLE_PLANNER: "规划角色",
    ROLE_EXECUTOR: "执行角色",
    ROLE_REPLANNER: "重规划角色",
}
