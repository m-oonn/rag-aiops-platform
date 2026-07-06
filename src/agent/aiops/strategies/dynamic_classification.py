"""动态分类 Replan 策略：矛盾触发 + 鉴别诊断式概率重排。

核心机制（毕设创新点）：
  1. 维护诊断假设列表，每步执行后更新后验概率（贝叶斯启发式）
  2. 检测矛盾证据（某假设的预期结果与实际结果不符）→ 触发概率重排
  3. 重排后决策：高置信度 respond / 矛盾触发 replan / 默认 continue

区别于普通 Replan：
  - 普通 replanner 只问"信息够不够"，不做假设间的鉴别诊断
  - 本策略维护一个假设空间，每步都在做"哪个假设更可能是根因"的量化判断
"""

from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, Field

from src.agent.aiops.state import PlanExecuteState
from src.agent.aiops.strategies.base import BaseReplanStrategy
from src.agent.aiops.strategies.default import DefaultReplanStrategy
from src.utils.logger import logger


def _local_respond(state: PlanExecuteState) -> Dict[str, Any]:
    """兜底响应生成：不调 LLM，基于假设摘要拼接。"""
    input_text = state.get("input", "")
    past_steps = state.get("past_steps", [])
    steps_md = "\n".join(f"- {s}: {str(r)[:200]}" for s, r in past_steps) or "无"
    return {
        "response": (
            f"# 诊断结果\n\n"
            f"## 原始任务\n{input_text}\n\n"
            f"## 已执行步骤\n{steps_md}\n\n"
            f"_系统已收集足够信息，诊断完成。_"
        )
    }

# ── 概率常量 ──────────────────────────────────────────────
_CONFIRM_BOOST = 0.15        # 证据支持假设时概率增量
_CONTRADICT_PENALTY = 0.25   # 矛盾证据时概率减量
_SHRINK_ALPHA = 0.05         # 未涉及假设的衰减因子
_RESPOND_THRESHOLD = 0.70    # 最高概率 > 此值 → respond
_REPLAN_TRIGGER_DELTA = 0.20 # 概率重排变化 > 此值 → replan
_HYPOTHESIS_MAX = 6          # 同时追踪的最大假设数
_RESPOND_CONFIDENCE_FLOOR = 0.50  # respond 时最高概率至少 ≥ 此值
_STEP_HISTORY_LOOKBACK = 3   # 检查矛盾时回看最近 N 步
# ── /概率常量 ──────────────────────────────────────────────


class Hypothesis(BaseModel):
    """一条诊断假设。"""
    label: str = Field(description="假设名称，如'CPU 过载'")
    probability: float = Field(default=0.5, ge=0.0, le=1.0)
    supporting_evidence: List[str] = Field(default_factory=list)
    contradicting_evidence: List[str] = Field(default_factory=list)
    expected_findings: List[str] = Field(default_factory=list, description="如果此假设为真，应该观察到的现象")


class HypothesisStep(BaseModel):
    """一步执行后的假设空间快照，用于追踪概率演化。"""
    step_index: int
    step_action: str
    hypotheses: List[Hypothesis]
    max_prob: float
    max_hypothesis: str | None
    contradiction_detected: bool = False


