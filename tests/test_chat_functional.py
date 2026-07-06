"""Chat 模块功能测试。"""

from unittest.mock import patch, AsyncMock

import pytest

from src.database.models import ChatSession, ChatInteraction


class TestChatFunctional:
    """验证聊天会话创建、消息发送、历史记录。"""

    @pytest.fixture
    def assistant_id(self, client, auth_headers):
        """创建一个测试助手。"""
        response = client.post(
            "/api/v1/assistants/",
            json={"name": "Chat Assistant", "kb_ids": [], "agent_ids": []},
            headers=auth_headers,
        )
        assert response.status_code == 200
        return response.json()["id"]

    def test_chat_without_assistant_uses_direct_llm(self, client, auth_headers):
        """无助手/无 KB 的纯聊天应调用 LLM 并创建会话。"""
        with patch(
            "src.api.routers.chat.rag_service.llm_client.generate_general_response",
            return_value="Hello from LLM",
        ):
            response = client.post(
                "/api/v1/chat/",
                json={"query": "Hi"},
                headers=auth_headers,
            )
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["answer"] == "Hello from LLM"
            assert data["session_id"]

    def test_chat_with_assistant(self, client, auth_headers, assistant_id):
        """带助手提问应返回答案。"""
        with patch(
            "src.api.routers.chat.rag_service.llm_client.generate_general_response",
            return_value="Answer with assistant",
        ):
            response = client.post(
                "/api/v1/chat/",
                json={"query": "Question", "assistant_id": assistant_id},
                headers=auth_headers,
            )
            assert response.status_code == 200, response.text
            assert response.json()["answer"] == "Answer with assistant"

    def test_chat_with_other_user_assistant_is_forbidden(
        self, client, auth_headers, db, other_user
    ):
        """不能使用其他用户的助手。"""
        from src.database.models import Assistant

        other_assistant = Assistant(name="Other", user_id=other_user.id)
        db.add(other_assistant)
        db.commit()
        db.refresh(other_assistant)

        response = client.post(
            "/api/v1/chat/",
            json={"query": "Hi", "assistant_id": other_assistant.id},
            headers=auth_headers,
        )
        assert response.status_code == 403

    def test_list_chat_sessions(self, client, auth_headers):
        """发送聊天后应能在会话列表中查到。"""
        with patch(
            "src.api.routers.chat.rag_service.llm_client.generate_general_response",
            return_value="OK",
        ):
            client.post(
                "/api/v1/chat/",
                json={"query": "Session test"},
                headers=auth_headers,
            )

        response = client.get("/api/v1/chat/sessions", headers=auth_headers)
        assert response.status_code == 200, response.text
        sessions = response.json()
        assert len(sessions) >= 1
        assert any("Session test" in (s["title"] or "") for s in sessions)

    def test_get_session_messages(self, client, auth_headers):
        """获取会话历史消息。"""
        with patch(
            "src.api.routers.chat.rag_service.llm_client.generate_general_response",
            return_value="History answer",
        ):
            chat_res = client.post(
                "/api/v1/chat/",
                json={"query": "History question"},
                headers=auth_headers,
            )
        session_id = chat_res.json()["session_id"]

        response = client.get(
            f"/api/v1/chat/sessions/{session_id}/messages", headers=auth_headers
        )
        assert response.status_code == 200, response.text
        messages = response.json()
        assert any(m["query"] == "History question" for m in messages)
        assert any(m["answer"] == "History answer" for m in messages)

    def test_delete_session(self, client, auth_headers, db):
        """删除会话应同时删除消息。"""
        with patch(
            "src.api.routers.chat.rag_service.llm_client.generate_general_response",
            return_value="To delete",
        ):
            chat_res = client.post(
                "/api/v1/chat/",
                json={"query": "Delete me"},
                headers=auth_headers,
            )
        session_id = chat_res.json()["session_id"]
        session = db.query(ChatSession).filter(ChatSession.session_uid == session_id).first()

        response = client.delete(
            f"/api/v1/chat/sessions/{session_id}", headers=auth_headers
        )
        assert response.status_code == 200, response.text
        assert db.query(ChatSession).filter(ChatSession.session_uid == session_id).first() is None
        assert (
            db.query(ChatInteraction).filter(ChatInteraction.session_id == session.id).count() == 0
        )

    def test_batch_delete_sessions(self, client, auth_headers):
        """批量删除会话。"""
        session_ids = []
        with patch(
            "src.api.routers.chat.rag_service.llm_client.generate_general_response",
            return_value="Batch",
        ):
            for i in range(2):
                res = client.post(
                    "/api/v1/chat/",
                    json={"query": f"Batch {i}"},
                    headers=auth_headers,
                )
                session_ids.append(res.json()["session_id"])

        response = client.request(
            "DELETE", "/api/v1/chat/sessions", json=session_ids, headers=auth_headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["message"] == "Deleted 2 sessions"
