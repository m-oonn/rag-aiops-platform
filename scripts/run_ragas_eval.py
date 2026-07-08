"""
RAGAS 实跑评测脚本 (RAG-PDF-System)
====================================
目标: 用 RAGAS 标准指标对真实项目数据做 RAG 质量评估, 替代/对照项目现有自定义 RAGEvaluator。

数据来源 (SQLite rag_system.db):
  - generated_qa_pairs : 问题(question) + 标准答案(answer 作 reference)
  - document_chunks    : 对应文档的真实分块, 作为 "检索到的上下文" (contexts)

为什么绕开 Milvus:
  本沙箱未启动 Milvus 向量库, 无法走真实向量检索。改为用 QA 对来源文档的 chunk
  作为 "黄金上下文", 再用 LLM 基于这些上下文重新生成 answer, 从而凑齐 RAGAS 需要的
  (question, contexts, answer, reference) 四元组。这能真实反映 "给定上下文时 RAG 的生成
  与忠实度", 指标可解释。

Judge 模型: qwen-max (settings 默认 qwen3.7-plus 在 DashScope 实测无效, 故显式指定)
Embedding : DashScope text-embedding-v1 (项目既有, 1536 维)

指标 (RAGAS 0.4.3):
  - faithfulness      : answer 是否完全基于 contexts (LLM judge)
  - answer_relevancy  : answer 是否切题 (LLM judge)
  - context_precision : 检索到的 contexts 是否相关 (LLM judge)
  - context_recall    : contexts 是否覆盖 reference (LLM judge)

用法:
  .venv/Scripts/python.exe scripts/run_ragas_eval.py [--limit N]
"""
import sys
import os
import json
import argparse
from datetime import datetime

# 项目根目录加入 path, 以便 import src.*
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from langchain_community.chat_models import ChatTongyi
from langchain_core.embeddings import Embeddings

from ragas import evaluate
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_precision,
    context_recall,
)
from datasets import Dataset

from src.settings import settings
from src.database.sql_session import SessionLocal
from src.database.models import GeneratedQAPair, DocumentChunk
from src.embedding.dashscope_embedding import DashScopeEmbeddingService


# ----------------------------------------------------------------------------
# 1. 把项目既有 DashScopeEmbeddingService 包装成 LangChain Embeddings (RAGAS 兼容)
# ----------------------------------------------------------------------------
class RagasDashScopeEmbeddings(Embeddings):
    """委托给项目既有 DashScopeEmbeddingService, 暴露 LangChain Embeddings 接口。"""

    def __init__(self):
        self._svc = DashScopeEmbeddingService()

    def embed_documents(self, texts):
        return self._svc.embed_documents(texts)

    def embed_query(self, text):
        return self._svc.embed_query(text)


# ----------------------------------------------------------------------------
# 2. 基于给定上下文生成 answer (模拟 RAG 生成步, 绕开 Milvus 检索)
# ----------------------------------------------------------------------------
RAG_PROMPT = """基于以下上下文信息，回答问题。

上下文：
{context}

问题：{query}

要求：
1. 基于上下文回答，不添加外部知识
2. 如上下文无相关信息，明确说明"根据提供的信息无法回答"
3. 保持回答准确、简洁
4. 使用 Markdown 格式输出

回答："""


def generate_answer(llm, query: str, contexts: list) -> str:
    prompt = RAG_PROMPT.format(context="\n\n".join(contexts), query=query)
    try:
        resp = llm.invoke(prompt)
        return resp.content if hasattr(resp, "content") else str(resp)
    except Exception as e:
        return f"[生成失败: {e}]"


