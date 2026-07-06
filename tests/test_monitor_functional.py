"""Monitor 模块功能测试。"""

from unittest.mock import patch, MagicMock

import pytest

from src.database.models import KnowledgeBase, KnowledgeDocument


class TestMonitorFunctional:
    """验证队列状态、统计、任务删除。"""

    def test_monitor_queue_status_requires_auth(self, client):
        """未认证访问 monitor 应返回 401。"""
        response = client.get("/api/v1/monitor/")
        assert response.status_code == 401

    def test_monitor_queue_status_empty(self, client, auth_headers):
        """无文档时队列状态为空。"""
        response = client.get("/api/v1/monitor/", headers=auth_headers)
        assert response.status_code == 200, response.text
        assert response.json() == []

    def test_monitor_queue_status_lists_owned_docs(
        self, client, auth_headers, db, test_user
    ):
        """队列状态应只返回当前用户的文档。"""
        kb = KnowledgeBase(name="Monitor KB", kb_uid="monitor-uid", owner_id=test_user.id)
        db.add(kb)
        db.commit()
        db.refresh(kb)

        doc = KnowledgeDocument(
            doc_uid="doc-uid",
            kb_id=kb.id,
            filename="report.txt",
            file_path="/tmp/report.txt",
            file_type="txt",
            status=0,
            celery_task_id="celery-task-123",
        )
        db.add(doc)
        db.commit()

        response = client.get("/api/v1/monitor/", headers=auth_headers)
        assert response.status_code == 200, response.text
        items = response.json()
        assert len(items) == 1
        assert items[0]["task_id"] == "celery-task-123"
        assert items[0]["filename"] == "report.txt"

    def test_monitor_queue_stats(self, client, auth_headers, db, test_user):
        """队列统计应正确计数。"""
        kb = KnowledgeBase(name="Stats KB", kb_uid="stats-uid", owner_id=test_user.id)
        db.add(kb)
        db.commit()
        db.refresh(kb)

        for status in [0, 1, 2, 3]:
            doc = KnowledgeDocument(
                doc_uid=f"doc-{status}",
                kb_id=kb.id,
                filename=f"file{status}.txt",
                file_path=f"/tmp/file{status}.txt",
                file_type="txt",
                status=status,
            )
            db.add(doc)
        db.commit()

        response = client.get("/api/v1/monitor/stats", headers=auth_headers)
        assert response.status_code == 200, response.text
        stats = response.json()
        assert stats["total_pending"] == 1
        assert stats["total_processing"] == 1
        assert stats["total_completed"] == 1
        assert stats["total_failed"] == 1

    def test_monitor_delete_task(self, client, auth_headers, db, test_user):
        """删除 monitor 任务（实际为文档）。"""
        kb = KnowledgeBase(name="Delete KB", kb_uid="delete-uid", owner_id=test_user.id)
        db.add(kb)
        db.commit()
        db.refresh(kb)

        doc = KnowledgeDocument(
            doc_uid="delete-doc",
            kb_id=kb.id,
            filename="delete.txt",
            file_path="/tmp/delete.txt",
            file_type="txt",
            status=0,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        response = client.delete(
            f"/api/v1/monitor/tasks/{doc.id}", headers=auth_headers
        )
        assert response.status_code == 200, response.text
        assert db.query(KnowledgeDocument).filter(KnowledgeDocument.id == doc.id).first() is None

    def test_monitor_batch_delete_tasks(self, client, auth_headers, db, test_user):
        """批量删除 monitor 任务。"""
        kb = KnowledgeBase(name="BatchDelete KB", kb_uid="batch-uid", owner_id=test_user.id)
        db.add(kb)
        db.commit()
        db.refresh(kb)

        doc_ids = []
        for i in range(2):
            doc = KnowledgeDocument(
                doc_uid=f"batch-doc-{i}",
                kb_id=kb.id,
                filename=f"batch{i}.txt",
                file_path=f"/tmp/batch{i}.txt",
                file_type="txt",
                status=0,
            )
            db.add(doc)
            db.commit()
            db.refresh(doc)
            doc_ids.append(str(doc.id))

        response = client.post(
            "/api/v1/monitor/tasks/batch-delete",
            json={"task_ids": doc_ids},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["message"] == "Deleted 2 tasks"
