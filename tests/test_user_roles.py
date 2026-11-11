"""用户角色管理：读取角色、管理员改角色、首个管理员的配置引导。

背景（真机复核发现的问题）：角色只存在数据库里，没有任何接口能读出来，
前端也没有用户管理页，所以 auditor（可读证据原文）这个能力在界面上走不通。
"""

import pytest

from src.database.models import User
from src.settings import settings


def _make_admin(db, user: User) -> None:
    user.role = "admin"
    db.commit()
    db.refresh(user)


class TestCurrentUser:
    def test_me_returns_role(self, client, test_user, auth_headers):
        response = client.get("/api/v1/auth/me", headers=auth_headers)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["username"] == "testuser"
        assert data["role"] == "user"
        assert "password_hash" not in data

    def test_me_requires_login(self, client):
        response = client.get("/api/v1/auth/me")
        assert response.status_code == 401


class TestRoleManagement:
    def test_list_users_requires_admin(self, client, test_user, other_user, auth_headers):
        response = client.get("/api/v1/auth/users", headers=auth_headers)
        assert response.status_code == 403, response.text
        assert "管理员" in response.json()["detail"]

    def test_admin_lists_users(self, client, db, test_user, other_user, auth_headers):
        _make_admin(db, test_user)
        response = client.get("/api/v1/auth/users", headers=auth_headers)
        assert response.status_code == 200, response.text
        usernames = {item["username"] for item in response.json()}
        assert {"testuser", "otheruser"} <= usernames

    def test_admin_changes_other_user_role(self, client, db, test_user, other_user, auth_headers):
        _make_admin(db, test_user)

        response = client.patch(
            "/api/v1/auth/users/{}/role".format(other_user.id),
            json={"role": "auditor"},
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["role"] == "auditor"

        db.refresh(other_user)
        assert other_user.role == "auditor"

        # 被改的人重新登录后，/me 应当读到新角色
        login = client.post(
            "/api/v1/auth/login/access-token",
            data={"username": "otheruser", "password": "otherpass"},
        )
        assert login.status_code == 200, login.text
        other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        me = client.get("/api/v1/auth/me", headers=other_headers)
        assert me.json()["role"] == "auditor"

    def test_admin_cannot_change_own_role(self, client, db, test_user, auth_headers):
        _make_admin(db, test_user)
        response = client.patch(
            "/api/v1/auth/users/{}/role".format(test_user.id),
            json={"role": "user"},
            headers=auth_headers,
        )
        assert response.status_code == 400, response.text
        assert "自己" in response.json()["detail"]

    def test_unknown_role_rejected(self, client, db, test_user, other_user, auth_headers):
        _make_admin(db, test_user)
        response = client.patch(
            "/api/v1/auth/users/{}/role".format(other_user.id),
            json={"role": "superuser"},
            headers=auth_headers,
        )
        assert response.status_code == 422, response.text

    def test_missing_user_returns_404(self, client, db, test_user, auth_headers):
        _make_admin(db, test_user)
        response = client.patch(
            "/api/v1/auth/users/999999/role",
            json={"role": "auditor"},
            headers=auth_headers,
        )
        assert response.status_code == 404, response.text


class TestBootstrapAdmin:
    def test_configured_username_promoted_on_login(self, client, db, test_user, monkeypatch):
        """首个管理员靠 ADMIN_USERNAMES 引导：登录即提权，幂等。"""
        monkeypatch.setattr(settings, "ADMIN_USERNAMES", "testuser")

        login = client.post(
            "/api/v1/auth/login/access-token",
            data={"username": "testuser", "password": "testpass"},
        )
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        me = client.get("/api/v1/auth/me", headers=headers)
        assert me.json()["role"] == "admin"

        db.refresh(test_user)
        assert test_user.role == "admin"

        # 幂等：再登录一次不会报错，角色仍是 admin
        again = client.post(
            "/api/v1/auth/login/access-token",
            data={"username": "testuser", "password": "testpass"},
        )
        assert again.status_code == 200
        assert client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {again.json()['access_token']}"},
        ).json()["role"] == "admin"

    def test_unlisted_username_stays_user(self, client, db, test_user, monkeypatch):
        monkeypatch.setattr(settings, "ADMIN_USERNAMES", "someoneelse, anothername")
        login = client.post(
            "/api/v1/auth/login/access-token",
            data={"username": "testuser", "password": "testpass"},
        )
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assert client.get("/api/v1/auth/me", headers=headers).json()["role"] == "user"

        db.refresh(test_user)
        assert test_user.role == "user"