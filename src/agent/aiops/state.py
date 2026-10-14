"""Plan-Execute-Replan 状态定义(简历版/甲:标准 LangGraph 教程骨架)。

⚠️ 本文件**不要**加 `from __future__ import annotations`:
   否则 Annotated 元数据会被字符串化,LangGraph 读不到 operator.add reducer,
   past_steps 的"追加"会退化成"覆盖"。这是并行/累积字段的经典坑。
"""

import operator
from typing import Annotated, List, NotRequired, Tuple, TypedDict


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

    # 已执行步骤的**工具原始返回** (步骤, 原始工具输出)，与 past_steps 一一对应、同步追加。
    # 存在的理由（2026-10-12 命中率根因诊断）：
    #   past_steps 里存的是 executor 让 LLM 写的"自然语言总结"，原始日志里的鉴别关键词
    #   （如 kubelet/evicted/OOMKilled、dial tcp/connection refused）会被转述稀释成中文
    #   通用词，导致规则裁判的关键词匹配失效、全倒向"外部依赖故障"。
    #   本字段保留未加工的原始工具返回，供证据裁判在开启
    #   settings.ENABLE_RAW_EVIDENCE_FOR_JUDGE 时优先采信，恢复判别力。
    # 默认不参与任何判定（旧行为零变化）；开关关闭时该字段只写不用。
    raw_evidence: Annotated[List[Tuple[str, str]], operator.add]

    # 最终诊断报告;非空即触发图结束。
    response: str

    # SSE 进度展示用: {"done": 累计已完成步数, "total": 计划总步数}
    # 仅 executor 节点增量输出携带,不参与业务决策(checkpointer 照常序列化)。
    _step_progress: NotRequired[dict]

    # 动态分类策略的假设空间快照（可选，用于前端展示/持久化）
    hypothesis_space: NotRequired[List[dict]]

    # 旁开引擎的伪并行分支记录（可选，用于前端展示/审计）
    sidebar_branches: NotRequired[List[dict]]

    # 假设信念变化曲线：每轮各假设概率快照（可选，用于可视化/论文数据）
    belief_history: NotRequired[List[dict]]

    # 证据源可用性快照（可选）：本次诊断实际可用的 MCP 证据源(指标/日志/变更/知识库/探测)。
    # 部分服务缺席时如实记录，供报告与 complete 事件标注"结论的可信边界"，避免静默失效。
    evidence_source_availability: NotRequired[List[dict]]
