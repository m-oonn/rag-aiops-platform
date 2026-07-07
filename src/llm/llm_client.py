from typing import List, Optional, Tuple
from langchain_community.chat_models import ChatTongyi
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from src.settings import settings
from src.utils.logger import logger

import time

# Qwen 系列模型前缀，匹配时使用 ChatTongyi（原生 SDK），否则使用 ChatOpenAI（兼容模式）
_QWEN_PREFIXES = ("qwen", "text-embedding")

_DEFAULT_TEMPERATURE = 0.7


def _is_qwen_model(model: str) -> bool:
    """判断是否为 Qwen 系列模型（ChatTongyi 仅支持 Qwen）。"""
    return any(model.lower().startswith(p) for p in _QWEN_PREFIXES)


class LLMClient:
    def __init__(self):
        self.model_name = settings.LLM_MODEL
        self.api_key = settings.DASHSCOPE_API_KEY
        # 缓存已创建的模型实例，避免每次请求都重建
        self._llm_cache: dict = {}
        
        try:
            self.llm = ChatTongyi(
                model=self.model_name,
                temperature=_DEFAULT_TEMPERATURE,
                top_p=0.8,
                api_key=self.api_key,
                streaming=True
            )
            self._llm_cache[(self.model_name, _DEFAULT_TEMPERATURE)] = self.llm
        except Exception as e:
            logger.error(f"Failed to initialize LLM Client: {e}")
            self.llm = None

    def _get_llm(self, model: Optional[str] = None, temperature: Optional[float] = None):
        """获取指定模型 + 温度的 LLM 实例，支持 Qwen 和非 Qwen 模型。

        - Qwen 系列 → ChatTongyi（dashscope 原生 SDK）
        - 非 Qwen（如 deepseek-v3）→ ChatOpenAI（dashscope compatible-mode）
        - model=None 且 temperature=None → 返回缓存的默认实例
        - 实例按 (model, temperature) 缓存，不同温度不复用
        """
        temp = _DEFAULT_TEMPERATURE if temperature is None else temperature
        target_model = model or self.model_name

        # 默认模型 + 默认温度 → 复用初始化实例
        if target_model == self.model_name and temp == _DEFAULT_TEMPERATURE:
            return self.llm

        cache_key = (target_model, temp)
        if cache_key in self._llm_cache:
            return self._llm_cache[cache_key]

        try:
            if _is_qwen_model(target_model):
                new_llm = ChatTongyi(
                    model=target_model,
                    temperature=temp,
                    top_p=0.8,
                    api_key=self.api_key,
                    streaming=True
                )
            else:
                # 非 Qwen 模型走 OpenAI 兼容模式（如 deepseek-v3）
                new_llm = ChatOpenAI(
                    model=target_model,
                    temperature=temp,
                    api_key=self.api_key,
                    base_url=settings.DASHSCOPE_API_BASE,
                    streaming=True
                )
            self._llm_cache[cache_key] = new_llm
            logger.info(f"[LLMClient] 创建模型实例: {target_model}@{temp} ({'ChatTongyi' if _is_qwen_model(target_model) else 'ChatOpenAI'})")
            return new_llm
        except Exception as e:
            logger.error(f"[LLMClient] 创建模型 {target_model}@{temp} 失败，降级到默认模型: {e}")
            return self.llm

    def generate_response_with_metrics(self, prompt: str, model: Optional[str] = None, temperature: Optional[float] = None) -> Tuple[str, float, float]:
        """
        Generate response and return (content, first_token_latency, total_latency)
        """
        llm = self._get_llm(model, temperature)
        if not llm:
            return "LLM Service unavailable.", 0.0, 0.0
            
        start_time = time.time()
        first_token_time = None
        content = ""
        
        try:
            messages = [
                SystemMessage(content="You are a helpful RAG assistant. Please format your response in Markdown."),
                HumanMessage(content=prompt)
            ]
            
            for chunk in llm.stream(messages):
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

    def generate_response(self, query: str, context: str, system_prompt: Optional[str] = None, model: Optional[str] = None, temperature: Optional[float] = None) -> str:
        if not self._get_llm(model, temperature):
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
             return self.generate_custom_response(prompt, model=model, temperature=temperature)

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
5. 使用 Markdown 格式输出，合理使用标题、列表、加粗等排版

回答："""

        return self.generate_custom_response(prompt, model=model, temperature=temperature)

    def generate_general_response(self, query: str, context: str = "", model: Optional[str] = None, temperature: Optional[float] = None) -> str:
        """
        Generate a response for general chat without strict RAG constraints.
        """
        if not self._get_llm(model, temperature):
            return "LLM Service unavailable."

        # For general chat, we allow external knowledge
        prompt = f"""你是一个有帮助的 AI 助手，请使用 Markdown 格式回答用户的问题。

当前日期: 2026-07-06。

{context}

用户问题: {query}

请使用 Markdown 格式回答（合理使用标题、列表、加粗、代码块等排版）："""

        return self.generate_custom_response(prompt, model=model, temperature=temperature)

    def generate_general_response_stream(self, query: str, context: str = "", model: Optional[str] = None, temperature: Optional[float] = None):
        """
        纯聊天的流式版本:逐 token yield,供 SSE 端点消费。
        与 generate_general_response 同一 prompt 拼法,只是改为流式输出。
        """
        llm = self._get_llm(model, temperature)
        if not llm:
            yield "LLM Service unavailable."
            return

        prompt = f"""你是一个有帮助的 AI 助手，请使用 Markdown 格式回答用户的问题。

当前日期: 2026-07-06。

{context}

用户问题: {query}

请使用 Markdown 格式回答（合理使用标题、列表、加粗、代码块等排版）："""

        messages = [
            SystemMessage(content="你是一个有帮助的 AI 助手，请使用 Markdown 格式输出回答。"),
            HumanMessage(content=prompt)
        ]

        try:
            for chunk in llm.stream(messages):
                if chunk.content:
                    yield chunk.content
        except Exception as e:
            logger.error(f"LLM stream failed (model={model or self.model_name}): {e}")
            yield f"[生成出错: {str(e)}]"

    def generate_custom_response(self, prompt: str, system_prompt: Optional[str] = None, model: Optional[str] = None, temperature: Optional[float] = None) -> str:
        llm = self._get_llm(model, temperature)
        if not llm:
            return "LLM Service unavailable."
            
        try:
            sys_msg = system_prompt if system_prompt else "You are a helpful RAG assistant. Please format your response in Markdown."
            messages = [
                SystemMessage(content=sys_msg),
                HumanMessage(content=prompt)
            ]
            response = llm.invoke(messages)
            return response.content
        except Exception as e:
            logger.error(f"LLM generation failed (model={model or self.model_name}): {e}")
            return f"Error generating response: {str(e)}"
