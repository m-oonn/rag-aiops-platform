import sys
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.services.rag_service import RAGService
from src.services.evaluator import RAGEvaluator
from src.llm.llm_client import LLMClient
from src.utils.logger import logger
import json

def main():
    rag_service = RAGService()
    llm_client = LLMClient()
    evaluator = RAGEvaluator(llm_client)

    # Sample queries for evaluation
    test_queries = [
        "什么是新质生产力？",
        "AI编程助手如何通过KRE理论架构从代码生成演进到系统设计？",
        "商汤日日新·代码小浣熊在评测中表现如何？"
    ]

    eval_results = []

    logger.info(f"Starting RAG evaluation with {len(test_queries)} queries...")

    for query in test_queries:
        logger.info(f"Evaluating query: {query}")
        try:
            # 1. Get RAG Response
            response = rag_service.query(query)
            
            # 2. Evaluate
            eval_result = evaluator.evaluate(
                query=query,
                answer=response["answer"],
                source_documents=response["source_documents"]
            )
            
            eval_results.append(eval_result)
        except Exception as e:
            logger.error(f"Failed to evaluate query '{query}': {e}")

    # 3. Generate Report
    report = evaluator.generate_summary_report(eval_results)
    
    # 4. Save Report
    report_path = project_root / "评估分析汇总.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    
    logger.info(f"Evaluation report generated at: {report_path}")

if __name__ == "__main__":
    main()
