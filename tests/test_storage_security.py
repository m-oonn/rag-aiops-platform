"""storage 路由的 _safe_object_name 安全测试。

目标：验证用户隔离前缀机制正确防御 IDOR 攻击，
确保用户只能访问自己命名空间下的文件。
"""

import pytest
from unittest.mock import MagicMock

from src.api.routers.storage import _safe_object_name, _user_prefix


class TestUserPrefix:
    """用户前缀生成。"""

    def test_prefix_uses_user_id(self):
        """前缀格式应为 user_{id}。"""
        user = MagicMock()
        user.id = 42
        assert _user_prefix(user) == "user_42"

    def test_prefix_is_deterministic(self):
        """同一用户多次调用应返回相同前缀。"""
        user = MagicMock()
        user.id = 1
        assert _user_prefix(user) == _user_prefix(user)


class TestSafeObjectNameBasic:
    """基本的 object_name 安全化。"""

    def test_bare_filename_gets_user_prefix(self):
        """裸文件名应自动添加用户前缀。"""
        user = MagicMock()
        user.id = 1
        result = _safe_object_name("document.pdf", user)
        assert result == "user_1/document.pdf"

    def test_already_prefixed_name_not_doubled(self):
        """已带正确前缀的 object_name 不应重复添加。"""
        user = MagicMock()
        user.id = 1
        result = _safe_object_name("user_1/document.pdf", user)
        assert result == "user_1/document.pdf"

    def test_path_traversal_is_blocked(self):
        """路径穿越载荷 (..) 应被移除。"""
        user = MagicMock()
        user.id = 1
        result = _safe_object_name("../../etc/passwd", user)
        assert ".." not in result
        assert result.startswith("user_1/")

    def test_leading_slash_is_stripped(self):
        """前导斜杠应被移除，防止逃逸用户命名空间。"""
        user = MagicMock()
        user.id = 1
        result = _safe_object_name("/secret/file.txt", user)
        assert result == "user_1/secret/file.txt"


class TestSafeObjectNameIDORPrevention:
    """IDOR 攻击防护验证。"""

    def test_other_user_prefix_is_replaced(self):
        """伪造其他用户前缀 (user_99) 应被替换为当前用户前缀。"""
        user = MagicMock()
        user.id = 1
        result = _safe_object_name("user_99/secret.pdf", user)
        assert result.startswith("user_1/")
        assert "user_99" not in result

    def test_cannot_access_other_user_namespace(self):
        """用户 A 无法通过构造 object_name 访问用户 B 的文件。"""
        user_a = MagicMock()
        user_a.id = 1
        # 尝试各种方式访问 user_2 的文件
        payloads = [
            "user_2/secret.pdf",
            "user_2/../user_1/secret.pdf",
            "../user_2/secret.pdf",
        ]
        for payload in payloads:
            result = _safe_object_name(payload, user_a)
            # 结果必须始终在 user_1/ 命名空间下
            assert result.startswith("user_1/"), f"载荷 '{payload}' 逃逸了用户命名空间: {result}"

    def test_empty_object_name_gets_prefix(self):
        """空 object_name 也应添加用户前缀。"""
        user = MagicMock()
        user.id = 1
        result = _safe_object_name("", user)
        assert result.startswith("user_1/")

    def test_nested_path_preserved_within_namespace(self):
        """合法的嵌套路径应在用户命名空间内保留。"""
        user = MagicMock()
        user.id = 1
        result = _safe_object_name("folder/subfolder/file.txt", user)
        assert result == "user_1/folder/subfolder/file.txt"
