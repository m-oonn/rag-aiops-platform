"""DynamicClassificationStrategy / HypothesisManager 单元测试。

覆盖毕设创新点「旁开式动态分类故障诊断机制」的可验证行为，分两组：

A. 信念更新机制（``HypothesisManager``，纯确定性，不依赖 LLM 与关键词）
   - 批次顺序无关性：同一批证据任意排列，结果一致（log-odds 原子更新）
   - 去重语义：同关系重复命中折叠取最大强度；相反关系不折叠、净效应生效
   - 保护期：保护轮数未耗尽时，矛盾证据不得淘汰假设
   - 淘汰判定：保护耗尽且最终概率低于阈值时才置 falsified
   - 竞争归一：多候选按 logit softmax 归一（概率和为 1）；单候选保持独立
   - 深度回溯复活：仅 falsified 可复活，并累计重解释次数

B. 决策规则（``DynamicClassificationStrategy`` + 可编程裁判）
   - 首步初始化 7 条默认假设
   - 计划执行完毕 / 步数上限 / 高置信度 → respond
   - 低置信且计划未毕 → continue
   - 领先假设被矛盾 → replan（旁开）
   - 信念显著跃迁 → replan
   - ``reset()`` 清空内部状态，供同实例复用于下一次诊断

设计说明：
  决策类用例注入 ``ScriptedJudge``（按步号返回预置证据）而非真实关键词裁判，
  使断言只依赖机制逻辑、不依赖关键词表内容，避免"改词表即挂测试"的脆弱性。
"""

import pytest

from src.agent.aiops.core.evidence_judge import EvidenceJudge
from src.agent.aiops.core.hypothesis import Evidence, Hypothesis, HypothesisManager
from src.agent.aiops.state import PlanExecuteState
from src.agent.aiops.strategies.dynamic_classification import (
    DynamicClassificationStrategy,
    _MAX_STEPS,
    _REPLAN_TRIGGER_DELTA,
    _RESPOND_THRESHOLD,
)

# 默认假设空间的期望构成（与 _DEFAULT_HYPOTHESES 对齐，改动此处即测试失败）
_EXPECTED_HYPOTHESIS_IDS = {
    "h_infra",
    "h_app",
    "h_net",
    "h_config",
    "h_dep",
    "h_container",
    "h_api",
}


# ── 测试替身与构造助手 ────────────────────────────────────


class ScriptedJudge(EvidenceJudge):
    """按步号返回预置证据的裁判替身。

    ``script`` 形如 ``{step: [(hypothesis_id, relation, strength), ...]}``；
    未声明的步号返回空证据（= 该步不产生信念变化），因此可精确控制
    每一步对假设空间的影响。
    """

    def __init__(self, script: dict[int, list[tuple[str, str, float]]] | None = None) -> None:
        super().__init__(llm=None)
        self.script = script or {}

    async def judge_async(  # type: ignore[override]
        self, hypotheses, observation, step: int = 0, source: str = "executor"
    ) -> list[Evidence]:
        return [
            Evidence(
                source=source,
                target_hypothesis_id=hid,
                relation=relation,
                strength=strength,
                step=step,
            )
            for hid, relation, strength in self.script.get(step, [])
        ]


def _state(input_text="CPU 负载过高", plan=None, past_steps=None, response=""):
    """构造最小可用的 PlanExecuteState。"""
    return PlanExecuteState(
        input=input_text,
        plan=plan if plan is not None else [],
        past_steps=past_steps or [],
        response=response,
    )


def _seed(strategy: DynamicClassificationStrategy, specs: list[tuple[str, float, int]]) -> None:
    """把假设空间替换为受控的一组假设（id, probability, protection_rounds）。"""
    strategy.reset()
    strategy.manager.add_hypotheses(
        [
            Hypothesis(id=hid, name=f"假设{hid}", probability=prob, protection_rounds=prot)
            for hid, prob, prot in specs
        ]
    )


def _manager(specs: list[tuple[str, float, int]]) -> HypothesisManager:
    """构造一个预置假设的 HypothesisManager。"""
    manager = HypothesisManager()
    manager.add_hypotheses(
        [
            Hypothesis(id=hid, name=f"假设{hid}", probability=prob, protection_rounds=prot)
            for hid, prob, prot in specs
        ]
    )
    return manager


def _probabilities(manager: HypothesisManager) -> dict[str, float]:
    return {h.id: h.probability for h in manager.get_all_hypotheses()}


