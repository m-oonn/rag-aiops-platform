"""假设空间管理：显式信念表示、log-odds 更新、保护期与状态管理。"""

from __future__ import annotations

from math import exp, log
from typing import Literal, Optional

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    """单次观测对某个假设的证据关系。"""

    source: str = Field(description="来源工具/查询")
    target_hypothesis_id: str = Field(description="目标假设 ID")
    relation: Literal["support", "contradict", "neutral"] = Field(
        description="证据关系：支持/矛盾/中性"
    )
    strength: float = Field(ge=0.0, le=1.0, description="证据强度")
    description: str = Field(default="", description="自然语言描述")
    step: int = Field(default=0, description="产生证据的步数")


class Hypothesis(BaseModel):
    """一条诊断假设。"""

    id: str = Field(description="唯一标识")
    name: str = Field(description="简短名称，如'CPU 过载'")
    description: str = Field(default="", description="详细描述")
    expected_findings: list[str] = Field(
        default_factory=list,
        description="若该假设为真，预期应观察到的证据",
    )
    contradictions: list[str] = Field(
        default_factory=list,
        description="若该假设为真，不应出现的证据",
    )
    probability: float = Field(default=0.5, ge=0.0, le=1.0)
    birth_step: int = Field(default=0, description="第几步被创建")
    status: Literal["active", "falsified", "confirmed", "dormant"] = Field(
        default="active"
    )
    protection_rounds: int = Field(
        default=0,
        description="剩余保护轮数，防止早期被证据不足误杀",
    )
    falsified_step: Optional[int] = Field(
        default=None,
        description="被淘汰时的步数（供深度回溯重解释复查）",
    )
    reinterpret_count: int = Field(
        default=0,
        description="深度回溯重解释次数（防抖：超过上限后不再复活）",
    )
    evidence_log: list[Evidence] = Field(default_factory=list)


