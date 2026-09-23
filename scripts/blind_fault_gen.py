"""非预埋盲测 · 程序化因果故障生成器。

目的：为「旁开式动态分类机制真实贡献」实验生成一组**非预埋**故障场景。
与 `cls_server.py` 中预埋的 `topic-003` 剧本的关键差异：
  - 根因由 RNG 抽取，只记录在 `ground_truth` 字段，**绝不写进 LLM 可见的日志/指标**；
  - 日志只含含混、临床式的症状描述（timeout / connection reset / queue growth 等），
    不含"注入/混沌/根因是网络"这类送分台词；
  - 按难度注入指向他因的干扰症状、同义词/否定句、可选级联次生症状，逼迫机制真正做
    假设保护 + 信念收敛，而不是撞关键词。

根因类别名与 `DynamicClassificationStrategy._DEFAULT_HYPOTHESES` 的 `name` 保持一致，
保证「生成器 ground_truth == 策略 top 假设 name」即判定命中（hit）。

用法：
  python scripts/blind_fault_gen.py --seed 100 --difficulty 1 [--out runtime/blind_scenario.json]
"""

from __future__ import annotations

import argparse
import json
import os
import random
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

# ── 根因类别(与策略假设 name 一一对应) ─────────────────────────────
# 注意: 系统假设空间未细分数据库/中间件, 二者都映射到「外部依赖故障」;
#      6 类运维故障评测靠 eval_precision_recall.py 的 CASE_TO_FAULT 按 case id 细分。
ROOT_CAUSE_NAMES = {
    "net": "网络/连通性问题",
    "infra": "基础设施/资源瓶颈",
    "app": "应用层异常",
    "config": "配置错误",
    "dep": "外部依赖故障",
    "middleware": "外部依赖故障",
    "container": "容器问题",
    "api": "服务接口异常",
}

SERVICE_ID = "blind-svc"

# ── 送分词(不允许出现在日志/指标里,否则视为"背题") ─────────────────
FORBIDDEN_TERMS = ["注入", "混沌", "根因", "故障注入", "chaos", "injection", "人为制造"]

# ── 候选:用户可见的上报症状(可写进诊断输入;不含根因名词) ───────────
USER_REPORT = {
    "net": "服务出现大量连接超时、连接偶发断开与请求失败",
    "infra": "服务响应变慢，疑似资源占用偏高",
    "app": "服务近期频繁报错，偶发接口不可用",
    "config": "近期配置调整后服务出现异常",
    "dep": "依赖的下游能力出现异常，服务受影响",
    "middleware": "消息队列与缓存类中间件出现异常，消费延迟与读取超时增多",
    "container": "服务实例反复重启，疑似容器被清理或内存受限",
    "api": "部分接口响应变慢且偶发失败，接口可用性下降",
}

# ── 症状模板库:每个根因的主治症状(临床式,不点名根因) ──────────────
_PRIMARY_LOG = {
    "net": [
        "connect to 10.0.3.21:8080 timed out (Connection timed out)",
        "request to svc-c failed: read timeout after 30000ms",
        "intermittent connection reset by peer while sending request",
        "retry storm on upstream endpoint, all attempts failed",
        "TCP connect to 10.0.4.55:443 did not complete, handshake stalled",
        "upstream connect timeout: proxy connect to 10.0.7.8:3000 timed out",
        "dial tcp 10.0.9.13:6379: connect: connection refused intermittently",
    ],
    "infra": [
        "worker pool saturated, incoming tasks queuing up",
        "GC pause lengthening, application threads blocked on allocation",
        "memory usage climbing toward hard limit, old-gen growing steadily",
        "connection count rising, file descriptor usage trending up",
        "load average high on worker nodes, scheduling latency increasing",
    ],
    "app": [
        "stacktrace: java.lang.OutOfMemoryError in order-processing handler",
        "worker thread unresponsive, thread dump shows long-running task holding a lock",
        "burst of HTTP 5xx responses during recent deploy window",
        "NullPointerException raised repeatedly in checkout handler",
        "task executor reported rejected execution: queue full",
    ],
    "config": [
        "requests throttled at gateway despite normal traffic",
        "timeout setting seems too aggressive for slow upstream, requests cut short",
        "config revision changed moments before failures began",
        "routing/authorization config mismatch causing intermittent denials",
        "rate limit policy returning 429 below expected capacity",
    ],
    "dep": [
        "connections to database exhausted, new connections refused",
        "redis read errors logged, fallback path activated",
        "MQ consumer lag growing, messages accumulating on topic",
        "upstream third-party API returning 503 consistently",
        "cache cluster one node unreachable, partial misses increasing",
    ],
    "middleware": [
        "kafka consumer group lag climbing, offsets falling further behind latest",
        "message consumption stalled, queue depth growing rapidly",
        "broker reports connection churn, producers retrying on stale metadata",
        "cache cluster one shard unavailable, key miss ratio rising",
        "redis master failover triggered, replica serving stale reads",
    ],
    "container": [
        "kubelet evicting pod due to node memory pressure",
        "container restarting repeatedly, last exit code 137",
        "pod marked for eviction, disk pressure on node",
        "OOMKilled event recorded for workload, memory over limit",
        "CrashLoopBackOff detected, backoff increasing each restart",
    ],
    "api": [
        "endpoint latency climbing, p99 exceeding SLO threshold",
        "error rate on checkout endpoint rising sharply",
        "circuit breaker opened for checkout endpoint after failures",
        "fallback handler activated for orders endpoint",
        "5xx responses increasing on payment endpoint",
    ],
}

