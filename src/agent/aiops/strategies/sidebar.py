"""旁开引擎：当主路径出现矛盾或 top-2 假设接近时，为备选假设开辟伪并行验证支线。

伪并行实现（与 spec §8.3 对齐）：
  - 旁开验证步骤并入 replan 返回的计划，串行执行；
  - 支线步骤产生的观测与主路径观测走同一个证据裁判与信念更新
    （全局证据池共享 = 合并），无需独立状态通道。

旁开触发条件（spec §6.3）：
  1. 主假设遭遇矛盾；
  2. top-2 假设概率接近（gap < 阈值）；
  3. 主假设置信不足且 runner-up 有竞争力（概率 ≥ 下限）。
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from src.agent.aiops.core.hypothesis import Hypothesis


class SidebarBranch(BaseModel):
    """一条旁开验证支线（伪并行）。"""

    id: str = Field(description="分支唯一 ID")
    target_hypothesis_id: str = Field(description="目标假设 ID")
    target_hypothesis_name: str = Field(description="目标假设名称")
    plan: List[str] = Field(default_factory=list, description="旁开验证步骤")
    status: str = Field(default="running", description="running / completed / abandoned")
    trigger_reason: str = Field(default="", description="触发原因")
    created_step: int = Field(default=0, description="创建时的执行步数")


class SidebarDecision(BaseModel):
    """旁开决策结果。"""

    should_sidebar: bool = False
    target_hypothesis_id: str = ""
    target_hypothesis_name: str = ""
    trigger_reason: str = ""
    verification_steps: List[str] = Field(default_factory=list)


class SidebarEngine:
    """旁开引擎：检测触发条件，为备选假设生成验证支线。"""

    def __init__(
        self,
        max_active_branches: int = 1,
        max_steps_per_branch: int = 2,
        gap_threshold: float = 0.15,
        min_runner_up_probability: float = 0.15,
        contradiction_trigger: bool = True,
    ) -> None:
        self.max_active_branches = max_active_branches
        self.max_steps_per_branch = max_steps_per_branch
        self.gap_threshold = gap_threshold
        self.min_runner_up_probability = min_runner_up_probability
        self.contradiction_trigger = contradiction_trigger

    # ── 决策入口 ──────────────────────────────────────────
    def decide(
        self,
        hypotheses: List[Hypothesis],
        step_count: int,
        latest_contradiction: bool = False,
        existing_branches: Optional[List[SidebarBranch]] = None,
    ) -> SidebarDecision:
        """判断是否需要旁开，以及目标假设与验证计划。"""
        active = [h for h in hypotheses if h.status == "active"]
        if len(active) < 2:
            return SidebarDecision()

        branches = existing_branches or []
        running = [b for b in branches if b.status == "running"]
        if len(running) >= self.max_active_branches:
            return SidebarDecision()

        sorted_h = sorted(active, key=lambda h: h.probability, reverse=True)
        top, runner_up = sorted_h[0], sorted_h[1]
        covered_ids = {b.target_hypothesis_id for b in running}

        # 目标选择：优先 runner-up，已被覆盖则顺延到后续未覆盖假设
        target = None
        for h in sorted_h[1:]:
            if h.id not in covered_ids and h.probability >= self.min_runner_up_probability:
                target = h
                break
        if target is None:
            return SidebarDecision()

        gap = top.probability - runner_up.probability
        reason = ""
        if latest_contradiction and self.contradiction_trigger:
            reason = "主假设遭遇矛盾"
        elif gap < self.gap_threshold and target.id == runner_up.id:
            reason = f"top-2 概率接近(gap={gap:.3f})"
        elif top.probability < 0.40 and target.probability >= self.min_runner_up_probability:
            reason = f"主假设置信不足(top={top.probability:.3f})"
        if not reason:
            return SidebarDecision()

        return SidebarDecision(
            should_sidebar=True,
            target_hypothesis_id=target.id,
            target_hypothesis_name=target.name,
            trigger_reason=reason,
            verification_steps=self._build_verification_steps(target),
        )

    # ── 验证计划生成 ──────────────────────────────────────
    def _build_verification_steps(self, hypothesis: Hypothesis) -> List[str]:
        """针对目标假设的 expected_findings 生成验证步骤。"""
        steps = []
        verify = f"验证 {hypothesis.name}"
        if hypothesis.expected_findings:
            key = ", ".join(hypothesis.expected_findings[:3])
            verify += f"(重点核查: {key})"
        steps.append(verify)
        steps.append(f"深入排查 {hypothesis.name}")
        return steps[: self.max_steps_per_branch]

    # ── 分支状态更新 ──────────────────────────────────────
    @staticmethod
    def update_branch_status(
        branches: List[SidebarBranch],
        done_steps: set,
    ) -> List[SidebarBranch]:
        """根据已执行步骤集合，把验证步骤全部完成的 running 分支标记为 completed。"""
        for b in branches:
            if b.status == "running" and all(s in done_steps for s in b.plan):
                b.status = "completed"
        return branches
