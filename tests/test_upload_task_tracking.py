"""文件上传真实 Celery task_id 跟踪测试。"""

import io
import pytest
from unittest.mock import patch, MagicMock

from src.database.models import KnowledgeDocument


class TestUploadTaskTracking:
    """验证上传文档时保存真实 Celery task_id，Monitor 能据此查询队列状态。"""

    @pytest.fixture(autouse=True)
    def setup_kb(self, client, auth_headers, db):
        """为每个测试创建一个知识库。"""
        response = client.post(
            "/api/v1/knowledge-bases/",
            json={"name": "Test KB", "description": "for task tracking tests"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        self.kb_id = response.json()["id"]

    def test_upload_saves_real_celery_task_id(self, client, auth_headers, db):
        """上传成功后，KnowledgeDocument 应保存真实 Celery task_id。"""
        real_task_id = "celery-task-123"

        with patch("src.api.routers.knowledge_base.process_document_task") as mock_task:
            mock_job = MagicMock()
            mock_job.id = real_task_id
            mock_task.delay.return_value = mock_job

            response = client.post(
                f"/api/v1/knowledge-bases/{self.kb_id}/upload",
                files={"file": ("report.txt", io.BytesIO(b"hello"), "text/plain")},
                headers=auth_headers,
            )
            assert response.status_code == 200, response.text
            doc_id = response.json()["doc_id"]

            # 关键断言：文档保存了真实 task_id，而不是用 doc_id 冒充
            doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc_id).first()
            assert doc.celery_task_id == real_task_id

    def test_monitor_uses_celery_task_id(self, client, auth_headers, db):
        """Monitor 端点返回的 task_id 应为真实 Celery task_id。"""
        real_task_id = "celery-task-456"

        with patch("src.api.routers.knowledge_base.process_document_task") as mock_task:
            mock_job = MagicMock()
            mock_job.id = real_task_id
            mock_task.delay.return_value = mock_job

            response = client.post(
                f"/api/v1/knowledge-bases/{self.kb_id}/upload",
                files={"file": ("report.txt", io.BytesIO(b"hello"), "text/plain")},
                headers={**auth_headers, "x-celery-available": "true"},
            )
            assert response.status_code == 200, response.text

        response = client.get("/api/v1/monitor/", headers=auth_headers)
        assert response.status_code == 200, response.text
        items = response.json()
        assert len(items) == 1
        assert items[0]["task_id"] == real_task_id
