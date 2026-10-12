"""论文消融开关测试（对齐开题报告口径：假设保护 / 证据门控 / 降级标注）。

三个开关各自只关闭一个机制，本文件逐个验证"关了确实关掉、没关确实生效"，
保证消融实验的归因成立、结果可复现。
"""

import json
from types import SimpleNamespace

import pytest

from src.agent.aiops.core.evidence_judge import EvidenceJudge
from src.agent.aiops.core.hypothesis import Evidence, Hypothesis
from src.agent.aiops.evidence_sources import source_availability
from src.agent.aiops.strategies.dynamic_classification import (
    DynamicClassificationStrategy,
    _local_respond,
)
from src.settings import settings


class _ScriptedJudge(EvidenceJudge):
    """按步号返回预置证据的裁判替身（不依赖关键词表）。"""

    def __init__(self, script=None):
        super().__init__(llm=None)
        self.script = script or {}

    async def judge_async(self, hypotheses, observation, step=0, source="executor"):
        return [
            Evidence(source=source, target_hypothesis_id=hid, relation=rel,
                     strength=st, step=step)
            for hid, rel, st in self.script.get(step, [])
        ]


def _tools(*names):
    return [SimpleNamespace(name=n) for n in names]


def _state(input_text="服务异常", plan=None, past_steps=None):
    return {
        "input": input_text,
        "plan": plan if plan is not None else [],
        "past_steps": past_steps or [],
        "response": "",
    }


# ── 降级标注 ─────────────────────────────────────────────


def test_degradation_label_off_hides_sources_and_caveat():
    """关降级标注 → 不输出证据来源小节与降级来源 caveat，但结论照常给出。"""
    availability = source_availability(_tools("query_cpu_metrics"))  # 仅指标可用
    state = _state()
    state["evidence_source_availability"] = availability
    space = [{"id": "h_app", "name": "应用层异常", "probability": 0.8}]
    note = "日志证据来自本地降级副本(日志服务不可达), 2 步观测中日志步骤已本地兜底"

    on = _local_respond(state, space, note, degradation_label=True)["response"]
    assert "## 证据来源" in on and "本地副本" in on

    off = _local_respond(state, space, note, degradation_label=False)["response"]
    assert "## 证据来源" not in off
    assert "本地副本" not in off
    # 降级来源是真实证据：关标注后结论照常给出，且不误判为"推测"
    assert "## 结论" in off and "推测" not in off


def test_degradation_label_off_keeps_missing_gate():
    """关降级标注不得覆盖证据门控：缺失类说明仍应触发"推测"。"""
    state = _state()
    space = [{"id": "h_app", "name": "应用层异常", "probability": 0.8}]
    note = "日志证据缺失(检索工具不可用), 2 步观测中日志步骤无法取证"
    off = _local_respond(state, space, note, degradation_label=False)["response"]
    assert "推测" in off


# ── 证据门控 ─────────────────────────────────────────────


def test_evidence_gate_toggle_changes_conclusion():
    """证据门控开 → 缺失时降级为"推测"；门控关（note=None）→ 一律确定性结论。"""
    state = _state()
    space = [{"id": "h_app", "name": "应用层异常", "probability": 0.8}]
    note = "日志证据缺失(检索工具不可用), 2 步观测中日志步骤无法取证"

    gated = _local_respond(state, space, note)["response"]
    assert "推测" in gated

    ungated = _local_respond(state, space, None)["response"]
    assert "推测" not in ungated
    assert "## 结论" in ungated


# ── 消融自描述元数据 ─────────────────────────────────────


def test_ablation_meta_records_switch_state(monkeypatch):
    monkeypatch.setattr(settings, "ABLATION_DISABLE_EVIDENCE_GATE", True)
    state = _state()
    space = [{"id": "h_app", "name": "应用层异常", "probability": 0.8}]
    report = _local_respond(state, space, None, degradation_label=False)["response"]
    meta_line = next(line for line in report.splitlines() if "diagnostic_meta" in line)
    meta = json.loads(meta_line.split("diagnostic_meta:")[1].split("-->")[0].strip())
    assert meta["ablation"] == {
        "hypothesis_protection": True,
        "evidence_gate": False,
        "degradation_label": False,
    }


# ── 假设保护（弱信号保护 + 深度回溯复活） ────────────────


@pytest.mark.asyncio
async def test_protection_on_calls_weak_signal_incubation(monkeypatch):
    monkeypatch.setattr(settings, "ABLATION_DISABLE_HYPOTHESIS_PROTECTION", False)
    strategy = DynamicClassificationStrategy(judge=_ScriptedJudge({1: [("h_x", "support", 0.5)]}))
    strategy.reset()
    strategy.manager.add_hypotheses([Hypothesis(id="h_x", name="X", probability=0.2, protection_rounds=0)])
    calls = []
    strategy._incubate_weak_signals = lambda evs: calls.append(1)
    await strategy.decide(_state(plan=["下一步"], past_steps=[("观测", "结果")]))
    assert calls == [1]


@pytest.mark.asyncio
async def test_protection_off_skips_weak_signal_incubation(monkeypatch):
    monkeypatch.setattr(settings, "ABLATION_DISABLE_HYPOTHESIS_PROTECTION", True)
    strategy = DynamicClassificationStrategy(judge=_ScriptedJudge({1: [("h_x", "support", 0.5)]}))
    strategy.reset()
    strategy.manager.add_hypotheses([Hypothesis(id="h_x", name="X", probability=0.2, protection_rounds=0)])
    calls = []
    strategy._incubate_weak_signals = lambda evs: calls.append(1)
    await strategy.decide(_state(plan=["下一步"], past_steps=[("观测", "结果")]))
    assert calls == []


@pytest.mark.asyncio
async def test_protection_off_skips_reactivation(monkeypatch):
    monkeypatch.setattr(settings, "ABLATION_DISABLE_HYPOTHESIS_PROTECTION", True)
    strategy = DynamicClassificationStrategy(judge=_ScriptedJudge({}))
    strategy.reset()
    strategy.manager.add_hypotheses([Hypothesis(id="h_x", name="X", probability=0.5, protection_rounds=0)])
    calls = []
    strategy._maybe_reactivate_hypotheses = lambda past: (calls.append(1), [])[1]
    await strategy.decide(_state(plan=["下一步"], past_steps=[("观测", "结果")]))
    assert calls == []


@pytest.mark.asyncio
async def test_protection_on_calls_reactivation(monkeypatch):
    monkeypatch.setattr(settings, "ABLATION_DISABLE_HYPOTHESIS_PROTECTION", False)
    strategy = DynamicClassificationStrategy(judge=_ScriptedJudge({}))
    strategy.reset()
    strategy.manager.add_hypotheses([Hypothesis(id="h_x", name="X", probability=0.5, protection_rounds=0)])
    calls = []
    strategy._maybe_reactivate_hypotheses = lambda past: (calls.append(1), [])[1]
    await strategy.decide(_state(plan=["下一步"], past_steps=[("观测", "结果")]))
    assert calls == [1]