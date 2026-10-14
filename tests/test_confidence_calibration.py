# -*- coding: utf-8 -*-
"""P2-1 回归测试：信念 softmax 温度校准（抑制证据真空/弱证据下的虚高置信度）。

背景（2026-10-12）：实测"0 证据却 99%"——7 条相近先验假设经 softmax 归一后，
微小先验差异被放大成压倒性置信度，把其余假设压死，导致：
  ① 报告过度自信；② 备用假设过早退出竞争，矛盾触发/旁开支线机制失去作用对象。

修复：HypothesisManager 新增 softmax_temperature；开启 ENABLE_CONFIDENCE_CALIBRATION
      时 logits 除以温度（>1 平滑）。

本测试锁定：
  1. T=1.0 时行为与旧版完全一致（回归安全）；
  2. T>1 时，同组证据下 top 置信度下降、备选假设概率被抬升（不再被压死）。
"""
from __future__ import annotations

from src.agent.aiops.core.hypothesis import Evidence, Hypothesis, HypothesisManager


def _build_manager(T: float) -> HypothesisManager:
    m = HypothesisManager(softmax_temperature=T)
    priors = [
        ("基础设施/资源瓶颈", 0.20), ("应用层异常", 0.20), ("网络/连通性问题", 0.20),
        ("配置错误", 0.20), ("外部依赖故障", 0.20), ("容器问题", 0.10), ("服务接口异常", 0.10),
    ]
    for i, (n, p) in enumerate(priors):
        m.add_hypotheses([Hypothesis(id=f"h{i}", name=n, probability=p)])
    return m


def _apply_three_moderate_supports(m: HypothesisManager, target_id: str = "h4") -> None:
    for step in (1, 2, 3):
        m.update_beliefs([
            Evidence(source="s", target_hypothesis_id=target_id,
                     relation="support", strength=0.5, step=step)
        ])


def test_temperature_one_is_legacy_behavior() -> None:
    """T=1.0 必须与旧版一致：3 条中等支持证据 → 目标假设高置信（~0.83）。"""
    m = _build_manager(1.0)
    _apply_three_moderate_supports(m)
    top = m.get_top_hypotheses(1)[0]
    assert top.id == "h4"
    assert top.probability > 0.8, f"T=1.0 应保持旧行为（高置信），实际 {top.probability}"


def test_high_temperature_suppresses_overconfidence() -> None:
    """T=3.0 必须显著压低 top 置信度，且抬升备选假设概率。"""
    m1 = _build_manager(1.0)
    _apply_three_moderate_supports(m1)
    top1 = m1.get_top_hypotheses(1)[0].probability
    others1 = min(h.probability for h in m1.get_all_hypotheses())

    m3 = _build_manager(3.0)
    _apply_three_moderate_supports(m3)
    top3 = m3.get_top_hypotheses(1)[0].probability
    others3 = min(h.probability for h in m3.get_all_hypotheses())

    assert top3 < top1, f"校准后 top 置信度应下降: {top1} → {top3}"
    assert others3 > others1, f"校准后备选假设不应被压死: {others1} → {others3}"
    # 顶部置信度应被压到合理区间（不再虚高到 80%+）
    assert top3 < 0.5, f"3 条中等证据不应给出 >50% 置信, 实际 {top3}"


def test_strong_evidence_still_confident_with_calibration() -> None:
    """校准不应削弱'强证据'的表达力：多条强支持 + 矛盾，仍应显著领先。"""
    m = _build_manager(3.0)
    # 目标假设：5 条强支持
    for step in range(1, 6):
        m.update_beliefs([
            Evidence(source="s", target_hypothesis_id="h4",
                     relation="support", strength=1.0, step=step)
        ])
    # 其余假设各给一条矛盾证据（模拟被排除）
    for hid in ("h0", "h1", "h2", "h3", "h5", "h6"):
        for step in range(1, 4):
            m.update_beliefs([
                Evidence(source="s", target_hypothesis_id=hid,
                         relation="contradict", strength=0.8, step=step)
            ])
    top = m.get_top_hypotheses(1)[0]
    assert top.id == "h4"
    assert top.probability > 0.5, f"强证据下校准后仍应有较高置信, 实际 {top.probability}"


def test_temperature_default_is_one() -> None:
    """HypothesisManager 默认温度必须为 1.0（不影响未显式配置的调用方）。"""
    assert HypothesisManager().softmax_temperature == 1.0


def test_calibration_switch_default_off() -> None:
    from src.settings import settings
    assert settings.ENABLE_CONFIDENCE_CALIBRATION is False
