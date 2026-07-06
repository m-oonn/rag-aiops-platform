"""AIOps Replanner 策略抽象基类。

定义 replan 决策的策略接口，Phase 3 的"动态分类"即插在这里。
"""

from abc import ABC, abstractmethod
from typing import Any, Dict

from src.agent.aiops.state import PlanExecuteState


class BaseReplanStrategy(ABC):
    """Replanner 决策策略接口。

    decide() 接收当前 LangGraph 状态，返回状态更新字典。
    返回值的语义与 LangGraph 节点一致：
      - {"response": "..."} → 结束诊断并出报告
      - {"plan": [...]} → 替换剩余计划
      - {} → 继续执行原计划
    """

    @abstractmethod
    async def decide(self, state: PlanExecuteState) -> Dict[str, Any]:
        """给定当前执行状态，返回决策结果。

        Args:
            state: 包含 input/plan/past_steps/response 的当前状态

        Returns:
            LangGraph 节点兼容的 State 更新字典
        """
        ...
