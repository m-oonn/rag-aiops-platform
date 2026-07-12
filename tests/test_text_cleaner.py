"""text_cleaner.py 的功能测试。

目标：验证文本清洗逻辑正确处理控制字符、空白和 PDF 提取问题。
"""

import pytest
from src.processors.text_cleaner import TextCleaner


class TestTextCleanerEmpty:
    """空输入处理。"""

    def test_empty_string_returns_empty(self):
        """空字符串应返回空字符串。"""
        assert TextCleaner.clean("") == ""

    def test_none_returns_empty(self):
        """None 应返回空字符串。"""
        assert TextCleaner.clean(None) == ""


class TestTextCleanerControlChars:
    """控制字符移除。"""

    def test_removes_control_characters(self):
        """应移除 ASCII 控制字符 (0x00-0x1f 除 \t \n \r)。"""
        text = "Hello\x00\x07\x1fWorld"
        result = TextCleaner.clean(text)
        assert "\x00" not in result
        assert "\x07" not in result
        assert "\x1f" not in result

    def test_removes_del_character(self):
        """应移除 DEL 字符 (0x7f)。"""
        text = "Hello\x7fWorld"
        result = TextCleaner.clean(text)
        assert "\x7f" not in result


class TestTextCleanerWhitespace:
    """空白规范化。"""

    def test_normalizes_multiple_spaces(self):
        """多个连续空格应合并为一个。"""
        text = "Hello    World"
        result = TextCleaner.clean(text)
        assert "  " not in result

    def test_strips_leading_trailing_whitespace(self):
        """应去除首尾空白。"""
        text = "  Hello World  "
        result = TextCleaner.clean(text)
        assert result == "Hello World"

    def test_normalizes_tabs_and_newlines(self):
        """制表符和换行符应被规范化为单个空格。"""
        text = "Hello\t\n\nWorld"
        result = TextCleaner.clean(text)
        assert "\t" not in result
        assert "\n" not in result


class TestTextCleanerHyphenation:
    """PDF 提取的连字符修复。"""

    def test_fixes_hyphenation_at_line_end(self):
        """行尾连字符应被拼接 (hel- lo → hello)。"""
        text = "hel- lo world"
        result = TextCleaner.clean(text)
        # 连字符 + 空格应被移除，拼接成完整单词
        assert "hello" in result

    def test_preserves_regular_hyphen(self):
        """普通连字符 (无后续空格) 不应被移除。"""
        text = "well-known term"
        result = TextCleaner.clean(text)
        assert "well-known" in result


class TestTextCleanerChunk:
    """clean_chunk 方法。"""

    def test_clean_chunk_delegates_to_clean(self):
        """clean_chunk 应与 clean 行为一致。"""
        text = "Hello\x00  World"
        assert TextCleaner.clean_chunk(text) == TextCleaner.clean(text)