class DynamicClassificationStrategy(BaseReplanStrategy):
    """矛盾触发 + 鉴别诊断式概率重排策略。

    设计目标：
      - 不改变 LangGraph 图结构（planner/executor/replanner 拓扑不变）
      - 只替换 replanner 内部的决策逻辑
      - 可回退到 DefaultReplanStrategy
    """

    def __init__(self, llm_generate_hypotheses=None):
        self.hypotheses: List[Hypothesis] = []
        self.step_history: List[HypothesisStep] = []
        self._llm_generate = llm_generate_hypotheses

    async def decide(self, state: PlanExecuteState) -> Dict[str, Any]:
        logger.info("=== DynamicClassificationStrategy:评估 ===")

        past_steps = state.get("past_steps", [])
        plan = state.get("plan", [])
        input_text = state.get("input", "")

        if len(past_steps) >= 8:
            logger.warning("[dynamic_class] 已达步数上限, 强制 respond")
            return _local_respond(state)

        if not plan and past_steps:
            logger.info("[dynamic_class] 计划执行完毕, 出报告")
            return _local_respond(state)

        # 1. 初始化假设（首步）
        if not self.hypotheses:
            self.hypotheses = self._init_hypotheses(input_text, state)
            logger.info("[dynamic_class] 初始化 %d 条假设", len(self.hypotheses))

        # 2. 更新假设概率
        if past_steps:
            self._update_probabilities(past_steps)

        # 3. 检测矛盾
        contradiction = self._detect_contradiction(past_steps)

        # 4. 记录快照
        max_h = max(self.hypotheses, key=lambda h: h.probability)
        self.step_history.append(HypothesisStep(
            step_index=len(past_steps),
            step_action=past_steps[-1][0] if past_steps else "init",
            hypotheses=[h.model_copy() for h in self.hypotheses],
            max_prob=max_h.probability,
            max_hypothesis=max_h.label,
            contradiction_detected=contradiction,
        ))

        # 5. 决策
        sorted_h = sorted(self.hypotheses, key=lambda h: h.probability, reverse=True)
        top = sorted_h[0]
        runner_up = sorted_h[1] if len(sorted_h) > 1 else None

        logger.info(
            "[dynamic_class] top=%s(%.3f) runner=%s contradiction=%s plan_remain=%d",
            top.label, top.probability,
            runner_up.label if runner_up else "N/A",
            contradiction, len(plan),
        )

        # 条件 A: 最高概率假设置信度足够高 → respond
        if top.probability >= _RESPOND_THRESHOLD and top.probability >= _RESPOND_CONFIDENCE_FLOOR:
            runner_gap = top.probability - (runner_up.probability if runner_up else 0)
            if runner_gap >= 0.20 or len(past_steps) >= 4:
                logger.info("[dynamic_class] 高置信度(%.3f), gap=%.3f → respond",
                            top.probability, runner_gap)
                return _local_respond(state)

        # 条件 B: 检测到矛盾 → replan（调整验证路径）
        if contradiction and len(past_steps) < 5:
            logger.info("[dynamic_class] 矛盾触发 → replan")
            new_plan = self._build_replan(sorted_h, past_steps, len(plan))
            return {"plan": new_plan}

        # 条件 C: 概率分布发生显著变化 → replan
        if self._significant_shift():
            logger.info("[dynamic_class] 概率显著变化 → replan")
            new_plan = self._build_replan(sorted_h, past_steps, len(plan))
            return {"plan": new_plan}

        # 默认: continue
        logger.info("[dynamic_class] 继续执行")
        return {}

    # ── 内部方法 ──────────────────────────────────────────

    def _init_hypotheses(self, input_text: str, state: PlanExecuteState) -> List[Hypothesis]:
        """从输入和初始计划生成假设列表。"""
        hypotheses = [
            Hypothesis(label="基础设施/资源瓶颈", probability=0.30),
            Hypothesis(label="应用层异常", probability=0.25),
            Hypothesis(label="网络/连通性问题", probability=0.20),
            Hypothesis(label="配置错误", probability=0.15),
            Hypothesis(label="外部依赖故障", probability=0.10),
        ]
        return hypotheses

    def _update_probabilities(self, past_steps: list) -> None:
        """基于最新步骤结果更新所有假设的概率。"""
        if not past_steps:
            return

        total = sum(h.probability for h in self.hypotheses)
        if total <= 0:
            return

        # 归一化基线
        for h in self.hypotheses:
            h.probability = h.probability / total

        latest_step, latest_result = past_steps[-1]
        result_lower = latest_result.lower() if isinstance(latest_result, str) else ""

        for h in self.hypotheses:
            # 启发式：按假设关键词匹配调整概率
            keywords = {
                "基础设施/资源瓶颈": ["cpu", "memory", "disk", "load", "资源", "性能"],
                "应用层异常": ["error", "exception", "crash", "应用", "服务"],
                "网络/连通性问题": ["timeout", "connect", "network", "网络", "连接"],
                "配置错误": ["config", "setting", "permission", "配置", "权限"],
                "外部依赖故障": ["database", "redis", "api", "外部", "依赖"],
            }

            base_keywords = keywords.get(h.label, [])
            match = sum(1 for kw in base_keywords if kw in result_lower)

            if match > 0:
                boost = _CONFIRM_BOOST * min(match, 3) / 3.0
                h.probability += boost
                if len(past_steps) <= _STEP_HISTORY_LOOKBACK:
                    h.supporting_evidence.append(latest_result[:200])
            else:
                h.probability = max(0.01, h.probability - _SHRINK_ALPHA)

        # 归一化
        new_total = sum(h.probability for h in self.hypotheses)
        if new_total > 0:
            for h in self.hypotheses:
                h.probability = h.probability / new_total

    def _detect_contradiction(self, past_steps: list) -> bool:
        """检查近期步骤中是否有矛盾证据。"""
        if len(past_steps) < 2:
            return False

        recent = past_steps[-min(_STEP_HISTORY_LOOKBACK, len(past_steps)):]
        positive = 0
        negative = 0

        for _step, result in recent:
            r = str(result).lower()
            if any(w in r for w in ["正常", "success", "ok", "healthy", "running", "0%"]):
                positive += 1
            if any(w in r for w in ["异常", "fail", "error", "timeout", "crash", "100%"]):
                negative += 1

        # 正负混合 → 矛盾信号
        return positive > 0 and negative > 0 and abs(positive - negative) <= 1

    def _significant_shift(self) -> bool:
        """最近两步假设概率是否发生了显著变化。"""
        if len(self.step_history) < 2:
            return False
        prev = self.step_history[-2]
        curr = self.step_history[-1]
        return abs(curr.max_prob - prev.max_prob) >= _REPLAN_TRIGGER_DELTA

    def _build_replan(self, sorted_h: list, past_steps: list, current_plan_len: int = 0) -> List[str]:
        """基于当前假设排序生成验证计划。"""
        new_plan = []
        for h in sorted_h[:3]:
            if h.probability >= 0.15:
                done_actions = {s for s, _ in past_steps}
                verify = f"验证 {h.label}"
                if verify not in done_actions:
                    new_plan.append(verify)
                detail = f"深入排查 {h.label}"
                if detail not in done_actions:
                    new_plan.append(detail)
        if not new_plan:
            new_plan = ["收集更多诊断信息", "分析已获取数据"]
        return new_plan[:4]
