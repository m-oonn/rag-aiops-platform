from typing import Dict, Any
from src.llm.llm_client import LLMClient
from src.utils.logger import logger
import json

class QuestionAnalyzer:
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    def analyze(self, query: str) -> Dict[str, Any]:
        """
        Analyze if a question is single-hop or multi-hop.
        Returns a dict with 'type' (single/multi) and 'sub_queries' if multi.
        """
        prompt = f"""分析以下用户问题，判断其属于“单跳问题”还是“多跳问题”。
        
“单跳问题”：意图明确直接，通常包含单一信息需求，可以在单个文档片段中找到完整答案。
“多跳问题”：隐含多个子查询，需要整合多个文档片段的信息或多步推理才能完整回答。

用户问题：{query}

请以 JSON 格式返回分析结果，包含以下字段：
1. is_multi_hop: 布尔值，是否为多跳问题
2. sub_queries: 如果是多跳问题，请将其分解为 2-3 个具体的子查询步骤；如果是单跳问题，该列表为空。
3. reason: 简短的判断理由。

示例返回：
{{
  "is_multi_hop": true,
  "sub_queries": ["子查询1...", "子查询2..."],
  "reason": "问题涉及两个不同章节的内容整合..."
}}
"""
        try:
            # We use a lower temperature for analysis
            # Since our LLMClient doesn't support temp override yet, we'll just use it as is
            # or we could add a method to LLMClient for generic completions.
            
            # For now, let's assume we can use the same invoke logic
            response_content = self.llm_client.generate_custom_response(prompt)
            # Try to extract JSON
            import re
            json_match = re.search(r'\{.*\}', response_content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            else:
                return {"is_multi_hop": False, "sub_queries": [], "reason": "解析失败，默认单跳"}
        except Exception as e:
            logger.error(f"Question analysis failed: {e}")
            return {"is_multi_hop": False, "sub_queries": [], "reason": f"异常: {str(e)}"}
