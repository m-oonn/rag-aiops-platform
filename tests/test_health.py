"""Health 模块功能测试。"""


class TestHealth:
    """验证健康检查端点。"""

    def test_health_check(self, client):
        """/health 端点应返回状态 ok。"""
        response = client.get("/api/v1/health/health")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] == "ok"
        assert data["version"] == "1.0.0"

    def test_health_queues(self, client):
        """/health/queues 端点应返回 Celery 队列信息（即使 broker 不可用也返回状态）。"""
        response = client.get("/api/v1/health/queues")
        assert response.status_code == 200, response.text
        data = response.json()
        assert "status" in data
