"""Plan-Execute-Replan 状态定义(简历版/甲:标准 LangGraph 教程骨架)。

⚠️ 本文件**不要**加 `from __future__ import annotations`:
   否则 Annotated 元数据会被字符串化,LangGraph 读不到 operator.add reducer,
   past_steps 的"追加"会退化成"覆盖"。这是并行/累积字段的经典坑。
"""

import operator
from typing import Annotated, List, Tuple, TypedDict


class PlanExecuteState(TypedDict):
    """运维诊断的 Plan-Execute-Replan 共享状态。

    一条路走到底: planner 出 plan(线性步骤列表)→ executor 逐步执行 →
    replanner 决定 continue/replan/respond。无并行、无旁开(那是毕设分支的事)。
    """

    # 用户输入(故障现象 / 诊断任务描述)
    input: str

    # 执行计划:待执行的线性步骤列表
    plan: List[str]

    # 已执行步骤历史 (步骤, 结果)。operator.add = 追加而非覆盖。
    past_steps: Annotated[List[Tuple[str, str]], operator.add]

    # 最终诊断报告;非空即触发图结束。
    response: str
