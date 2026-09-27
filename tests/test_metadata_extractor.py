"""metadata_extractor.py 的功能测试。

目标：验证元数据提取接口返回结构正确，
即使当前是占位实现，也要锁定返回结构契约。
"""

import pytest
from src.processors.metadata_extractor import MetadataExtractor


class TestMetadataExtractor:
    """MetadataExtractor.extract() 返回结构验证。"""

    def test_returns_dict_with_keywords_key(self):
        """返回值应包含 keywords 键。"""
        result = MetadataExtractor.extract("any text")
        assert "keywords" in result

    def test_returns_dict_with_summary_key(self):
        """返回值应包含 summary 键。"""
        result = MetadataExtractor.extract("any text")
        assert "summary" in result

    def test_keywords_is_list(self):
        """keywords 应为列表类型。"""
        result = MetadataExtractor.extract("any text")
        assert isinstance(result["keywords"], list)

    def test_summary_is_str(self):
        """summary 应为字符串类型。"""
        result = MetadataExtractor.extract("any text")
        assert isinstance(result["summary"], str)

    def test_empty_text_does_not_crash(self):
        """空文本不应导致崩溃。"""
        result = MetadataExtractor.extract("")
        assert "keywords" in result
        assert "summary" in result

    def test_none_text_does_not_crash(self):
        """None 输入应安全处理（返回默认结构或抛出可预期异常）。"""
        try:
            result = MetadataExtractor.extract(None)
            assert "keywords" in result
        except (TypeError, AttributeError):
            # 如果实现选择抛异常，也是可接受的
            pass
