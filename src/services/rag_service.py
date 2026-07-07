from typing import List, Dict, Any, Optional
from src.retrieval.hybrid_retriever import HybridRetriever
from src.retrieval.reranker import DashScopeReranker
from src.llm.llm_client import LLMClient
from src.utils.logger import logger
from src.utils.tracing import get_trace_id, trace_span
from src.settings import settings
from src.services.question_analyzer import QuestionAnalyzer
from src.services.memory_service import MemorySystem
from src.services.agent_tool_service import execute_agent_query


# ── 意图快过滤（规则命中则跳过 LLM 分类，0ms） ──

_CHAT_PATTERNS = [
    "你好", "hello", "hi", "谢谢", "感谢", "再见", "拜拜",
    "你是谁", "你叫什么", "早上好", "晚上好", "下午好",
]

_DIAGNOSIS_PATTERNS = [
    "cpu", "内存", "memory", "磁盘", "disk", "网络", "network",
    "告警", "alarm", "alert", "故障", "宕机", "down",
    "延迟高", "latency", "超时", "timeout", "oom", "泄漏", "leak",
    "慢", "slow", "报错", "异常", "error",
]


def _quick_intent_check(query: str) -> Optional[str]:
    """规则预过滤：对明显场景快速返回意图标签，不确定则返回 None 交给 LLM。

    Returns:
        "chat" / "diagnosis" / None
    """
    q = query.strip().lower()
    if not q:
        return None

    # 闲聊：短句 + 包含问候/致谢类关键词
    if len(q) < 15 and any(p in q for p in _CHAT_PATTERNS):
        return "chat"

    # 运维诊断：包含监控/故障类关键词
    if any(p in q for p in _DIAGNOSIS_PATTERNS):
        return "diagnosis"

    return None


def _assess_retrieval_quality(results: List[Any], top_k: int) -> None:
    """评价检索质量，输出结构化日志供监控告警。"""
    if not results:
        logger.warning("[retrieval_quality] 检索结果为空, top_k=%d", top_k)
        return
    scores = [r.score for r in results if r.score is not None]
    if not scores:
        logger.info("[retrieval_quality] 检索结果无评分, count=%d", len(results))
        return
    max_score = max(scores)
    avg_score = sum(scores) / len(scores)
    below_half = sum(1 for s in scores if s < 0.5)
    logger.info(
        "[retrieval_quality] count=%d max=%.3f avg=%.3f below_0.5=%d/%d",
        len(results), max_score, avg_score, below_half, len(scores),
    )


