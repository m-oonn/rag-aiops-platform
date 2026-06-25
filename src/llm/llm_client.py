from typing import List, Optional, Tuple
from langchain_community.chat_models import ChatTongyi
from langchain_core.messages import HumanMessage, SystemMessage
from src.settings import settings
from src.utils.logger import logger

import time
from typing import List, Optional, Tuple

class LLMClient:
    def __init__(self):
        self.model_name = settings.LLM_MODEL
        self.api_key = settings.DASHSCOPE_API_KEY
        
        try:
            self.llm = ChatTongyi(
                model=self.model_name,
                temperature=0.7,
                top_p=0.8,
                api_key=self.api_key,
                streaming=True
            )
        except Exception as e:
            logger.error(f"Failed to initialize LLM Client: {e}")
            self.llm = None

    def generate_response_with_metrics(self, prompt: str) -> Tuple[str, float, float]:
        """
        Generate response and return (content, first_token_latency, total_latency)
        """
        if not self.llm:
            return "LLM Service unavailable.", 0.0, 0.0
            
        start_time = time.time()
        first_token_time = None
        content = ""
        
        try:
            messages = [
                SystemMessage(content="You are a helpful RAG assistant."),
                HumanMessage(content=prompt)
            ]
            
            for chunk in self.llm.stream(messages):
                if first_token_time is None:
                    first_token_time = time.time()
                content += chunk.content
                
            end_time = time.time()
            
            first_token_latency = (first_token_time - start_time) if first_token_time else 0.0
            total_latency = end_time - start_time
            
            return content, first_token_latency, total_latency
            
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            return f"Error generating response: {str(e)}", 0.0, 0.0

    def generate_response(self, query: str, context: str, system_prompt: Optional[str] = None) -> str:
        if not self.llm:
            return "LLM Service unavailable."
            
        # If explicit system prompt is provided (e.g. for QA generation), use it with context
        if system_prompt:
             prompt = f"""{system_prompt}
             
上下文：
{context}

问题：{query}

要求：
1. 基于上下文回答
2. 输出符合指令要求
"""
             return self.generate_custom_response(prompt)

        # Default RAG prompt
        prompt = f"""基于以下上下文信息，回答问题。
        
上下文：
{context}

问题：{query}

要求：
1. 基于上下文回答，不添加外部知识
2. 如上下文无相关信息，明确说明"根据提供的信息无法回答"
3. 引用相关段落编号
4. 保持回答准确、简洁

回答："""

        return self.generate_custom_response(prompt)

    def generate_general_response(self, query: str, context: str = "") -> str:
        """
        Generate a response for general chat without strict RAG constraints.
        """
        if not self.llm:
            return "LLM Service unavailable."
            
        # For general chat, we allow external knowledge
        prompt = f"""You are a helpful assistant.
        
{context}

User Question: {query}

Answer:"""
        
        return self.generate_custom_response(prompt)

    def generate_custom_response(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        if not self.llm:
            return "LLM Service unavailable."
            
        try:
            sys_msg = system_prompt if system_prompt else "You are a helpful RAG assistant."
            messages = [
                SystemMessage(content=sys_msg),
                HumanMessage(content=prompt)
            ]
            response = self.llm.invoke(messages)
            return response.content
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            return f"Error generating response: {str(e)}"
