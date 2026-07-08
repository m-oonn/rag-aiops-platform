"""Health 模块功能测试。"""


class TestHealth:
    """验证健康检查端点。"""

    def test_health_check(self, client):
        """/health 端点应返回状态 ok（公开端点，无需认证）。"""
        response = client.get("/api/v1/health/health")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] == "ok"
        assert data["version"] == "1.0.0"

    def test_health_queues_requires_auth(self, client):
        """安全最佳实践: /health/queues 暴露 Celery 任务详情，需要认证。"""
        response = client.get("/api/v1/health/queues")
        assert response.status_code == 401  # 未认证应被拒绝

    def test_health_queues(self, client, auth_headers):
        """/health/queues 端点带认证后应返回 Celery 队列信息。"""
        response = client.get("/api/v1/health/queues", headers=auth_headers)
        assert response.status_code == 200, response.text
        data = response.json()
        assert "status" in data
