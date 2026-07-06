"""Replanner 节点：决策策略的薄封装。

当前委托给 DefaultReplanStrategy。Phase 3 注入 DynamicClassificationStrategy 即切换。
"""

from typing import Any, Dict

from src.agent.aiops.state import PlanExecuteState
from src.agent.aiops.strategies.default import DefaultReplanStrategy

_default_strategy = DefaultReplanStrategy()


async def replanner(state: PlanExecuteState) -> Dict[str, Any]:
    """重新规划节点：委托给当前生效的策略。"""
    return await _default_strategy.decide(state)
