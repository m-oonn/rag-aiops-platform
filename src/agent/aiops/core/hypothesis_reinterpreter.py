"""深度回溯重解释器：对已淘汰假设进行复查并可能复活（spec §11.2 可选增强第 3 项）。

动机：
  早期淘汰可能是单条强反证或局部误报导致（保护期耗尽即淘汰），后续观测若重新
  出现该假设的支持证据，说明之前的"错杀"可能不成立——例如配置错误假设曾被淘汰，
  但后续观测出现配置相关证据时应重新激活，避免漏掉真根因。

防抖机制（避免反复抖动）：
  - 次数上限：每个假设限定重解释次数（max_reinterpretations），再次淘汰后不再复活；
  - 净证据门槛：淘汰后需积累足够强的净支持证据（support - contradict >= min_support_hits）；
  - 最小间隔：淘汰后至少间隔 min_steps_after_falsify 轮才允许复查，防止同轮反复。
"""

from __future__ import annotations

from typing import List

from src.agent.aiops.core.hypothesis import Hypothesis


class HypothesisReinterpreter:
    """规则式深度回溯重解释器（确定性、可测试）。

    Args:
        max_reinterpretations: 单个假设允许重解释的最大次数（0 表示禁用）。
        min_support_hits: 淘汰后需要达到的净支持证据命中数。
        min_steps_after_falsify: 淘汰后至少间隔的轮数。
        revival_probability: 复活后的初始概率。
        revival_protection_rounds: 复活后重新获得的保护轮数。
    """

    def __init__(
        self,
        max_reinterpretations: int = 1,
        min_support_hits: int = 2,
        min_steps_after_falsify: int = 1,
        revival_probability: float = 0.30,
        revival_protection_rounds: int = 2,
    ) -> None:
        self.max_reinterpretations = max_reinterpretations
        self.min_support_hits = min_support_hits
        self.min_steps_after_falsify = min_steps_after_falsify
        self.revival_probability = revival_probability
        self.revival_protection_rounds = revival_protection_rounds

    def examine(
        self,
        hypotheses: List[Hypothesis],
        past_steps: list,
        current_step: int,
    ) -> List[Hypothesis]:
        """返回应被复活的已淘汰假设列表（纯判断，不修改状态）。

        Args:
            hypotheses: 全部假设（含 falsified）。
            past_steps: [(step_name, result), ...] 已执行步骤序列。
            current_step: 当前步数（= len(past_steps)）。

        Returns:
            满足复活条件的假设列表。调用方负责执行 manager.reactivate。
        """
        revived: List[Hypothesis] = []
        for h in hypotheses:
            if not self._eligible(h, current_step):
                continue
            if self._has_net_support(h, past_steps):
                revived.append(h)
        return revived

    def _eligible(self, h: Hypothesis, current_step: int) -> bool:
        """基础门槛检查（状态/次数/间隔）。"""
        if h.status != "falsified":
            return False
        if h.falsified_step is None:
            return False
        if h.reinterpret_count >= self.max_reinterpretations:
            return False
        if current_step < h.falsified_step + self.min_steps_after_falsify:
            return False
        return True

    def _has_net_support(self, h: Hypothesis, past_steps: list) -> bool:
        """统计淘汰后的新观测，判断净支持证据是否达到复查门槛。

        只统计下标 >= falsified_step 的观测（即淘汰当轮之后新增的结果）。
        """
        new_results = [
            result for i, (_, result) in enumerate(past_steps) if i >= h.falsified_step
        ]
        if not new_results:
            return False
        text = " ".join(new_results).lower()
        support = sum(1 for kw in h.expected_findings if kw in text)
        contra = sum(1 for kw in h.contradictions if kw in text)
        return support - contra >= self.min_support_hits
