import pytest

from src.agent.aiops.report_text import readable_tool_text


def test_unwraps_single_tool_message_array():
    raw = '[{"type": "text", "text": "1792392816764", "id": "lc_abc"}]'
    assert readable_tool_text(raw) == "1792392816764"


def test_joins_multiple_text_items_and_drops_non_text():
    raw = '[{"type": "text", "text": "第一段"}, {"type": "text", "text": "第二段"}, {"id": "x"}]'
    assert readable_tool_text(raw) == "第一段\n第二段"


def test_leaves_plain_report_text_untouched():
    text = "# 诊断结果\n\n## 结论\n最可能的根因是应用层异常。"
    assert readable_tool_text(text) is text


def test_leaves_non_array_json_untouched():
    raw = '{"total": 0, "topics": []}'
    assert readable_tool_text(raw) is raw


def test_keeps_original_when_array_is_invalid_json():
    raw = '[{"type": "text", "text": "未闭合'
    assert readable_tool_text(raw) is raw


def test_returns_empty_text_array_as_original():
    raw = '[{"type": "text", "text": ""}]'
    assert readable_tool_text(raw) is raw


def test_non_string_input_is_stringified():
    assert readable_tool_text(12345) == "12345"


def test_unwraps_nested_escaped_inner_json():
    raw = '[{"type": "text", "text": "{\\"topic_id\\":\\"order-logs\\",\\"total\\":0}"}]'
    assert readable_tool_text(raw) == '{"topic_id":"order-logs","total":0}'