# ══════════════════════════════════════════════════════════
# A. 信念更新机制
# ══════════════════════════════════════════════════════════


def test_batch_order_independence():
    """同一批证据无论排列顺序如何，更新后的概率完全一致。

    这是 log-odds 批次原子更新的核心保证：旧实现逐条就地改写概率，
    先处理者先饱和、先淘汰，使批次顺序成为隐性偏置。
    """
    evidences = [
        Evidence(source="s1", target_hypothesis_id="a", relation="support", strength=1.0, step=1),
        Evidence(source="s2", target_hypothesis_id="a", relation="contradict", strength=0.8, step=2),
        Evidence(source="s3", target_hypothesis_id="b", relation="support", strength=0.9, step=1),
        Evidence(source="s4", target_hypothesis_id="b", relation="contradict", strength=0.4, step=3),
        Evidence(source="s5", target_hypothesis_id="a", relation="support", strength=0.6, step=4),
    ]
    specs = [("a", 0.30, 0), ("b", 0.45, 0)]

    forward = _manager(specs)
    forward.update_beliefs(evidences)

    backward = _manager(specs)
    backward.update_beliefs(list(reversed(evidences)))

    pf, pb = _probabilities(forward), _probabilities(backward)
    for hid in ("a", "b"):
        assert pf[hid] == pytest.approx(pb[hid], abs=1e-12), (
            f"假设 {hid} 的概率受证据排列顺序影响: 正序={pf[hid]}, 逆序={pb[hid]}"
        )


def test_dedupe_same_relation_keeps_max_strength():
    """同一 (来源, 步号, 目标, 关系) 的重复命中只保留强度最高的一条。"""
    manager = _manager([("a", 0.50, 0)])

    manager.update_beliefs(
        [
            Evidence(source="s", target_hypothesis_id="a", relation="support", strength=0.30, step=1),
            Evidence(source="s", target_hypothesis_id="a", relation="support", strength=0.90, step=1),
        ]
    )

    logged = manager.get_hypothesis("a").evidence_log
    assert len(logged) == 1, "重复命中未折叠为一条"
    assert logged[0].strength == pytest.approx(0.90), "未保留强度更高的那条"


def test_opposite_relations_are_not_deduped():
    """同一观测给出的支持与矛盾证据含义相反，不得互相折叠。"""
    manager = _manager([("a", 0.50, 0)])

    manager.update_beliefs(
        [
            Evidence(source="s", target_hypothesis_id="a", relation="support", strength=0.60, step=1),
            Evidence(source="s", target_hypothesis_id="a", relation="contradict", strength=0.60, step=1),
        ]
    )

    logged = manager.get_hypothesis("a").evidence_log
    assert len(logged) == 2, "相反关系的证据被错误折叠"
    relations = {ev.relation for ev in logged}
    assert relations == {"support", "contradict"}
    # 净效应：矛盾系数(2.5) > 支持系数(1.5)，概率应低于先验
    assert manager.get_hypothesis("a").probability < 0.50


def test_protection_period_blocks_falsification():
    """保护期内矛盾证据照常更新信念，但不得淘汰假设（针对 E1 过早放弃）。"""
    manager = _manager([("a", 0.50, 2)])

    manager.update_beliefs(
        [Evidence(source="s", target_hypothesis_id="a", relation="contradict", strength=1.0, step=1)]
    )

    h = manager.get_hypothesis("a")
    assert h.status == "active", "保护期内的假设被错误淘汰"
    assert h.protection_rounds == 1, "保护轮数未按矛盾命中数消耗"
    assert h.probability < 0.20, "矛盾证据未正常降低概率"


def test_falsification_after_protection_exhausted():
    """保护耗尽后，矛盾证据把概率压到阈值以下才置 falsified。"""
    manager = _manager([("a", 0.10, 0)])

    manager.update_beliefs(
        [Evidence(source="s", target_hypothesis_id="a", relation="contradict", strength=1.0, step=7)]
    )

    h = manager.get_hypothesis("a")
    assert h.status == "falsified"
    assert h.falsified_step == 7, "未记录淘汰步数（深度回溯复查依赖该字段）"


