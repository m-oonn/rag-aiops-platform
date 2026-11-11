"""鲁棒性实验 harness：D 组(输入扰动) / E 组(模型降级) / F 组(工具故障) / G 组(复杂度梯度) + S(稳定性)。

重建说明
--------
原始采集脚本 ``scripts/verify_scenarios.py`` 属**论文侧**且从未随本仓库入库（原说明见已移除的
``docs/architecture.md`` 附录「脚本交付说明」）。本脚本按 ``docs/history/修复工作总结报告.md``
§3.1 的口径**重新实现**，口径对齐如下目标值：

======  ======================================  ==========================
组别     内容                                     原文档目标
======  ======================================  ==========================
D       输入扰动（同义改写，服务名不变）           8/8 结论一致
E       模型降级（规则裁判 vs LLM 语义裁判）        15/15 逐场景一致
F       工具故障（停 monitor / 停 cls）            停 monitor 8/8、停 cls 7/8
G       复杂度梯度（难度 0→2：干扰+否定+级联）      15/15/15 全命中
S       结果稳定性（同输入重跑 N 次）              8/8 一致率 100%
======  ======================================  ==========================

注意事项
--------
* 本脚本与 ``run_explainability.py`` **共用 MCP 端口(8103/8104/8105)**，两者不可并发运行。
* F 组依赖 ``runtime/log_cache/``（cls_server 正常运行时落盘的日志本地副本）作为停服降级源，
  因此 **F 组前应先完整跑过一轮正常实验**以预热缓存。
* 成本：证据裁判线路默认跟随 ``settings.ENABLE_LLM_EVIDENCE_JUDGE``；E 组的 LLM 线会
  显式注入 ``EvidenceJudge(llm=...)``（用 ``EVIDENCE_LLM_MODEL``，本项目配置为免费档）。

用法::

    python scripts/run_robustness.py --groups F          # 只跑 F 组
    python scripts/run_robustness.py --groups D,E,F,G,S  # 指定多组
    python scripts/run_robustness.py --self-test         # 离线自检，不连 MCP/LLM
    python scripts/run_robustness.py --dry-run           # 只起/停服务与构造输入，不跑 LLM
    python scripts/run_robustness.py                     # 全部组
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

# ── 复用可解释性 harness 的环境准备(load_dotenv / sys.path / ENABLE_HITL 等) ──
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
import run_explainability as ex  # noqa: E402

from run_full_pipeline import (  # noqa: E402
    MCP_SERVERS,
    PROJECT_ROOT,
    PYTHON_EXE,
    _stop_servers,
    _wait_for_ports,
)
from mcp_servers.mock_scenario import SCENARIO_SERVICES  # noqa: E402

RUNTIME_DIR = ex.RUNTIME_DIR
REPORT_FILE = os.path.join(RUNTIME_DIR, "robustness_report.md")
DATA_FILE = os.path.join(RUNTIME_DIR, "robustness_report.json")


def _server_name(script: str) -> str:
    return os.path.basename(script).replace("_server.py", "")


ALL_GROUPS = ["D", "E", "F", "G", "S"]


# ══════════════════════════════════════════════════════════
# D 组 · 输入扰动：同义改写（服务名不变 → 命中同一 mock 剧本）
# ══════════════════════════════════════════════════════════
PERTURBED_SYMPTOM: Dict[str, str] = {
    "infra_cpu": "接口响应迟缓，资源开销疑似偏高",
    "network": "请求大量超时、连接时断时续、调用失败",
    "config": "配置变更之后服务开始表现异常",
    "app_oom": "服务反复报错，个别接口偶尔不可用",
    "dependency": "所依赖的下游能力异常，本服务被牵连",
    "complex_overload": "请求偶尔超时并伴有应用报错，CPU 偏高",
    "cascade_dependency": "服务大面积 503，下游缓存与三方接口均异常",
    "container": "实例屡次重启，疑似被容器清理",
    "service_api": "部分接口变慢且时而失败，可用性下滑",
}

# ══════════════════════════════════════════════════════════
# G 组 · 复杂度梯度
#   难度 0 = 原始症状
#   难度 1 = 原始症状 + 干扰项(来自其它根因的次生描述)
#   难度 2 = 原始症状 + 干扰项 + 否定项 + 级联描述
# ══════════════════════════════════════════════════════════
DISTRACTOR: Dict[str, str] = {
    "infra_cpu": "同时有用户反馈登录偶发失败",
    "network": "同时监控大盘显示磁盘使用率偏高",
    "config": "同时有零星请求超时反馈",
    "app_oom": "同时有调用方反馈网络抖动",
    "dependency": "同时 CPU 使用率出现短时尖峰",
    "complex_overload": "同时有下游服务反馈连接被重置",
    "cascade_dependency": "同时配置中心有无变更提示",
    "container": "同时有用户反馈接口返回较慢",
    "service_api": "同时监控显示内存占用偏高",
}
NEGATION: Dict[str, str] = {
    "infra_cpu": "但 CPU 与内存用量并不高",
    "network": "但服务自身的 CPU / 内存均正常",
    "config": "但近期并无任何配置发布记录",
    "app_oom": "但堆内存与线程数均未见异常",
    "dependency": "但下游服务自报健康检查全部通过",
    "complex_overload": "但资源用量并不算高",
    "cascade_dependency": "但本地服务指标一切正常",
    "container": "但节点资源充足、未见调度压力",
    "service_api": "但后端资源指标保持平稳",
}
CASCADE = "并且已出现跨服务调用失败的级联现象"


def build_input(scenario: str, service: str, difficulty: int = 0, perturbed: bool = False) -> str:
    """按难度/是否扰动构造诊断输入（服务名始终保留，确保命中同一剧本）。"""
    if perturbed:
        symptom = PERTURBED_SYMPTOM.get(scenario, ex.SCENARIO_SYMPTOM.get(scenario, "服务出现异常"))
        return f"{service}：{symptom}，请定位根因并给出诊断结论"
    if difficulty <= 0:
        symptom = ex.SCENARIO_SYMPTOM.get(scenario, "服务出现异常")
    elif difficulty == 1:
        symptom = f"{ex.SCENARIO_SYMPTOM.get(scenario, '服务出现异常')}；{DISTRACTOR.get(scenario, '')}"
    else:
        symptom = (
            f"{ex.SCENARIO_SYMPTOM.get(scenario, '服务出现异常')}；{DISTRACTOR.get(scenario, '')}，"
            f"{NEGATION.get(scenario, '')}，{CASCADE}"
        )
    return f"{service}：{symptom}，请定位根因并给出诊断结论"


# ══════════════════════════════════════════════════════════
# MCP 服务子集启动（F 组需要"停某个服务"）
# ══════════════════════════════════════════════════════════
def _start_subset(include: set[str]) -> List[subprocess.Popen]:
    """只启动 include 中的 MCP 服务（其余视为"停服"，不启动进程）。"""
    procs: List[subprocess.Popen] = []
    for script, port in MCP_SERVERS:
        name = _server_name(script)
        if name not in include:
            print(f"[停服] {name} 不启动（模拟该服务不可达）")
            continue
        cmd = [PYTHON_EXE, os.path.join(PROJECT_ROOT, script)]
        print(f"[启动] {script} -> 127.0.0.1:{port}")
        os.makedirs(os.path.join(PROJECT_ROOT, "logs"), exist_ok=True)
        log_path = os.path.join(PROJECT_ROOT, "logs", f"{os.path.basename(script)}.robust.log")
        proc = subprocess.Popen(
            cmd,
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=open(log_path, "w", encoding="utf-8"),
        )
        proc._log_path = log_path  # type: ignore[attr-defined]
        procs.append(proc)
    return procs


def _ready_ports(include: set[str]) -> List[int]:
    return [port for script, port in MCP_SERVERS if _server_name(script) in include]


# ══════════════════════════════════════════════════════════
# 策略构造（可注入显式 judge，用于 E 组"模型降级"对比）
# ══════════════════════════════════════════════════════════
def _rule_judge():
    from src.agent.aiops.core.evidence_judge import EvidenceJudge

    return EvidenceJudge(llm=None)


def _llm_judge():
    """构造 LLM 语义裁判（使用 EVIDENCE_LLM_MODEL）。失败则返回 None。"""
    from src.agent.aiops.core.evidence_judge import EvidenceJudge
    from src.agent.aiops_llm import create_agent_llm
    from src.settings import settings

    llm = create_agent_llm(model=settings.EVIDENCE_LLM_MODEL, temperature=0)
    return EvidenceJudge(llm=llm)


def _strategy_cls(judge=None):
    """返回一个可实例化的动态分类策略子类（judge 非 None 时显式注入）。"""
    from src.agent.aiops.strategies.dynamic_classification import DynamicClassificationStrategy

    class _S(DynamicClassificationStrategy):
        def __init__(self, *a, **k):
            if judge is not None:
                k.setdefault("judge", judge)
            super().__init__(*a, **k)

    return _S


async def _run_one(user_input: str, judge=None) -> Dict[str, Any]:
    """跑一次诊断，返回 Top1/置信度/步数/是否命中。"""
    strategy = _strategy_cls(judge)
    rec = await ex._Runner(strategy()).run(user_input)
    top = ex._top_names(rec.get("hypothesis_space", []), 1)
    top_name = top[0][0] if top else "-"
    top_conf = round(top[0][1], 4) if top else 0.0
    return {
        "top_name": top_name,
        "top_conf": top_conf,
        "steps": rec.get("steps", 0),
        "hypothesis_space": rec.get("hypothesis_space", []),
    }


def _hit(top_name: str, expected: str) -> bool:
    return bool(expected) and top_name == expected


# ══════════════════════════════════════════════════════════
# 额度护栏：预检 + 运行中检测到"免费额度耗尽"立即中止
#   （2026-09-27 事故：全量实验跑到一半额度耗尽，后续场景静默降级成
#     无证据的平坦先验，报告却照常生成 —— 必须主动失败而非产出无效数据）
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
            print("       本脚本不做付费调用，已停止；请等待额度恢复或更换模型后重跑。")
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
            "       已产出的部分数据仍写入 JSON，但请勿直接采信，需按日志中首个 403 时间点截断。\n"
        )


# ══════════════════════════════════════════════════════════
# 各实验组
# ══════════════════════════════════════════════════════════
def _plan(limit: int) -> List[Tuple[str, str, str]]:
    plan = [(s, svc, ex.SCENARIO_EXPECTED_ROOT.get(s, "")) for s, svc in SCENARIO_SERVICES.items()]
    return plan[:limit] if limit else plan


async def exp_D(plan, dry_run: bool) -> Dict[str, Any]:
    """D 组：同义改写 → 结论是否与原始输入一致。"""
    rows = []
    for scenario, service, expected in plan:
        base_in = build_input(scenario, service)
        pert_in = build_input(scenario, service, perturbed=True)
        print(f"\n[D组 {scenario}] 服务={service} 期望={expected}")
        print(f"  原始: {base_in}")
        print(f"  扰动: {pert_in}")
        if dry_run:
            rows.append({"scenario": scenario, "expected": expected, "dry_run": True})
            continue
        a = await _run_one(base_in)
        b = await _run_one(pert_in)
        consistent = (a["top_name"] == b["top_name"])
        print(f"  原始 Top1={a['top_name']}({a['top_conf']:.0%})  扰动 Top1={b['top_name']}({b['top_conf']:.0%})"
              f"  一致={'是' if consistent else '否'}")
        rows.append({
            "scenario": scenario, "expected": expected,
            "base_top": a["top_name"], "base_conf": a["top_conf"], "base_steps": a["steps"],
            "perturbed_top": b["top_name"], "perturbed_conf": b["top_conf"], "perturbed_steps": b["steps"],
            "consistent": consistent,
        })
        _check_quota_midrun()
    return {"group": "D", "title": "输入扰动（同义改写）", "rows": rows}


async def exp_E(plan, dry_run: bool) -> Dict[str, Any]:
    """E 组：规则裁判 vs LLM 语义裁判 → 逐场景结论是否一致。"""
    rows = []
    llm_judge = None if dry_run else _llm_judge()
    for scenario, service, expected in plan:
        user_input = build_input(scenario, service)
        print(f"\n[E组 {scenario}] 服务={service} 期望={expected}")
        if dry_run:
            rows.append({"scenario": scenario, "expected": expected, "dry_run": True})
            continue
        a = await _run_one(user_input, judge=_rule_judge())
        b = await _run_one(user_input, judge=llm_judge)
        consistent = (a["top_name"] == b["top_name"])
        print(f"  规则 Top1={a['top_name']}({a['top_conf']:.0%})  LLM Top1={b['top_name']}({b['top_conf']:.0%})"
              f"  一致={'是' if consistent else '否'}")
        rows.append({
            "scenario": scenario, "expected": expected,
            "rule_top": a["top_name"], "rule_conf": a["top_conf"],
            "llm_top": b["top_name"], "llm_conf": b["top_conf"],
            "consistent": consistent,
        })
        _check_quota_midrun()
    return {"group": "E", "title": "模型降级（规则裁判 vs LLM 语义裁判）", "rows": rows}


async def _exp_F_variant(plan, disabled: Optional[str], dry_run: bool) -> Dict[str, Any]:
    """F 组单个变体：disabled=None 为基线(全服务)，否则停掉该服务后测命中率。"""
    include = {_server_name(s) for s, _ in MCP_SERVERS} - ({disabled} if disabled else set())
    label = f"停 {disabled}" if disabled else "基线(全服务)"
    print(f"\n{'#' * 72}\n# F 组变体：{label}  启动={sorted(include)}\n{'#' * 72}")
    procs = _start_subset(include)
    rows = []
    try:
        _wait_for_ports(_ready_ports(include), procs, max_wait=60)
        print("[就绪] MCP 服务就绪（已按需停服）")
        for scenario, service, expected in plan:
            user_input = build_input(scenario, service)
            if dry_run:
                rows.append({"scenario": scenario, "expected": expected, "dry_run": True})
                continue
            t0 = time.monotonic()
            try:
                r = await _run_one(user_input)
            except Exception as e:  # 单场景失败不中断
                print(f"  [{scenario}] 运行异常: {e}")
                rows.append({"scenario": scenario, "expected": expected, "error": str(e), "hit": False})
                continue
            ok = _hit(r["top_name"], expected)
            print(f"  [{scenario}] Top1={r['top_name']}({r['top_conf']:.0%}) 期望={expected} "
                  f"命中={'是' if ok else '否'} 步数={r['steps']} 耗时={time.monotonic() - t0:.1f}s")
            rows.append({
                "scenario": scenario, "expected": expected, "top_name": r["top_name"],
                "top_conf": r["top_conf"], "steps": r["steps"], "hit": ok,
            })
            _check_quota_midrun()
    finally:
        print(f"[清理] 关闭「{label}」变体服务...")
        _stop_servers(procs)
    return {"label": label, "disabled": disabled, "rows": rows}


async def exp_F(plan, dry_run: bool) -> Dict[str, Any]:
    """F 组：基线 / 停 monitor / 停 cls 三变体对比命中率。"""
    baseline = await _exp_F_variant(plan, None, dry_run)
    monitor = await _exp_F_variant(plan, "monitor", dry_run)
    cls = await _exp_F_variant(plan, "cls", dry_run)
    return {"group": "F", "title": "工具故障（MCP 按 server 容错 + 本地日志降级）",
            "variants": {"baseline": baseline, "monitor_off": monitor, "cls_off": cls}}


async def exp_G(plan, dry_run: bool) -> Dict[str, Any]:
    """G 组：复杂度梯度 0/1/2 → 各难度命中率与步数。"""
    rows: List[Dict[str, Any]] = []
    for scenario, service, expected in plan:
        print(f"\n[G组 {scenario}] 服务={service} 期望={expected}")
        entry: Dict[str, Any] = {"scenario": scenario, "expected": expected, "levels": {}}
        for diff in (0, 1, 2):
            user_input = build_input(scenario, service, difficulty=diff)
            if dry_run:
                entry["levels"][diff] = {"dry_run": True}
                continue
            r = await _run_one(user_input)
            ok = _hit(r["top_name"], expected)
            print(f"  难度{diff}: Top1={r['top_name']}({r['top_conf']:.0%}) "
                  f"命中={'是' if ok else '否'} 步数={r['steps']}")
            entry["levels"][diff] = {
                "top_name": r["top_name"], "top_conf": r["top_conf"],
                "steps": r["steps"], "hit": ok,
            }
        rows.append(entry)
        _check_quota_midrun()
    return {"group": "G", "title": "复杂度梯度（0→2 干扰+否定+级联）", "rows": rows}


async def exp_S(plan, dry_run: bool, repeats: int) -> Dict[str, Any]:
    """S：同输入重跑 repeats 次 → Top1 一致率。"""
    rows = []
    for scenario, service, expected in plan:
        user_input = build_input(scenario, service)
        print(f"\n[S组 {scenario}] 服务={service} 期望={expected} 重复={repeats}")
        tops: List[str] = []
        if not dry_run:
            for i in range(max(2, repeats)):
                r = await _run_one(user_input)
                tops.append(r["top_name"])
                print(f"  第{i + 1}次: Top1={r['top_name']}({r['top_conf']:.0%}) 步数={r['steps']}")
        consistent = (len(set(tops)) == 1) if tops else None
        rows.append({
            "scenario": scenario, "expected": expected, "tops": tops,
            "consistent": consistent,
        })
        _check_quota_midrun()
    return {"group": "S", "title": "结果稳定性（同输入重跑）", "rows": rows, "repeats": max(2, repeats)}


# ══════════════════════════════════════════════════════════
# 汇总与报告
# ══════════════════════════════════════════════════════════
def _summarize(results: Dict[str, Any]) -> Dict[str, Any]:
    s: Dict[str, Any] = {}
    if "D" in results:
        rows = results["D"]["rows"]
        ok = sum(1 for r in rows if r.get("consistent"))
        s["D"] = {"consistent": ok, "total": len(rows)}
    if "E" in results:
        rows = results["E"]["rows"]
        ok = sum(1 for r in rows if r.get("consistent"))
        s["E"] = {"consistent": ok, "total": len(rows)}
    if "F" in results:
        v = results["F"]["variants"]
        for key, label in (("baseline", "baseline"), ("monitor_off", "monitor"), ("cls_off", "cls")):
            rows = v[key]["rows"]
            ok = sum(1 for r in rows if r.get("hit"))
            s[f"F_{label}"] = {"hit": ok, "total": len(rows)}
    if "G" in results:
        per = {}
        for diff in (0, 1, 2):
            hit = tot = 0
            steps = []
            for r in results["G"]["rows"]:
                lv = r["levels"].get(diff) or {}
                if "hit" in lv:
                    tot += 1
                    hit += 1 if lv["hit"] else 0
                    if lv.get("steps"):
                        steps.append(lv["steps"])
            per[diff] = {
                "hit": hit, "total": tot,
                "avg_steps": round(sum(steps) / len(steps), 2) if steps else None,
            }
        s["G"] = per
    if "S" in results:
        rows = results["S"]["rows"]
        tot = len([r for r in rows if r.get("tops")])
        ok = sum(1 for r in rows if r.get("consistent"))
        s["S"] = {"consistent": ok, "total": tot, "repeats": results["S"].get("repeats")}
    return s


def _write_report(payload: Dict[str, Any], path: str) -> None:
    s = payload["summary"]
    judge = payload["meta"]["judge"]
    lines: List[str] = []
    lines.append("# 鲁棒性实验结果")
    lines.append("")
    lines.append(f"- 场景数: {payload['meta']['scene_count']}   证据裁判(默认线): {judge}   "
                 f"生成时间: {payload['meta']['generated_at']}")
    lines.append("- 重建说明: 原采集脚本 `scripts/verify_scenarios.py` 属论文侧、未随仓库交付；"
                 "本报告由 `scripts/run_robustness.py` 按 `docs/history/修复工作总结报告.md` §3.1 口径重新采集。")
    lines.append("")
    lines.append("## 汇总")
    lines.append("")
    lines.append("| 组别 | 指标 | 目标(原文档) | 本次实测 |")
    lines.append("|------|------|-------------|---------|")
    if "D" in s:
        lines.append(f"| D · 输入扰动 | 结论一致数 | 8/8 | **{s['D']['consistent']}/{s['D']['total']}** |")
    if "E" in s:
        lines.append(f"| E · 模型降级 | 逐场景一致数 | 15/15 | **{s['E']['consistent']}/{s['E']['total']}** |")
    if "F_baseline" in s:
        lines.append(f"| F · 基线(全服务) | 命中数 | — | **{s['F_baseline']['hit']}/{s['F_baseline']['total']}** |")
    if "F_monitor" in s:
        lines.append(f"| F · 停 monitor | 命中数 | 8/8 | **{s['F_monitor']['hit']}/{s['F_monitor']['total']}** |")
    if "F_cls" in s:
        lines.append(f"| F · 停 cls | 命中数 | 7/8 | **{s['F_cls']['hit']}/{s['F_cls']['total']}** |")
    if "G" in s:
        g = s["G"]
        cells = " / ".join(f"{g[d]['hit']}/{g[d]['total']}" for d in (0, 1, 2))
        steps = " → ".join(str(g[d]["avg_steps"]) for d in (0, 1, 2))
        lines.append(f"| G · 复杂度梯度 | 难度0/1/2 命中数 | 15/15/15 | **{cells}** |")
        lines.append(f"| G · 步数均值 | 难度0/1/2 | 4.0 → 4.33 | {steps} |")
    if "S" in s:
        lines.append(f"| S · 结果稳定性 | 一致数(重跑 {s['S'].get('repeats')} 次) | 8/8 | "
                     f"**{s['S']['consistent']}/{s['S']['total']}** |")
    lines.append("")
    # 明细
    if "D" in payload["results"]:
        lines.append("## D 组明细 · 输入扰动（同义改写）")
        lines.append("")
        lines.append("| 场景 | 原始 Top1 | 扰动 Top1 | 一致 |")
        lines.append("|------|----------|----------|------|")
        for r in payload["results"]["D"]["rows"]:
            lines.append(f"| {r['scenario']} | {r.get('base_top', '-')} | {r.get('perturbed_top', '-')} "
                         f"| {'✓' if r.get('consistent') else '✗'} |")
        lines.append("")
    if "E" in payload["results"]:
        lines.append("## E 组明细 · 模型降级（规则 vs LLM 语义裁判）")
        lines.append("")
        lines.append("| 场景 | 规则 Top1 | LLM Top1 | 一致 |")
        lines.append("|------|----------|---------|------|")
        for r in payload["results"]["E"]["rows"]:
            lines.append(f"| {r['scenario']} | {r.get('rule_top', '-')} | {r.get('llm_top', '-')} "
                         f"| {'✓' if r.get('consistent') else '✗'} |")
        lines.append("")
    if "F" in payload["results"]:
        lines.append("## F 组明细 · 工具故障")
        lines.append("")
        for key, title in (("baseline", "基线(全服务)"), ("monitor_off", "停 monitor"), ("cls_off", "停 cls")):
            lines.append(f"### {title}")
            lines.append("")
            lines.append("| 场景 | 期望根因 | Top1 | 置信度 | 步数 | 命中 |")
            lines.append("|------|---------|------|-------|------|------|")
            for r in payload["results"]["F"]["variants"][key]["rows"]:
                lines.append(f"| {r['scenario']} | {r.get('expected', '-')} | {r.get('top_name', '-')} "
                             f"| {r.get('top_conf', '-')} | {r.get('steps', '-')} | "
                             f"{'✓' if r.get('hit') else '✗'} |")
            lines.append("")
    if "G" in payload["results"]:
        lines.append("## G 组明细 · 复杂度梯度")
        lines.append("")
        lines.append("| 场景 | 难度0 | 难度1 | 难度2 |")
        lines.append("|------|-------|-------|-------|")
        for r in payload["results"]["G"]["rows"]:
            cells = []
            for d in (0, 1, 2):
                lv = r["levels"].get(d) or {}
                mark = "✓" if lv.get("hit") else ("✗" if "hit" in lv else "-")
                cells.append(f"{lv.get('top_name', '-')} {mark}")
            lines.append(f"| {r['scenario']} | " + " | ".join(cells) + " |")
        lines.append("")
    if "S" in payload["results"]:
        lines.append("## S 组明细 · 结果稳定性")
        lines.append("")
        lines.append("| 场景 | 期望根因 | Top1 序列 | 一致 |")
        lines.append("|------|---------|----------|------|")
        for r in payload["results"]["S"]["rows"]:
            lines.append(f"| {r['scenario']} | {r.get('expected', '-')} | "
                         f"{', '.join(r.get('tops') or []) or '-'} | "
                         f"{'✓' if r.get('consistent') else '✗'} |")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("_说明：命中口径 = 最终 `hypothesis_space` 的 Top1 名称与场景期望根因相等；"
                 "F 组依赖 `runtime/log_cache/` 本地日志副本作为停 cls 的降级源。_")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _self_test() -> None:
    """离线自检：输入构造 + 汇总/渲染，不连 MCP/LLM。"""
    plan = _plan(0)
    assert len(plan) == len(SCENARIO_SERVICES), "场景数不匹配"
    # 输入构造
    for scenario, service, expected in plan:
        i0 = build_input(scenario, service, 0)
        i1 = build_input(scenario, service, 1)
        i2 = build_input(scenario, service, 2)
        ip = build_input(scenario, service, perturbed=True)
        for s, txt in (("0", i0), ("1", i1), ("2", i2), ("P", ip)):
            assert service in txt, f"{scenario} 难度{s} 输入丢失服务名"
        assert len({i0, i1, i2, ip}) == 4, f"{scenario} 四种输入应互不相同"
        assert i0 != ip, "扰动输入应与原始输入不同"
    # 汇总/渲染
    fake = {
        "D": {"group": "D", "title": "输入扰动", "rows": [
            {"scenario": "s1", "expected": "A", "base_top": "A", "perturbed_top": "A", "consistent": True},
            {"scenario": "s2", "expected": "B", "base_top": "B", "perturbed_top": "C", "consistent": False},
        ]},
        "E": {"group": "E", "title": "模型降级", "rows": [
            {"scenario": "s1", "expected": "A", "rule_top": "A", "llm_top": "A", "consistent": True},
            {"scenario": "s2", "expected": "B", "rule_top": "B", "llm_top": "B", "consistent": True},
        ]},
        "F": {"group": "F", "title": "工具故障", "variants": {
            "baseline": {"label": "基线(全服务)", "disabled": None, "rows": [
                {"scenario": "s1", "expected": "A", "top_name": "A", "top_conf": 0.9, "steps": 4, "hit": True},
                {"scenario": "s2", "expected": "B", "top_name": "C", "top_conf": 0.5, "steps": 5, "hit": False},
            ]},
            "monitor_off": {"label": "停 monitor", "disabled": "monitor", "rows": [
                {"scenario": "s1", "expected": "A", "top_name": "A", "top_conf": 0.9, "steps": 4, "hit": True},
                {"scenario": "s2", "expected": "B", "top_name": "B", "top_conf": 0.8, "steps": 4, "hit": True},
            ]},
            "cls_off": {"disabled": "cls", "rows": [
                {"scenario": "s1", "expected": "A", "top_name": "A", "top_conf": 0.9, "steps": 4, "hit": True},
                {"scenario": "s2", "expected": "B", "top_name": "C", "top_conf": 0.5, "steps": 5, "hit": False},
            ]},
        }},
        "G": {"group": "G", "title": "复杂度梯度", "rows": [
            {"scenario": "s1", "expected": "A", "levels": {
                0: {"top_name": "A", "top_conf": 0.9, "steps": 4, "hit": True},
                1: {"top_name": "A", "top_conf": 0.9, "steps": 4, "hit": True},
                2: {"top_name": "C", "top_conf": 0.6, "steps": 5, "hit": False},
            }},
        ]},
        "S": {"group": "S", "title": "结果稳定性", "repeats": 2, "rows": [
            {"scenario": "s1", "expected": "A", "tops": ["A", "A"], "consistent": True},
        ]},
    }
    summary = _summarize(fake)
    assert summary["D"] == {"consistent": 1, "total": 2}
    assert summary["F_monitor"]["hit"] == 2 and summary["F_cls"]["hit"] == 1
    assert summary["F_baseline"] == {"hit": 1, "total": 2}
    assert summary["G"][0]["hit"] == 1 and summary["G"][2]["hit"] == 0
    payload = {
        "meta": {"scene_count": len(plan), "judge": "self-test", "generated_at": "self-test"},
        "results": fake, "summary": summary,
    }
    _report = REPORT_FILE.replace(".md", "_selftest.md")
    _write_report(payload, _report)
    print("[self-test] 输入构造 / 汇总 / 报告渲染 全部通过")
    print(f"  产物(自检): {_report}")


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--groups", default="D,E,F,G,S", help="要跑的组(逗号分隔): D,E,F,G,S")
    ap.add_argument("--scenarios", type=int, default=0, help="只跑前 N 个场景(0=全部)")
    ap.add_argument("--repeats", type=int, default=3, help="S 组重跑次数(默认 3)")
    ap.add_argument("--dry-run", action="store_true", help="只起/停服务与构造输入，不跑 LLM")
    ap.add_argument("--self-test", action="store_true", help="离线自检，不连 MCP/LLM")
    args = ap.parse_args()

    if args.self_test:
        _self_test()
        return

    groups = [g.strip().upper() for g in args.groups.split(",") if g.strip()]
    for g in groups:
        if g not in ALL_GROUPS:
            raise SystemExit(f"未知组: {g}（可选 {ALL_GROUPS}）")

    # 额度护栏：预检 + 运行中监听（dry-run 不调模型，跳过预检）
    _install_quota_watch()
    if not args.dry_run and not _ensure_quota_or_abort():
        sys.exit(2)  # 非零退出码: 让自动化/CI 能识别"因额度中止", 而非误判为成功

    plan = _plan(args.scenarios)
    results: Dict[str, Any] = {}
    t_start = time.monotonic()

    # D/E/G/S 使用全量服务；F 组自行管理子集服务
    full_include = {_server_name(s) for s, _ in MCP_SERVERS}
    needs_full = any(g in groups for g in ("D", "E", "G", "S"))

    if needs_full:
        procs = _start_subset(full_include)
        try:
            _wait_for_ports(_ready_ports(full_include), procs, max_wait=60)
            print("[就绪] MCP 服务全部在线")
            if "D" in groups:
                results["D"] = await exp_D(plan, args.dry_run)
            if "E" in groups:
                results["E"] = await exp_E(plan, args.dry_run)
            if "G" in groups:
                results["G"] = await exp_G(plan, args.dry_run)
            if "S" in groups:
                results["S"] = await exp_S(plan, args.dry_run, args.repeats)
        finally:
            print("\n[清理] 关闭 MCP 服务...")
            _stop_servers(procs)

    if "F" in groups:
        results["F"] = await exp_F(plan, args.dry_run)

    from src.settings import settings as _settings

    judge = ("LLM 语义(settings.ENABLE_LLM_EVIDENCE_JUDGE=True)"
             if _settings.ENABLE_LLM_EVIDENCE_JUDGE
             else "规则关键词(settings.ENABLE_LLM_EVIDENCE_JUDGE=False)")

    payload = {
        "meta": {
            "scene_count": len(plan),
            "judge": judge,
            "groups": groups,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_sec": round(time.monotonic() - t_start, 1),
        },
        "results": results,
        "summary": _summarize(results),
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    if args.dry_run:
        print(f"\n[dry-run] 未跑 LLM；数据结构已写入 {DATA_FILE}")
        return
    _write_report(payload, REPORT_FILE)
    print(f"\n[完成] 报告已写入 {REPORT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
