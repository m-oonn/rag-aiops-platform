"""
项目 RAGEvaluator 对照评测 (RAG-PDF-System)
=========================================
目的: 把项目自带的 RAGEvaluator (LLM-as-Judge, 0~10) 跑在 RAGAS 那次评测用的
      *完全相同* 的 10 条样本上, 做方法论 + 数字双对照, 并给出低指标优化 action。

数据来源: data/reports/ragas_eval_20260709_111024_raw.json
          (含 question / contexts / answer / reference 四元组, 与 RAGAS 评测一致)

注意: 项目 RAGEvaluator 的 accuracy 维度需要 ground_truth, 这里不传 (传 None),
       故只对比 faithfulness / relevancy / context_precision 三项。
       归一化: 项目 0~10 ÷ 10 = 0~1, 与 RAGAS 同一量纲。

用法:
  .venv/Scripts/python.exe scripts/compare_with_project_evaluator.py
"""
import sys
import os
import json
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.services.evaluator import RAGEvaluator
from src.llm.llm_client import LLMClient
from src.settings import settings

RAW_PATH = "data/reports/ragas_eval_20260709_111024_raw.json"

# 项目默认模型 qwen3.7-plus 在 DashScope 实测无效, 改为与 RAGAS 一致的 qwen-plus 以保证可跑
settings.LLM_MODEL = "qwen-plus"


def main():
    if not os.path.exists(RAW_PATH):
        raise SystemExit(f"找不到原始四元组文件: {RAW_PATH} (请先跑 run_ragas_eval.py)")

    with open(RAW_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    print(f"[info] 载入样本数 = {len(raw)} (judge 模型={settings.LLM_MODEL})")

    client = LLMClient()
    evaluator = RAGEvaluator(client)

    project_scores = []   # 每样本: {faithfulness, relevancy, context_precision}
    for i, rec in enumerate(raw):
        q = rec["question"]
        a = rec["answer"]
        ctx = [{"text": c} for c in rec["contexts"]]
        try:
            res = evaluator.evaluate(query=q, answer=a, source_documents=ctx, ground_truth=None)
            sc = res.get("scores", {})
            project_scores.append({
                "idx": i + 1,
                "qa_type": rec.get("qa_type"),
                "faithfulness": sc.get("faithfulness"),
                "relevancy": sc.get("relevancy"),
                "context_precision": sc.get("context_precision"),
                "summary": res.get("summary"),
                "error": res.get("error"),
            })
            print(f"[ok] 样本 {i+1} faith={sc.get('faithfulness')} rel={sc.get('relevancy')} prec={sc.get('context_precision')}")
        except Exception as e:
            print(f"[fail] 样本 {i+1}: {e}")
            project_scores.append({"idx": i + 1, "error": str(e)})

    # 聚合 (仅取数值, 忽略 None/error)
    def avg(key):
        vals = [s[key] for s in project_scores if isinstance(s.get(key), (int, float))]
        return round(sum(vals) / len(vals), 4) if vals else None

    means = {
        "faithfulness": avg("faithfulness"),
        "relevancy": avg("relevancy"),
        "context_precision": avg("context_precision"),
    }
    # 归一化到 0~1
    norm = {k: (round(v / 10, 4) if v is not None else None) for k, v in means.items()}

    out = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sample_count": len(raw),
        "project_means_raw_0_10": means,
        "project_means_norm_0_1": norm,
        "per_sample": project_scores,
    }
    os.makedirs("data/reports", exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"data/reports/project_evaluator_cmp_{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[done] 项目评估器对照结果: {path}")
    print("[done] 归一化均值(0~1):", json.dumps(norm, ensure_ascii=False))


if __name__ == "__main__":
    main()