class RAGService:
    def __init__(self):
        self.retriever = HybridRetriever()
        self.llm_client = LLMClient()
        self.reranker = DashScopeReranker()
        self.analyzer = QuestionAnalyzer(self.llm_client)
        self.memory = MemorySystem()

    async def query(
        self,
        query_text: str,
        top_k: int = 5,
        session_id: str = "default",
        kb_ids: Optional[List[int]] = None,
        assistant_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        async with trace_span("rag_service.query", session_id=session_id):
            system_prompt = assistant_config.get("system_prompt") if assistant_config else None
            agent_ids = assistant_config.get("agent_ids") if assistant_config else None
            agents = assistant_config.get("agents") if assistant_config else None
            llm_model = assistant_config.get("llm_model") if assistant_config else None  # 前端/助手切换的模型
            temperature = assistant_config.get("temperature") if assistant_config else None  # 助手配置的采样温度

            memory_config = (assistant_config.get("memory_config") if assistant_config else None) or {}
            enable_short_term = memory_config.get("enable_short_term", True)
            window_size = memory_config.get("window_size", 10)

            history = []
            if enable_short_term:
                history = self.memory.get_short_term_memory(session_id, limit=window_size)

            history_str = "\n".join([f"{m['role']}: {m['content']}" for m in history])

            enable_long_term = memory_config.get("enable_long_term", False)
            long_term_context = ""
            if enable_long_term:
                logger.info(f"Long-term memory enabled for session {session_id}")

            # ── 意图路由（Step 6） ──
            # 第一层：规则快过滤（0ms）
            intent = _quick_intent_check(query_text)

            # 第二层：LLM 意图分类（仅在规则未命中时调用）
            analysis = None
            if intent is None:
                contextual_query = f"历史对话:\n{history_str}\n当前问题: {query_text}" if history else query_text
                analysis = self.analyzer.analyze(contextual_query)
                intent = analysis.get("intent", "chat")
                logger.info(f"Question Analysis: {analysis}")
            else:
                logger.info(f"Quick intent check: {intent}")

            has_kb = bool(kb_ids)
            has_agent = bool(agent_ids and agents)

            # ── 路由决策矩阵 ──

            # chat 意图 → 永远走 General Chat
            if intent == "chat":
                return self._general_chat(query_text, history, history_str, long_term_context,
                                          system_prompt, session_id, llm_model, temperature)

            # knowledge 意图
            if intent == "knowledge":
                if has_kb:
                    return self._rag_path(query_text, top_k, history_str, kb_ids,
                                             system_prompt, session_id, llm_model, analysis, temperature)
                else:
                    return self._general_chat(query_text, history, history_str, long_term_context,
                                              system_prompt, session_id, llm_model, temperature)

            # diagnosis 意图
            if intent == "diagnosis":
                if has_agent:
                    return await self._agent_path(query_text, top_k, kb_ids, session_id,
                                                  agent_ids, agents)
                elif has_kb:
                    # 无 Agent 但有 KB → 从知识库找排查文档
                    return self._rag_path(query_text, top_k, history_str, kb_ids,
                                          system_prompt, session_id, llm_model, analysis, temperature)
                else:
                    return self._general_chat(query_text, history, history_str, long_term_context,
                                              system_prompt, session_id, llm_model, temperature)

            # 兜底 → General Chat
            return self._general_chat(query_text, history, history_str, long_term_context,
                                      system_prompt, session_id, llm_model, temperature)

    # ── 路由路径实现 ──

    def _general_chat(
        self, query_text: str, history: list, history_str: str,
        long_term_context: str, system_prompt: str, session_id: str,
        llm_model: Optional[str] = None, temperature: Optional[float] = None
    ) -> Dict[str, Any]:
        """General Chat 路径：直接 LLM 对话，不检索不调工具。"""
        context = f"历史对话:\n{history_str}" if history else ""
        if long_term_context:
            context = f"长期记忆:\n{long_term_context}\n\n{context}"
        if system_prompt:
            context = f"系统指令: {system_prompt}\n\n{context}"

        answer = self.llm_client.generate_general_response(query_text, context, model=llm_model, temperature=temperature)
        self.memory.add_short_term_memory(session_id, "user", query_text)
        self.memory.add_short_term_memory(session_id, "assistant", answer)
        return {"query": query_text, "answer": answer, "source_documents": []}

    def _rag_path(
        self, query_text: str, top_k: int, history_str: str,
        kb_ids: List[int], system_prompt: str, session_id: str,
        llm_model: Optional[str] = None,
        analysis: Optional[Dict] = None,
        temperature: Optional[float] = None
    ) -> Dict[str, Any]:
        """RAG 路径：混合检索 + 生成。支持单跳和多跳。"""
        if analysis and settings.ENABLE_MULTI_HOP and analysis.get("is_multi_hop"):
            result = self._multi_hop_query(
                query_text, analysis.get("sub_queries", []),
                top_k, history_str, kb_ids, system_prompt, llm_model, temperature
            )
        else:
            result = self._single_hop_query(
                query_text, top_k, history_str, kb_ids, system_prompt, llm_model, temperature
            )

        self.memory.add_short_term_memory(session_id, "user", query_text)
        self.memory.add_short_term_memory(session_id, "assistant", result["answer"])
        return result

    async def _agent_path(
        self, query_text: str, top_k: int, kb_ids: Optional[List[int]],
        session_id: str, agent_ids: list, agents: list
    ) -> Dict[str, Any]:
        """Agent 路径：MCP 工具调用 + 可选 RAG 增强。"""
        agent = agents[0]
        augmented_query = query_text

        if kb_ids:
            try:
                rag_results = self.retriever.retrieve(query_text, top_k=top_k, kb_ids=kb_ids)
                if rag_results:
                    if settings.ENABLE_RERANK:
                        rag_results = self.reranker.rerank(query_text, rag_results)
                    context_snippets = [r.text for r in rag_results[:top_k]]
                    augmented_query = (
                        f"{query_text}\n\n"
                        f"【知识库参考资料】\n" +
                        "\n---\n".join(context_snippets)
                    )
                    logger.info(f"Agent augmented with {len(context_snippets)} RAG snippets")
            except Exception as e:
                logger.warning(f"RAG augmentation for agent failed: {e}")

        result = await execute_agent_query(agent, augmented_query, self.llm_client)
        self.memory.add_short_term_memory(session_id, "user", query_text)
        self.memory.add_short_term_memory(session_id, "assistant", result["answer"])
        return {
            "query": query_text,
            "answer": result["answer"],
            "source_documents": [],
            "tool_calls": result.get("tool_calls", []),
        }

    def _single_hop_query(
        self,
        query_text: str,
        top_k: int,
        history_str: str = "",
        kb_ids: Optional[List[int]] = None,
        system_prompt: str = None,
        llm_model: Optional[str] = None,
        temperature: Optional[float] = None
    ) -> Dict[str, Any]:
        # 1. Retrieve
        initial_k = top_k * 2 if settings.ENABLE_RERANK else top_k
        search_results = []
        if kb_ids:
            search_results = self.retriever.retrieve(query_text, top_k=initial_k, kb_ids=kb_ids)

        # 1b. Quality gate: log score stats for monitoring
        _assess_retrieval_quality(search_results, top_k)

        # 2. Rerank
        if settings.ENABLE_RERANK and search_results:
            search_results = self.reranker.rerank(query_text, search_results)
        else:
            search_results = search_results[:top_k]

        # 3. Format Context
        context = self._format_context(search_results)
        if history_str:
            context = f"历史背景:\n{history_str}\n\n检索到的资料:\n{context}"
        else:
            context = f"检索到的资料:\n{context}"

        if system_prompt:
             context = f"系统指令: {system_prompt}\n\n{context}"

        # 4. Generate Answer
        if hasattr(self.llm_client, 'generate_response_with_metrics'):
             prompt = f"""基于以下上下文信息，回答问题。

        上下文：
        {context}

        问题：{query_text}

        要求：
        1. 基于上下文回答，不添加外部知识
        2. 如上下文无相关信息，明确说明“根据提供的信息无法回答”
        3. 引用相关段落编号
        4. 保持回答准确、简洁
        5. 使用 Markdown 格式输出，合理使用标题、列表、加粗等排版

        回答："""
             answer, first_token, total_time = self.llm_client.generate_response_with_metrics(prompt, model=llm_model, temperature=temperature)

             result = self._format_response(query_text, answer, search_results)
             result["metrics"] = {
                 "first_token_latency": first_token,
                 "total_latency": total_time
             }
             return result
        else:
            answer = self.llm_client.generate_response(query_text, context, model=llm_model, temperature=temperature)
            return self._format_response(query_text, answer, search_results)

    def _multi_hop_query(
        self,
        query_text: str,
        sub_queries: List[str],
        top_k: int,
        history_str: str = "",
        kb_ids: Optional[List[int]] = None,
        system_prompt: str = None,
        llm_model: Optional[str] = None,
        temperature: Optional[float] = None
    ) -> Dict[str, Any]:

        all_results = []
        accumulated_context = history_str + "\n" if history_str else ""

        steps = sub_queries[:settings.MAX_HOP]

        for i, sub_query in enumerate(steps):
            logger.info(f"Multi-hop Step {i+1}: {sub_query}")

            if kb_ids:
                results = self.retriever.retrieve(sub_query, top_k=top_k, kb_ids=kb_ids)

                new_results = [r for r in results if r.id not in [existing.id for existing in all_results]]
                all_results.extend(new_results)

                accumulated_context += f"\n--- Step {i+1} Context ---\n"
                accumulated_context += self._format_context(new_results)

        if settings.ENABLE_RERANK and all_results:
            all_results = self.reranker.rerank(query_text, all_results)
        else:
            all_results = all_results[:top_k]

        final_context = accumulated_context + "\n\n最终检索结果:\n" + self._format_context(all_results)

        if system_prompt:
             final_context = f"系统指令: {system_prompt}\n\n{final_context}"

        answer = self.llm_client.generate_response(query_text, final_context, model=llm_model, temperature=temperature)

        return self._format_response(query_text, answer, all_results)

    def _format_response(self, query: str, answer: str, results: List[Any]) -> Dict[str, Any]:
        return {
            "query": query,
            "answer": answer,
            "source_documents": [
                {
                    "id": res.id,
                    "text": res.text,
                    "score": res.score,
                    "metadata": res.metadata
                }
                for res in results
            ]
        }

    def _format_context(self, search_results: List[Any]) -> str:
        context_parts = []
        for i, res in enumerate(search_results):
            context_parts.append(f"段落 {i+1} (ID: {res.id}):\n{res.text}")
        return "\n\n".join(context_parts)
