"""Chat 与 Agent MCP 工具集成测试。"""

from unittest.mock import patch, AsyncMock

import pytest

from src.database.models import Assistant, Agent


class TestChatAgentIntegration:
    """验证 Chat 端点在 Assistant 配置了 agent_ids 时会走 Agent 工具执行。"""

    @pytest.fixture(autouse=True)
    def setup(self, client, auth_headers, db):
        """创建一个绑定 MCP Agent 的 Assistant。"""
        agent = Agent(
            name="Monitor Agent",
            type="function_call",
            user_id=self._user_id if hasattr(self, "_user_id") else 1,
            tools_config={
                "monitor": {
                    "transport": "streamable_http",
                    "url": "http://127.0.0.1:8104/mcp",
                }
            },
        )
        db.add(agent)
        db.commit()
        db.refresh(agent)
        self.agent_id = agent.id

        assistant = Assistant(
            name="AIOps Assistant",
            user_id=agent.user_id,
            agent_ids=[agent.id],
        )
        db.add(assistant)
        db.commit()
        db.refresh(assistant)
        self.assistant_id = assistant.id

    def test_chat_with_assistant_uses_agent_tools(self, client, auth_headers):
        """选择带 Agent 的 Assistant 提问，应调用 Agent 工具执行而非普通 LLM。"""
        with patch(
            "src.services.rag_service.execute_agent_query", new_callable=AsyncMock
        ) as mock_execute:
            mock_execute.return_value = {
                "query": "CPU usage?",
                "answer": "CPU is at 15% via agent.",
                "tool_calls": [{"name": "query_cpu_metrics", "args": {}}],
            }

            response = client.post(
                "/api/v1/chat/",
                json={
                    "query": "CPU usage?",
                    "assistant_id": self.assistant_id,
                },
                headers=auth_headers,
            )
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["answer"] == "CPU is at 15% via agent."
            mock_execute.assert_awaited_once()
