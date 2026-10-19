import pytest

from src.agent.aiops.report_text import readable_tool_text, summarize_step_result
from src.agent.aiops.strategies.dynamic_classification import _clean_step_result


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


def test_summarize_search_log_shape():
    raw = ('[{"type": "text", "text": "{\\"topic_id\\":\\"order-service-logs-2026.10.13\\",'
           '\\"start_time\\":1792391024522,\\"end_time\\":1792398224522,\\"query\\":\\"*\\",'
           '\\"limit\\":50,\\"total\\":0,\\"logs\\":[],\\"took_ms\\":2,'
           '\\"data_source\\":\\"elasticsearch\\",\\"message\\":\\"未找到服务 api 的日志主题\\"}"}]')
    out = summarize_step_result(raw)
    assert out.startswith("翻了服务日志（窗口 ")
    assert "没有查到匹配的记录" in out
    assert "未找到服务 api 的日志主题" in out
    assert "{" not in out


def test_summarize_search_changes_shape():
    raw = '{"service_name": "order-service", "changes": [], "total": 0, "data_source": "elasticsearch"}'
    out = summarize_step_result(raw)
    assert out.startswith("查了变更记录（来自日志库）")
    assert "排除" in out


def test_summarize_topics_shape():
    raw = '{"total": 2, "topics": [{"topic_name": "a-logs"}, {"topic_name": "b-logs"}]}'
    out = summarize_step_result(raw)
    assert out == "日志库里找到 2 个相关日志主题：a-logs、b-logs。"


def test_summarize_unknown_json_untouched():
    raw = '{"foo": {"bar": 1}}'
    assert summarize_step_result(raw) is raw


def test_summarize_plain_text_untouched():
    text = "网站首页检查结果（真实探测）HTTP 200"
    assert summarize_step_result(text) is text


def test_clean_step_result_strips_headings_and_cuts_table():
    raw = "## 诊断结果：变更时间对齐 ### 1. 变更查询结果| 查询窗口| 服务| 命中数||---|---|---| 最近 1 小时| order| 0"
    out = _clean_step_result(raw)
    assert "#" not in out
    assert out.endswith("…")
    assert "|" not in out


def test_clean_step_result_keeps_plain_prose():
    out = _clean_step_result("网站首页可以正常打开，状态码 200。")
    assert out == "网站首页可以正常打开，状态码 200。"


def test_unwraps_nested_escaped_inner_json():
    raw = '[{"type": "text", "text": "{\\"topic_id\\":\\"order-logs\\",\\"total\\":0}"}]'
    assert readable_tool_text(raw) == '{"topic_id":"order-logs","total":0}'
