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
    _CHANGE_HYPOTHESIS,
    _MAX_STEPS,
    _REPLAN_TRIGGER_DELTA,
    _RESPOND_THRESHOLD,
    _change_conflict_evidences,
    _evidence_sufficiency_problem,
    _local_respond,
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


# ── C. 变更/发布事件的矛盾触发判定（_change_conflict_evidences） ──────────
# 锁死两条纪律: (1) 窗口内有变更 → 支持 h_change,并对领先症状假设判矛盾(触发旁开);
# (2) 变更数据"没查成"(不可用/未取得)绝不等于"无变更" —— 不得据此判矛盾。


def test_change_evidence_supports_change_hypothesis():
    """窗口内存在变更 → 对 h_change 判支持。"""
    evs = _change_conflict_evidences(
        "查询最近变更记录", "命中 1 条变更事件: config change by ops", None, 1, "查询变更"
    )
    assert len(evs) == 1
    assert evs[0].target_hypothesis_id == _CHANGE_HYPOTHESIS.id
    assert evs[0].relation == "support"


def test_change_absent_contradicts_change_hypothesis():
    """窗口内无变更 → 对 h_change 判矛盾(排除'变更/发布引入')。"""
    evs = _change_conflict_evidences("查询变更记录", "窗口内无变更记录", None, 1, "查询变更")
    assert len(evs) == 1
    assert evs[0].target_hypothesis_id == _CHANGE_HYPOTHESIS.id
    assert evs[0].relation == "contradict"


def test_change_unavailable_not_treated_as_absent():
    """变更数据不可用/未取得 → 不产出任何证据(不得当成'无变更'判矛盾)。"""
    for text in ("变更服务不可用", "未取得变更数据", "search_changes 调用失败"):
        evs = _change_conflict_evidences("查询变更记录", text, "h_infra", 3, "查询变更")
        assert evs == [], f"'{text}' 不应被当成无变更"


def test_change_evidence_contradicts_leading_symptom():
    """已有≥2步观测且领先为症状层假设时,同期变更对其判矛盾(触发旁开式 replan)。"""
    evs = _change_conflict_evidences(
        "查询变更记录", "命中变更事件: 灰度发布", "h_infra", 3, "查询变更"
    )
    targets = {(e.target_hypothesis_id, e.relation) for e in evs}
    assert (_CHANGE_HYPOTHESIS.id, "support") in targets
    assert ("h_infra", "contradict") in targets


def test_change_evidence_does_not_contradict_before_two_steps():
    """首步(step_no<2)时不对领先假设判矛盾,避免任意先验导致的误触发。"""
    evs = _change_conflict_evidences(
        "查询变更记录", "命中变更事件: 部署", "h_infra", 1, "查询变更"
    )
    assert evs
    assert all(e.target_hypothesis_id == _CHANGE_HYPOTHESIS.id for e in evs)
    assert all(e.relation == "support" for e in evs)


def test_non_change_step_produces_no_evidence():
    """非变更步骤且结果无变更标记 → 不产出证据(避免污染假设空间)。"""
    evs = _change_conflict_evidences(
        "查询 CPU 指标", "cpu 使用率 96%", "h_infra", 3, "查询 CPU 指标"
    )
    assert evs == []


# ── D. 证据不足时的诚实声明（_evidence_sufficiency_problem / _local_respond） ──
# 纪律: 关键证据源(日志)缺失时,不得把并列猜测伪装成"已锁定根因"。


def test_sufficiency_problem_detects_missing_log_source():
    note = _evidence_sufficiency_problem([("查询日志", "工具 'search_log' 不存在,跳过")])
    assert note and "日志证据缺失" in note


def test_sufficiency_problem_detects_degraded_local_copy():
    note = _evidence_sufficiency_problem([("查询日志", "已降级读取本地副本降级(local_cache)")])
    assert note and ("降级" in note or "本地副本" in note)


def test_sufficiency_problem_none_when_log_present():
    assert _evidence_sufficiency_problem([("查询日志", "命中 3 条日志: OOM")]) is None


def test_local_respond_flags_uncertain_when_evidence_missing():
    """证据缺失 + 高概率 → 结论应标注为'推测',不伪装成确定结论。"""
    note = "日志证据缺失(检索工具不可用), 2 步观测中日志步骤无法取证"
    state = {"input": "服务异常", "plan": [], "past_steps": [("检查服务", "5xx 上升")], "response": ""}
    space = [{"id": "h_app", "name": "应用层异常", "probability": 0.80}]
    report = _local_respond(state, space, note)["response"]
    assert "推测" in report
    assert "日志证据缺失" in report


def test_local_respond_marks_degraded_source_as_auditable():
    """降级来源(本地副本)证据真实 → 输出结论但标注可审计。"""
    note = "日志证据来自本地降级副本(日志服务不可达), 2 步观测中日志步骤已本地兜底"
    state = {"input": "服务异常", "plan": [], "past_steps": [("查询日志", "OOM")], "response": ""}
    space = [{"id": "h_app", "name": "应用层异常", "probability": 0.80}]
    report = _local_respond(state, space, note)["response"]
    assert "本地副本" in report
    assert "复核" in report
