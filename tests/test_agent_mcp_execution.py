"""Agent MCP 工具执行测试。"""

from unittest.mock import patch, AsyncMock

import pytest

from src.database.models import Agent


class TestAgentMCPExecution:
    """验证 MCP 工具型 Agent 不只是保存配置，还能被调用执行。"""

    @pytest.fixture(autouse=True)
    def setup_agent(self, client, auth_headers, db):
        """为每个测试创建一个 MCP 工具型 Agent。"""
        response = client.post(
            "/api/v1/agents/",
            json={
                "name": "Metric Agent",
                "type": "function_call",
                "system_prompt": "You are a monitoring assistant.",
                "tools_config": {
                    "monitor": {
                        "transport": "streamable_http",
                        "url": "http://127.0.0.1:8104/mcp",
                    }
                },
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        self.agent_id = response.json()["id"]

    def test_agent_execute_endpoint_exists(self, client, auth_headers):
        """Agent 执行端点应存在并返回调用结果。"""
        with patch(
            "src.api.routers.agent.execute_agent_query", new_callable=AsyncMock
        ) as mock_execute:
            mock_execute.return_value = {
                "query": "CPU usage?",
                "answer": "CPU is at 15%.",
                "tool_calls": [{"name": "query_cpu_metrics", "args": {}}],
            }

            response = client.post(
                f"/api/v1/agents/{self.agent_id}/execute",
                json={"query": "CPU usage?"},
                headers=auth_headers,
            )
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["answer"] == "CPU is at 15%."
            assert len(data["tool_calls"]) == 1
            mock_execute.assert_awaited_once()

    def test_agent_execute_validates_ownership(self, client, auth_headers, db, other_user):
        """用户不能执行其他用户的 Agent。"""
        other_agent = Agent(
            name="Other Agent",
            type="function_call",
            user_id=other_user.id,
        )
        db.add(other_agent)
        db.commit()
        db.refresh(other_agent)

        response = client.post(
            f"/api/v1/agents/{other_agent.id}/execute",
            json={"query": "test"},
            headers=auth_headers,
        )
        assert response.status_code == 403
