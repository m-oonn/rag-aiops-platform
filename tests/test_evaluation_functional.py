"""评估模块功能测试。"""

import io
import json

import pytest

from src.database.models import EvaluationTask, EvaluationDatasetItem, KnowledgeDocument


class TestEvaluationFunctional:
    """验证评估任务创建、数据集上传、运行、删除。"""

    @pytest.fixture
    def kb_id(self, client, db, auth_headers):
        """创建一个测试知识库，含一份已处理完成的文档。"""
        response = client.post(
            "/api/v1/knowledge-bases/",
            json={"name": "Eval KB", "description": "for eval tests"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        kb_id = response.json()["id"]

        # 插入一份已处理完成的文档，使 evaluation 的前置校验通过
        doc = KnowledgeDocument(
            doc_uid=f"eval-doc-{kb_id}",
            kb_id=kb_id,
            filename="eval_test.pdf",
            file_path="/tmp/eval_test.pdf",
            file_type="pdf",
            status=2,       # Completed
            chunk_count=10, # > 0
        )
        db.add(doc)
        db.commit()

        return kb_id

    def test_generate_evaluation_dataset_task(self, client, auth_headers, kb_id):
        """生成评估数据集任务应创建任务记录。"""
        response = client.post(
            "/api/v1/evaluations/generate",
            json={"kb_id": kb_id, "num_questions": 5, "mode": "kb"},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["name"].startswith("Eval-")
        assert data["status"] == 0

    def test_upload_evaluation_dataset(self, client, auth_headers):
        """自定义评估任务可上传 JSON 数据集。"""
        # 1. 创建自定义任务
        response = client.post(
            "/api/v1/evaluations/generate",
            json={
                "kb_id": None,
                "num_questions": 2,
                "mode": "kb",
                "is_custom_upload": True,
            },
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        task_id = response.json()["id"]

        # 2. 上传数据集
        dataset = [
            {"question": "Q1", "ground_truth": "A1", "qa_type": "single_hop"},
            {"question": "Q2", "ground_truth": "A2", "qa_type": "single_hop"},
        ]
        response = client.post(
            f"/api/v1/evaluations/{task_id}/upload-dataset",
            files={"file": ("dataset.json", io.BytesIO(json.dumps(dataset).encode()), "application/json")},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        assert "2" in response.json()["message"]

        # 3. 验证数据集条目
        response = client.get(
            f"/api/v1/evaluations/{task_id}/dataset", headers=auth_headers
        )
        assert response.status_code == 200, response.text
        items = response.json()
        assert len(items) == 2
        assert items[0]["question"] == "Q1"

    def test_run_evaluation_requires_ready_status(self, client, auth_headers):
        """未就绪任务不能运行评估。"""
        response = client.post(
            "/api/v1/evaluations/generate",
            json={"kb_id": None, "num_questions": 1, "mode": "kb", "is_custom_upload": True},
            headers=auth_headers,
        )
        task_id = response.json()["id"]

        response = client.post(
            f"/api/v1/evaluations/{task_id}/run", headers=auth_headers
        )
        assert response.status_code == 400
        assert "not ready" in response.json()["detail"].lower()

    def test_update_dataset_item(self, client, auth_headers):
        """更新数据集条目。"""
        response = client.post(
            "/api/v1/evaluations/generate",
            json={"kb_id": None, "num_questions": 1, "mode": "kb", "is_custom_upload": True},
            headers=auth_headers,
        )
        task_id = response.json()["id"]

        dataset = [{"question": "Q1", "ground_truth": "A1", "qa_type": "single_hop"}]
        client.post(
            f"/api/v1/evaluations/{task_id}/upload-dataset",
            files={"file": ("dataset.json", io.BytesIO(json.dumps(dataset).encode()), "application/json")},
            headers=auth_headers,
        )

        item = client.get(
            f"/api/v1/evaluations/{task_id}/dataset", headers=auth_headers
        ).json()[0]

        response = client.put(
            f"/api/v1/evaluations/dataset-items/{item['id']}",
            json={"question": "Updated Q", "ground_truth": "Updated A", "qa_type": "multi_hop"},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["question"] == "Updated Q"

    def test_delete_dataset_item(self, client, auth_headers, db):
        """删除数据集条目应减少 total_count。"""
        response = client.post(
            "/api/v1/evaluations/generate",
            json={"kb_id": None, "num_questions": 1, "mode": "kb", "is_custom_upload": True},
            headers=auth_headers,
        )
        task_id = response.json()["id"]

        dataset = [{"question": "Q1", "ground_truth": "A1", "qa_type": "single_hop"}]
        client.post(
            f"/api/v1/evaluations/{task_id}/upload-dataset",
            files={"file": ("dataset.json", io.BytesIO(json.dumps(dataset).encode()), "application/json")},
            headers=auth_headers,
        )

        item = client.get(
            f"/api/v1/evaluations/{task_id}/dataset", headers=auth_headers
        ).json()[0]

        response = client.delete(
            f"/api/v1/evaluations/dataset-items/{item['id']}", headers=auth_headers
        )
        assert response.status_code == 200, response.text

        task = db.query(EvaluationTask).filter(EvaluationTask.id == task_id).first()
        assert task.total_count == 0

    def test_list_evaluation_tasks(self, client, auth_headers, kb_id):
        """列出评估任务。"""
        client.post(
            "/api/v1/evaluations/generate",
            json={"kb_id": kb_id, "num_questions": 3, "mode": "kb"},
            headers=auth_headers,
        )

        response = client.get("/api/v1/evaluations/tasks", headers=auth_headers)
        assert response.status_code == 200, response.text
        assert len(response.json()) >= 1
