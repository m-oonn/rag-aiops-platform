"""认证模块功能测试。"""

import pytest
from jose import jwt

from src.database.models import User
from src.settings import settings
from src.utils.security import verify_password


class TestAuthFunctional:
    """验证注册、登录、用户信息等认证链路。"""

    def test_register_new_user(self, client):
        """新用户注册应成功并返回用户信息（不含密码哈希）。"""
        response = client.post(
            "/api/v1/auth/register",
            json={
                "username": "newuser",
                "email": "new@example.com",
                "password": "newpass123",
            },
        )
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["username"] == "newuser"
        assert data["email"] == "new@example.com"
        assert "password" not in data
        assert "password_hash" not in data

    def test_register_duplicate_username(self, client, test_user):
        """重复用户名应返回 409。"""
        response = client.post(
            "/api/v1/auth/register",
            json={
                "username": test_user.username,
                "email": "unique@example.com",
                "password": "newpass123",
            },
        )
        assert response.status_code == 409
        # 安全最佳实践: 统一错误消息防用户枚举，不区分用户名/邮箱
        assert "已被注册" in response.json()["detail"]

    def test_register_duplicate_email(self, client, test_user):
        """重复邮箱应返回 409。"""
        response = client.post(
            "/api/v1/auth/register",
            json={
                "username": "uniqueuser",
                "email": test_user.email,
                "password": "newpass123",
            },
        )
        assert response.status_code == 409
        assert "已被注册" in response.json()["detail"]

    def test_login_with_valid_credentials(self, client, test_user):
        """正确用户名密码应返回 access_token。"""
        response = client.post(
            "/api/v1/auth/login/access-token",
            data={"username": "testuser", "password": "testpass"},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["token_type"] == "bearer"
        assert data["access_token"]

        payload = jwt.decode(data["access_token"], settings.SECRET_KEY, algorithms=["HS256"])
        assert payload["sub"] == str(test_user.id)

    def test_login_with_invalid_password(self, client, test_user):
        """错误密码应返回 401。"""
        response = client.post(
            "/api/v1/auth/login/access-token",
            data={"username": "testuser", "password": "wrongpass"},
        )
        assert response.status_code == 401

    def test_login_inactive_user(self, db, client):
        """未激活用户应拒绝登录。"""
        from src.utils.security import get_password_hash

        inactive = User(
            username="inactiveuser",
            email="inactive@example.com",
            password_hash=get_password_hash("pass"),
            is_active=False,
        )
        db.add(inactive)
        db.commit()

        response = client.post(
            "/api/v1/auth/login/access-token",
            data={"username": "inactiveuser", "password": "pass"},
        )
        assert response.status_code == 401
        assert "inactive" in response.json()["detail"].lower()

    def test_password_hash_stored_not_plaintext(self, db, test_user):
        """数据库中必须存储哈希密码，不能是明文。"""
        assert test_user.password_hash != "testpass"
        assert verify_password("testpass", test_user.password_hash)
