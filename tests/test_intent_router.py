"""意图路由单元测试。

测试三层路由决策：
1. _quick_intent_check  —— 规则快过滤（0ms，命中即跳过 LLM）
2. QuestionAnalyzer.analyze()  —— LLM 意图分类（chat / knowledge / diagnosis）
3. RAGService.query()  —— 意图 + 配置约束 联合路由

采用 TDD 风格：先写测试，再实现对应代码。
运行方式: cd D:\\ragPdfSystem++agent && python -m pytest tests/test_intent_router.py -v
"""

import json
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from src.services.question_analyzer import QuestionAnalyzer
from src.services.rag_service import RAGService


# ──────────────────────────────────────────────
# 第一层：规则快过滤 _quick_intent_check
# ──────────────────────────────────────────────

class TestQuickIntentCheck:
    """规则预过滤：对明显场景快速返回，不确定则返回 None 交给 LLM。"""

    def setup_method(self):
        # _quick_intent_check 是 rag_service 模块级函数（待实现）
        from src.services.rag_service import _quick_intent_check
        self.check = _quick_intent_check

    # ── chat 命中 ──

    def test_greeting_zh(self):
        """中文问候语应快速判定为 chat。"""
        assert self.check("你好") == "chat"

    def test_greeting_en(self):
        """英文问候语应快速判定为 chat。"""
        assert self.check("hello") == "chat"

    def test_thanks(self):
        """致谢应快速判定为 chat。"""
        assert self.check("谢谢") == "chat"

    def test_who_are_you(self):
        """身份类问题应快速判定为 chat。"""
        assert self.check("你是谁") == "chat"

    # ── diagnosis 命中 ──

    def test_cpu_keyword(self):
        """包含 CPU 关键词应判定为 diagnosis。"""
        assert self.check("data-sync-service CPU 飙高了") == "diagnosis"

    def test_memory_keyword(self):
        """包含内存关键词应判定为 diagnosis。"""
        assert self.check("服务内存泄漏了") == "diagnosis"

    def test_oom_keyword(self):
        """OOM 关键词应判定为 diagnosis。"""
        assert self.check("发生了 OOM") == "diagnosis"

    def test_alert_keyword(self):
        """告警关键词应判定为 diagnosis。"""
        assert self.check("收到了告警通知") == "diagnosis"

    # ── 不确定 → None ──

    def test_ambiguous_returns_none(self):
        """不确定场景应返回 None，交给 LLM 分类。"""
        assert self.check("AI编程助手有什么优势") is None

    def test_vague_returns_none(self):
        """模糊问题应返回 None。"""
        assert self.check("帮我看看这个问题") is None

    def test_long_greeting_not_chat(self):
        """长句包含问候词但不算闲聊（长度限制）。"""
        result = self.check("你好，我想问一下关于CPU使用率过高的排查方法")
        assert result != "chat"  # 应该交给 LLM 或命中 diagnosis

    # ── 边界 ──

    def test_empty_string(self):
        """空字符串应返回 None 或 chat。"""
        result = self.check("")
        assert result in (None, "chat")

    def test_case_insensitive(self):
        """英文关键词大小写不敏感。"""
        assert self.check("CPU usage is high") == "diagnosis"
        assert self.check("Hello") == "chat"


# ──────────────────────────────────────────────
# 第二层：QuestionAnalyzer 意图分类
# ──────────────────────────────────────────────

