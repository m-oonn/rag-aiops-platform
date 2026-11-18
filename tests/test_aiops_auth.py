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

    def test_tool_call_ledger_is_redacted_and_owner_scoped(
        self, client, engine, monkeypatch, test_user, other_user, auth_headers
    ):
        from sqlalchemy.orm import sessionmaker

        from src.agent.aiops import run_store

        monkeypatch.setattr(run_store, "SessionLocal", sessionmaker(bind=engine))
        thread_id = "tool-audit-run"
        run_store.create_run(thread_id, test_user.id, "diagnose mall")
        call_uid = run_store.start_tool_call(
            thread_id, test_user.id, 2, "check mall", "call-1", "probe_service_status",
            {"proposed": {"api_key": "secret-key"}, "executed": {"service": "mall"}},
        )
        assert run_store.finish_tool_call(
            call_uid, status="success", result={"status": "ok", "password": "hidden-value"},
            elapsed_ms=12.5,
        ) is True
        assert run_store.finish_tool_call(
            "missing-tool-call", status="success", result="orphan", elapsed_ms=1,
        ) is False

        response = client.get(f"/api/v1/aiops/runs/{thread_id}/tool-calls", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        call = data["tool_calls"][0]
        assert call["status"] == "success"
        assert call["arguments"]["proposed"]["api_key"] == "[REDACTED]"
        assert "hidden-value" not in response.text

        login = client.post(
            "/api/v1/auth/login/access-token",
            data={"username": other_user.username, "password": "otherpass"},
        )
        assert login.status_code == 200
        denied = client.get(
            f"/api/v1/aiops/runs/{thread_id}/tool-calls",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        )
        assert denied.status_code == 404

    def test_tool_call_ledger_read_failure_is_not_reported_as_empty(
        self, client, monkeypatch, auth_headers
    ):
        from src.agent.aiops import run_store

        def unavailable_session():
            raise RuntimeError("database unavailable")

        monkeypatch.setattr(run_store, "SessionLocal", unavailable_session)
        response = client.get(
            "/api/v1/aiops/runs/tool-audit-read-failure/tool-calls",
            headers=auth_headers,
        )

        assert response.status_code == 503
        assert response.json()["detail"] == "工具调用审计记录暂不可读取"
