from typing import Dict, Any
from src.llm.llm_client import LLMClient
from src.utils.logger import logger
import json
import re


class QuestionAnalyzer:
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    def analyze(self, query: str) -> Dict[str, Any]:
        """
        Analyze the user question for routing and retrieval strategy.
        Returns intent (chat/knowledge/diagnosis) and multi-hop decomposition.
        """
        prompt = f"""分析以下用户问题，返回两个判断维度：

## 维度 1：intent（意图分类）
- "chat"：闲聊、问候、简单事实，不需要查资料也不需要调用工具
- "knowledge"：关于文档/知识库内容的问题，需要检索资料来回答
- "diagnosis"：运维诊断、故障排查、监控指标相关，需要调用工具获取数据

## 维度 2：is_multi_hop（是否多跳问题）
- true：隐含多个子查询，需要整合多个文档片段的信息或多步推理
- false：意图明确直接，可以在单个文档片段中找到完整答案

用户问题：{query}

请以 JSON 格式返回分析结果：
{{
  "intent": "chat|knowledge|diagnosis",
  "is_multi_hop": false,
  "sub_queries": [],
  "reason": "简短的判断理由"
}}

示例：
- "你好" → {{"intent": "chat", "is_multi_hop": false, "sub_queries": [], "reason": "简单问候"}}
- "AI编程助手的优势" → {{"intent": "knowledge", "is_multi_hop": false, "sub_queries": [], "reason": "询问文档内容"}}
- "data-sync-service CPU飙高了" → {{"intent": "diagnosis", "is_multi_hop": false, "sub_queries": [], "reason": "运维故障排查"}}
"""
        try:
            response_content = self.llm_client.generate_custom_response(prompt)
            json_match = re.search(r'\{.*\}', response_content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                # 确保 intent 字段存在（向后兼容）
                result.setdefault("intent", "chat")
                return result
            else:
                return {"intent": "chat", "is_multi_hop": False, "sub_queries": [],
                        "reason": "解析失败，默认 chat"}
        except Exception as e:
            logger.error(f"Question analysis failed: {e}")
            return {"intent": "chat", "is_multi_hop": False, "sub_queries": [],
                    "reason": f"异常: {str(e)}"}
