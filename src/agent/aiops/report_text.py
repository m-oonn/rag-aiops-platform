"""报告层步骤结果可读化。

executor 偶尔会把工具的原始返回（形如 `[{"type": "text", "text": "..."}]` 的
ToolMessage 数组）当作步骤结果文本存入 past_steps；组装报告"关键证据"或喂给
报告 LLM 前，先在这里解包出 text 内容，并对已知 MCP 输出形态（日志检索/变更
检索/主题检索）生成一句确定性人话摘要，避免原始 JSON 直出到报告或被长度截断
截成非法片段。只做展示层清洗，不影响 executor 保存的原始证据。
"""

import json
from datetime import datetime
from typing import Any


def readable_tool_text(raw: Any) -> str:
    """识别 ToolMessage 数组形态并解包 text 字段；其余输入原样返回。"""
    if not isinstance(raw, str):
        raw = str(raw)
    s = raw.strip()
    if not (s.startswith("[{") and '"type"' in s[:400]):
        return raw
    try:
        parsed = json.loads(s)
    except (ValueError, TypeError):
        return raw
    if not (isinstance(parsed, list) and parsed
            and all(isinstance(item, dict) for item in parsed)):
        return raw
    texts = [str(item.get("text") or "") for item in parsed]
    joined = "\n".join(t for t in texts if t.strip())
    return joined if joined.strip() else raw


def _fmt_ts(value: Any) -> str:
    """epoch 毫秒 → 本地 HH:MM；失败返回空串。"""
    try:
        return datetime.fromtimestamp(int(value) / 1000).strftime("%H:%M")
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def _tail_message(obj: dict, line: str) -> str:
    msg = obj.get("message")
    if isinstance(msg, str) and msg.strip():
        return f"{line}；{msg.strip()[:80]}"
    return line


def _format_json_object(obj: dict) -> str | None:
    """对已知 MCP 输出形态生成一句确定性摘要；未知形态返回 None。"""
    ds = obj.get("data_source")
    tag = f"（数据源 {ds}）" if isinstance(ds, str) and ds else ""

    if "topic_id" in obj and "logs" in obj:
        total = obj.get("total")
        line = f"日志检索 {obj.get('topic_id')}{tag}：命中 {total if total is not None else '?'} 条"
        st, et = _fmt_ts(obj.get("start_time")), _fmt_ts(obj.get("end_time"))
        if st and et:
            line += f"（窗口 {st}–{et}）"
        query = obj.get("query")
        if isinstance(query, str) and query.strip() and query != "*":
            line += f"，条件「{query[:60]}」"
        if not (obj.get("logs") or []):
            line += "，窗口内无日志记录"
        return _tail_message(obj, line)

    if "changes" in obj and "service_name" in obj:
        total = obj.get("total")
        line = f"变更检索 service={obj.get('service_name')}{tag}：命中 {total if total is not None else '?'} 条"
        st, et = _fmt_ts(obj.get("start_time")), _fmt_ts(obj.get("end_time"))
        if st and et:
            line += f"（窗口 {st}–{et}）"
        if not (obj.get("changes") or []):
            line += "，窗口内无变更记录"
        return _tail_message(obj, line)

    if "topics" in obj:
        topics = obj.get("topics") or []
        names = []
        for item in topics[:5]:
            if isinstance(item, dict):
                name = str(item.get("topic_name") or item.get("topic_id") or "")
                if name:
                    names.append(name)
        line = f"日志主题检索{tag}：命中 {len(topics)} 个"
        if names:
            line += "：" + "、".join(names)
        return _tail_message(obj, line)

    return None


def summarize_step_result(raw: Any) -> str:
    """报告展示入口：解包工具数组 → 已知 JSON 形态转人话 → 其余原样。"""
    text = readable_tool_text(raw)
    s = text.strip()
    if s.startswith("{") and s.endswith("}"):
        try:
            obj = json.loads(s)
        except (ValueError, TypeError):
            obj = None
        if isinstance(obj, dict):
            summary = _format_json_object(obj)
            if summary:
                return summary
    return text
