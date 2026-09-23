"""6 类运维故障逐类 precision/recall 评测。

口径: 用户的 6 类运维故障 = 主机资源 / 容器 / 数据库 / 中间件 / 网络请求 / 服务接口。
数据源: runtime/blind_eval_results.json(盲测每场景的 ground_truth + top_name)。

两种口径:
  - strict(精确): 系统假设类别映射到 6 类, "外部依赖故障"未细分数据库/中间件 → 不算命中
    (如实反映系统假设空间的粒度不足);
  - loose(宽容): "外部依赖故障"命中数据库或中间件场景均算正确(粒度放宽到"依赖层")。

输出: runtime/eval_precision_recall.json + 控制台汇总。
"""

import json
import os
from collections import defaultdict
from typing import Dict, Optional

FAULT_ORDER = ["主机资源", "容器", "数据库", "中间件", "网络请求", "服务接口"]

# 盲测 case id -> 6 类运维故障(不在 6 类的场景=None,不参与 6 类评测)
CASE_TO_FAULT: Dict[str, Optional[str]] = {
    "101-net.dynamic": "网络请求",
    "202-infra.dynamic": "主机资源",
    "303-dep.dynamic": "数据库",       # payment 连接池
    "404-config.dynamic": None,        # 配置错误(非 6 类)
    "505-app.dynamic": None,           # 应用层(非 6 类)
    "606-net.dynamic": "网络请求",
    "707-infra.dynamic": "主机资源",
    "808-app.dynamic": None,           # 应用层(非 6 类)
    "909-container.dynamic": "容器",
    "1010-api.dynamic": "服务接口",
    # 中间件(2026-09-15): 假设名为外部依赖故障,按 case id 细分为中间件类
    "1111-middleware.dynamic": "中间件",
    "1212-middleware.dynamic": "中间件",
}

# 系统假设类别 -> 6 类(严格口径, 无映射=None)
TOP_TO_FAULT_STRICT: Dict[str, Optional[str]] = {
    "基础设施/资源瓶颈": "主机资源",
    "容器问题": "容器",
    "网络/连通性问题": "网络请求",
    "服务接口异常": "服务接口",
    "外部依赖故障": None,               # 未细分数据库/中间件
    "应用层异常": None,
    "配置错误": None,
}

# 宽容口径: 外部依赖故障命中数据库/中间件场景都算正确
TOP_TO_FAULT_LOOSE: Dict[str, Optional[str]] = {
    **TOP_TO_FAULT_STRICT,
    "外部依赖故障": "外部依赖(数据库/中间件)",
}


def load_results() -> dict:
    path = os.path.join("runtime", "blind_eval_results.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def evaluate(results: dict, loose: bool = False) -> dict:
    mapping = TOP_TO_FAULT_LOOSE if loose else TOP_TO_FAULT_STRICT
    tp: Dict[str, int] = defaultdict(int)
    fp: Dict[str, int] = defaultdict(int)
    fn: Dict[str, int] = defaultdict(int)
    per_case = []

    for case_id, r in results.items():
        gt_fault = CASE_TO_FAULT.get(case_id)
        pred_name = r.get("top_name", "")
        # 未命中(空报告)视为"无预测"
        if not r.get("hit") and not pred_name:
            pred_fault = None
        else:
            pred_fault = mapping.get(pred_name)

        record = {
            "case": case_id,
            "ground_truth": gt_fault,
            "top_name": pred_name,
            "hit": r.get("hit"),
            "steps": r.get("steps"),
        }
        per_case.append(record)

        if gt_fault is None:
            continue  # 非 6 类场景不计入

        if loose and pred_fault == "外部依赖(数据库/中间件)" and gt_fault in ("数据库", "中间件"):
            pred_fault = gt_fault

        if pred_fault == gt_fault:
            tp[gt_fault] += 1
            record["evaluation"] = "TP"
        elif pred_fault is not None:
            fp[pred_fault] += 1
            fn[gt_fault] += 1
            record["evaluation"] = "FN"
        else:
            fn[gt_fault] += 1
            record["evaluation"] = "FN"

    items = []
    total_tp = total_fp = total_fn = 0
    for fault in FAULT_ORDER:
        t, f, n = tp[fault], fp[fault], fn[fault]
        total_tp += t
        total_fp += f
        total_fn += n
        items.append({
            "fault": fault,
            "samples": t + n,
            "tp": t,
            "fp": f,
            "fn": n,
            "precision": round(t / (t + f), 3) if (t + f) else 0.0,
            "recall": round(t / (t + n), 3) if (t + n) else 0.0,
        })

    macro_precision = round(sum(i["precision"] for i in items) / len(items), 3)
    macro_recall = round(sum(i["recall"] for i in items) / len(items), 3)
    micro_precision = round(total_tp / (total_tp + total_fp), 3) if (total_tp + total_fp) else 0.0
    micro_recall = round(total_tp / (total_tp + total_fn), 3) if (total_tp + total_fn) else 0.0

    return {
        "口径": "loose(外部依赖命中数据库/中间件)" if loose else "strict(外部依赖不细分)",
        "6类样本分布": {f: next(i["samples"] for i in items if i["fault"] == f) for f in FAULT_ORDER},
        "items": items,
        "macro_precision": macro_precision,
        "macro_recall": macro_recall,
        "micro_precision": micro_precision,
        "micro_recall": micro_recall,
        "per_case": per_case,
    }


def main():
    results = load_results()
    out = {"results_file": "runtime/blind_eval_results.json", "strict": evaluate(results, loose=False),
           "loose": evaluate(results, loose=True)}

    for label in ("strict", "loose"):
        e = out[label]
        print(f"\n===== 口径: {label} ({e['口径']}) =====")
        print(f"{'故障类':<6} {'样本':<4} {'TP':<4} {'FP':<4} {'FN':<4} {'P':<7} {'R':<7}")
        for i in e["items"]:
            print(f"{i['fault']:<6} {i['samples']:<4} {i['tp']:<4} {i['fp']:<4} {i['fn']:<4} "
                  f"{i['precision']:<7} {i['recall']:<7}")
        print(f"macro P={e['macro_precision']}  R={e['macro_recall']}")
        print(f"micro P={e['micro_precision']}  R={e['micro_recall']}")

    with open(os.path.join("runtime", "eval_precision_recall.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\n已写入 runtime/eval_precision_recall.json")


if __name__ == "__main__":
    main()
