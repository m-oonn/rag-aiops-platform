# -*- coding: utf-8 -*-
"""P1 回归测试：证据裁判的观测文本来源切换 + 输入去诱导。

锁定：
  1. ENABLE_RAW_EVIDENCE_FOR_JUDGE 关闭时，裁判只吃转述文本（旧行为）；
  2. 开启时，裁判吃到"原始返回 + 转述补充"的拼接文本；
  3. USER_REPORT 的盲测文案不再泄漏机制/部件名（去诱导）。
"""
from __future__ import annotations

import asyncio

import pytest

from src.agent.aiops.core.hypothesis import Hypothesis
from src.agent.aiops.strategies.dynamic_classification import DynamicClassificationStrategy
from src.settings import settings


class _RecordingJudge:
    """记录 judge_async 收到的 observation，供断言切换是否生效。"""

    def __init__(self) -> None:
        self.seen: list[str] = []

    async def judge_async(self, hypotheses, observation, step=0, source="executor"):
        self.seen.append(observation)
        from src.agent.aiops.core.hypothesis import Evidence

        return [
            Evidence(
                source=source,
                target_hypothesis_id=hypotheses[0].id,
                relation="neutral",
                strength=0.0,
                description="test",
                step=step,
            )
        ]


def _make_state() -> dict:
    return {
        "input": "服务异常",
        "plan": ["验证 网络/连通性问题"],
        "past_steps": [("查日志", "LLM 转述: 依赖调用超时")],
        "raw_evidence": [("查日志", "dial tcp 10.0.4.55:443 handshake stalled")],
    }


def test_judge_uses_transcript_when_switch_off(monkeypatch) -> None:
    j = _RecordingJudge()
    strat = DynamicClassificationStrategy(judge=j)
    monkeypatch.setattr(settings, "ENABLE_RAW_EVIDENCE_FOR_JUDGE", False)
    monkeypatch.setattr(strat, "_init_hypotheses", lambda *a, **k: None)
    strat.manager.add_hypotheses([Hypothesis(id="h1", name="网络/连通性问题", probability=0.2)])

    asyncio.run(strat.decide(_make_state()))
    assert len(j.seen) == 1
    assert "dial tcp" not in j.seen[0]           # 关闭时不吃原文
    assert j.seen[0] == "LLM 转述: 依赖调用超时"


def test_judge_uses_raw_evidence_when_switch_on(monkeypatch) -> None:
    j = _RecordingJudge()
    strat = DynamicClassificationStrategy(judge=j)
    monkeypatch.setattr(settings, "ENABLE_RAW_EVIDENCE_FOR_JUDGE", True)
    monkeypatch.setattr(strat, "_init_hypotheses", lambda *a, **k: None)
    strat.manager.add_hypotheses([Hypothesis(id="h1", name="网络/连通性问题", probability=0.2)])

    asyncio.run(strat.decide(_make_state()))
    assert len(j.seen) == 1
    assert "dial tcp 10.0.4.55:443 handshake stalled" in j.seen[0]  # 优先吃原文
    assert "LLM 转述" in j.seen[0]                                  # 转述作为补充仍在


def test_user_report_no_mechanism_leak() -> None:
    """盲测上报文案不得点名机制/部件（去诱导）。"""
    from scripts.blind_fault_gen import USER_REPORT

    forbidden = ["配置调整", "消息队列", "容器", "中间件", "缓存类", "依赖的下游"]
    for root, text in USER_REPORT.items():
        for kw in forbidden:
            assert kw not in text, f"USER_REPORT[{root}] 仍泄漏机制词 '{kw}': {text}"
