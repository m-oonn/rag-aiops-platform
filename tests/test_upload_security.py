"""知识库文件上传安全测试。"""

import io

import pytest


class TestUploadSecurity:
    """验证文件上传有大小限制和文件名安全处理。"""

    @pytest.fixture(autouse=True)
    def setup_kb(self, client, auth_headers, db):
        """为每个测试创建一个知识库。"""
        response = client.post(
            "/api/v1/knowledge-bases/",
            json={"name": "Test KB", "description": "for upload tests"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        self.kb_id = response.json()["id"]

    def test_upload_path_traversal_filename_is_rejected(self, client, auth_headers):
        """文件名包含 .. 或绝对路径时应被拒绝，不能写出 UPLOAD_DIR 之外。"""
        response = client.post(
            f"/api/v1/knowledge-bases/{self.kb_id}/upload",
            files={"file": ("../../../etc/passwd.txt", io.BytesIO(b"secret"), "text/plain")},
            headers=auth_headers,
        )
        assert response.status_code == 400, (
            f"Expected 400, got {response.status_code}: {response.text}"
        )

    def test_upload_oversized_file_is_rejected(self, client, auth_headers):
        """超过最大限制的文件应返回 413 Payload Too Large。"""
        # 构造一个超过 50MB 的假文件（Streaming 内存占用可控）
        big_file = io.BytesIO(b"x" * (51 * 1024 * 1024))
        response = client.post(
            f"/api/v1/knowledge-bases/{self.kb_id}/upload",
            files={"file": ("big.txt", big_file, "text/plain")},
            headers=auth_headers,
        )
        assert response.status_code == 413, (
            f"Expected 413, got {response.status_code}: {response.text}"
        )

    def test_upload_valid_filename_succeeds(self, client, auth_headers):
        """合法文件名应正常上传。"""
        response = client.post(
            f"/api/v1/knowledge-bases/{self.kb_id}/upload",
            files={"file": ("report.txt", io.BytesIO(b"hello world"), "text/plain")},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["doc_id"] is not None
