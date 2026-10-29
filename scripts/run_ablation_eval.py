"""论文消融实验批量跑分：量化三个消融开关对诊断结果的净影响。

对齐开题报告口径——「消融分析：逐项关闭 假设保护 / 证据门控 / 降级标注」。
每个配置只关一个机制、其余链路不变，保证结果可归因。对每个配置，在同一批
**固定种子**场景上跑完整诊断链路，从报告头部 ``diagnostic_meta`` 提取结论状态、
命中、步数、耗时，汇总为可在仓库内复现的指标表。

配置（--configs 可选其一/多个）：
  full        三个机制全开（生产默认，实验对照组）
  no_protect  关假设保护   (ABLATION_DISABLE_HYPOTHESIS_PROTECTION)
  no_gate     关证据门控   (ABLATION_DISABLE_EVIDENCE_GATE)
  no_label    关降级标注   (ABLATION_DISABLE_DEGRADATION_LABEL)

定判口径（与 run_blind_eval.py 一致，便于与盲测对照）：
  hit = 最终假设空间 top 假设 name == 场景 ground_truth。

用法：
  python scripts/run_ablation_eval.py --dry-run          # 只起服务、写场景，自检链路
  python scripts/run_ablation_eval.py                    # 全量：4 配置 × 场景计划
  python scripts/run_ablation_eval.py --configs full no_gate --scenarios 3
  python scripts/run_ablation_eval.py --once 1           # 只跑第 1 个场景（快速验证）

产物（均落盘 runtime/）：
  ablation_results.json   逐场景逐配置的原始结果（增量续跑，已完成的跳过）
  ablation_report.md      汇总指标表（命中率/收敛步数/结论状态分布/耗时）
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
# 消融实验测的是动态分类机制本身，强制开启；HITL 挂起会让 complete 事件取不到 top，强制关。
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
RESULTS_FILE = os.path.join(RUNTIME_DIR, "ablation_results.json")
REPORT_FILE = os.path.join(RUNTIME_DIR, "ablation_report.md")

from run_full_pipeline import MCP_SERVERS, _port_ready, _stop_servers, _wait_for_ports
from scripts.blind_fault_gen import (ROOT_CAUSE_NAMES, SERVICE_ID, USER_REPORT,
                                     assert_no_verbatim_answer, gen_scenario,
                                     write_scenario)

# change 服务(8106)不在 run_full_pipeline 的启动清单里，这里补上，保证证据源齐全。
SERVERS: List[tuple] = list(MCP_SERVERS) + [("mcp_servers/change_server.py", 8106)]

# 与 run_blind_eval.py 同一批固定种子(可复现)，覆盖全部根因类别。
SCENARIO_PLAN = [
    (101, 1, "net"), (202, 2, "infra"), (303, 1, "dep"), (404, 2, "config"),
    (505, 1, "app"), (606, 2, "net"), (707, 1, "infra"), (808, 2, "app"),
    (909, 1, "container"), (1010, 2, "api"),
    (1111, 1, "middleware"), (1212, 2, "middleware"),
]

# 配置名 → 需要置 True 的消融开关（其余保持 False）
_CONFIGS: Dict[str, Dict[str, bool]] = {
    "full": {},
    "no_protect": {"ABLATION_DISABLE_HYPOTHESIS_PROTECTION": True},
    "no_gate": {"ABLATION_DISABLE_EVIDENCE_GATE": True},
    "no_label": {"ABLATION_DISABLE_DEGRADATION_LABEL": True},
}


# ── 消融开关应用（读时生效，直接改 settings 单例即可） ─────────────
def _apply_config(name: str) -> None:
    from src.settings import settings

    settings.ABLATION_DISABLE_HYPOTHESIS_PROTECTION = False
    settings.ABLATION_DISABLE_EVIDENCE_GATE = False
    settings.ABLATION_DISABLE_DEGRADATION_LABEL = False
    for key, value in _CONFIGS[name].items():
        setattr(settings, key, value)


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
    """对单个场景跑一次诊断，采集步数/假设空间/报告/结论元数据。"""

    def __init__(self) -> None:
        import src.agent.aiops.graph as graph_mod
        self.service = graph_mod.AIOpsService(replan_strategy=graph_mod.DynamicClassificationStrategy())

    async def run(self, user_input: str) -> Dict[str, Any]:
        from src.utils.token_meter import start_meter, stop_meter

        hyp_space: list = []
        report = ""
        steps = 0
        # 启用全局 token 计量：planner/executor 在节点内 create_agent_llm 时会自动挂载计量器。
        start_meter()
        try:
            async for event in self.service.execute(user_input, session_id="ablation-eval"):
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
            "hypothesis_space": hyp_space,
            "conclusion_state": meta.get("conclusion_state"),
            "evidence_sufficiency": meta.get("evidence_sufficiency"),
            "ablation_meta": meta.get("ablation"),
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
        runner = _Runner()
        t0 = time.monotonic()
        try:
            res = await runner.run(user_input)
        except Exception as exc:  # 单场景失败不中断整轮，记录后继续
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
            "conclusion_state": res["conclusion_state"],
            "evidence_sufficiency": res["evidence_sufficiency"],
            "ablation_meta": res["ablation_meta"], "elapsed_s": elapsed,
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
            "elapsed_sum": 0.0, "elapsed_n": 0, "states": {}, "suff": {}, "ablation_ok": True,
            "tok_sum": 0, "tok_n": 0, "calls_sum": 0, "cost_sum": 0.0}
        for c in configs
    }
    for key, r in results.items():
        cfg = key.rsplit(".", 1)[1]
        if cfg not in agg or r.get("dry_run"):
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
        if r.get("llm_calls") is not None:
            a["calls_sum"] += r["llm_calls"]
        if r.get("cost_cny_estimated") is not None:
            a["cost_sum"] += r["cost_cny_estimated"]
        if r.get("conclusion_state"):
            a["states"][r["conclusion_state"]] = a["states"].get(r["conclusion_state"], 0) + 1
        if r.get("evidence_sufficiency"):
            a["suff"][r["evidence_sufficiency"]] = a["suff"].get(r["evidence_sufficiency"], 0) + 1
        # 校验消融自描述与实际配置一致（防止"改了开关但链路没读"）
        expected = {
            "hypothesis_protection": not _CONFIGS[cfg].get("ABLATION_DISABLE_HYPOTHESIS_PROTECTION", False),
            "evidence_gate": not _CONFIGS[cfg].get("ABLATION_DISABLE_EVIDENCE_GATE", False),
            "degradation_label": not _CONFIGS[cfg].get("ABLATION_DISABLE_DEGRADATION_LABEL", False),
        }
        meta = r.get("ablation_meta") or {}
        if meta and meta != expected:
            a["ablation_ok"] = False
    for a in agg.values():
        a["hit_rate"] = a["hits"] / a["n"] if a["n"] else 0.0
        a["avg_steps"] = a["steps_sum"] / a["steps_n"] if a["steps_n"] else 0.0
        a["avg_conf"] = a["conf_sum"] / a["conf_n"] if a["conf_n"] else 0.0
        a["avg_elapsed"] = a["elapsed_sum"] / a["elapsed_n"] if a["elapsed_n"] else 0.0
        a["avg_tokens"] = a["tok_sum"] / a["tok_n"] if a["tok_n"] else 0.0
        a["avg_calls"] = a["calls_sum"] / a["n"] if a["n"] else 0.0
    return agg


def _write_report(results: Dict[str, Any], plan: List[tuple], configs: List[str]) -> None:
    agg = _aggregate(results, configs)
    lines = ["# 消融实验批量跑分结果", "",
             f"- 场景数: {len(plan)}   配置: {', '.join(configs)}",
             "- 定判: 最终假设空间 top 假设 name == 场景 ground_truth",
             "- 口径: 每个配置只关一个机制，其余链路不变（对齐开题报告消融设计）", "",
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
              "| 配置 | 命中率 | 平均收敛步数 | 平均置信度 | 平均耗时(s) | 平均LLM调用 | 平均token | 合计token | 估算费用(¥) | 结论状态分布 | 证据充分性 |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for cfg in configs:
        a = agg[cfg]
        states = ", ".join(f"{k}:{v}" for k, v in sorted(a["states"].items())) or "—"
        suff = ", ".join(f"{k}:{v}" for k, v in sorted(a["suff"].items())) or "—"
        lines.append(f"| {cfg} | {a['hits']}/{a['n']} ({a['hit_rate']:.0%}) | "
                     f"{a['avg_steps']:.1f} | {a['avg_conf']:.0%} | {a['avg_elapsed']:.1f} | "
                     f"{a['avg_calls']:.1f} | {a['avg_tokens']:,.0f} | {a['tok_sum']:,} | "
                     f"{a['cost_sum']:.4f} | {states} | {suff} |")
    if "full" in agg:
        base = agg["full"]["hit_rate"]
        lines += ["", "## 净影响（相对 full 对照组）", ""]
        for cfg in configs:
            if cfg == "full":
                continue
            delta = agg[cfg]["hit_rate"] - base
            lines.append(f"- **{cfg}**: 命中率 {agg[cfg]['hit_rate']:.0%} "
                         f"（Δ {delta:+.0%}），平均步数 {agg[cfg]['avg_steps']:.1f} "
                         f"（Δ {agg[cfg]['avg_steps'] - agg['full']['avg_steps']:+.1f}）")
    bad = [c for c in configs if not agg[c]["ablation_ok"]]
    if bad:
        lines += ["", f"> ⚠️ 消融自描述校验不一致的配置: {', '.join(bad)} —— 请检查开关是否真正生效。"]
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
        os.makedirs(os.path.join(PROJECT_ROOT, "logs"), exist_ok=True)
        log_path = os.path.join(PROJECT_ROOT, "logs", f"{os.path.basename(script)}.log")
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
    ap.add_argument("--configs", nargs="+", choices=list(_CONFIGS), default=list(_CONFIGS))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--once", type=int, default=0, help="只跑第 N 个场景（cli 首页为 1）")
    ap.add_argument("--tag", default="", help="结果/报告文件后缀，用于多轮隔离")
    args = ap.parse_args()

    if args.tag:
        global RESULTS_FILE, REPORT_FILE
        RESULTS_FILE = os.path.join(RUNTIME_DIR, f"ablation_results_{args.tag}.json")
        REPORT_FILE = os.path.join(RUNTIME_DIR, f"ablation_report_{args.tag}.md")

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
