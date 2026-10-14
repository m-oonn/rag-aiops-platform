# -*- coding: utf-8 -*-
"""P2 回归测试：规则裁判的类别判别力（防"外部依赖吸铁石"偏置回归）。

背景（2026-10-12 根因诊断）：
  命中率低的主因是 executor 的 LLM 转述稀释关键词，而非裁判本身。
  本测试锁定"裁判层"这条基线：**只要喂原始日志，裁判必须按类别正确判别**，
  防止未来改动把裁判改出系统性偏置（例如把所有类别都判成外部依赖故障）。

设计：
  - 用 blind_fault_gen 生成每类场景（force_root 固定，含真实鉴别关键词）；
  - 直接调 EvidenceJudge().judge()（纯规则裁判，无 LLM）；
  - 断言 top 假设 == ground_truth。

若某类失败 → 说明该类别的 expected_findings 关键词被改坏 / 被别的类别压过。
"""
from __future__ import annotations

import pytest

from scripts.blind_fault_gen import ROOT_CAUSE_NAMES, gen_scenario
from src.agent.aiops.core.evidence_judge import EvidenceJudge
from src.agent.aiops.strategies.dynamic_classification import _DEFAULT_HYPOTHESES

# 每类取 1~2 个固定种子（保证可复现）
CASES = [
    (101, 1, "net"), (606, 2, "net"),
    (202, 2, "infra"), (707, 1, "infra"),
    (303, 1, "dep"), (1111, 1, "middleware"), (1212, 2, "middleware"),
    (404, 2, "config"),
    (505, 1, "app"), (808, 2, "app"),
    (909, 1, "container"),
    (1010, 2, "api"),
]


def _rule_top(observation: str) -> tuple[str, float]:
    """用纯规则裁判算 top 假设（support 加分，contradict 减分）。"""
    judge = EvidenceJudge()
    score = {h.name: 0.0 for h in _DEFAULT_HYPOTHESES}
    for h in _DEFAULT_HYPOTHESES:
        for ev in judge.judge([h], observation, 0, "regression"):
            if ev.relation == "support":
                score[h.name] += ev.strength
            elif ev.relation == "contradict":
                score[h.name] -= ev.strength
    top = max(score, key=score.get)
    return top, score[top]


@pytest.mark.parametrize("seed,difficulty,root", CASES)
def test_rule_judge_identifies_raw_log_category(seed: int, difficulty: int, root: str) -> None:
    """原始日志喂规则裁判，top 假设必须等于场景 ground_truth。

    这是"裁判层判别力"的基线——原文未被转述稀释时必须 100% 命中。
    """
    sc = gen_scenario(seed, difficulty, force_root=root)
    observation = "\n".join(
        f"[{line['level']}] {line['message']}" for line in sc["scenario"]["logs"]
    )
    top, _ = _rule_top(observation)
    assert top == sc["ground_truth"], (
        f"场景 {seed}-{root}: 期望 {sc['ground_truth']}，规则裁判给出 {top}。"
        f"裁判层判别力回归（可能是某类 expected_findings 被改坏，或关键词被其他类压过）。"
    )


def test_judge_not_biased_to_external_dependency() -> None:
    """"外部依赖吸铁石"防回归：非依赖类场景不得被统一判成外部依赖故障。

    这是 2026-10-12 诊断发现的偏置形态（12 场景 11 个答外部依赖）。
    这里用原始日志（无转述稀释）验证裁判层不存在该偏置。
    """
    non_dep_roots = ["net", "infra", "app", "config", "container", "api"]
    misjudged = []
    for seed, diff, root in CASES:
        if root in non_dep_roots:
            sc = gen_scenario(seed, diff, force_root=root)
            observation = "\n".join(
                f"[{line['level']}] {line['message']}" for line in sc["scenario"]["logs"]
            )
            top, _ = _rule_top(observation)
            if top == "外部依赖故障" and sc["ground_truth"] != "外部依赖故障":
                misjudged.append(f"{seed}-{root}")
    assert not misjudged, (
        f"以下非依赖类场景被规则裁判误判为『外部依赖故障』: {misjudged}。"
        f"裁判层出现系统性偏置，需检查 expected_findings 关键词权重。"
    )


def test_hypothesis_space_covers_all_ground_truth() -> None:
    """假设空间必须完整覆盖评测的全部 ground_truth 类别（防未来漂移）。

    2026-10-12 复检结论：系统假设空间 7 类，完整覆盖 8 个 ground_truth 标签——
    middleware 与 dep 都映射"外部依赖故障"是生成器与策略双方约定的设计映射，
    不构成结构性失分（此前"6 类 vs 8 类"的判断已更正为误读）。
    """
    space = {h.name for h in _DEFAULT_HYPOTHESES}
    missing = sorted(set(ROOT_CAUSE_NAMES.values()) - space)
    assert not missing, f"假设空间未覆盖以下 ground_truth 类别: {missing}"