def test_softmax_normalization_over_candidates():
    """多候选时按 logit 竞争归一：概率之和为 1，且保持排序。"""
    manager = _manager([("a", 0.50, 0), ("b", 0.30, 0), ("c", 0.20, 0)])

    manager.update_beliefs(
        [Evidence(source="s", target_hypothesis_id="a", relation="support", strength=0.5, step=1)]
    )

    probs = _probabilities(manager)
    assert sum(probs.values()) == pytest.approx(1.0, abs=1e-9), "竞争归一后概率和不为 1"
    assert probs["a"] > probs["b"] > probs["c"], "归一化破坏了假设排序"


def test_single_candidate_keeps_independence():
    """单候选不参与归一：概率只由自身证据决定（保持独立性语义）。"""
    manager = _manager([("a", 0.30, 0)])

    manager.update_beliefs(
        [Evidence(source="s", target_hypothesis_id="a", relation="support", strength=1.0, step=1)]
    )

    # 期望 = sigmoid(logit(0.30) + 1.0 × support_strength(1.5))
    import math

    expected = 1.0 / (1.0 + math.exp(-(math.log(0.30 / 0.70) + 1.5)))
    assert manager.get_hypothesis("a").probability == pytest.approx(expected, abs=1e-6)


def test_reactivate_falsified_hypothesis():
    """深度回溯复活：falsified → active，重置概率、重获保护期并累计次数。"""
    manager = _manager([("a", 0.10, 0)])

    manager.update_beliefs(
        [Evidence(source="s", target_hypothesis_id="a", relation="contradict", strength=1.0, step=1)]
    )
    assert manager.get_hypothesis("a").status == "falsified"

    restored = manager.reactivate("a", new_probability=0.35, protection_rounds=2)

    assert restored is not None
    assert restored.status == "active"
    assert restored.probability == pytest.approx(0.35)
    assert restored.protection_rounds == 2
    assert restored.reinterpret_count == 1


def test_reactivate_rejects_non_falsified():
    """只有已淘汰的假设可被复活，active 假设调用 reactivate 应返回 None。"""
    manager = _manager([("a", 0.60, 0)])

    assert manager.reactivate("a", new_probability=0.9, protection_rounds=2) is None
    assert manager.get_hypothesis("a").reinterpret_count == 0


def test_falsified_hypothesis_excluded_from_ranking():
    """已淘汰的假设不再进入 active 列表与 top-k 排序。"""
    manager = _manager([("a", 0.80, 0), ("b", 0.10, 0)])

    manager.update_beliefs(
        [Evidence(source="s", target_hypothesis_id="b", relation="contradict", strength=1.0, step=1)]
    )

    assert manager.get_hypothesis("b").status == "falsified"
    assert "b" not in {h.id for h in manager.get_active_hypotheses()}
    assert "b" not in {h.id for h in manager.get_top_hypotheses(k=5)}
    # 全量查询仍需包含被淘汰假设，供深度回溯复查
    assert "b" in {h.id for h in manager.get_all_hypotheses()}


# ══════════════════════════════════════════════════════════
# B. 决策规则
# ══════════════════════════════════════════════════════════


@pytest.fixture
def strategy():
    return DynamicClassificationStrategy(judge=ScriptedJudge())


@pytest.mark.asyncio
async def test_first_decide_initializes_default_hypotheses():
    """首次 decide 应初始化 7 条默认假设，且 id 集合与预期一致。"""
    strategy = DynamicClassificationStrategy(judge=ScriptedJudge())

    await strategy.decide(_state(plan=["检查 CPU"], past_steps=[("检查 CPU", "ok")]))

    active = strategy.manager.get_active_hypotheses()
    assert len(active) == 7
    assert {h.id for h in active} == _EXPECTED_HYPOTHESIS_IDS


@pytest.mark.asyncio
async def test_plan_exhausted_responds():
    """计划为空且已有执行步骤 → 输出诊断报告。"""
    strategy = DynamicClassificationStrategy(judge=ScriptedJudge())

    result = await strategy.decide(
        _state(plan=[], past_steps=[("检查 CPU", "CPU 使用率 95%")])
    )

    assert "response" in result
    assert result["response"].strip()


@pytest.mark.asyncio
async def test_max_steps_forces_respond():
    """达到步数上限 → 强制输出报告（绝对兜底）。"""
    strategy = DynamicClassificationStrategy(judge=ScriptedJudge())
    past_steps = [(f"步骤{i}", "ok") for i in range(_MAX_STEPS)]

    result = await strategy.decide(_state(plan=["继续排查"], past_steps=past_steps))

    assert "response" in result


