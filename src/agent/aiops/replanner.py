"""Replanner 节点：决策策略的薄封装。

当前委托给 DefaultReplanStrategy。Phase 3 注入 DynamicClassificationStrategy 即切换。
"""

from typing import Any, Dict

from src.agent.aiops.state import PlanExecuteState

_default_strategy: Any = None


def _get_default_strategy() -> Any:
    """延迟加载默认策略，避免未使用默认策略时触发重依赖导入。"""
    global _default_strategy
    if _default_strategy is None:
        from src.agent.aiops.strategies.default import DefaultReplanStrategy

        _default_strategy = DefaultReplanStrategy()
    return _default_strategy


def create_replanner(strategy: Any = None):
    """创建使用指定策略的 replanner 节点函数。

    Args:
        strategy: 要注入的 BaseReplanStrategy 实例。为 None 时使用默认策略。

    Returns:
        适配 LangGraph 的异步节点函数。
    """
    _strategy = strategy or _get_default_strategy()

    async def replanner(state: PlanExecuteState) -> Dict[str, Any]:
        """重新规划节点：委托给当前生效的策略。"""
        return await _strategy.decide(state)

    return replanner
