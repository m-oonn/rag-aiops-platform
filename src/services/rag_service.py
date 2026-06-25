from typing import List, Dict, Any, Optional
from src.retrieval.vector_retriever import VectorRetriever
from src.retrieval.reranker import DashScopeReranker
from src.llm.llm_client import LLMClient
from src.utils.logger import logger
from src.settings import settings
from src.services.question_analyzer import QuestionAnalyzer
from src.services.memory_service import MemorySystem

class RAGService:
    def __init__(self):
        self.retriever = VectorRetriever()
        self.llm_client = LLMClient()
        self.reranker = DashScopeReranker()
        self.analyzer = QuestionAnalyzer(self.llm_client)
        self.memory = MemorySystem()

    def query(
        self, 
        query_text: str, 
        top_k: int = 5, 
        session_id: str = "default", 
        kb_ids: Optional[List[int]] = None,
        assistant_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        
        # Config Extraction
        system_prompt = assistant_config.get("system_prompt") if assistant_config else None
        agent_ids = assistant_config.get("agent_ids") if assistant_config else None
        # model = assistant_config.get("llm_model") # Pass to LLMClient if supported
        
        # 0. Get History (Short-term memory)
        memory_config = assistant_config.get("memory_config", {}) if assistant_config else {}
        enable_short_term = memory_config.get("enable_short_term", True) # Default to True if not specified
        window_size = memory_config.get("window_size", 10)
        
        history = []
        if enable_short_term:
            history = self.memory.get_short_term_memory(session_id, limit=window_size)
            
        history_str = "\n".join([f"{m['role']}: {m['content']}" for m in history])
        
        # Long-term Memory Injection (Placeholder/Mock)
        enable_long_term = memory_config.get("enable_long_term", False)
        long_term_context = ""
        if enable_long_term:
            # In a real system, we would embed the query and search the long-term vector store
            # For now, we simulate this or just log it
            logger.info(f"Long-term memory enabled for session {session_id}")
            # long_term_memories = self.memory.retrieve_long_term_memory(query_text)
            # long_term_context = "\n".join([m['content'] for m in long_term_memories])
            pass

        # 1. Analyze Question (incorporating history)
        # If no KBs, we are in "General Chat" mode.
        
        if not kb_ids:
            # General Chat Mode
            logger.info("No KB selected, using General Chat Mode")
            context = f"历史对话:\n{history_str}" if history else ""
            if long_term_context:
                context = f"长期记忆:\n{long_term_context}\n\n{context}"
                
            if system_prompt:
                context = f"系统指令: {system_prompt}\n\n{context}"
                
            # TODO: If agent_ids are present, we could invoke AgentExecutor here
            if agent_ids:
                logger.info(f"Agents configured: {agent_ids}. Agent execution logic to be implemented.")
                
            # Direct LLM call
            # Use general response method for non-RAG queries
            answer = self.llm_client.generate_general_response(query_text, context)
            
            # Update Memory
            self.memory.add_short_term_memory(session_id, "user", query_text)
            self.memory.add_short_term_memory(session_id, "assistant", answer)
            
            return {
                "query": query_text,
                "answer": answer,
                "source_documents": []
            }

        # RAG Mode
        contextual_query = f"历史对话:\n{history_str}\n当前问题: {query_text}" if history else query_text
        analysis = self.analyzer.analyze(contextual_query)
        logger.info(f"Question Analysis: {analysis}")

        if settings.ENABLE_MULTI_HOP and analysis.get("is_multi_hop"):
            result = self._multi_hop_query(query_text, analysis.get("sub_queries", []), top_k, history_str, kb_ids, system_prompt)
        else:
            result = self._single_hop_query(query_text, top_k, history_str, kb_ids, system_prompt)
        
        # 2. Update Short-term memory
        self.memory.add_short_term_memory(session_id, "user", query_text)
        self.memory.add_short_term_memory(session_id, "assistant", result["answer"])
        
        return result

    def _single_hop_query(
        self, 
        query_text: str, 
        top_k: int, 
        history_str: str = "", 
        kb_ids: Optional[List[int]] = None,
        system_prompt: str = None
    ) -> Dict[str, Any]:
        
        # 1. Retrieve
        initial_k = top_k * 2 if settings.ENABLE_RERANK else top_k
        search_results = []
        if kb_ids:
            search_results = self.retriever.retrieve(query_text, top_k=initial_k, kb_ids=kb_ids)
        
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
             # Construct full prompt as generate_response does
             # The generate_response method in LLMClient constructs the prompt internally
             # We need to replicate that or modify generate_response to support metrics
             # For now, let's just use generate_response logic here to construct prompt
             prompt = f"""基于以下上下文信息，回答问题。
            
        上下文：
        {context}

        问题：{query_text}

        要求：
        1. 基于上下文回答，不添加外部知识
        2. 如上下文无相关信息，明确说明"根据提供的信息无法回答"
        3. 引用相关段落编号
        4. 保持回答准确、简洁

        回答："""
             answer, first_token, total_time = self.llm_client.generate_response_with_metrics(prompt)
             
             result = self._format_response(query_text, answer, search_results)
             result["metrics"] = {
                 "first_token_latency": first_token,
                 "total_latency": total_time
             }
             return result
        else:
            answer = self.llm_client.generate_response(query_text, context)
            return self._format_response(query_text, answer, search_results)

    def _multi_hop_query(
        self, 
        query_text: str, 
        sub_queries: List[str], 
        top_k: int, 
        history_str: str = "", 
        kb_ids: Optional[List[int]] = None,
        system_prompt: str = None
    ) -> Dict[str, Any]:
        
        all_results = []
        accumulated_context = history_str + "\n" if history_str else ""
        
        # Limit sub-queries by MAX_HOP
        steps = sub_queries[:settings.MAX_HOP]
        
        for i, sub_query in enumerate(steps):
            logger.info(f"Multi-hop Step {i+1}: {sub_query}")
            
            # Retrieve for sub-query
            if kb_ids:
                results = self.retriever.retrieve(sub_query, top_k=top_k, kb_ids=kb_ids)
                
                # Filter unique results
                new_results = [r for r in results if r.id not in [existing.id for existing in all_results]]
                all_results.extend(new_results)
                
                # Update accumulated context for next step
                accumulated_context += f"\n--- Step {i+1} Context ---\n"
                accumulated_context += self._format_context(new_results)

        # Final Rerank of all collected evidence
        if settings.ENABLE_RERANK and all_results:
            all_results = self.reranker.rerank(query_text, all_results)
        else:
            all_results = all_results[:top_k]

        # Final Context
        final_context = accumulated_context + "\n\n最终检索结果:\n" + self._format_context(all_results)
        
        if system_prompt:
             final_context = f"系统指令: {system_prompt}\n\n{final_context}"

        # Final Answer
        answer = self.llm_client.generate_response(query_text, final_context)
        
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