@pytest.mark.asyncio
async def test_high_confidence_responds():
    """领先假设越过阈值且次选已被充分排除、计划收尾 → respond。"""
    strategy = DynamicClassificationStrategy(judge=ScriptedJudge())
    _seed(
        strategy,
        [("h_infra", 0.86, 0), ("h_app", 0.08, 0), ("h_net", 0.04, 0), ("h_dep", 0.02, 0)],
    )

    result = await strategy.decide(
        _state(plan=["检查网络"], past_steps=[("检查 CPU", "cpu 高"), ("检查内存", "内存高"), ("检查磁盘", "磁盘正常")])
    )

    assert "response" in result
    assert result["response"].strip()


@pytest.mark.asyncio
async def test_low_confidence_continues():
    """概率分布扁平且计划未执行完 → continue（不产出 plan，也不产出 response）。"""
    strategy = DynamicClassificationStrategy(judge=ScriptedJudge())
    _seed(
        strategy,
        [("h_infra", 0.22, 0), ("h_app", 0.21, 0), ("h_net", 0.20, 0), ("h_config", 0.19, 0), ("h_dep", 0.18, 0)],
    )

    result = await strategy.decide(
        _state(plan=["检查内存", "检查磁盘"], past_steps=[("检查 CPU", "cpu 正常")])
    )

    assert "response" not in result, "低置信度不应出报告"
    assert "plan" not in result, "不应触发重新规划"
    assert "hypothesis_space" in result, "continue 需回传最新假设空间快照"


@pytest.mark.asyncio
async def test_leading_hypothesis_contradiction_triggers_replan():
    """领先假设被矛盾证据否定且步数尚少 → replan（旁开）。"""
    strategy = DynamicClassificationStrategy(judge=ScriptedJudge({
        1: [("h_infra", "contradict", 1.0)],
    }))
    _seed(
        strategy,
        [("h_infra", 0.60, 0), ("h_app", 0.15, 0), ("h_net", 0.15, 0), ("h_dep", 0.10, 0)],
    )

    result = await strategy.decide(
        _state(plan=["检查网络", "检查依赖"], past_steps=[("检查 CPU", "cpu 正常，无资源瓶颈")])
    )

    assert "plan" in result, "领先假设被矛盾后未触发旁开式 replan"
    assert result["plan"], "replan 应给出非空验证计划"


@pytest.mark.asyncio
async def test_significant_belief_shift_triggers_replan():
    """信念分布出现 ≥ 阈值的跃迁 → replan。"""
    strategy = DynamicClassificationStrategy(judge=ScriptedJudge({
        2: [("h_app", "support", 1.0)],
    }))
    _seed(
        strategy,
        [("h_infra", 0.25, 0), ("h_app", 0.20, 0), ("h_net", 0.20, 0), ("h_config", 0.20, 0), ("h_dep", 0.15, 0)],
    )

    # 第一步：建立基线（记录 _last_top_prob），此时不应 replan
    baseline = await strategy.decide(
        _state(plan=["检查内存", "检查磁盘"], past_steps=[("检查 CPU", "ok")])
    )
    assert "plan" not in baseline

    # 第二步：应用支持证据，h_app 概率大幅上升（跃迁 ≥ _REPLAN_TRIGGER_DELTA）
    result = await strategy.decide(
        _state(
            plan=["检查内存", "检查磁盘"],
            past_steps=[("检查 CPU", "ok"), ("检查日志", "应用抛异常")],
        )
    )

    top = strategy.manager.get_top_hypotheses(k=1)[0]
    assert top.probability - 0.25 >= _REPLAN_TRIGGER_DELTA, "测试前提不成立：跃迁幅度不足"
    assert "plan" in result, "信念显著跃迁后未触发 replan"


@pytest.mark.asyncio
async def test_reset_clears_state_for_reuse():
    """reset() 应清空假设空间与内部计数，使同一实例可复用于下一次诊断。"""
    strategy = DynamicClassificationStrategy(judge=ScriptedJudge())

    await strategy.decide(_state(plan=["检查 CPU"], past_steps=[("检查 CPU", "cpu 高")]))
    assert strategy.manager.get_active_hypotheses()
    assert strategy._belief_history

    strategy.reset()

    assert strategy.manager.get_active_hypotheses() == []
    assert strategy._belief_history == []
    assert strategy._step_count == 0
    assert strategy._last_top_prob is None
    assert strategy._evidence_seen is False
