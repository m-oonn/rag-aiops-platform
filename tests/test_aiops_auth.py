"""AIOps 诊断端点的认证测试。"""

import pytest


class TestAIOpsAuthentication:
    """验证 AIOps 诊断端点必须登录后才能访问。"""

    def test_diagnose_without_token_returns_401(self, client):
        """未携带 token 调用 /api/v1/aiops 应返回 401 Unauthorized。"""
        response = client.post("/api/v1/aiops", json={"query": "test incident"})
        assert response.status_code == 401, (
            f"Expected 401, got {response.status_code}: {response.text}"
        )

    def test_diagnose_with_valid_token_returns_streaming(self, client, auth_headers):
        """携带有效 token 调用 /api/v1/aiops 应进入流式响应流程（200 或 422）。"""
        response = client.post(
            "/api/v1/aiops",
            json={"query": "test incident"},
            headers=auth_headers,
        )
        # LLM/MCP 依赖外部服务，测试中只要认证通过即可接受非 401 状态码
        assert response.status_code != 401
