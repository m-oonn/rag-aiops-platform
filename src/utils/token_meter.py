#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""诊断过程的 token 计量（2026-10-09 新增）

为什么需要：答辩/验收需要**真实消耗数据**（耗时、token、折算费用），
而本项目此前只有耗时（trace_span），没有 token 统计。

实现：LangChain 回调钩子 `on_llm_end` 读取 `LLMResult.llm_output["token_usage"]`
（OpenAI 兼容接口都会回传），按模型聚合。

用法（一键启用/关闭）：
    from src.utils.token_meter import TokenMeter
    meter = TokenMeter()
    llm = create_agent_llm(callbacks=[meter])

    # 诊断结束后
    print(meter.summary())         # 人类可读汇总
    d = meter.as_dict()            # {calls, input_tokens, output_tokens, by_model}

单价表（人民币/百万 token，2026-10-09 查证 DeepSeek 官方定价页并折算）：
    deepseek-v4-flash: 输入 ¥1.0 / 输出 ¥2.8      （$0.14 / $0.39，按 1USD≈7.1CNY）
    deepseek-v4-pro  : 输入 ¥3.1 / 输出 ¥6.2      （$0.435 / $0.87）
    deepseek-chat/reasoner（旧别名，已下线，仅兜底）: 同 flash
    未知模型 → 按 flash 单价估算（并在汇总里标注"估算"）
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from langchain_core.callbacks import BaseCallbackHandler

# 人民币 / 百万 token（2026-10-09 查证；改价时更新这里）
_PRICE_CNY_PER_M: Dict[str, Dict[str, float]] = {
    "deepseek-v4-flash": {"in": 1.0, "out": 2.8},
    "deepseek-v4-pro": {"in": 3.1, "out": 6.2},
    "deepseek-chat": {"in": 1.0, "out": 2.8},
    "deepseek-reasoner": {"in": 1.0, "out": 2.8},
}
_USD_TO_CNY = 7.1  # 折算用（仅注释说明，不参与计算）


# ── 全局计量器（可选启用）─────────────────────────────────────────
# 设计：诊断链路里 LLM 实例在多个节点各自创建（planner/executor/replanner），
# 逐个传参侵入性太大。改用一个"活动计量器"：启用后 create_agent_llm 自动挂载，
# 诊断结束时读取汇总。
_active_meter: Optional["TokenMeter"] = None


def get_active_meter() -> Optional["TokenMeter"]:
    return _active_meter


def start_meter() -> "TokenMeter":
    """启用全局计量（返回全新计量器；重复调用会重置）。"""
    global _active_meter
    _active_meter = TokenMeter()
    return _active_meter


def stop_meter() -> Optional["TokenMeter"]:
    """停用并返回本次计量器（供汇总）。"""
    global _active_meter
    m = _active_meter
    _active_meter = None
    return m


class TokenMeter(BaseCallbackHandler):
    """累计一次诊断里所有 LLM 调用的 token 消耗。"""

    def __init__(self):
        super().__init__()
        self.calls: int = 0
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.by_model: Dict[str, Dict[str, int]] = {}
        self.errors: List[str] = []

    # LangChain 回调：每次 LLM 调用结束
    def on_llm_end(self, response, **kwargs: Any) -> None:  # noqa: ANN001
        try:
            llm_output = getattr(response, "llm_output", None) or {}
            usage = (
                llm_output.get("token_usage")
                or llm_output.get("usage")
                or {}
            )
            # 有些实现把 usage 放在 generations[].message.usage_metadata
            if not usage and getattr(response, "generations", None):
                gen = response.generations[0][0]
                msg = getattr(gen, "message", None)
                meta = getattr(msg, "usage_metadata", None) if msg is not None else None
                if meta:
                    usage = {
                        "prompt_tokens": meta.get("input_tokens", 0),
                        "completion_tokens": meta.get("output_tokens", 0),
                    }
            in_tok = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
            out_tok = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
            model = llm_output.get("model_name") or llm_output.get("model") or "unknown"

            self.calls += 1
            self.input_tokens += in_tok
            self.output_tokens += out_tok

            slot = self.by_model.setdefault(model, {"calls": 0, "in": 0, "out": 0})
            slot["calls"] += 1
            slot["in"] += in_tok
            slot["out"] += out_tok
        except Exception as e:  # 计量失败绝不能影响诊断主流程
            self.errors.append(f"{type(e).__name__}: {e}")

    # ── 汇总 ──
    def cost_cny(self, model: Optional[str] = None) -> float:
        """折算人民币费用。model=None 时对全部模型分别折算后求和。"""
        def price_for(m: str) -> Dict[str, float]:
            for key, p in _PRICE_CNY_PER_M.items():
                if m.startswith(key):
                    return p
            return _PRICE_CNY_PER_M["deepseek-v4-flash"]  # 未知模型按 flash 估算

        total = 0.0
        if model is None:
            for m, s in self.by_model.items():
                p = price_for(m)
                total += s["in"] / 1_000_000 * p["in"] + s["out"] / 1_000_000 * p["out"]
            return round(total, 4)
        p = price_for(model)
        return round(self.input_tokens / 1_000_000 * p["in"]
                     + self.output_tokens / 1_000_000 * p["out"], 4)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "llm_calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.input_tokens + self.output_tokens,
            "by_model": self.by_model,
            "cost_cny_estimated": self.cost_cny(),
            "count_errors": self.errors[:3],
        }

    def summary(self) -> str:
        lines = [
            f"LLM 调用次数   : {self.calls}",
            f"输入 token     : {self.input_tokens:,}",
            f"输出 token     : {self.output_tokens:,}",
            f"合计 token     : {self.input_tokens + self.output_tokens:,}",
            f"折算费用(估算) : ¥{self.cost_cny():.4f}",
        ]
        if self.by_model:
            lines.append("按模型明细:")
            for m, s in self.by_model.items():
                lines.append(f"  - {m}: {s['calls']} 次, 入 {s['in']:,}, 出 {s['out']:,}")
        return "\n".join(lines)
