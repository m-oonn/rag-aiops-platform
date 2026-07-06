"""Assistant 模块功能测试。"""

import pytest

from src.database.models import Assistant


class TestAssistantFunctional:
    """验证助手的增删改查、版本管理。"""

    def test_create_assistant(self, client, auth_headers):
        """创建助手应成功并返回配置。"""
        response = client.post(
            "/api/v1/assistants/",
            json={
                "name": "Test Assistant",
                "description": "for functional test",
                "llm_model": "qwen-max",
                "temperature": 0.5,
                "system_prompt": "You are a test assistant.",
                "kb_ids": [],
                "agent_ids": [],
            },
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["name"] == "Test Assistant"
        assert data["temperature"] == 0.5

    def test_list_assistants_only_owned(self, client, auth_headers, db, other_user):
        """列表应只返回当前用户创建的助手。"""
        own = Assistant(name="Own Assistant", user_id=1)
        other = Assistant(name="Other Assistant", user_id=other_user.id)
        db.add_all([own, other])
        db.commit()

        response = client.get("/api/v1/assistants/", headers=auth_headers)
        assert response.status_code == 200, response.text
        names = {a["name"] for a in response.json()}
        assert "Own Assistant" in names
        assert "Other Assistant" not in names

    def test_get_assistant(self, client, auth_headers):
        """获取单个助手详情。"""
        created = client.post(
            "/api/v1/assistants/",
            json={"name": "Detail Assistant"},
            headers=auth_headers,
        )
        assistant_id = created.json()["id"]

        response = client.get(f"/api/v1/assistants/{assistant_id}", headers=auth_headers)
        assert response.status_code == 200, response.text
        assert response.json()["name"] == "Detail Assistant"

    def test_get_other_user_assistant_is_forbidden(self, client, auth_headers, db, other_user):
        """不能访问其他用户的助手。"""
        other_assistant = Assistant(name="Secret", user_id=other_user.id)
        db.add(other_assistant)
        db.commit()
        db.refresh(other_assistant)

        response = client.get(
            f"/api/v1/assistants/{other_assistant.id}", headers=auth_headers
        )
        assert response.status_code == 403

    def test_update_assistant(self, client, auth_headers):
        """更新助手配置应持久化。"""
        created = client.post(
            "/api/v1/assistants/",
            json={"name": "Before Update"},
            headers=auth_headers,
        )
        assistant_id = created.json()["id"]

        response = client.put(
            f"/api/v1/assistants/{assistant_id}",
            json={"name": "After Update", "temperature": 0.1},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["name"] == "After Update"
        assert data["temperature"] == 0.1

    def test_delete_assistant(self, client, auth_headers, db):
        """删除助手应成功。"""
        created = client.post(
            "/api/v1/assistants/",
            json={"name": "To Delete"},
            headers=auth_headers,
        )
        assistant_id = created.json()["id"]

        response = client.delete(
            f"/api/v1/assistants/{assistant_id}", headers=auth_headers
        )
        assert response.status_code == 200, response.text
        assert db.query(Assistant).filter(Assistant.id == assistant_id).first() is None

    def test_create_assistant_version(self, client, auth_headers):
        """创建并列出助手版本。"""
        created = client.post(
            "/api/v1/assistants/",
            json={"name": "Versioned Assistant"},
            headers=auth_headers,
        )
        assistant_id = created.json()["id"]

        response = client.post(
            f"/api/v1/assistants/{assistant_id}/versions",
            json={"version": "v1.0.0", "config": {"temperature": 0.3}},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text

        response = client.get(
            f"/api/v1/assistants/{assistant_id}/versions", headers=auth_headers
        )
        assert response.status_code == 200, response.text
        versions = response.json()
        assert len(versions) == 1
        assert versions[0]["version"] == "v1.0.0"
