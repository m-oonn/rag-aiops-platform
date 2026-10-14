"""B2a/B2b 优化 A/B 实验（pi 思路借鉴的量化验证）。

对照设计（同场景、同模型、固定种子；对齐 run_ablation_eval.py 的跑分口径）：
  baseline  两开关关（旧行为）—— ENABLE_CONTEXT_COMPACTION=False, ENABLE_SKILL_ROUTING=False
  pi_opt    两开关开 —— 上下文压缩（B2a） + 技能路由（B2b）

度量（诊断事件流 + 全局 token 计量器）：
  命中率（top 假设 name == ground_truth）、收敛步数、耗时、LLM 调用数、
  input/output/total tokens、折算费用。

用法：
  python scripts/run_pi_opt_ab_eval.py --dry-run          # 只起服务、写场景、自检链路
  python scripts/run_pi_opt_ab_eval.py --once 1           # 只跑第 1 个场景（快速验证）
  python scripts/run_pi_opt_ab_eval.py --scenarios 6      # 前 6 场景 × 2 配置
  python scripts/run_pi_opt_ab_eval.py --tag v2           # 结果文件加后缀（多轮隔离）

产物（均落盘 runtime/）：
  pi_opt_ab_results.json   逐场景逐配置的原始结果（增量续跑，已完成跳过）
  pi_opt_ab_report.md      汇总指标表 + pi_opt 相对 baseline 的净影响
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

# ── 环境必须在本模块 import 任何 src.* 之前设置 ──────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
# 本实验测动态分类链路（技能路由挂在其 planner/executor 上），强制开启；HITL 会挂起，强制关。
os.environ.setdefault("ENABLE_DYNAMIC_CLASSIFICATION", "true")
os.environ["ENABLE_HITL"] = "false"

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "src")):
    parent = os.path.dirname(PROJECT_ROOT)
    if parent == PROJECT_ROOT:
        break
    PROJECT_ROOT = parent
sys.path.insert(0, PROJECT_ROOT)

RUNTIME_DIR = os.path.join(PROJECT_ROOT, "runtime")
os.makedirs(RUNTIME_DIR, exist_ok=True)
SCENARIO_FILE = os.path.join(RUNTIME_DIR, "ablation_scenario.json")
RESULTS_FILE = os.path.join(RUNTIME_DIR, "pi_opt_ab_results.json")
REPORT_FILE = os.path.join(RUNTIME_DIR, "pi_opt_ab_report.md")

from run_full_pipeline import MCP_SERVERS, _port_ready, _stop_servers, _wait_for_ports
from scripts.blind_fault_gen import (ROOT_CAUSE_NAMES, SERVICE_ID, USER_REPORT,
                                     assert_no_verbatim_answer, gen_scenario,
                                     write_scenario)

# change 服务(8106)补齐，保证证据源齐全（与 run_ablation_eval.py 一致）。
SERVERS: List[tuple] = list(MCP_SERVERS) + [("mcp_servers/change_server.py", 8106)]

# 与盲测/消融同一批固定种子（不同脚本间可复现可比）。
SCENARIO_PLAN = [
    (101, 1, "net"), (202, 2, "infra"), (303, 1, "dep"), (404, 2, "config"),
    (505, 1, "app"), (606, 2, "net"), (707, 1, "infra"), (808, 2, "app"),
    (909, 1, "container"), (1010, 2, "api"),
    (1111, 1, "middleware"), (1212, 2, "middleware"),
]

# 配置名 → 需要置 True 的优化开关（其余保持 False）
# fixed = 采纳 2026-10-12 根因诊断的全部修复项（原始证据采信 + 置信度校准）。
_CONFIGS: Dict[str, Dict[str, bool]] = {
    "baseline": {},
    "pi_opt": {"ENABLE_CONTEXT_COMPACTION": True, "ENABLE_SKILL_ROUTING": True},
    "fixed": {"ENABLE_RAW_EVIDENCE_FOR_JUDGE": True, "ENABLE_CONFIDENCE_CALIBRATION": True},
    "fixed_all": {
        "ENABLE_CONTEXT_COMPACTION": True, "ENABLE_SKILL_ROUTING": True,
        "ENABLE_RAW_EVIDENCE_FOR_JUDGE": True, "ENABLE_CONFIDENCE_CALIBRATION": True,
    },
}

# 对照组统一复位的开关（避免上一组残留）
_RESET_KEYS = (
    "ENABLE_CONTEXT_COMPACTION", "ENABLE_SKILL_ROUTING",
    "ENABLE_RAW_EVIDENCE_FOR_JUDGE", "ENABLE_CONFIDENCE_CALIBRATION",
)


# ── 开关应用（读时生效，直接改 settings 单例即可） ─────────────
def _apply_config(name: str) -> None:
    from src.settings import settings

    for key in _RESET_KEYS:
        setattr(settings, key, False)
    for key, value in _CONFIGS[name].items():
        setattr(settings, key, value)


# ── 开关生效自检（跨组打印：技能块长度对照，证明路由真的起作用） ─
def _sanity_check() -> None:
    from src.agent.aiops.planner import _build_skills_block

    full_len = len(_build_skills_block("__no_hit_probe__"))     # 零命中 → 全量兜底
    routed_len = len(_build_skills_block("接口延迟高、丢包"))      # 命中网络卡 → 应显著变短
    print(f"  [自检] skills_block: 零命中={full_len} 字 / 命中(网络)={routed_len} 字")


# ── 报告头 diagnostic_meta 提取 ──────────────────────────────
def _extract_meta(report: str) -> Dict[str, Any]:
    for line in (report or "").splitlines():
        if "diagnostic_meta" in line:
            try:
                return json.loads(line.split("diagnostic_meta:")[1].split("-->")[0].strip())
            except Exception:
                return {}
    return {}


def _top_hypothesis(hyp_space: list) -> Optional[Dict[str, Any]]:
    if not hyp_space:
        return None
    return max(hyp_space, key=lambda h: h.get("probability", 0))


class _Runner:
    """对单个场景跑一次诊断，采集步数/假设空间/报告/token 消耗。"""

    def __init__(self) -> None:
        import src.agent.aiops.graph as graph_mod
        self.service = graph_mod.AIOpsService(replan_strategy=graph_mod.DynamicClassificationStrategy())

    async def run(self, user_input: str) -> Dict[str, Any]:
        from src.utils.token_meter import start_meter, stop_meter

        hyp_space: list = []
        report = ""
        steps = 0
        start_meter()  # 节点内 create_agent_llm 会自动挂载计量器
        try:
            async for event in self.service.execute(user_input, session_id="pi-opt-ab"):
                etype = event.get("type")
                if etype == "step_complete":
                    steps += 1
                elif etype == "complete":
                    hyp_space = event.get("hypothesis_space", [])
                    report = event.get("response", "") or ""
                elif etype == "report":
                    report = event.get("report", "") or ""
        finally:
            meter = stop_meter()
        usage = meter.as_dict() if meter else {}
        top = _top_hypothesis(hyp_space)
        meta = _extract_meta(report)
        return {
            "steps": steps,
            "top_name": top["name"] if top else "",
            "top_prob": top["probability"] if top else 0.0,
            "conclusion_state": meta.get("conclusion_state"),
            "llm_calls": usage.get("llm_calls"),
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "cost_cny_estimated": usage.get("cost_cny_estimated"),
        }


# ── 结果落盘（增量续跑） ─────────────────────────────────────
def _load_results() -> Dict[str, Any]:
    if os.path.exists(RESULTS_FILE):
        try:
            with open(RESULTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_results(results: Dict[str, Any]) -> None:
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


def _user_prompt(root: str) -> str:
    return f"{SERVICE_ID}：{USER_REPORT[root]}，请定位根因并给出诊断结论"


async def _eval_one(seed: int, difficulty: int, root: str, configs: List[str],
                    results: Dict[str, Any], dry_run: bool) -> None:
    key_prefix = f"{seed}-{root}"
    scenario = gen_scenario(seed, difficulty, force_root=root)
    assert_no_verbatim_answer(scenario)
    write_scenario(scenario, SCENARIO_FILE)
    ground_truth = scenario["ground_truth"]
    user_input = _user_prompt(root)
    print(f"\n{'=' * 72}\n[场景 {key_prefix}] 难度={difficulty}  ground_truth={ground_truth}")

    for cfg in configs:
        key = f"{key_prefix}.{cfg}"
        if not dry_run and key in results:
            print(f"  [{cfg}] 已缓存，跳过")
            continue
        if dry_run:
            results[key] = {"hit": None, "steps": -1, "top_prob": None, "top_name": None,
                            "ground_truth": ground_truth, "dry_run": True}
            print(f"  [{cfg}] dry-run")
            continue

        _apply_config(cfg)
        _sanity_check()
        runner = _Runner()
        t0 = time.monotonic()
        try:
            res = await runner.run(user_input)
        except Exception as exc:  # 单场景失败不中断整轮
            print(f"  [{cfg}] 运行异常: {exc}")
            results[key] = {"hit": None, "steps": None, "top_prob": None, "top_name": None,
                            "ground_truth": ground_truth, "config": cfg, "error": str(exc)}
            _save_results(results)
            continue
        elapsed = round(time.monotonic() - t0, 1)
        hit = (res["top_name"] == ground_truth)
        results[key] = {
            "hit": hit, "steps": res["steps"], "top_prob": res["top_prob"],
            "top_name": res["top_name"], "ground_truth": ground_truth, "config": cfg,
            "conclusion_state": res["conclusion_state"], "elapsed_s": elapsed,
            "llm_calls": res["llm_calls"], "input_tokens": res["input_tokens"],
            "output_tokens": res["output_tokens"], "total_tokens": res["total_tokens"],
            "cost_cny_estimated": res["cost_cny_estimated"],
        }
        print(f"  [{cfg}] 命中={'是' if hit else '否'}  top='{res['top_name']}' "
              f"conf={res['top_prob']:.0%}  步数={res['steps']}  状态={res['conclusion_state']}  "
              f"耗时={elapsed}s  LLM={res['llm_calls']}次  token={res['total_tokens']}  "
              f"≈¥{res['cost_cny_estimated']}")
        _save_results(results)


# ── 汇总 ────────────────────────────────────────────────────
def _aggregate(results: Dict[str, Any], configs: List[str]) -> Dict[str, Any]:
    agg: Dict[str, Any] = {
        c: {"n": 0, "hits": 0, "steps_sum": 0, "steps_n": 0, "conf_sum": 0.0, "conf_n": 0,
            "elapsed_sum": 0.0, "elapsed_n": 0, "states": {},
            "tok_sum": 0, "tok_n": 0, "in_sum": 0, "out_sum": 0, "calls_sum": 0,
            "cost_sum": 0.0}
        for c in configs
    }
    for key, r in results.items():
        cfg = key.rsplit(".", 1)[1]
        if cfg not in agg or r.get("dry_run") or r.get("error"):
            continue
        a = agg[cfg]
        a["n"] += 1
        if r.get("hit") is True:
            a["hits"] += 1
        if r.get("steps") is not None:
            a["steps_sum"] += r["steps"]; a["steps_n"] += 1
        if r.get("top_prob"):
            a["conf_sum"] += r["top_prob"]; a["conf_n"] += 1
        if r.get("elapsed_s"):
            a["elapsed_sum"] += r["elapsed_s"]; a["elapsed_n"] += 1
        if r.get("total_tokens") is not None:
            a["tok_sum"] += r["total_tokens"]; a["tok_n"] += 1
        if r.get("input_tokens") is not None:
            a["in_sum"] += r["input_tokens"]
        if r.get("output_tokens") is not None:
            a["out_sum"] += r["output_tokens"]
        if r.get("llm_calls") is not None:
            a["calls_sum"] += r["llm_calls"]
        if r.get("cost_cny_estimated") is not None:
            a["cost_sum"] += r["cost_cny_estimated"]
        if r.get("conclusion_state"):
            a["states"][r["conclusion_state"]] = a["states"].get(r["conclusion_state"], 0) + 1
    for a in agg.values():
        a["hit_rate"] = a["hits"] / a["n"] if a["n"] else 0.0
        a["avg_steps"] = a["steps_sum"] / a["steps_n"] if a["steps_n"] else 0.0
        a["avg_conf"] = a["conf_sum"] / a["conf_n"] if a["conf_n"] else 0.0
        a["avg_elapsed"] = a["elapsed_sum"] / a["elapsed_n"] if a["elapsed_n"] else 0.0
        a["avg_tokens"] = a["tok_sum"] / a["tok_n"] if a["tok_n"] else 0.0
        a["avg_calls"] = a["calls_sum"] / a["n"] if a["n"] else 0.0
    return agg


def _delta_pct(a: float, b: float) -> str:
    """(b-a)/a 的百分比展示；a=0 时返回 '—'。"""
    if not a:
        return "—"
    return f"{(b - a) / a:+.1%}"


def _write_report(results: Dict[str, Any], plan: List[tuple], configs: List[str]) -> None:
    agg = _aggregate(results, configs)
    lines = ["# B2a/B2b 优化 A/B 实验结果（pi 思路借鉴量化）", "",
             f"- 场景数: {len(plan)}   配置: {', '.join(configs)}",
             "- 对照: baseline=两开关关（旧行为） / pi_opt=上下文压缩+技能路由开",
             "- 定判: 最终假设空间 top 假设 name == 场景 ground_truth", "",
             "## 逐场景明细", "",
             "| 场景 | 难度 | ground_truth | " + " | ".join(configs) + " |",
             "| --- | --- | --- | " + " | ".join("---" for _ in configs) + " |"]
    for seed, diff, root in plan:
        gt = ROOT_CAUSE_NAMES[root]
        cells = [str(seed), str(diff), gt]
        for cfg in configs:
            r = results.get(f"{seed}-{root}.{cfg}")
            if not r or r.get("dry_run"):
                cells.append("—")
                continue
            hit = r.get("hit")
            mark = "√" if hit else ("✗" if hit is False else "?")
            cells.append(f"{r.get('top_name') or 'N/A'} ({r.get('top_prob', 0):.0%},"
                         f"{r.get('steps')}步,{mark})")
        lines.append("| " + " | ".join(cells) + " |")

    lines += ["", "## 汇总", "",
              "| 配置 | 命中率 | 平均步数 | 平均置信度 | 平均耗时(s) | 平均LLM调用 | 平均token | 平均input | 平均output | 合计费用(¥) |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for cfg in configs:
        a = agg[cfg]
        lines.append(f"| {cfg} | {a['hits']}/{a['n']} ({a['hit_rate']:.0%}) | "
                     f"{a['avg_steps']:.1f} | {a['avg_conf']:.0%} | {a['avg_elapsed']:.1f} | "
                     f"{a['avg_calls']:.1f} | {a['avg_tokens']:,.0f} | "
                     f"{(a['in_sum'] / a['n']) if a['n'] else 0:,.0f} | "
                     f"{(a['out_sum'] / a['n']) if a['n'] else 0:,.0f} | "
                     f"{a['cost_sum']:.4f} |")

    if "baseline" in agg and "pi_opt" in agg:
        b, p = agg["baseline"], agg["pi_opt"]
        lines += ["", "## 净影响（pi_opt 相对 baseline）", "",
                  f"- 命中率: {b['hit_rate']:.0%} → {p['hit_rate']:.0%} "
                  f"（Δ {p['hit_rate'] - b['hit_rate']:+.0%}）",
                  f"- 平均 token: {b['avg_tokens']:,.0f} → {p['avg_tokens']:,.0f} "
                  f"（{_delta_pct(b['avg_tokens'], p['avg_tokens'])}）",
                  f"- 平均 input tokens: "
                  f"{(b['in_sum'] / b['n']) if b['n'] else 0:,.0f} → "
                  f"{(p['in_sum'] / p['n']) if p['n'] else 0:,.0f}",
                  f"- 平均耗时: {b['avg_elapsed']:.1f}s → {p['avg_elapsed']:.1f}s "
                  f"（{_delta_pct(b['avg_elapsed'], p['avg_elapsed'])}）",
                  f"- 平均步数: {b['avg_steps']:.1f} → {p['avg_steps']:.1f}",
                  "",
                  "> 注：B2b（技能路由）主要压低 planner 的输入长度；B2a（上下文压缩）"
                  "仅在诊断步数超过 5 步时触发——短诊断中其影响为零，属预期现象。"]
    lines += ["", f"_注: 结果文件 runtime/{os.path.basename(RESULTS_FILE)} 增量续跑，已完成的场景自动跳过。_"]
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n[完成] 报告已写入 {REPORT_FILE}")


# ── 服务启停：仅启动端口未监听的，避免与已在跑的服务冲突 ──────────
def _ensure_servers() -> list:
    procs = []
    import subprocess

    for script, port in SERVERS:
        path = os.path.join(PROJECT_ROOT, script)
        if _port_ready(port):
            print(f"[跳过] {script} 端口 {port} 已在监听")
            continue
        if not os.path.exists(path):
            print(f"[警告] 找不到 {script}，跳过")
            continue
        print(f"[启动] {script} -> 127.0.0.1:{port}")
        log_path = os.path.join(PROJECT_ROOT, f"{os.path.basename(script)}.log")
        proc = subprocess.Popen(
            [sys.executable, path], cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL, stderr=open(log_path, "w", encoding="utf-8"),
        )
        proc._log_path = log_path
        procs.append(proc)
    return procs


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenarios", type=int, default=len(SCENARIO_PLAN))
    ap.add_argument("--configs", nargs="+", choices=list(_CONFIGS),
                    default=list(_CONFIGS))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--once", type=int, default=0, help="只跑第 N 个场景（cli 首页为 1）")
    ap.add_argument("--tag", default="", help="结果/报告文件后缀，用于多轮隔离")
    args = ap.parse_args()

    if args.tag:
        global RESULTS_FILE, REPORT_FILE
        RESULTS_FILE = os.path.join(RUNTIME_DIR, f"pi_opt_ab_results_{args.tag}.json")
        REPORT_FILE = os.path.join(RUNTIME_DIR, f"pi_opt_ab_report_{args.tag}.md")

    plan = [SCENARIO_PLAN[args.once - 1]] if args.once else SCENARIO_PLAN[: args.scenarios]
    results = {} if args.dry_run else _load_results()

    procs = _ensure_servers()
    try:
        _wait_for_ports([p for _, p in SERVERS], procs) if procs else None
        print("[就绪] MCP 服务在线")
        for seed, diff, root in plan:
            await _eval_one(seed, diff, root, args.configs, results, args.dry_run)
    finally:
        if procs:
            print("\n[清理] 关闭本次启动的 MCP 服务...")
            _stop_servers(procs)

    if not args.dry_run:
        _write_report(results, plan, args.configs)


if __name__ == "__main__":
    asyncio.run(main())
