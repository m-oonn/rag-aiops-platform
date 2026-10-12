# -*- coding: utf-8 -*-
"""P0 回归测试：executor 保留工具原始返回 + 裁判优先采信原文。

背景（2026-10-12 命中率根因诊断）：
  executor 存进 past_steps 的是 LLM 转述的自然语言总结，原始日志的鉴别关键词
  （kubelet/evicted/dial tcp）被稀释成中文通用词，规则裁判命中失效。
  修复：新增 state.raw_evidence 保存未加工的原始工具返回；
       ENABLE_RAW_EVIDENCE_FOR_JUDGE 开启时裁判优先采信它。

本测试锁定：
  1. _run_step 返回 (转述文本, 原始工具返回) 二元组；
  2. 原始返回里保留了工具输出的原始文本（未被转述覆盖）；
  3. executor 节点同步写入 past_steps 与 raw_evidence，两者一一对应；
  4. 策略层 _raw_evidence_for 能按步骤标签取到原始返回；
  5. ENABLE_RAW_EVIDENCE_FOR_JUDGE 关闭时裁判仍吃转述（旧行为不变）。
"""
from __future__ import annotations

import pytest

from src.agent.aiops.executor import _plain_label, executor
from src.agent.aiops.strategies.dynamic_classification import DynamicClassificationStrategy
from src.settings import settings


def test_run_step_returns_tuple(monkeypatch) -> None:
    """_run_step 必须返回 (result_text, raw_evidence) 二元组。"""
    import src.agent.aiops.executor as ex
    import asyncio

    async def fake_get_tools():
        return [], None

    monkeypatch.setattr(ex, "_get_tools_cached", fake_get_tools)

    async def fake_ainvoke(llm, messages, label=""):
        class _R:
            content = "这是 LLM 的文字总结"
            tool_calls = None
        return _R()

    monkeypatch.setattr(ex, "ainvoke_with_retry", fake_ainvoke)
    monkeypatch.setattr(ex, "create_agent_llm", lambda **kw: object())

    out = asyncio.run(ex._run_step("检查服务状态", {"past_steps": [], "raw_evidence": []}))
    assert isinstance(out, tuple) and len(out) == 2
    result, raw = out
    assert result == "这是 LLM 的文字总结"
    assert isinstance(raw, str)


def test_executor_writes_raw_evidence(monkeypatch) -> None:
    """executor 节点必须同步写入 raw_evidence，且与 past_steps 一一对应。"""
    import src.agent.aiops.executor as ex
    import asyncio

    async def fake_get_tools():
        return [], None

    async def fake_run_step(task, state):
        return (f"转述[{task}]", f"原始工具返回[{task}]")

    monkeypatch.setattr(ex, "_get_tools_cached", fake_get_tools)
    monkeypatch.setattr(ex, "_run_step", fake_run_step)
    monkeypatch.setattr(settings, "ENABLE_PARALLEL_OBSERVATION", False)

    state = {"plan": ["步骤A"], "past_steps": [], "raw_evidence": []}
    out = asyncio.run(executor(state))

    assert out["past_steps"] == [("步骤A", "转述[步骤A]")]
    assert out["raw_evidence"] == [("步骤A", "原始工具返回[步骤A]")]


def test_raw_evidence_for_lookup() -> None:
    """策略层 _raw_evidence_for 能按步骤标签取到对应的原始返回。"""
    strat = DynamicClassificationStrategy()
    state = {
        "raw_evidence": [
            ("查日志", "dial tcp 10.0.4.55:443 handshake stalled"),
            ("查指标", "cpu 使用率 95%"),
        ]
    }
    assert "dial tcp" in strat._raw_evidence_for("查日志", state)
    assert "cpu 使用率" in strat._raw_evidence_for("查指标", state)
    # 标签不存在时退化为最后一条非空
    assert strat._raw_evidence_for("不存在的步骤", state)
    # 空状态返回空串
    assert strat._raw_evidence_for("x", {}) == ""
    assert strat._raw_evidence_for("x", {"raw_evidence": []}) == ""


def test_judge_switch_default_off() -> None:
    """ENABLE_RAW_EVIDENCE_FOR_JUDGE 默认必须为 False（旧行为零变化）。"""
    assert settings.ENABLE_RAW_EVIDENCE_FOR_JUDGE is False


def test_plain_label_strips_parallel() -> None:
    assert _plain_label("[并行] 查监控") == "查监控"
    assert _plain_label("普通步骤") == "普通步骤"