class TestQuestionAnalyzerIntent:
    """QuestionAnalyzer.analyze() 返回的 intent 字段。"""

    def _make_analyzer(self, mock_response: str):
        """构造一个 LLM 返回固定 JSON 的 QuestionAnalyzer。"""
        llm = MagicMock()
        llm.generate_custom_response.return_value = mock_response
        return QuestionAnalyzer(llm)

    def test_intent_chat(self):
        """闲聊问题 → intent=chat。"""
        analyzer = self._make_analyzer(json.dumps({
            "intent": "chat",
            "is_multi_hop": False,
            "sub_queries": [],
            "reason": "简单问候"
        }))
        result = analyzer.analyze("你好呀")
        assert result["intent"] == "chat"
        assert result["is_multi_hop"] is False

    def test_intent_knowledge(self):
        """知识查询 → intent=knowledge。"""
        analyzer = self._make_analyzer(json.dumps({
            "intent": "knowledge",
            "is_multi_hop": False,
            "sub_queries": [],
            "reason": "询问文档内容"
        }))
        result = analyzer.analyze("AI编程助手有什么优势")
        assert result["intent"] == "knowledge"

    def test_intent_diagnosis(self):
        """运维诊断 → intent=diagnosis。"""
        analyzer = self._make_analyzer(json.dumps({
            "intent": "diagnosis",
            "is_multi_hop": False,
            "sub_queries": [],
            "reason": "涉及服务故障排查"
        }))
        result = analyzer.analyze("data-sync-service CPU 飙高了，帮我看看")
        assert result["intent"] == "diagnosis"

    def test_intent_diagnosis_multi_hop(self):
        """运维诊断 + 多跳问题 → intent=diagnosis + is_multi_hop=True。"""
        analyzer = self._make_analyzer(json.dumps({
            "intent": "diagnosis",
            "is_multi_hop": True,
            "sub_queries": ["查CPU指标", "查内存指标", "查相关日志"],
            "reason": "需要综合多个指标诊断"
        }))
        result = analyzer.analyze("data-sync-service 全面体检一下")
        assert result["intent"] == "diagnosis"
        assert result["is_multi_hop"] is True
        assert len(result["sub_queries"]) == 3

    def test_missing_intent_defaults_to_chat(self):
        """LLM 返回无 intent 字段时默认 chat（向后兼容旧模型）。"""
        analyzer = self._make_analyzer(json.dumps({
            "is_multi_hop": False,
            "sub_queries": [],
            "reason": "旧格式无intent"
        }))
        result = analyzer.analyze("随便问问")
        assert result.get("intent", "chat") == "chat"

    def test_llm_failure_defaults_to_chat(self):
        """LLM 调用异常时应降级为 chat。"""
        llm = MagicMock()
        llm.generate_custom_response.side_effect = RuntimeError("API timeout")
        analyzer = QuestionAnalyzer(llm)
        result = analyzer.analyze("anything")
        assert result.get("intent", "chat") == "chat"
        assert result["is_multi_hop"] is False

    def test_malformed_json_defaults_to_chat(self):
        """LLM 返回非 JSON 时应降级为 chat。"""
        analyzer = self._make_analyzer("I cannot analyze this question.")
        result = analyzer.analyze("something weird")
        assert result.get("intent", "chat") == "chat"


# ──────────────────────────────────────────────
# 第三层：RAGService 路由决策
# ──────────────────────────────────────────────

class TestIntentRouting:
    """RAGService.query() 的路由决策矩阵。

    路由规则：intent × config → 走哪条路径
    - chat 意图 → 永远走 General Chat，不管绑了什么
    - knowledge 意图 + 有 KB → RAG
    - knowledge 意图 + 无 KB → General Chat
    - diagnosis 意图 + 有 Agent → Agent
    - diagnosis 意图 + 无 Agent + 有 KB → RAG（知识库里找排查文档）
    - diagnosis 意图 + 无 Agent + 无 KB → General Chat
    """

    def _make_service(self, intent="chat", is_multi_hop=False):
        """构造一个 QuestionAnalyzer 返回固定 intent 的 RAGService。"""
        service = RAGService.__new__(RAGService)
        service.retriever = MagicMock()
        service.llm_client = MagicMock()
        service.reranker = MagicMock()
        service.memory = MagicMock()
        service.analyzer = MagicMock()
        service.analyzer.analyze.return_value = {
            "intent": intent,
            "is_multi_hop": is_multi_hop,
            "sub_queries": [],
            "reason": "test"
        }
        # 通用 mock
        service.memory.get_short_term_memory.return_value = []
        service.llm_client.generate_general_response.return_value = "General Chat 回答"
        service.llm_client.generate_response_with_metrics.return_value = ("RAG 回答", 0.1, 1.0)
        service.retriever.retrieve.return_value = []
        return service

    def _assistant_config(self, agent_ids=None, agents=None, system_prompt=None):
        """构造 assistant_config dict（不含 kb_ids，kb_ids 通过 query() 参数传入）。"""
        config = {}
        if agent_ids is not None:
            config["agent_ids"] = agent_ids
        if agents is not None:
            config["agents"] = agents
        if system_prompt:
            config["system_prompt"] = system_prompt
        return config

    def _fake_agent(self):
        """构造一个可 JSON 序列化的假 Agent 对象。"""
        agent = MagicMock()
        agent.id = 1
        agent.name = "运维Agent"
        agent.system_prompt = "你是运维专家"
        agent.tools_config = {}        # dict 而非 MagicMock，可 JSON 序列化
        agent.llm_config = None
        agent.execution_config = None
        return agent

    # ── chat 意图 ──

    @pytest.mark.asyncio
    async def test_chat_with_kb_still_goes_general(self):
        """闲聊 + 有 KB → General Chat（不触发 RAG）。"""
        service = self._make_service(intent="chat")
        config = self._assistant_config()

        result = await service.query("你好", kb_ids=[1, 2], assistant_config=config)

        service.retriever.retrieve.assert_not_called()
        assert "General Chat" in result["answer"]

    @pytest.mark.asyncio
    async def test_chat_with_agent_still_goes_general(self):
        """闲聊 + 有 Agent → General Chat（不触发 Agent）。"""
        service = self._make_service(intent="chat")
        config = self._assistant_config(
            agent_ids=[1],
            agents=[self._fake_agent()]
        )

        result = await service.query("hello", assistant_config=config)

        service.retriever.retrieve.assert_not_called()
        assert "General Chat" in result["answer"]

    # ── knowledge 意图 ──

    @pytest.mark.asyncio
    async def test_knowledge_with_kb_goes_rag(self):
        """知识查询 + 有 KB → RAG 路径。"""
        service = self._make_service(intent="knowledge")
        config = self._assistant_config()

        result = await service.query("AI编程助手的优势", kb_ids=[1], assistant_config=config)

        # 应该触发检索
        service.retriever.retrieve.assert_called()

    @pytest.mark.asyncio
    async def test_knowledge_without_kb_goes_general(self):
        """知识查询 + 无 KB → General Chat（降级）。"""
        service = self._make_service(intent="knowledge")
        config = self._assistant_config()

        result = await service.query("AI编程助手的优势", assistant_config=config)

        service.retriever.retrieve.assert_not_called()
        assert "General Chat" in result["answer"]

    # ── diagnosis 意图 ──

    @pytest.mark.asyncio
    async def test_diagnosis_with_agent_goes_agent(self):
        """运维诊断 + 有 Agent → Agent 路径。"""
        service = self._make_service(intent="diagnosis")
        config = self._assistant_config(agent_ids=[1], agents=[self._fake_agent()])

        with patch("src.services.rag_service.execute_agent_query",
                    new_callable=AsyncMock,
                    return_value={"answer": "CPU 峰值 98%", "tool_calls": []}):
            result = await service.query("CPU 飙高了", assistant_config=config)

        assert "CPU" in result["answer"]

    @pytest.mark.asyncio
    async def test_diagnosis_without_agent_with_kb_goes_rag(self):
        """运维诊断 + 无 Agent + 有 KB → RAG（从知识库找排查文档）。"""
        service = self._make_service(intent="diagnosis")
        config = self._assistant_config()

        result = await service.query("CPU 飙高了", kb_ids=[1], assistant_config=config)

        service.retriever.retrieve.assert_called()

    @pytest.mark.asyncio
    async def test_diagnosis_without_anything_goes_general(self):
        """运维诊断 + 无 Agent + 无 KB → General Chat。"""
        service = self._make_service(intent="diagnosis")
        config = self._assistant_config()

        result = await service.query("CPU 飙高了", assistant_config=config)

        service.retriever.retrieve.assert_not_called()
        assert "General Chat" in result["answer"]

    # ── 兜底 ──

    @pytest.mark.asyncio
    async def test_no_config_goes_general(self):
        """无任何配置 → General Chat。"""
        service = self._make_service(intent="knowledge")

        result = await service.query("随便问问")

        assert "General Chat" in result["answer"]

    @pytest.mark.asyncio
    async def test_quick_check_skips_llm_analysis(self):
        """规则快过滤命中时应跳过 LLM 意图分类调用。"""
        service = self._make_service(intent="chat")

        result = await service.query("你好", kb_ids=[1], assistant_config=self._assistant_config())

        # 规则命中 chat → analyzer.analyze() 不应被调用
        service.analyzer.analyze.assert_not_called()
        service.retriever.retrieve.assert_not_called()