# ----------------------------------------------------------------------------
# 3. 主流程
# ----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10, help="评测样本数 (默认 10, 即全部)")
    parser.add_argument("--model", type=str, default="qwen-max", help="Judge / 生成模型")
    args = parser.parse_args()

    api_key = settings.DASHSCOPE_API_KEY
    if not api_key:
        raise SystemExit("DASHSCOPE_API_KEY 未配置, 无法运行 RAGAS (需要 LLM judge + embedding)。")

    # --- 构造 RAGAS 需要的 llm / embeddings ---
    llm = ChatTongyi(model=args.model, api_key=api_key, streaming=False)
    ragas_llm = LangchainLLMWrapper(llm)
    ragas_embeddings = LangchainEmbeddingsWrapper(RagasDashScopeEmbeddings())

    # --- 取评测数据 ---
    db = SessionLocal()
    qa_pairs = (
        db.query(GeneratedQAPair)
        .filter(GeneratedQAPair.doc_id.isnot(None))
        .limit(args.limit)
        .all()
    )
    if not qa_pairs:
        raise SystemExit("generated_qa_pairs 中没有带 doc_id 的样本, 无法评测。")

    questions, contexts_list, answers, references = [], [], [], []
    raw_records = []

    for qa in qa_pairs:
        chunks = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.doc_id == qa.doc_id)
            .order_by(DocumentChunk.id)
            .all()
        )
        ctx = [c.content for c in chunks if c.content]
        if not ctx:
            continue
        ans = generate_answer(llm, qa.question, ctx)

        questions.append(qa.question)
        contexts_list.append(ctx)
        answers.append(ans)
        references.append(qa.answer)  # generated_qa_pairs.answer 当作 ground truth / reference
        raw_records.append({
            "qa_id": qa.id,
            "doc_id": qa.doc_id,
            "qa_type": qa.qa_type,
            "question": qa.question,
            "reference": qa.answer,
            "contexts": ctx,
            "answer": ans,
        })
    db.close()

    n = len(questions)
    print(f"[info] 评测样本数 = {n}")

    # --- 构造 RAGAS Dataset ---
    dataset = Dataset.from_dict({
        "question": questions,
        "contexts": contexts_list,
        "answer": answers,
        "reference": references,
    })

    # --- 跑 RAGAS ---
    metrics = [faithfulness, answer_relevancy, context_precision, context_recall]
    print("[info] 开始 RAGAS 评估 (faithfulness/answer_relevancy/context_precision/context_recall) ...")
    result = evaluate(
        dataset,
        metrics=metrics,
        llm=ragas_llm,
        embeddings=ragas_embeddings,
        raise_exceptions=False,
        show_progress=True,
    )

    # --- 汇总 ---
    df = result.to_pandas()
    summary = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "judge_model": args.model,
        "embedding_model": settings.EMBEDDING_MODEL,
        "sample_count": n,
        "metrics_mean": {col: round(float(df[col].mean()), 4) for col in df.columns},
        "metrics_per_sample": df.to_dict(orient="records"),
    }

    # --- 落盘 ---
    os.makedirs("data/reports", exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = f"data/reports/ragas_eval_{ts}.json"
    md_path = f"data/reports/ragas_eval_{ts}.md"
    raw_path = f"data/reports/ragas_eval_{ts}_raw.json"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(raw_records, f, ensure_ascii=False, indent=2)

    means = summary["metrics_mean"]
    md = f"""# RAGAS 实跑评测报告

- 生成时间: {summary['generated_at']}
- Judge 模型: {args.model}
- Embedding 模型: {settings.EMBEDDING_MODEL}
- 评测样本数: {n}

> 数据来源: `generated_qa_pairs`(问题+标准答案) + `document_chunks`(来源文档真实分块作上下文)。
> 说明: 沙箱未启动 Milvus, 用来源文档 chunk 作 "黄金上下文" 并据此重新生成 answer,
> 绕开向量检索但保留 RAGAS 四元组 (question/contexts/answer/reference), 指标可解释。

## 一、核心指标均值 (0~1)

| 指标 | 含义 | 均值 |
|---|---|---|
| faithfulness | 答案是否完全基于上下文 (无幻觉) | {means.get('faithfulness', 'NA')} |
| answer_relevancy | 答案是否切题 | {means.get('answer_relevancy', 'NA')} |
| context_precision | 检索上下文是否相关 | {means.get('context_precision', 'NA')} |
| context_recall | 上下文是否覆盖参考答案 | {means.get('context_recall', 'NA')} |

## 二、与项目现有自定义评估器 (RAGEvaluator) 对照

| 维度 | 本项目 RAGEvaluator (0~10 LLM judge) | RAGAS 标准 (0~1) |
|---|---|---|
| 忠实度 | faithfulness | faithfulness |
| 相关性 | relevancy | answer_relevancy |
| 上下文精度 | context_precision | context_precision |
| 准确性 | accuracy (需 ground truth) | context_recall (覆盖度) |

RAGAS 优势: 指标定义标准化、社区统一、可直接横向对比业界基线; 本项目评估器胜在
可自由加 latency / 场景维度拆分。两者可并存: 用 RAGAS 做标准质量分, 用本项目评估器做
工程侧 (延迟/场景) 分析。

## 三、逐样本明细

| # | 类型 | faithfulness | answer_relevancy | context_precision | context_recall |
|---|---|---|---|---|---|
"""
    for i, rec in enumerate(summary["metrics_per_sample"]):
        md += (
            f"| {i+1} | {raw_records[i]['qa_type']} "
            f"| {rec.get('faithfulness', 'NA')} | {rec.get('answer_relevancy', 'NA')} "
            f"| {rec.get('context_precision', 'NA')} | {rec.get('context_recall', 'NA')} |\n"
        )

    md += f"\n## 四、原始记录\n\n完整 question/contexts/answer/reference 见: `{os.path.basename(raw_path)}`\n"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"[done] 报告已生成:\n  - {md_path}\n  - {json_path}\n  - {raw_path}")
    print("[done] 指标均值:", json.dumps(means, ensure_ascii=False))


if __name__ == "__main__":
    main()
