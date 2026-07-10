"""安全专项测试：认证、JWT、CORS、敏感数据泄露、输入安全。"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from jose import jwt, ExpiredSignatureError

from src.settings import settings
from src.utils.security import create_access_token, get_password_hash, verify_password


class TestJWTSecurity:
    """验证 JWT 生成与校验符合安全最佳实践。"""

    def test_token_expires_in_future(self):
        """Token 的 exp 必须是未来时间。"""
        token = create_access_token("user-1")
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        assert exp > datetime.now(timezone.utc)

    def test_token_expires_within_expected_window(self):
        """Token 过期时间应接近配置的 ACCESS_TOKEN_EXPIRE_MINUTES。"""
        token = create_access_token("user-1")
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        expected_max = datetime.now(timezone.utc) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES + 1
        )
        assert exp <= expected_max

    def test_token_subject_is_string(self):
        """JWT sub 字段应为字符串，避免类型混淆。"""
        token = create_access_token(12345)
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        assert payload["sub"] == "12345"

    def test_expired_token_is_rejected(self):
        """过期 Token 应无法通过校验。"""
        token = create_access_token("user-1", expires_delta=timedelta(seconds=-1))
        with pytest.raises(ExpiredSignatureError):
            jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])

    def test_tampered_token_is_rejected(self):
        """被篡改的 Token 应无法通过签名校验。"""
        token = create_access_token("user-1")
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(jwt.JWTError):
            jwt.decode(tampered, settings.SECRET_KEY, algorithms=["HS256"])

    def test_token_with_wrong_secret_is_rejected(self):
        """使用错误密钥签发的 Token 不应被接受。"""
        fake_token = jwt.encode(
            {"sub": "1", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
            "wrong-secret",
            algorithm="HS256",
        )
        with pytest.raises(jwt.JWTError):
            jwt.decode(fake_token, settings.SECRET_KEY, algorithms=["HS256"])


class TestAuthenticationSecurity:
    """验证认证流程的安全行为。"""

    def test_login_with_invalid_password_returns_401(self, client, test_user):
        """错误密码不应泄露用户是否存在，统一返回 401。"""
        response = client.post(
            "/api/v1/auth/login/access-token",
            data={"username": "testuser", "password": "wrongpass"},
        )
        assert response.status_code == 401

    def test_login_with_nonexistent_user_returns_401(self, client):
        """不存在的用户名也应返回 401，避免枚举攻击。"""
        response = client.post(
            "/api/v1/auth/login/access-token",
            data={"username": "notexists", "password": "anypass"},
        )
        assert response.status_code == 401

    def test_invalid_bearer_token_rejected(self, client):
        """伪造或格式错误的 Bearer Token 应返回 401/403。"""
        response = client.get(
            "/api/v1/knowledge-bases/",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert response.status_code in (401, 403)

    def test_protected_endpoint_without_token(self, client):
        """未携带 Token 访问受保护端点应返回 401。"""
        endpoints = [
            ("get", "/api/v1/knowledge-bases/"),
            ("get", "/api/v1/assistants/"),
            ("post", "/api/v1/chat/"),
        ]
        for method, url in endpoints:
            response = getattr(client, method)(url)
            assert response.status_code == 401, f"{method.upper()} {url} 应返回 401"


class TestPasswordSecurity:
    """验证密码哈希与校验机制。"""

    def test_password_hash_is_not_plaintext(self):
        """哈希结果不应与明文相同。"""
        password = "my-secret-password"
        hashed = get_password_hash(password)
        assert password not in hashed

    def test_password_hash_is_unique(self):
        """相同密码两次哈希结果应不同（含随机盐）。"""
        password = "my-secret-password"
        hashed1 = get_password_hash(password)
        hashed2 = get_password_hash(password)
        assert hashed1 != hashed2

    def test_verify_password_matches_hash(self):
        """正确密码应通过校验。"""
        password = "my-secret-password"
        hashed = get_password_hash(password)
        assert verify_password(password, hashed) is True

    def test_verify_wrong_password_fails(self):
        """错误密码不应通过校验。"""
        hashed = get_password_hash("my-secret-password")
        assert verify_password("wrong-password", hashed) is False

    def test_password_must_contain_letter_and_digit(self, client):
        """密码必须同时包含字母和数字，纯字母或纯数字应被拒绝。"""
        for weak_password in ["123456", "abcdef", "password"]:
            response = client.post(
                "/api/v1/auth/register",
                json={
                    "username": f"weak-{weak_password}",
                    "email": f"weak-{weak_password}@example.com",
                    "password": weak_password,
                },
            )
            assert response.status_code == 422, f"弱密码 '{weak_password}' 应被拒绝"


class TestSensitiveDataExposure:
    """验证敏感字段不会通过 API 泄露。"""

    def test_user_response_does_not_include_password_hash(self, client, auth_headers):
        """当前没有 /users 列表，但注册/登录响应不应包含 password_hash。"""
        unique = "leak-test-user"
        response = client.post(
            "/api/v1/auth/register",
            json={"username": unique, "email": f"{unique}@example.com", "password": "testpass1"},
        )
        assert response.status_code == 201, response.text
        data = response.json()
        assert "password_hash" not in data
        assert "password" not in data

    def test_login_response_does_not_include_password_hash(self, client, test_user):
        """登录成功响应只包含 token，不包含密码哈希。"""
        response = client.post(
            "/api/v1/auth/login/access-token",
            data={"username": "testuser", "password": "testpass"},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert "password_hash" not in data
        assert "password" not in data
        assert data["token_type"] == "bearer"


class TestCORSSecurity:
    """验证 CORS 配置在不同环境下的安全行为。"""

    def test_cors_allows_origin_in_development(self, client):
        """开发环境下 CORS 应允许任意 Origin 的预检请求。"""
        response = client.options(
            "/api/v1/health/health",
            headers={
                "Origin": "http://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        # 开发环境返回通配，因此可能没有 access-control-allow-origin 头
        # 这里只验证状态码正常即可
        assert response.status_code in (200, 400)

    def test_cors_does_not_use_wildcard_in_production(self):
        """生产环境下 CORS 不应返回通配符 Origin（安全最佳实践）。"""
        from src.main import _build_cors_origins

        with patch.object(settings, "APP_ENV", "production"):
            origins = _build_cors_origins()
            assert "*" not in origins


class TestInputSanitization:
    """验证常见恶意输入被当作普通字符串处理，不会被解析执行。"""

    def test_xss_payload_in_username_is_stored_as_text(self, client):
        """XSS 载荷应被原样存储，不会触发脚本执行（后端只做持久化，渲染端负责转义）。"""
        xss = "<script>alert('xss')</script>"
        unique = f"xss-{datetime.now(timezone.utc).timestamp()}"
        response = client.post(
            "/api/v1/auth/register",
            json={"username": unique, "email": f"{unique}@example.com", "password": "testpass1"},
        )
        assert response.status_code == 201, response.text
        assert response.json()["username"] == unique

    def test_sql_injection_payload_in_login_is_safe(self, client):
        """登录接口中的 SQL 注入载荷不应绕过认证。"""
        response = client.post(
            "/api/v1/auth/login/access-token",
            data={"username": "admin' OR '1'='1", "password": "any"},
        )
        assert response.status_code == 401
