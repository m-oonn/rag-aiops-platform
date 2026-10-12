"""可解释性实验：A 组可审计性 / B 组置信度校准 / C 组结果稳定性。

对齐 `docs/architecture.md` 附录「可解释性实验结果」的口径与输出格式，
产出 `runtime/explainability_report.md` 与 `runtime/explainability_report.json`。

场景源：`mcp_servers/mock_scenario.py` 的 `SCENARIO_SERVICES`（9 个剧本），
通过「服务名」驱动 MCP mock 播放对应剧本的指标曲线与日志，无需真实监控后端。

三组设计
--------
A 组 · 决策可审计性（结构性对比）
    对 T1 动态分类 / T2 基线(DefaultReplanStrategy) 两路输出，逐维度检查
    可解释材料是否存在：信念演化轨迹 / 候选根因集+置信度 / 证据→假设映射 /
    决策过程记录。非对称即结论，不依赖主观评价。

B 组 · 置信度校准（ECE）
    采样点为「场景 × 假设空间 top 概率」与「场景 × 步级 top 概率」两种口径，
    分箱 [0.50,0.65) / [0.65,0.80) / [0.80,0.90) / [0.90,1.01]，
    计算 ECE = Σ (nᵢ/N)·|accᵢ − confᵢ|。

    ⚠️ 与原始 47 点口径的差异：原始样本 = 固定 8 场景(报告置信度 7 点) +
    盲测 40 场景(假设空间 top)。本脚本默认只覆盖 9 场景端到端部分；
    盲测 40 点需另跑盲测(消耗真实 LLM 配额)，见 `--include-blind`。

C 组 · 结果稳定性
    固定种子重跑 N 次（`--repeats`），统计结论一致率与收敛步数分布。

用法
----
  python scripts/run_explainability.py --dry-run        # 只起 MCP + 校验场景构造, 不跑 LLM
  python scripts/run_explainability.py --scenarios 1    # 只跑第 1 个场景(快速验证)
  python scripts/run_explainability.py                  # 全量 9 场景
  python scripts/run_explainability.py --repeats 3      # C 组: 固定种子重跑 3 次
  python scripts/run_explainability.py --tag A          # 产物隔离(explainability_report_A.*)

注意：LLM 相关依赖走 `.env`（DASHSCOPE_API_KEY）。证据裁判线路由
`settings.ENABLE_LLM_EVIDENCE_JUDGE` 决定（**当前 .env 未启用 ⇒ 规则关键词**）；
`--deterministic` 会强制注入 `EvidenceJudge(llm=None)` 锁定规则线路以换取可复现。
报告头部会如实标注实际生效的裁判线路。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import statistics
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

# ── 环境必须在 import 任何 src.* 之前设置 ──────────────────────────
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass
# 证据裁判要拿到 complete/report 事件；HITL 挂起为 pending_review 会使 top 取空
os.environ["ENABLE_HITL"] = "false"
os.environ.setdefault("ENABLE_DYNAMIC_CLASSIFICATION", "true")

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "src")):
    parent = os.path.dirname(PROJECT_ROOT)
    if parent == PROJECT_ROOT:
        break
    PROJECT_ROOT = parent
sys.path.insert(0, PROJECT_ROOT)

RUNTIME_DIR = os.path.join(PROJECT_ROOT, "runtime")
os.makedirs(RUNTIME_DIR, exist_ok=True)
REPORT_FILE = os.path.join(RUNTIME_DIR, "explainability_report.md")
DATA_FILE = os.path.join(RUNTIME_DIR, "explainability_report.json")

from mcp_servers.mock_scenario import SCENARIO_SERVICES  # noqa: E402
from run_full_pipeline import MCP_SERVERS, _start_servers, _stop_servers, _wait_for_ports  # noqa: E402

# ── 场景 → 期望根因（由 mock_scenario._LOG_MESSAGES 的语义推出）────────
# 说明：mock_scenario 只定义「服务名 → 剧本 → 指标曲线/日志」，未显式声明
# 期望根因。下表按剧本日志的主治症状人工对齐（与 blind_fault_gen.ROOT_CAUSE_NAMES
# 的假设名一致）。
SCENARIO_EXPECTED_ROOT: Dict[str, str] = {
    "infra_cpu": "基础设施/资源瓶颈",
    "network": "网络/连通性问题",
    "config": "配置错误",
    "app_oom": "应用层异常",
    "dependency": "外部依赖故障",
    "complex_overload": "应用层异常",
    "cascade_dependency": "外部依赖故障",
    "container": "容器问题",
    "service_api": "服务接口异常",
}

# ── 场景 → 用户上报症状（须不含根因名词，不"背题"）──────────────────
SCENARIO_SYMPTOM: Dict[str, str] = {
    "infra_cpu": "服务响应变慢，疑似资源占用偏高",
    "network": "服务出现大量连接超时、连接偶发断开与请求失败",
    "config": "近期配置调整后服务出现异常",
    "app_oom": "服务近期频繁报错，偶发接口不可用",
    "dependency": "依赖的下游能力出现异常，服务受影响",
    "complex_overload": "服务偶发请求超时并伴随应用报错，CPU 偏高",
    "cascade_dependency": "服务大量 503，下游缓存与第三方接口异常",
    "container": "服务实例反复重启，疑似容器被清理",
    "service_api": "部分接口响应变慢且偶发失败，接口可用性下降",
}

# ── ECE 分箱（与 architecture.md 附录 B 组一致）──────────────────────
ECE_BINS: List[Tuple[float, float]] = [
    (0.50, 0.65),
    (0.65, 0.80),
    (0.80, 0.90),
    (0.90, 1.01),
]


# ══════════════════════════════════════════════════════════
# 插桩：在 harness 侧子类化策略，记录每轮决策（零侵入 src）
# ══════════════════════════════════════════════════════════
def _classify_decision(out: Dict[str, Any]) -> str:
    """按策略返回值语义判定本轮决策类型。

    BaseReplanStrategy 契约：{"response"} → respond；{"plan"} → replan；否则 continue。
    """
    if out.get("response"):
        return "respond"
    if out.get("plan"):
        return "replan"
    return "continue"


def _make_instrumented_dynamic(force_rule_judge: bool = False):
    """动态分类策略 + 决策插桩（懒导入）。

    force_rule_judge=True 时显式注入 ``EvidenceJudge(llm=None)``，强制走确定性规则裁判。

    注意：``src.settings`` 是导入期缓存的单例，事后修改 ``ENABLE_LLM_EVIDENCE_JUDGE``
    环境变量**不会**影响 ``_maybe_create_judge_llm()``（它读的是 settings），因此本脚本
    用「注入 judge」而非「改 os.environ」来控制裁判线路。
    """
    from src.agent.aiops.core.evidence_judge import EvidenceJudge
    from src.agent.aiops.strategies.dynamic_classification import (
        DynamicClassificationStrategy,
    )

    class InstrumentedDynamic(DynamicClassificationStrategy):
        """记录每轮决策、top 假设与旁开支线数。"""

        def __init__(self, *args, **kwargs) -> None:
            if force_rule_judge and "judge" not in kwargs:
                kwargs["judge"] = EvidenceJudge(llm=None)
            super().__init__(*args, **kwargs)
            self.decisions: List[Dict[str, Any]] = []

        def reset(self) -> None:  # 与父类一致地清理插桩状态
            super().reset()
            self.decisions = []

        async def decide(self, state):
            out = await super().decide(state)
            top = self.manager.get_top_hypotheses(k=1)
            self.decisions.append(
                {
                    "step": self._step_count,
                    "action": _classify_decision(out),
                    "top_name": top[0].name if top else None,
                    "top_prob": round(top[0].probability, 4) if top else None,
                    "reply_keys": sorted(k for k in out.keys()),
                    "sidebar_branches": len(getattr(self, "_sidebar_branches", []) or []),
                }
            )
            return out

    return InstrumentedDynamic


def _make_instrumented_base():
    """基线策略 + 决策插桩。"""
    from src.agent.aiops.strategies.default import DefaultReplanStrategy

    class InstrumentedBase(DefaultReplanStrategy):
        """基线无假设空间，仅记录决策类型（用于 A 组结构性对比）。"""

        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.decisions: List[Dict[str, Any]] = []

        def reset(self) -> None:
            super().reset()
            self.decisions = []

        async def decide(self, state):
            out = await super().decide(state)
            self.decisions.append(
                {
                    "step": len(state.get("past_steps", []) or []),
                    "action": _classify_decision(out),
                    "reply_keys": sorted(k for k in out.keys()),
                }
            )
            return out

    return InstrumentedBase


# ══════════════════════════════════════════════════════════
# 单场景运行与数据采集
# ══════════════════════════════════════════════════════════
class _Runner:
    """跑一次诊断并采集可解释性材料。"""

    def __init__(self, strategy) -> None:
        import src.agent.aiops.graph as graph_mod

        self.strategy = strategy
        self.service = graph_mod.AIOpsService(replan_strategy=strategy)

    async def run(self, user_input: str) -> Dict[str, Any]:
        hypothesis_space: List[dict] = []
        report = ""
        steps = 0
        async for event in self.service.execute(user_input, session_id="explain-eval"):
            etype = event.get("type")
            if etype == "step_complete":
                steps += 1
            elif etype == "complete":
                hypothesis_space = event.get("hypothesis_space", []) or []
                report = event.get("response", "") or ""
            elif etype == "report":
                report = event.get("report", "") or ""

        return {
            "steps": steps,
            "hypothesis_space": hypothesis_space,
            "report": report,
            "belief_history": list(getattr(self.strategy, "_belief_history", []) or []),
            "decisions": list(getattr(self.strategy, "decisions", []) or []),
            "evidence_map": _evidence_map(self.strategy),
        }


def _evidence_map(strategy) -> Dict[str, List[dict]]:
    """抽取「证据 → 假设」映射（仅动态策略有假设空间）。"""
    manager = getattr(strategy, "manager", None)
    if manager is None:
        return {}
    out: Dict[str, List[dict]] = {}
    for h in manager.get_all_hypotheses():
        logs = getattr(h, "evidence_log", []) or []
        if not logs:
            continue
        out[h.id] = [
            {
                "source": ev.source,
                "relation": ev.relation,
                "strength": ev.strength,
                "step": ev.step,
                "description": ev.description,
            }
            for ev in logs
        ]
    return out


def _ranked(hypothesis_space: List[dict]) -> List[dict]:
    return sorted(hypothesis_space, key=lambda h: h.get("probability", 0.0), reverse=True)


def _top_names(hypothesis_space: List[dict], k: int = 3) -> List[Tuple[str, float]]:
    return [(h.get("name", "?"), h.get("probability", 0.0)) for h in _ranked(hypothesis_space)[:k]]


def _belief_points(record: Dict[str, Any], expected_root: str) -> List[Tuple[float, bool]]:
    """把信念轨迹换算成 (置信度, 是否判对) 采样点。

    id → name 映射取自最终假设空间快照；轨迹中出现的未知 id(孵化/复活新增)
    若不在快照中则跳过，避免臆造名称。
    """
    id2name = {h.get("id"): h.get("name", "?") for h in record.get("hypothesis_space", [])}
    points: List[Tuple[float, bool]] = []
    for snap in record.get("belief_history", []):
        probs: Dict[str, float] = snap.get("probabilities", {}) or {}
        named = {id2name[i]: p for i, p in probs.items() if i in id2name}
        if not named:
            continue
        top_name, top_prob = max(named.items(), key=lambda kv: kv[1])
        points.append((float(top_prob), top_name == expected_root))
    return points


# ══════════════════════════════════════════════════════════
# 指标计算
# ══════════════════════════════════════════════════════════
def _ece(points: List[Tuple[float, bool]]) -> Dict[str, Any]:
    """按分箱计算 ECE 与各箱明细。"""
    n = len(points)
    rows = []
    ece = 0.0
    for lo, hi in ECE_BINS:
        confs = [c for c, _ in points if lo <= c < hi]
        oks = [ok for c, ok in points if lo <= c < hi]
        cnt = len(confs)
        if cnt == 0:
            rows.append({"range": f"{lo:.2f}-{hi:.2f}", "n": 0, "conf": None, "acc": None, "gap": None})
            continue
        avg_conf = sum(confs) / cnt
        acc = sum(1 for ok in oks if ok) / cnt
        gap = abs(acc - avg_conf)
        ece += (cnt / n) * gap
        rows.append(
            {
                "range": f"{lo:.2f}-{hi:.2f}",
                "n": cnt,
                "conf": round(avg_conf, 3),
                "acc": round(acc, 3),
                "gap": round(gap, 3),
            }
        )
    return {"n": n, "ece": round(ece, 4), "bins": rows}


BASE_REPLY_KEYS = {"plan", "response"}


def _auditability(dynamic_rec: Dict[str, Any], base_rec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """A 组：4 维度可解释材料的存在性对比。

    判定以**策略自身的输出契约**为准，而非 harness 的外部插桩：
    「决策过程记录」维度要求策略每轮返回值携带 {plan, response} 之外的结构化状态
    （动态分类返回 belief_history / hypothesis_space，基线只返回文本或计划）。
    否则 harness 的插桩会把基线也"补"上该维度，污染对比。
    """
    def dims(rec: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "belief_trajectory": bool(rec.get("belief_history")),
            "top_candidates": bool(_top_names(rec.get("hypothesis_space", []), 3)),
            "evidence_mapping": bool(rec.get("evidence_map")),
            "decision_records": any(
                set(d.get("reply_keys", [])) - BASE_REPLY_KEYS
                for d in rec.get("decisions", [])
            ),
        }

    d_dyn, d_base = dims(dynamic_rec), dims(base_rec)
    labels = {
        "belief_trajectory": "信念演化轨迹(belief_history)",
        "top_candidates": "候选根因集 + 置信度(Top3)",
        "evidence_mapping": "证据→假设映射(evidence_log)",
        "decision_records": "决策过程记录",
    }
    return [
        {
            "dimension": labels[k],
            "dynamic": d_dyn[k],
            "baseline": d_base[k],
        }
        for k in labels
    ]


# ══════════════════════════════════════════════════════════
# 报告渲染
# ══════════════════════════════════════════════════════════
def _write_report(payload: Dict[str, Any], path: str) -> None:
    lines: List[str] = []
    lines.append("# 可解释性实验结果")
    lines.append("")
    lines.append(
        f"- 场景数: {payload['meta']['scenarios']}   重复次数: {payload['meta']['repeats']}   "
        f"证据裁判: {payload['meta']['judge']}   生成时间: {payload['meta']['generated_at']}"
    )
    lines.append("- 场景源: `mcp_servers/mock_scenario.py::SCENARIO_SERVICES`（服务名驱动 MCP 剧本）")
    lines.append("")

    # A 组
    lines.append("## A 组 · 决策可审计性（结构性对比，非对称即结论）")
    lines.append("")
    lines.append("| 维度 | T1 动态分类 | T2 基线(DefaultReplanStrategy) |")
    lines.append("|------|-----------|-------------------------------|")
    for row in payload["A_auditability"]:
        tl = "✓" if row["dynamic"] else "✗"
        bl = "✓" if row["baseline"] else "✗"
        lines.append(f"| {row['dimension']} | {tl} | {bl} |")
    ok = sum(1 for r in payload["A_auditability"] if r["dynamic"])
    lines.append("")
    lines.append(f"**结论**：T1 具备 {ok}/4 维度，T2 具备 "
                 f"{sum(1 for r in payload['A_auditability'] if r['baseline'])}/4。")
    lines.append("")

    # 逐场景明细
    lines.append("### 逐场景明细（T1 动态分类）")
    lines.append("")
    lines.append("| 场景 | 期望根因 | Top1 | 置信度 | 步数 | Top3 | 证据条数 | 决策序列 |")
    lines.append("|------|---------|------|-------|------|------|---------|---------|")
    for r in payload["scenarios"]:
        top = _top_names(r["dynamic"].get("hypothesis_space", []), 1)
        top_name, top_prob = (top[0][0], top[0][1]) if top else ("-", 0.0)
        t3 = ", ".join(f"{n}({p:.0%})" for n, p in _top_names(r["dynamic"].get("hypothesis_space", []), 3))
        ev = sum(len(v) for v in r["dynamic"].get("evidence_map", {}).values())
        seq = "→".join(d["action"] for d in r["dynamic"].get("decisions", []))
        mark = "√" if top_name == r["expected_root"] else "✗"
        lines.append(
            f"| {r['scenario']} | {r['expected_root']} | {top_name} {mark} | {top_prob:.0%} | "
            f"{r['dynamic'].get('steps')} | {t3} | {ev} | {seq} |"
        )
    lines.append("")

    # B 组
    lines.append("## B 组 · 置信度校准（ECE）")
    lines.append("")
    for label, key in (("场景级（最终假设空间 Top1）", "scenario_level"),
                       ("步级（信念轨迹每轮 Top1）", "step_level")):
        e = payload["B_calibration"][key]
        lines.append(f"### {label} · 共 {e['n']} 点，ECE = {e['ece']}")
        lines.append("")
        lines.append("| 置信度区间 | 样本数 | 平均置信度 | 实际正确率 | 差距 |")
        lines.append("|-----------|-------|-----------|----------|-----|")
        for b in e["bins"]:
            if b["n"] == 0:
                lines.append(f"| {b['range']} | 0 | - | - | - |")
            else:
                lines.append(
                    f"| {b['range']} | {b['n']} | {b['conf']:.3f} | {b['acc']:.3f} | {b['gap']:.3f} |"
                )
        lines.append("")

    # C 组
    lines.append("## C 组 · 结果稳定性（固定种子重跑）")
    lines.append("")
    c = payload["C_stability"]
    if c["repeats"] <= 1:
        lines.append("_未启用（加 `--repeats N` 且 N≥2 才计算一致性）_")
    else:
        lines.append(f"- 重复次数: {c['repeats']}   结论一致率: {c['consistent']}/{c['total']} "
                     f"({c['rate']:.0%})")
        if c.get("steps_mean") is not None:
            lines.append(f"- 收敛步数: 均值 {c['steps_mean']:.2f}，范围 [{c['steps_min']}, {c['steps_max']}]")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("_判定口径：T1 用最终 `hypothesis_space` 的 Top1 名称与期望根因比对；"
                 "证据裁判线路见头部标注（由 `settings.ENABLE_LLM_EVIDENCE_JUDGE` 决定，"
                 "`--deterministic` 可强制锁定为规则关键词以提升可复现性）。_")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ══════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════
# 额度护栏：预检 + 运行中检测到"免费额度耗尽"立即中止
#   （2026-09-27 事故：实验跑到一半额度耗尽，后续场景静默降级成无证据的
#     平坦先验，报告却照常生成 —— 必须主动失败而非产出无效数据）
# ══════════════════════════════════════════════════════════
_QUOTA = {"exhausted": False}


class _QuotaWatch(logging.Handler):
    """监听日志，捕获 DashScope 免费额度耗尽(403 FreeTierOnly)。"""

    def emit(self, record):  # noqa: D102
        try:
            msg = record.getMessage()
        except Exception:
            return
        if "Free quota exhausted" in msg or "AllocationQuota.FreeTierOnly" in msg:
            _QUOTA["exhausted"] = True


def _install_quota_watch() -> None:
    logging.getLogger().addHandler(_QuotaWatch())


def _ensure_quota_or_abort() -> bool:
    """预检免费额度；不可用时打印原因并返回 False（不产生付费调用）。"""
    from langchain_openai import ChatOpenAI
    from src.settings import settings

    try:
        llm = ChatOpenAI(
            model=settings.AGENT_MODEL,
            api_key=settings.DASHSCOPE_API_KEY,
            base_url=settings.DASHSCOPE_API_BASE,
            temperature=0, timeout=30, max_retries=0,
        )
        llm.invoke("ok")
        return True
    except Exception as e:
        msg = str(e)
        print("\n" + "=" * 74)
        if "FreeTierOnly" in msg or "Free quota exhausted" in msg:
            print("[中止] 免费额度已耗尽(403 AllocationQuota.FreeTierOnly)。")
            print("       本脚本不做付费调用，已停止；请更换模型或等待额度恢复后重跑。")
        else:
            print(f"[中止] 额度预检失败: {type(e).__name__}: {msg[:300]}")
        print("=" * 74 + "\n")
        return False


def _check_quota_midrun() -> None:
    """每完成一个场景后调用：运行中额度耗尽则立即中止，避免产出无效数据。"""
    if _QUOTA["exhausted"]:
        raise SystemExit(
            "\n[中止] 运行中检测到『免费额度耗尽』(403 FreeTierOnly)。\n"
            "       继续跑只会得到无证据的平坦先验结果，已主动停止。\n"
        )


async def _run_suite(
    plan: List[Tuple[str, str, str]],
    dynamic_cls,
    base_cls,
    dry_run: bool,
) -> Dict[str, Any]:
    """跑一轮完整套件，返回逐场景记录。"""
    records: List[Dict[str, Any]] = []
    for scenario, service, expected in plan:
        symptom = SCENARIO_SYMPTOM.get(scenario, "服务出现异常")
        user_input = f"{service}：{symptom}，请定位根因并给出诊断结论"
        print(f"\n{'=' * 72}\n[场景 {scenario}] 服务={service}  期望根因={expected}")
        print(f"  输入: {user_input}")

        if dry_run:
            records.append(
                {
                    "scenario": scenario,
                    "service": service,
                    "expected_root": expected,
                    "dynamic": {},
                    "baseline": {},
                    "dry_run": True,
                }
            )
            continue

        dyn_rec: Dict[str, Any] = {}
        base_rec: Dict[str, Any] = {}
        for label, cls, sink in (("T1-dynamic", dynamic_cls, dyn_rec), ("T2-baseline", base_cls, base_rec)):
            t0 = time.monotonic()
            try:
                sink.update(await _Runner(cls()).run(user_input))
            except Exception as e:  # 单策略失败不中断整轮
                print(f"  [{label}] 运行异常: {e}")
                sink["error"] = str(e)
                continue
            top = _top_names(sink.get("hypothesis_space", []), 1)
            top_name = top[0][0] if top else "-"
            top_conf = top[0][1] if top else 0.0
            print(f"  [{label}] top='{top_name}' "
                  f"conf={top_conf:.0%} 步数={sink.get('steps')} 耗时={time.monotonic() - t0:.1f}s")
        records.append(
            {
                "scenario": scenario,
                "service": service,
                "expected_root": expected,
                "dynamic": dyn_rec,
                "baseline": base_rec,
            }
        )
        _check_quota_midrun()
    return {"scenarios": records}


def _build_payload(records: List[Dict[str, Any]], repeats: int, judge: str) -> Dict[str, Any]:
    real = [r for r in records if not r.get("dry_run")]

    # A 组：取第一个有效场景做维度存在性对比（每场景结论一致，取聚合更稳）
    a_rows: List[Dict[str, Any]] = []
    if real:
        def _agg(key: str) -> Dict[str, Any]:
            """聚合某一路在全部场景上的可解释材料（取首个非空样本 + 合并决策）。"""
            recs = [r[key] for r in real if r.get(key)]
            def _first(field: str, default: Any) -> Any:
                for r in recs:
                    if r.get(field):
                        return r[field]
                return default
            return {
                "belief_history": _first("belief_history", []),
                "hypothesis_space": _first("hypothesis_space", []),
                "evidence_map": _first("evidence_map", {}),
                "decisions": [d for r in recs for d in (r.get("decisions") or [])],
            }

        a_rows = _auditability(_agg("dynamic"), _agg("baseline"))

    # B 组
    scenario_points: List[Tuple[float, bool]] = []
    step_points: List[Tuple[float, bool]] = []
    for r in real:
        top = _top_names(r["dynamic"].get("hypothesis_space", []), 1)
        if top:
            scenario_points.append((float(top[0][1]), top[0][0] == r["expected_root"]))
        step_points.extend(_belief_points(r["dynamic"], r["expected_root"]))

    # C 组：以「场景 → Top1 名称」序列在重复轮次间比对（本轮 records 已含全部轮次）
    c = {"repeats": repeats, "consistent": 0, "total": 0, "rate": 0.0,
         "steps_mean": None, "steps_min": None, "steps_max": None}
    if repeats >= 2 and real:
        per_scenario: Dict[str, List[str]] = {}
        steps_all: List[int] = []
        for r in real:
            top = _top_names(r["dynamic"].get("hypothesis_space", []), 1)
            per_scenario.setdefault(r["scenario"], []).append(top[0][0] if top else "-")
            if r["dynamic"].get("steps"):
                steps_all.append(int(r["dynamic"]["steps"]))
        consistent = sum(1 for v in per_scenario.values() if len(set(v)) == 1)
        c.update(
            repeats=repeats,
            consistent=consistent,
            total=len(per_scenario),
            rate=(consistent / len(per_scenario)) if per_scenario else 0.0,
            steps_mean=round(statistics.mean(steps_all), 2) if steps_all else None,
            steps_min=min(steps_all) if steps_all else None,
            steps_max=max(steps_all) if steps_all else None,
        )

    return {
        "meta": {
            "scenarios": len(real),
            "repeats": repeats,
            "judge": judge,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "A_auditability": a_rows,
        "scenarios": records,
        "B_calibration": {
            "scenario_level": _ece(scenario_points),
            "step_level": _ece(step_points),
        },
        "C_stability": c,
    }


def _self_test() -> None:
    """离线自检：用合成记录验证 payload 组装与报告渲染（不连 MCP/LLM）。

    覆盖的关键分支：基线策略的**空假设空间**（A 组维度应为 0/4）、
    信念轨迹换算、ECE 分箱、判错场景的 ✗ 渲染、C 组未启用分支。
    """
    def _dyn(top_conf: float, steps: int) -> Dict[str, Any]:
        hs = [
            {"id": "h0", "name": "网络/连通性问题", "probability": top_conf},
            {"id": "h1", "name": "应用层异常", "probability": round((1 - top_conf) * 0.6, 4)},
            {"id": "h2", "name": "配置错误", "probability": round((1 - top_conf) * 0.4, 4)},
        ]
        return {
            "steps": steps,
            "hypothesis_space": hs,
            "report": "（合成报告）",
            "belief_history": [
                {"step": 1, "probabilities": {"h0": top_conf * 0.6, "h1": 0.3, "h2": 0.1}},
                {"step": 2, "probabilities": {"h0": top_conf, "h1": (1 - top_conf) * 0.6,
                                              "h2": (1 - top_conf) * 0.4}},
            ],
            "decisions": [
                {"step": 0, "action": "continue", "top_name": "网络/连通性问题",
                 "top_prob": top_conf * 0.6, "reply_keys": [], "sidebar_branches": 0},
                {"step": 1, "action": "respond", "top_name": "网络/连通性问题",
                 "top_prob": top_conf, "reply_keys": ["belief_history", "hypothesis_space", "response"],
                 "sidebar_branches": 0},
            ],
            "evidence_map": {"h0": [{"source": "search_log", "relation": "support",
                                     "strength": 0.9, "step": 1, "description": "命中 dial tcp"}]},
        }

    base = {
        "steps": 4,
        "hypothesis_space": [],          # 基线无假设空间：A 组应为 ✗
        "report": "（合成基线报告）",
        "belief_history": [],
        "decisions": [{"step": 0, "action": "respond", "reply_keys": ["response"]}],
        "evidence_map": {},
    }
    records = [
        {"scenario": "network", "service": "api-gateway-service",
         "expected_root": "网络/连通性问题", "dynamic": _dyn(0.89, 4), "baseline": dict(base)},
        {"scenario": "config", "service": "auth-service",        # 期望配置错误→Top1 网络→✗
         "expected_root": "配置错误", "dynamic": _dyn(0.55, 5), "baseline": dict(base)},
    ]
    payload = _build_payload(records, repeats=1, judge="self-test(合成数据)")
    # 自检产物使用独立文件名，避免覆盖正式实验报告 runtime/explainability_report.*
    _report = REPORT_FILE.replace(".md", "_selftest.md")
    _data = DATA_FILE.replace(".json", "_selftest.json")
    _write_report(payload, _report)
    with open(_data, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    a_dyn = sum(1 for r in payload["A_auditability"] if r["dynamic"])
    a_base = sum(1 for r in payload["A_auditability"] if r["baseline"])
    print("[self-test] 合成数据渲染通过")
    print(f"  A 组维度: T1={a_dyn}/4  T2={a_base}/4 (期望 4/4 与 0/4)")
    print(f"  B 组: 场景级 {payload['B_calibration']['scenario_level']}")
    print(f"        步级   {payload['B_calibration']['step_level']}")
    print(f"  产物(自检): {_report} / {_data}")
    assert a_dyn == 4 and a_base == 0, "A 组结构性对比不符合预期"
    assert payload["B_calibration"]["step_level"]["n"] == 4, "步级采样点数应为 2 场景 × 2 轮"
    print("  ✓ 断言全部通过")


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scenarios", type=int, default=0, help="只跑前 N 个场景(0=全部)")
    ap.add_argument("--repeats", type=int, default=1, help="C 组: 固定种子重跑次数")
    ap.add_argument("--dry-run", action="store_true", help="只起 MCP + 校验场景构造, 不跑 LLM")
    ap.add_argument("--deterministic", action="store_true", help="证据裁判压成规则关键词(提升可复现性)")
    ap.add_argument("--tag", default="", help="产物后缀(explainability_report_<tag>.*)")
    ap.add_argument("--self-test", action="store_true",
                    help="离线自检: 合成数据跑通 payload/报告渲染, 不连 MCP/LLM")
    args = ap.parse_args()

    global REPORT_FILE, DATA_FILE
    if args.tag:
        REPORT_FILE = os.path.join(RUNTIME_DIR, f"explainability_report_{args.tag}.md")
        DATA_FILE = os.path.join(RUNTIME_DIR, f"explainability_report_{args.tag}.json")

    if args.self_test:
        _self_test()
        return

    # 额度护栏：预检 + 运行中监听（dry-run 不调模型，跳过预检）
    _install_quota_watch()
    if not args.dry_run and not _ensure_quota_or_abort():
        sys.exit(2)  # 非零退出码: 让自动化/CI 能识别"因额度中止", 而非误判为成功

    plan: List[Tuple[str, str, str]] = [
        (scen, svc, SCENARIO_EXPECTED_ROOT.get(scen, "")) for scen, svc in SCENARIO_SERVICES.items()
    ]
    if args.scenarios:
        plan = plan[: args.scenarios]

    dynamic_cls = _make_instrumented_dynamic(force_rule_judge=args.deterministic)
    base_cls = _make_instrumented_base()

    all_records: List[Dict[str, Any]] = []
    procs = _start_servers()
    try:
        _wait_for_ports([port for _, port in MCP_SERVERS], procs)
        print("[就绪] MCP 服务全部在线")
        for i in range(max(1, args.repeats)):
            if args.repeats > 1:
                print(f"\n########## 第 {i + 1}/{args.repeats} 轮 ##########")
            res = await _run_suite(plan, dynamic_cls, base_cls, args.dry_run)
            all_records.extend(res["scenarios"])
    finally:
        print("\n[清理] 关闭 MCP 服务...")
        _stop_servers(procs)

    from src.settings import settings as _settings

    if args.deterministic:
        judge = "规则关键词(--deterministic,强制注入 EvidenceJudge(llm=None))"
    elif _settings.ENABLE_LLM_EVIDENCE_JUDGE:
        judge = "LLM 语义(settings.ENABLE_LLM_EVIDENCE_JUDGE=True)"
    else:
        judge = "规则关键词(settings.ENABLE_LLM_EVIDENCE_JUDGE=False)"
    payload = _build_payload(all_records, args.repeats, judge)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    if args.dry_run:
        print(f"\n[dry-run] 场景构造校验完成，未跑 LLM。数据已写入 {DATA_FILE}")
        return
    _write_report(payload, REPORT_FILE)
    print(f"\n[完成] 报告已写入 {REPORT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