# ── 级联/次生症状(可指向他因,作为干扰或对主症状的次生影响) ──────────
_CASCADE_LOG = {
    "net": [
        "circuit breaker opened for upstream cluster after consecutive failures",
        "thread pool queue backing up as a result of repeated timeouts",
    ],
    "infra": [
        "health check flapping as processes struggle to get CPU",
        "requests timing out under load pressure",
    ],
    "app": [
        "dependent service calls timing out because worker thread abandoned them",
        "queue of HTTP requests growing due to slow processing thread",
    ],
    "config": [
        "some service instances rejecting config, others accepting, half-split",
        "clients seeing intermittent 403 from route policy",
    ],
    "dep": [
        "application logs showing failed calls caused by upstream unavailability",
    ],
    "middleware": [
        "application threads blocked waiting on message acknowledgment",
        "timeouts surfacing on read path that depends on cache lookup",
    ],
    "container": [
        "requests timing out while pod is restarting",
        "health probe failing during container restart window",
    ],
    "api": [
        # 修复 707 盲测: 旧模板 "dependent calls timing out..." 的"依赖调用"语义
        # 会误导 LLM/规则裁判判外部依赖故障。改为不含依赖方语义的接口侧级联表述。
        "inbound requests piling up while endpoint stays degraded",
        "thread pool queue backing up due to slow endpoint responses",
    ],
}

# ── 正常基线日志(无异常信号) ───────────────────────────────────────
_BASELINE_LOG = [
    "heartbeat ok, health check passing",
    "request served normally, latency within SLO",
    "phone-home metrics reported, no anomalies",
    "routine cleanup finished, no errors",
    "config reloaded successfully, no issues",
]

# ── 否定句/同义词干扰(看似排除某些根因,实则含糊) ───────────────────
_NEGATION_LOG = [
    "CPU utilization nominal, flat near baseline",
    "memory usage nominal, well below limit",
    "no application exceptions observed in window",
    "no config changes detected during window",
    "database and cache appear reachable",
]

# ── 指标形态:资源类异常才让 CPU/内存爬升,其余保持 normal ──────────
_METRIC_MODE = {
    "infra": {"cpu": "rising", "mem": "rising"},
    "dep": {"cpu": "moderate", "mem": "moderate"},
    "middleware": {"cpu": "moderate", "mem": "moderate"},
    # net/app/config:资源应正常(作为"排除资源瓶颈"的旁证)
    "net": {"cpu": "normal", "mem": "normal"},
    "app": {"cpu": "normal", "mem": "normal"},
    "config": {"cpu": "normal", "mem": "normal"},
    # container/api:资源侧不作为主治信号,鉴别证据在日志
    "container": {"cpu": "normal", "mem": "normal"},
    "api": {"cpu": "normal", "mem": "normal"},
}


