from typing import List, Dict, Any
import json
from src.llm.llm_client import LLMClient
from src.utils.logger import logger

class QAGenerator:
    def __init__(self):
        self.llm_client = LLMClient()

    def generate_qa_pairs(self, text: str, num_pairs: int = 5, qa_type: str = "general") -> List[Dict[str, str]]:
        type_desc = {
            "single_hop": "单跳问题（Single-hop）：答案直接位于文中的某一句或一段。",
            "multi_hop": "多跳问题（Multi-hop）：需要综合文中多个段落的信息才能回答。",
            "summary": "总结性问题（Summary）：对全文或某一部分的概括。",
            "error": "错误问题（Error）：基于文中不存在的信息提问，或具有误导性的问题（答案应指出文中未提及）。",
            "general": "综合各类问题。"
        }
        
        desc = type_desc.get(qa_type, type_desc["general"])
        
        prompt = f"""
        请根据以下文本生成 {num_pairs} 个高质量的问答对（QA Pair）。
        问题类型重点关注：{desc}
        
        输出格式必须为 JSON 列表，每个元素包含 "question" 和 "answer" 两个字段。
        
        文本内容：
        {text[:3000]}... (截断)
        
        要求：
        1. 问题要具体，答案要准确。
        2. {qa_type}类型的特点要鲜明。
        3. 输出纯 JSON，不要包含 Markdown 格式标记。
        """
        
        system_prompt = "你是一个专业的教育专家，擅长根据教材生成考试题目。"
        if qa_type == "error":
            system_prompt = "你是一个专业的考官，擅长设计陷阱题和干扰项，测试考生对资料的掌握程度。"

        response = self.llm_client.generate_custom_response(prompt, system_prompt=system_prompt)
        
        # Clean response if it contains markdown code blocks
        clean_response = response.replace("```json", "").replace("```", "").strip()
        
        try:
            qa_pairs = json.loads(clean_response)
            if isinstance(qa_pairs, list):
                # Inject type
                for qa in qa_pairs:
                    qa["qa_type"] = qa_type
                return qa_pairs
            else:
                logger.error("LLM returned valid JSON but not a list")
                return []
        except json.JSONDecodeError:
            logger.error(f"Failed to parse QA pairs from LLM response: {response}")
            return []

qa_generator = QAGenerator()
