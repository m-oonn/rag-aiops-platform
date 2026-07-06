"""DynamicClassificationStrategy 单元测试。

测试重点（毕设创新点的可验证行为）：
  1. 首步初始化 5 条假设
  2. 支持证据 → 概率上升
  3. 矛盾检测
  4. 高置信度 → respond
  5. 显著概率变化 → replan
"""

import pytest

from src.agent.aiops.state import PlanExecuteState
from src.agent.aiops.strategies.dynamic_classification import (
    DynamicClassificationStrategy,
    Hypothesis,
    _RESPOND_THRESHOLD,
)


@pytest.fixture
def strategy():
    return DynamicClassificationStrategy()


def _make_state(input_text="CPU 负载过高", plan=None, past_steps=None, response=""):
    return PlanExecuteState(
        input=input_text,
        plan=plan or [],
        past_steps=past_steps or [],
        response=response,
    )


@pytest.mark.asyncio
async def test_init_hypotheses_on_first_call(strategy):
    """首步 decide 应初始化 5 条假设。"""
    state = _make_state(plan=["check cpu"])
    result = await strategy.decide(state)
    assert len(strategy.hypotheses) == 5
    assert any(h.label == "基础设施/资源瓶颈" for h in strategy.hypotheses)


@pytest.mark.asyncio
async def test_supporting_evidence_boosts_probability(strategy):
    """匹配假设关键词的结果应提升对应假设概率。"""
    state = _make_state(plan=["check cpu"], past_steps=[("check cpu", "CPU usage: 95%, memory: 80%")])
    await strategy.decide(state)
    infra = next(h for h in strategy.hypotheses if h.label == "基础设施/资源瓶颈")
    assert infra.probability > 0.30, f"expected >0.30, got {infra.probability:.3f}"


@pytest.mark.asyncio
async def test_contradiction_detected(strategy):
    """正负混合的结果应触发 contradiction。"""
    past_steps = [
        ("check cpu", "CPU usage: 95%, high load"),
        ("check app", "Application running normally, no errors"),
    ]
    state = _make_state(plan=["check network"], past_steps=past_steps)
    await strategy.decide(state)
    assert len(strategy.step_history) >= 1
    # 正负混在 → contradiction
    step = strategy.step_history[-1]
    assert step.contradiction_detected, f"expected contradiction, got {step.contradiction_detected}"


@pytest.mark.asyncio
async def test_high_confidence_responds(strategy):
    """最高概率假设超过阈值应触发 respond。"""
    # 直接注入高置信度假设
    strategy.hypotheses = [
        Hypothesis(label="基础设施/资源瓶颈", probability=0.85),
        Hypothesis(label="应用层异常", probability=0.10),
        Hypothesis(label="网络/连通性问题", probability=0.03),
        Hypothesis(label="配置错误", probability=0.01),
        Hypothesis(label="外部依赖故障", probability=0.01),
    ]

    past_steps = [
        ("check cpu", "CPU: 95%"),
        ("check memory", "Memory: 80%"),
        ("check disk", "Disk: 60%"),
        ("check app", "App normal"),
    ]
    state = _make_state(plan=["check network"], past_steps=past_steps)
    result = await strategy.decide(state)
    assert "response" in result, f"expected respond, got {result}"
    assert result["response"]


@pytest.mark.asyncio
async def test_plan_exhausted_responds(strategy):
    """计划为空且已有执行步骤时出报告。"""
    state = _make_state(plan=[], past_steps=[("check cpu", "CPU ok")])
    result = await strategy.decide(state)
    assert "response" in result


@pytest.mark.asyncio
async def test_continue_when_low_confidence(strategy):
    """概率分布扁平时继续执行。"""
    strategy.hypotheses = [
        Hypothesis(label="基础设施/资源瓶颈", probability=0.22),
        Hypothesis(label="应用层异常", probability=0.21),
        Hypothesis(label="网络/连通性问题", probability=0.20),
        Hypothesis(label="配置错误", probability=0.19),
        Hypothesis(label="外部依赖故障", probability=0.18),
    ]
    past_steps = [("check cpu", "CPU: 30%, normal")]
    state = _make_state(plan=["check memory", "check disk"], past_steps=past_steps)
    result = await strategy.decide(state)
    assert result == {}, f"expected empty (continue), got {result}"


@pytest.mark.asyncio
async def test_max_steps_forces_respond(strategy):
    """超过步数上限应强制 respond。"""
    past_steps = [(f"step_{i}", "ok") for i in range(8)]
    state = _make_state(plan=["more"], past_steps=past_steps)
    result = await strategy.decide(state)
    assert "response" in result


@pytest.mark.asyncio
async def test_significant_shift_triggers_replan(strategy):
    """概率分布显著变化应触发 replan（返回 plan）。"""
    strategy.hypotheses = [
        Hypothesis(label="基础设施/资源瓶颈", probability=0.50),
        Hypothesis(label="应用层异常", probability=0.25),
        Hypothesis(label="网络/连通性问题", probability=0.15),
        Hypothesis(label="配置错误", probability=0.05),
        Hypothesis(label="外部依赖故障", probability=0.05),
    ]
    # 制造概率跃迁记录
    class FakeStep:
        max_prob = 0.30
        max_hypothesis = "app"
        step_index = 1
        step_action = "prev"
        contradiction_detected = False
    strategy.step_history = [FakeStep()]

    past_steps = [("check cpu", "CPU: 95%, high load")]
    state = _make_state(plan=["check memory"], past_steps=past_steps)
    result = await strategy.decide(state)
    assert "plan" in result, f"expected replan (plan), got {result}"
