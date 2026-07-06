"""助手版本持久化测试。"""

import pytest


class TestAssistantVersions:
    """验证助手版本保存到数据库，而不是内存 Mock。"""

    @pytest.fixture(autouse=True)
    def setup_assistant(self, client, auth_headers, db):
        """为每个测试创建一个助手。"""
        response = client.post(
            "/api/v1/assistants/",
            json={"name": "Test Assistant"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        self.assistant_id = response.json()["id"]

    def test_create_and_list_version(self, client, auth_headers, db):
        """创建版本后应持久化到数据库，并能在列表中查到。"""
        response = client.post(
            f"/api/v1/assistants/{self.assistant_id}/versions",
            json={
                "version": "v1.0.0",
                "config": {"temperature": 0.5, "system_prompt": "hello"},
            },
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text

        response = client.get(
            f"/api/v1/assistants/{self.assistant_id}/versions",
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        versions = response.json()
        assert len(versions) == 1
        assert versions[0]["version"] == "v1.0.0"
        assert versions[0]["config"]["temperature"] == 0.5

        # 关键断言：版本必须真实写入数据库，而非内存 Mock
        from src.database.models import AssistantVersion
        db_record = db.query(AssistantVersion).filter(
            AssistantVersion.assistant_id == self.assistant_id
        ).first()
        assert db_record is not None, "Version was not persisted to database"
        assert db_record.version == "v1.0.0"
