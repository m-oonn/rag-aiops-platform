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
        """携带有效 token 调用 /api/v1/aiops 应进入流式响应流程（200）。"""
        response = client.post(
            "/api/v1/aiops",
            json={"query": "test incident"},
            headers=auth_headers,
        )
        # conftest 中 mock_aiops_service 已替换 AIOps 服务为假实现，
        # 认证通过后应返回 200，不应接受 422/500 等错误状态码
        assert response.status_code == 200, (
            f"Expected 200, got {response.status_code}: {response.text}"
        )
