"""知识库模块功能测试。"""

import io

import pytest

from src.database.models import KnowledgeBase, KnowledgeDocument


class TestKnowledgeBaseFunctional:
    """验证知识库 CRUD、文档列表、QA 对管理。"""

    @pytest.fixture
    def kb_id(self, client, auth_headers):
        """创建一个测试知识库并返回 id。"""
        response = client.post(
            "/api/v1/knowledge-bases/",
            json={"name": "Functional KB", "description": "for functional tests"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        return response.json()["id"]

    def test_create_knowledge_base(self, client, auth_headers):
        """创建 KB 应成功并带 owner_id。"""
        response = client.post(
            "/api/v1/knowledge-bases/",
            json={"name": "New KB", "description": "desc"},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["name"] == "New KB"
        assert data["owner_id"] == 1

    def test_list_knowledge_bases(self, client, auth_headers, db, other_user):
        """列表只返回当前用户的知识库。"""
        own = KnowledgeBase(name="Own KB", kb_uid="own-uid", owner_id=1)
        other = KnowledgeBase(name="Other KB", kb_uid="other-uid", owner_id=other_user.id)
        db.add_all([own, other])
        db.commit()

        response = client.get("/api/v1/knowledge-bases/", headers=auth_headers)
        assert response.status_code == 200, response.text
        names = {kb["name"] for kb in response.json()}
        assert "Own KB" in names
        assert "Other KB" not in names

    def test_get_knowledge_base(self, client, auth_headers, kb_id):
        """获取 KB 详情。"""
        response = client.get(
            f"/api/v1/knowledge-bases/{kb_id}", headers=auth_headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["name"] == "Functional KB"

    def test_update_knowledge_base(self, client, auth_headers, kb_id):
        """更新 KB 名称和描述。"""
        response = client.put(
            f"/api/v1/knowledge-bases/{kb_id}",
            json={"name": "Updated KB", "description": "updated desc"},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["name"] == "Updated KB"
        assert data["description"] == "updated desc"

    def test_delete_knowledge_base(self, client, auth_headers, kb_id, db):
        """删除 KB 应成功并清理相关文档（mock Milvus）。"""
        from unittest.mock import patch

        with patch("src.api.routers.knowledge_base.vector_db_client") as mock_client:
            response = client.delete(
                f"/api/v1/knowledge-bases/{kb_id}", headers=auth_headers
            )
            assert response.status_code == 200, response.text
            assert db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first() is None
            mock_client.delete_by_kb_id.assert_called_once_with(kb_id)

    def test_other_user_kb_is_forbidden(self, client, auth_headers, db, other_user):
        """不能访问其他用户的私有 KB。"""
        kb = KnowledgeBase(name="Secret", kb_uid="secret-uid", owner_id=other_user.id)
        db.add(kb)
        db.commit()
        db.refresh(kb)

        response = client.get(
            f"/api/v1/knowledge-bases/{kb.id}", headers=auth_headers
        )
        assert response.status_code == 403

    def test_upload_document_tracks_doc(self, client, auth_headers, kb_id, db):
        """上传文档后应能在文档列表中查到。"""
        response = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/upload",
            files={"file": ("report.txt", io.BytesIO(b"hello world"), "text/plain")},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        doc_id = response.json()["doc_id"]

        response = client.get(
            f"/api/v1/knowledge-bases/{kb_id}/documents", headers=auth_headers
        )
        assert response.status_code == 200, response.text
        docs = response.json()
        assert any(d["id"] == doc_id for d in docs)

        doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
        assert doc is not None
        assert doc.filename == "report.txt"

    def test_public_kb_is_readable_by_other(self, client, auth_headers, db, other_user):
        """公开 KB 可被其他用户读取。"""
        kb = KnowledgeBase(
            name="Public KB", kb_uid="public-uid", owner_id=other_user.id, is_public=True
        )
        db.add(kb)
        db.commit()
        db.refresh(kb)

        response = client.get(
            f"/api/v1/knowledge-bases/{kb.id}", headers=auth_headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["name"] == "Public KB"