def gen_scenario(seed: int, difficulty: int = 1,
                 force_root: Optional[str] = None) -> Dict[str, Any]:
    """生成一个非预埋盲测场景。

    Args:
        seed: 随机种子(固定可复现)。
        difficulty: 0=单纯症状;1=加干扰;2=干扰+否定+级联。
        force_root: 若给,强制使用该根因(net/infra/app/config/dep/middleware/
                     container/api),便于单元测试与单类样本补足。

    Returns:
        dict,含:
          scenario: {service, logs, metrics, kb}(LLM 全程可见,不含根因)
          ground_truth: 根因类别名(与策略假设 name 一致)
          seed/difficulty/meta
    """
    if difficulty not in (0, 1, 2):
        raise ValueError("difficulty 只能为 0/1/2")
    rng = random.Random(seed)

    root = force_root or rng.choice(list(ROOT_CAUSE_NAMES.keys()))
    ground_truth = ROOT_CAUSE_NAMES[root]

    logs: List[Dict[str, Any]] = []
    # 主治症状(务必拷贝全局模板再洗,避免破坏可复现性)
    primary = list(_PRIMARY_LOG[root])
    k_primary = 2 + difficulty  # 证据越强,主治症状越充分
    rng.shuffle(primary)
    picked = primary[:k_primary]

    for msg in picked:
        level = "ERROR" if root in ("net", "app", "dep", "middleware") else "WARN"
        logs.append({"level": level, "message": msg})
    # 正常基线
    baseline_pool = list(_BASELINE_LOG)
    rng.shuffle(baseline_pool)
    for msg in baseline_pool[:2]:
        logs.append({"level": "INFO", "message": msg})
    # 干扰(难度>=1):从他因的病种里挑 1~2 条,弱化/含混
    if difficulty >= 1:
        other_roots = [k for k in ROOT_CAUSE_NAMES if k != root]
        inter_pool = []
        for other in other_roots:
            inter_pool.extend(_CASCADE_LOG.get(other, []))
            # container 主治(驱逐/OOMKilled/kubelet)信号太强,作干扰会抢走他因场景
            # (1010 回归根因: api 场景被 INFO 级 "kubelet evicting pod" 反复抬容器)。
            # 容器作为干扰只用弱级联信号。
            if other != "container":
                inter_pool.extend(_PRIMARY_LOG[other][:2])  # 只取他因首两条,作为弱干扰
        rng.shuffle(inter_pool)
        for msg in inter_pool[: (1 + int(difficulty * 0.6))]:
            logs.append({"level": "INFO", "message": msg})
    # 级联次生(难度>=2)
    if difficulty >= 2 and _CASCADE_LOG.get(root):
        logs.append({"level": "WARN", "message": rng.choice(_CASCADE_LOG[root])})
        logs.append({"level": "INFO", "message": rng.choice(_NEGATION_LOG)})

    # 打乱并铺时间戳(倒推,最近一条最新)
    rng.shuffle(logs)
    now = datetime.now().replace(microsecond=0)
    for i, line in enumerate(logs):
        ts = (now - timedelta(minutes=len(logs) - i)).strftime("%Y-%m-%d %H:%M:%S")
        line["timestamp"] = ts

    metrics = _METRIC_MODE[root]
    scenario = {
        "service": SERVICE_ID,
        "logs": logs,
        "metrics": metrics,
        "kb": [],
    }
    return {
        "scenario": scenario,
        "ground_truth": ground_truth,
        "seed": seed,
        "difficulty": difficulty,
        "root": root,
        "meta": {"service": SERVICE_ID, "generated_at": datetime.now().isoformat()},
    }


def assert_no_verbatim_answer(scenario: Dict[str, Any]) -> None:
    """断言场景内容不含送分词 —— 防止生成器无意间把答案写进日志。"""
    text = json.dumps(scenario["scenario"], ensure_ascii=False)
    leaked = [t for t in FORBIDDEN_TERMS if t in text]
    if leaked:
        raise AssertionError(f"场景泄漏送分词: {leaked}")
    # 根因类别名也不应作为完整名词出现在可见内容里
    for name in ROOT_CAUSE_NAMES.values():
        if name in text:
            raise AssertionError(f"场景出现根因类别名: {name}")


def write_scenario(scenario: Dict[str, Any], out_path: str) -> str:
    """把场景落地为 JSON(供 MCP 服务查询时读盘)。"""
    out_path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(scenario, f, ensure_ascii=False, indent=2)
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=100)
    ap.add_argument("--difficulty", type=int, choices=[0, 1, 2], default=1)
    ap.add_argument("--force-root", choices=list(ROOT_CAUSE_NAMES), default=None)
    ap.add_argument("--out", default=os.path.join("runtime", "blind_scenario.json"))
    args = ap.parse_args()

    scenario = gen_scenario(args.seed, args.difficulty, args.force_root)
    assert_no_verbatim_answer(scenario)
    path = write_scenario(scenario, args.out)
    print(f"已生成场景 → {path}")
    print(f"  根因(ground_truth): {scenario['ground_truth']}  seed={args.seed}  diff={args.difficulty}")
    print(f"  日志条数: {len(scenario['scenario']['logs'])}  指标: {scenario['scenario']['metrics']}")
    for line in scenario["scenario"]["logs"]:
        print(f"    [{line['level']}] {line['message']}")


if __name__ == "__main__":
    main()