class HypothesisManager:
    """管理诊断假设空间，提供信念更新与查询接口。"""

    def __init__(
        self,
        support_strength: float = 1.5,
        contradiction_strength: float = 2.5,
        strong_contradiction_threshold: float = 0.7,
    ) -> None:
        self._hypotheses: dict[str, Hypothesis] = {}
        self.support_strength = support_strength
        self.contradiction_strength = contradiction_strength
        self.strong_contradiction_threshold = strong_contradiction_threshold

    def add_hypotheses(self, hypotheses: list[Hypothesis]) -> None:
        """安全添加新假设，避免重复覆盖。"""
        for h in hypotheses:
            if h.id not in self._hypotheses:
                self._hypotheses[h.id] = h

    def get_hypothesis(self, hypothesis_id: str) -> Optional[Hypothesis]:
        """按 ID 获取假设。"""
        return self._hypotheses.get(hypothesis_id)

    def get_active_hypotheses(self) -> list[Hypothesis]:
        """返回未被 falsified 的假设。"""
        return [h for h in self._hypotheses.values() if h.status != "falsified"]

    def get_all_hypotheses(self) -> list[Hypothesis]:
        """返回全部假设（含已淘汰），供深度回溯复查。"""
        return list(self._hypotheses.values())

    def get_top_hypotheses(self, k: int = 3) -> list[Hypothesis]:
        """返回概率最高的 k 个假设（仅含 active）。"""
        active = self.get_active_hypotheses()
        sorted_h = sorted(active, key=lambda h: h.probability, reverse=True)
        return sorted_h[:k]

    def update_beliefs(self, evidences: list[Evidence]) -> None:
        """应用证据更新所有相关假设的信念。

        **批次内顺序无关**（确定性回放暴露的原始缺陷修复）：
        旧实现逐条应用证据并就地改写 h.probability，同批证据的处理顺序
        影响结果——先处理者先饱和/先触发 falsified，被淘汰的假设随即退出
        竞争归一，使批次顺序成为隐性偏置（606-net 场景 h_dep 反超 h_net
        的原始缺陷）。修复：对同一假设的整批证据，以 log-odds 为累积量
        一次累加换算概率（log-odds 加法可交换 → 序无关），falsified 统一
        在批次末基于**最终概率**判定，归一化仍对批次结束后存活的 active
        假设执行。

        1b 同步证据去重：同一 (source, step, target) 只保留强度最高的一条，
        避免同一步内对同一假设的重复命中被当成独立证据累加、加速饱和。
        1c 竞争归一：仅有多个候选假设时，对全空间按 logit 做 softmax，
        使概率和为 1，正确拉开领先与次选假设的差距；单候选时不归一，
        保持独立性。
        """
        # 1) 分组：同一假设的整批证据合并；逐条记录证据日志（仅对 active 假设）
        grouped: dict[str, list[Evidence]] = {}
        for ev in self._dedupe(evidences):
            h = self._hypotheses.get(ev.target_hypothesis_id)
            if h is None or h.status == "falsified":
                continue
            h.evidence_log.append(ev)
            grouped.setdefault(ev.target_hypothesis_id, []).append(ev)

        if not grouped:
            return

        # 2) 批次原子更新：累加 log-odds 后一次性换算概率并统一判定 falsified
        for hid, evs in grouped.items():
            h = self._hypotheses[hid]
            n_contradict = sum(1 for ev in evs if ev.relation == "contradict")
            has_effect = any(ev.relation != "neutral" for ev in evs)

            if has_effect:
                logit = log(
                    max(h.probability, 1e-12) / max(1.0 - h.probability, 1e-12)
                )
                logit += sum(self._evidence_logit_delta(ev) for ev in evs)
                h.probability = self._clamp(1.0 / (1.0 + exp(-logit)))

            # 保护期逻辑：保护轮数 > 0 时，矛盾证据**不得淘汰**假设。
            # 修复(对抗测试 premature_falsify)：之前强矛盾(>=threshold)会穿透保护期
            # 直接把概率压到 <0.05 触发 falsified，单条观测(可能是误报/局部正常)
            # 即可永久淘汰一个假设。现在保护期内矛盾照常更新信念、消耗保护轮数，
            # 但 falsified 判定只在保护轮数耗尽后生效。
            if n_contradict > 0 and h.protection_rounds > 0:
                h.protection_rounds = max(0, h.protection_rounds - n_contradict)

            # 判定 falsified：本批内存在矛盾证据、保护已耗尽且最终概率 < 0.05。
            # 统一在批次末基于最终概率判定，消除"矛盾先处理→当批即淘汰、
            # 后处理→残留"的顺序差异。
            if (
                n_contradict > 0
                and h.protection_rounds <= 0
                and h.probability < 0.05
            ):
                h.status = "falsified"
                h.falsified_step = max(ev.step for ev in evs)

        self._normalize_active()

    @staticmethod
    def _dedupe(evidences: list[Evidence]) -> list[Evidence]:
        """对重复命中去重：同一 (source, step, target, **relation**) 只保留
        strength 最高的一条。

        **按 relation 区分键**（顺序敏感修复的一部分）：同一观测对同一假设
        同时给出 support 与 contradict 时，二者含义相反、不能视为重复直接
        丢弃——去重只折叠**同关系**的重复命中；跨关系的相反证据保留，由
        update_beliefs 按整批净 log-odds 综合（序无关）。键中不含输入顺序
        信息，去重结果不受证据排列顺序影响。
        """
        best: dict[tuple[str, int, str, str], Evidence] = {}
        for ev in evidences:
            key = (ev.source, ev.step, ev.target_hypothesis_id, ev.relation)
            cur = best.get(key)
            if cur is None or ev.strength > cur.strength:
                best[key] = ev
        return list(best.values())

    def _normalize_active(self) -> None:
        """对全部 active 假设按 logit 做 softmax 竞争归一（使概率和为 1）。

        仅在存在多个候选时生效；单候选(如绝大多数单元测试)保持独立性不动，
        避免破坏『一条假设的概率只由自身证据决定』的语义。
        """
        active = self.get_active_hypotheses()
        if len(active) <= 1:
            return
        logits = [
            log(max(h.probability, 1e-12) / max(1.0 - h.probability, 1e-12))
            for h in active
        ]
        m = max(logits)
        exps = [exp(l - m) for l in logits]
        total = sum(exps)
        if total <= 0:
            return
        for h, e in zip(active, exps):
            h.probability = self._clamp(e / total)

    def reactivate(
        self, hypothesis_id: str, new_probability: float, protection_rounds: int
    ) -> Optional[Hypothesis]:
        """深度回溯重解释：复活一个已淘汰的假设。

        仅允许 falsified 状态的假设复活；复活后概率重置、重新获得保护期，
        并累计重解释次数（超过上限后不再允许复活，避免反复抖动）。
        """
        h = self._hypotheses.get(hypothesis_id)
        if h is None or h.status != "falsified":
            return None
        h.status = "active"
        h.probability = self._clamp(new_probability)
        h.protection_rounds = max(0, protection_rounds)
        h.reinterpret_count += 1
        return h

    def _evidence_logit_delta(self, evidence: Evidence) -> float:
        """返回单条证据在 log-odds 空间的增量（支持正向、矛盾负向、中性 0）。

        供 update_beliefs 以 log-odds 为累积量做**批次原子**更新：log-odds
        加法可交换，先累加全部增量再一次性换算概率，天然顺序无关。
        """
        if evidence.relation == "support":
            return evidence.strength * self.support_strength
        if evidence.relation == "contradict":
            return -evidence.strength * self.contradiction_strength
        return 0.0

    @staticmethod
    def _clamp(value: float, min_val: float = 0.01, max_val: float = 0.99) -> float:
        """将概率限制在 (min, max) 之间，避免饱和。"""
        return max(min_val, min(max_val, value))


# 解决动态加载时 Pydantic v2 的前向引用问题
Hypothesis.model_rebuild()
Evidence.model_rebuild()
