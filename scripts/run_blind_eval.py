"""非预埋盲测驱动：检验旁开式动态分类机制的净贡献。

流程：
  1. 按计划生成 8 个非预埋场景(根因/难度混合,seed 固定可复现)；
  2. 启动 3 个 MCP 服务(复用 run_full_pipeline 的启停逻辑)，服务在查询时实时读盘；
  3. 对每个场景，先跑【动态分类策略】再跑【默认线性基线】，读同一份场景文件；
  4. 判定命中(动态取 hypothesis_space top name==ground_truth；基线解析报告分类)；
  5. 汇总:动态命中率、基线命中率、Δ、平均收敛步数、平均置信度 → runtime/blind_eval_report.md。

用法：
  python scripts/run_blind_eval.py                 # 全量 8 场景 × both
  python scripts/run_blind_eval.py --dry-run       # 只起 MCP、写场景、不跑 LLM，自检链路
  python scripts/run_blind_eval.py --scenarios 3   # 只跑前 3 个场景
  python scripts/run_blind_eval.py --strategies dynamic|base

继续性：每场景结果增量落盘 runtime/blind_eval_results.json，已完成的场景跳过(断点续跑)。
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
# 先加载 .env 生产配置:证据裁判默认跟随 .env(=LLM 语义裁判),确保对照公平、
# 测的是"真实机制"而非被弱化的关键词裁判。仅当显式 --deterministic 时才
# 压成关键词裁判(见 main),换取可复现。
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
os.environ.setdefault("ENABLE_DYNAMIC_CLASSIFICATION", "true")
# 评测要拿到 complete/report 事件;HITL 挂起为 pending_review 会导致 top 取空,强制关闭
# (必须强制赋值:load_dotenv 已把 .env 的 ENABLE_HITL=true 写入 os.environ,setdefault 不会覆盖)
os.environ["ENABLE_HITL"] = "false"
# 注意:不要在此处写死 ENABLE_LLM_EVIDENCE_JUDGE=false——
# 一旦写进 os.environ,pydantic settings(env 优先于 .env)就会读到 false,
# 使动态策略永远走弱化的关键词裁判,系统性偏向基线。

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
while not os.path.isdir(os.path.join(PROJECT_ROOT, "src")):
    parent = os.path.dirname(PROJECT_ROOT)
    if parent == PROJECT_ROOT:
        break
    PROJECT_ROOT = parent
sys.path.insert(0, PROJECT_ROOT)

RUNTIME_DIR = os.path.join(PROJECT_ROOT, "runtime")
os.makedirs(RUNTIME_DIR, exist_ok=True)
SCENARIO_FILE = os.path.join(RUNTIME_DIR, "blind_scenario.json")
RESULTS_FILE = os.path.join(RUNTIME_DIR, "blind_eval_results.json")
REPORT_FILE = os.path.join(RUNTIME_DIR, "blind_eval_report.md")

from scripts.blind_fault_gen import (ROOT_CAUSE_NAMES, SERVICE_ID, USER_REPORT,
                                     assert_no_verbatim_answer, gen_scenario,
                                     write_scenario)
from run_full_pipeline import MCP_SERVERS, _start_servers, _stop_servers, _wait_for_ports

# ── 场景计划:覆盖全部根因类别,难度随机混合(diff=1 简单/2 难) ─────────
SCENARIO_PLAN = [
    (101, 1, "net"), (202, 2, "infra"), (303, 1, "dep"), (404, 2, "config"),
    (505, 1, "app"), (606, 2, "net"), (707, 1, "infra"), (808, 2, "app"),
    # 6 类运维故障覆盖(2026-09): 容器驱逐/OOMKilled + 服务接口超时/熔断
    (909, 1, "container"), (1010, 2, "api"),
    # 6 类运维故障覆盖(2026-09-15): 中间件(MQ/缓存类外部依赖,假设名仍为外部依赖故障)
    (1111, 1, "middleware"), (1212, 2, "middleware"),
]

# ── 基线报告分类:类别 → 关键词(启发式解析 LLM 报告中的根因) ─────────
_CLASSIFY_KEYWORDS = {
    "网络/连通性问题": ["网络", "连通", "timeout", "超时", "connect", "连接", "dns",
                       "reset", "丢包", "握手", "链路"],
    "基础设施/资源瓶颈": ["cpu", "内存", "memory", "资源", "负载", "load", "fd",
                         "oo m", "使用率", "线程池", "排队", "耗尽"],
    "应用层异常": ["exception", "堆栈", "崩溃", "crash", "5xx", "oom",
                   "OutOfMemory", "死锁", "线程卡"],
    "配置错误": ["配置", "阈值", "限流", "429", "路由", "时钟", "参数"],
    "外部依赖故障": ["数据库", "database", "redis", "mq", "kafka", "依赖", "上游",
                    "503", "消费", "消息队列"],
    "容器问题": ["容器", "pod", "kubelet", "驱逐", "oomkilled", "crashloop",
                 "evict", "重启", "编排"],
    "服务接口异常": ["接口", "p99", "fallback", "熔断", "错误率", "endpoint",
                     "circuit", "降级"],
}


def _classify_root(text: str) -> str:
    """把一段报告/结论文本归类到某个根因类别(启发式关键词计分)。"""
    text = (text or "").lower()
    best, best_score = "", 0
    for cat, kws in _CLASSIFY_KEYWORDS.items():
        score = sum(1 for kw in kws if kw in text)
        # "oo m" 是内存缩写 of out-of-memory 的分词占位,额外扣:  不与 infra 冲突
        if "内存" in text or "cpu" in text:
            score += 1
        if score > best_score:
            best, best_score = cat, score
    return best


def _top_hypothesis(hyp_space: list) -> Optional[Dict[str, Any]]:
    """从 hypothesis_space 取概率最高的假设。"""
    if not hyp_space:
        return None
    ranked = sorted(hyp_space, key=lambda h: h.get("probability", 0), reverse=True)
    return ranked[0] if ranked else None


class _EvalRunner:
    """针对单个场景运行某个策略,并从 complete 事件 / 报告里提取结论。"""

    def __init__(self, strategy) -> None:
        import src.agent.aiops.graph as graph_mod
        self.service = graph_mod.AIOpsService(replan_strategy=strategy)

    async def run(self, user_input: str) -> Dict[str, Any]:
        hyp_space: list = []
        report = ""
        steps = 0
        async for event in self.service.execute(user_input, session_id="blind-eval"):
            etype = event.get("type")
            if etype == "step_complete":
                steps += 1
            elif etype == "complete":
                hyp_space = event.get("hypothesis_space", [])
                report = event.get("response", "") or ""
            elif etype == "report":
                report = event.get("report", "") or ""
        top = _top_hypothesis(hyp_space)
        return {
            "steps": steps,
            "top_name": top["name"] if top else "",
            "top_prob": top["probability"] if top else 0.0,
            "hypothesis_space": hyp_space,
            "report": report,
        }


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


def _user_prompt(root) -> str:
    return f"{SERVICE_ID}：{USER_REPORT[root]}，请定位根因并给出诊断结论"


def _write_report(results: Dict[str, Any], plan: List[tuple], order: List[str]) -> None:
    rows = []
    for seed, diff, root in plan:
        key = f"{seed}-{root}"
        gt = ROOT_CAUSE_NAMES[root]
        row = {"seed": seed, "diff": diff, "ground_truth": gt}
        for s in order:
            r = results.get(f"{key}.{s}")
            if not r:
                row[s] = {"hit": None, "steps": None, "conf": None, "top": "E/N/A"}
                continue
            hit = r.get("hit")
            row[s] = {"hit": hit, "steps": r.get("steps"),
                      "conf": r.get("top_prob"),
                      "top": r.get("top_name") or ""}
        rows.append(row)

    lines = ["# 非预埋盲测结果(机制净贡献)", "",
             f"- 场景数: {len(plan)}   策略: {' + '.join(order)}   定判: 动态取假设空间 top==ground_truth / 基线解析报告",
             "", "| 场景 | 难度 | ground_truth | " +
                 " | ".join(f"{s}" for s in order) + " |", "| --- | --- | --- |" +
                 " | ".join(" --- " for _ in order) + " |"]
    for row in rows:
        cells = [str(row["seed"]), str(row["diff"]), row["ground_truth"]]
        for s in order:
            d = row[s]
            cells.append(f"{d['top']}({d['conf']:.0%},{d['steps']}步,{'√' if d['hit'] else '✗' if d['hit'] is False else '?'})")
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    # 汇总
    agg = _aggregate(results, order)
    lines.append("## 汇总")
    for s in order:
        a = agg[s]
        hits = a["hit_t"] + a["hit_f"]
        rate = a["hit_t"] / hits if hits else 0.0
        lines.append(f"- **{s}**: 命中 {a['hit_t']}/{hits} ({rate:.0%}，" +
                     f"未命中 {a['hit_f']}，弱命中 {a['weak']})   平均收敛步数 {a['steps']:.1f}   平均置信度 {a['conf']:.0%}")
    delta = (agg["dynamic"]["hit_t"] / (agg["dynamic"]["hit_t"] + agg["dynamic"]["hit_f"])
             if "dynamic" in agg and (agg["dynamic"]["hit_t"] + agg["dynamic"]["hit_f"])
             else 0.0) if "dynamic" in agg else 0.0
    base_rate = (agg["base"]["hit_t"] / (agg["base"]["hit_t"] + agg["base"]["hit_f"])
                 if "base" in agg and (agg["base"]["hit_t"] + agg["base"]["hit_f"]) else 0.0)
    if "dynamic" in agg and "base" in agg:
        lines.append(f"- **Δ(机制净贡献) = 动态命中率 − 基线命中率 = {delta:.0%} − {base_rate:.0%} = {delta - base_rate:+.0%}**")
    lines.append("\n_定判口径: dynamic 用最终状态假设空间 top；base 用报告关键词分类。_")
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n[完成] 报告已写入 {REPORT_FILE}")


def _aggregate(results: Dict[str, Any], order: List[str]) -> Dict[str, Any]:
    agg = {s: {"hit_t": 0, "hit_f": 0, "weak": 0, "steps": 0.0, "conf": 0.0, "n": 0}
           for s in order}
    for key, r in results.items():
        if not key.endswith(tuple(f".{s}" for s in order)):
            continue
        s = key.rsplit(".", 1)[1]
        a = agg[s]
        if r.get("hit") is True:
            a["hit_t"] += 1
        elif r.get("hit") is False:
            a["hit_f"] += 1
        if r.get("weak"):
            a["weak"] += 1
        if r.get("steps"):
            a["steps"] += r["steps"]; a["n"] += 1
        if r.get("top_prob"):
            a["conf"] += r["top_prob"]
    for a in agg.values():
        if a["n"]:
            a["steps"] /= a["n"]; a["conf"] /= a["n"]
    return agg


async def _eval_one_scenario(seed: int, difficulty: int, root: str,
                             strategy_factories: Dict[str, Any],
                             order: List[str],
                             results: Dict[str, Any], dry_run: bool) -> None:
    key_prefix = f"{seed}-{root}"
    scenario = gen_scenario(seed, difficulty, force_root=root)
    assert_no_verbatim_answer(scenario)
    write_scenario(scenario, SCENARIO_FILE)
    ground_truth = scenario["ground_truth"]
    user_input = _user_prompt(root)
    print(f"\n{'='*72}\n[场景 {key_prefix}] 难度={difficulty}  根因(ground_truth)={ground_truth}")
    print(f"  输入: {user_input}")

    for s in order:
        key = f"{key_prefix}.{s}"
        if not dry_run and key in results:
            print(f"  [{s}] 已缓存,跳过")
            continue
        if dry_run:
            results[key] = {"hit": None, "steps": -1, "top_prob": None,
                            "top_name": None, "ground_truth": ground_truth, "dry_run": True}
            print(f"  [{s}] dry-run 命中判定基准: {ground_truth}")
            continue
        # 每场景每策略都新造实例:动态策略的 HypothesisManager/信念历史/旁开等
        # 是有状态实例字段,若跨场景复用会携带上一场景证据,污染实验结果。
        runner = _EvalRunner(strategy_factories[s]())
        t0 = time.monotonic()
        try:
            res = await runner.run(user_input)
        except Exception as e:
            print(f"  [{s}] 运行异常: {e}")
            results[key] = {"hit": None, "steps": None, "top_prob": None,
                            "top_name": None, "ground_truth": ground_truth, "error": str(e)}
            continue
        elapsed_s = round(time.monotonic() - t0, 1)
        if s == "dynamic":
            hit = (res["top_name"] == ground_truth)
            weak = (res["top_name"] == ground_truth and res["top_prob"] < 0.70)
        else:
            inferred = _classify_root(res["report"])
            hit = (inferred == ground_truth)
            weak = False
        results[key] = {"hit": hit, "weak": weak, "steps": res["steps"],
                        "top_prob": res["top_prob"], "top_name": res["top_name"],
                        "ground_truth": ground_truth, "elapsed_s": elapsed_s}
        print(f"  [{s}] 命中={'是' if hit else '否'}{f'(弱置信)' if weak else ''}  "
              f"top='{res['top_name']}' conf={res['top_prob']:.0%} 步数={res['steps']} 耗时={elapsed_s}s")
        _save_results(results)


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scenarios", type=int, default=len(SCENARIO_PLAN))
    ap.add_argument("--strategies", choices=["both", "dynamic", "base"], default="both")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--once", type=int, default=0, help="只跑第 N 个场景(cli 首页为 1)进行验证")
    ap.add_argument("--deterministic", action="store_true",
                    help="强制关键词证据裁判(替代 .env 的 LLM 语义),换取可复现;默认跟随生产配置")
    ap.add_argument("--tag", default="",
                    help="结果文件后缀(如 --tag A → blind_eval_results_A.json),用于 A/B 对照隔离")
    args = ap.parse_args()

    # A/B 对照: 结果/报告文件按 tag 隔离
    if args.tag:
        global RESULTS_FILE, REPORT_FILE
        RESULTS_FILE = os.path.join(RUNTIME_DIR, f"blind_eval_results_{args.tag}.json")
        REPORT_FILE = os.path.join(RUNTIME_DIR, f"blind_eval_report_{args.tag}.md")

    # 证据裁判配置:默认跟随 .env(LLM 语义);--deterministic 时压成规则关键词。
    # 必须在构造策略(即首次 import src.settings 创建单例)之前设置,否则 settings 读到旧值。
    if args.deterministic:
        os.environ["ENABLE_LLM_EVIDENCE_JUDGE"] = "false"

    order = ["dynamic", "base"] if args.strategies == "both" else [args.strategies]
    plan = SCENARIO_PLAN
    if args.once:
        plan = [SCENARIO_PLAN[args.once - 1]]
    else:
        plan = plan[: args.scenarios]

    results = _load_results() if not args.dry_run else {}

    import src.agent.aiops.graph as graph_mod  # noqa: F401
    # 策略工厂:每次调用返回全新实例(_eval_one_scenario 内逐场景构建),
    # 避免动态策略的有状态信念/假设空间跨场景污染实验结果。
    strategy_factories: Dict[str, Any] = {}
    if "dynamic" in order:
        strategy_factories["dynamic"] = graph_mod.DynamicClassificationStrategy
    if "base" in order:
        strategy_factories["base"] = graph_mod.DefaultReplanStrategy

    procs = _start_servers()
    try:
        _wait_for_ports([port for _, port in MCP_SERVERS], procs)
        print("[就绪] MCP 服务全部在线")
        for seed, diff, root in plan:
            await _eval_one_scenario(seed, diff, root, strategy_factories, order, results, args.dry_run)
    finally:
        print("\n[清理] 关闭 MCP 服务...")
        _stop_servers(procs)

    if not args.dry_run:
        _write_report(results, plan, order)


if __name__ == "__main__":
    asyncio.run(main())