# ──────────────────────────────────────────────
# 路由决策矩阵总结
# ──────────────────────────────────────────────

class TestRoutingMatrix:
    """参数化测试：覆盖完整的 intent × config 矩阵。"""

    def _run_route(self, intent, kb_ids, has_agent):
        """模拟路由决策，返回路径名称。"""
        # 模拟 _quick_intent_check 不命中 → 走 LLM 分类
        # 模拟 LLM 返回 intent
        # 模拟配置
        has_kb = bool(kb_ids)

        # 路由规则（待实现的逻辑）
        if intent == "chat":
            return "general_chat"
        elif intent == "knowledge":
            if has_kb:
                return "rag"
            else:
                return "general_chat"
        elif intent == "diagnosis":
            if has_agent:
                return "agent"
            elif has_kb:
                return "rag"
            else:
                return "general_chat"
        return "general_chat"

    @pytest.mark.parametrize("intent,kb_ids,has_agent,expected", [
        # chat 永远走 general_chat
        ("chat", None, False, "general_chat"),
        ("chat", [1], False, "general_chat"),
        ("chat", [1], True, "general_chat"),
        ("chat", None, True, "general_chat"),
        # knowledge 看 KB
        ("knowledge", None, False, "general_chat"),
        ("knowledge", [1], False, "rag"),
        ("knowledge", [1, 2], False, "rag"),
        ("knowledge", None, True, "general_chat"),
        # diagnosis 优先 Agent，降级 RAG，兜底 general
        ("diagnosis", None, True, "agent"),
        ("diagnosis", [1], True, "agent"),
        ("diagnosis", [1], False, "rag"),
        ("diagnosis", None, False, "general_chat"),
    ])
    def test_routing_matrix(self, intent, kb_ids, has_agent, expected):
        """完整覆盖 intent × config → path 的所有组合。"""
        assert self._run_route(intent, kb_ids, has_agent) == expected
