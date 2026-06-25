from typing import List, Dict, Any
from src.llm.llm_client import LLMClient
from src.utils.logger import logger
import json
from datetime import datetime

class RAGEvaluator:
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    def evaluate(self, query: str, answer: str, source_documents: List[Dict[str, Any]], ground_truth: str = None) -> Dict[str, Any]:
        """
        Evaluate a single RAG response.
        """
        context = "\n".join([doc.get("text", "") for doc in source_documents])
        
        prompt = f"""作为一名专业的 RAG 系统评测专家，请根据以下信息对系统回答进行评测。

[用户问题]: {query}
[系统回答]: {answer}
[参考答案 (Ground Truth)]: {ground_truth if ground_truth else "无"}
[检索上下文]: {context}

请从以下四个维度进行评分（0-10分）并给出理由：
1. 忠实度 (Faithfulness): 回答是否完全基于检索到的上下文？是否存在幻觉？
2. 相关性 (Relevancy): 回答是否直接且完整地解决了用户的问题？
3. 上下文精度 (Context Precision): 检索到的上下文片段是否与回答问题高度相关？
4. 准确性 (Accuracy): 系统回答与参考答案的一致性程度（仅当提供参考答案时评分，否则忽略）。

请以 JSON 格式返回评测结果：
{{
  "scores": {{
    "faithfulness": 0,
    "relevancy": 0,
    "context_precision": 0,
    "accuracy": 0
  }},
  "reasons": {{
    "faithfulness": "...",
    "relevancy": "...",
    "context_precision": "...",
    "accuracy": "..."
  }},
  "overall_score": 0,
  "summary": "综合评价..."
}}
"""
        try:
            response = self.llm_client.generate_custom_response(prompt)
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                result["timestamp"] = datetime.now().isoformat()
                result["query"] = query
                return result
            else:
                return {"error": "Failed to parse evaluation JSON"}
        except Exception as e:
            logger.error(f"Evaluation failed: {e}")
            return {"error": str(e)}

    def generate_summary_report(self, eval_results: List[Dict[str, Any]]) -> str:
        """
        Generate a Markdown summary report from a list of evaluation results.
        """
        if not eval_results:
            return "无评测数据。"

        total_faith = sum(r.get("scores", {}).get("faithfulness", 0) for r in eval_results) / len(eval_results)
        total_rel = sum(r.get("scores", {}).get("relevancy", 0) for r in eval_results) / len(eval_results)
        total_prec = sum(r.get("scores", {}).get("context_precision", 0) for r in eval_results) / len(eval_results)
        avg_overall = sum(r.get("overall_score", 0) for r in eval_results) / len(eval_results)
        
        # Latency Metrics
        avg_first_token = sum(r.get("metrics", {}).get("first_token_latency", 0) for r in eval_results) / len(eval_results)
        avg_total_latency = sum(r.get("metrics", {}).get("total_latency", 0) for r in eval_results) / len(eval_results)

        # Type Breakdown
        type_stats = {}
        for r in eval_results:
            qa_type = r.get("qa_type", "unknown")
            if qa_type not in type_stats:
                type_stats[qa_type] = {"count": 0, "overall_score": 0, "first_token": 0, "total_time": 0}
            
            type_stats[qa_type]["count"] += 1
            type_stats[qa_type]["overall_score"] += r.get("overall_score", 0)
            type_stats[qa_type]["first_token"] += r.get("metrics", {}).get("first_token_latency", 0)
            type_stats[qa_type]["total_time"] += r.get("metrics", {}).get("total_latency", 0)
            
        for t in type_stats:
            count = type_stats[t]["count"]
            if count > 0:
                type_stats[t]["overall_score"] /= count
                type_stats[t]["first_token"] /= count
                type_stats[t]["total_time"] /= count

        report = f"""# RAG 系统评测分析汇总报告
报告生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
评测样本数: {len(eval_results)}

## 1. 核心指标概览
- **平均综合得分**: {avg_overall:.2f} / 10
- **忠实度 (Faithfulness)**: {total_faith:.2f} / 10
- **相关性 (Relevancy)**: {total_rel:.2f} / 10
- **上下文精度 (Context Precision)**: {total_prec:.2f} / 10
- **平均首字响应时间**: {avg_first_token:.4f} s
- **平均完整响应时间**: {avg_total_latency:.4f} s

## 2. 场景维度分析
| 场景类型 | 样本数 | 平均得分 | 首字延迟 (s) | 完整延迟 (s) |
|---|---|---|---|---|
"""
        for t, stats in type_stats.items():
            report += f"| {t} | {stats['count']} | {stats['overall_score']:.2f} | {stats['first_token']:.4f} | {stats['total_time']:.4f} |\n"

        report += f"""
## 3. 指标详情分析
- **忠实度**: 反映了系统避免幻觉的能力。目前得分 {total_faith:.2f}，表明系统在基于文档回答方面的表现。
- **相关性**: 反映了系统对用户意图的理解和回答质量。
- **上下文精度**: 反映了检索模块的有效性。

## 4. 典型案例分析
"""
        # Add top 3 results
        for i, res in enumerate(eval_results[:3]):
            report += f"""
### 案例 {i+1}
- **问题**: {res.get("query")}
- **类型**: {res.get("qa_type")}
- **综合得分**: {res.get("overall_score")}
- **评价总结**: {res.get("summary")}
"""
        
        report += """
## 5. 优化建议
1. 如果**上下文精度**较低，建议优化向量检索参数或增强 Rerank 模型。
2. 如果**忠实度**较低，建议调整 Prompt 以强化“仅基于上下文回答”的约束。
3. 如果**相关性**较低，考虑引入多跳识别和查询重写。
"""
        return report
