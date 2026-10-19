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


_DS_LABELS = {"prometheus": "监控", "elasticsearch": "日志库"}


def _ds_tag(obj: dict) -> str:
    """数据源 → 短中文标注；未知数据源保留原值（诚实可见）。"""
    ds = obj.get("data_source")
    if not (isinstance(ds, str) and ds.strip()):
        return ""
    label = _DS_LABELS.get(ds.lower())
    return f"（来自{label}）" if label else f"（数据源 {ds}）"


def _tail_note(obj: dict, line: str) -> str:
    """把 message 拼到句尾；与已有内容重复或为空时不拼。"""
    msg = obj.get("message")
    if not (isinstance(msg, str) and msg.strip()):
        return line
    core = msg.strip()[:6]
    if core and core in line:
        return line
    return f"{line}（日志库备注：{msg.strip()[:60]}）"


def _format_json_object(obj: dict) -> str | None:
    """对已知 MCP 输出形态生成一句人话摘要；未知形态返回 None。"""
    ds_tag = _ds_tag(obj)

    if "topic_id" in obj and "logs" in obj:
        st, et = _fmt_ts(obj.get("start_time")), _fmt_ts(obj.get("end_time"))
        window = f"（窗口 {st}–{et}）" if st and et else ""
        total = obj.get("total")
        query = obj.get("query")
        cond = ""
        if isinstance(query, str) and query.strip() and query != "*":
            cond = f"，搜索词「{query[:60]}」"
        if total == 0 or not (obj.get("logs") or []):
            line = f"翻了服务日志{window}：没有查到匹配的记录{cond}。"
        else:
            line = f"翻了服务日志{window}：找到 {total} 条相关记录{cond}。"
        return _tail_note(obj, line)

    if "changes" in obj and "service_name" in obj:
        st, et = _fmt_ts(obj.get("start_time")), _fmt_ts(obj.get("end_time"))
        window = f"（窗口 {st}–{et}）" if st and et else ""
        total = obj.get("total")
        if total == 0 or not (obj.get("changes") or []):
            line = f"查了变更记录{ds_tag}{window}：这段时间没有发布、改配置或扩缩容的动作——先排除\"改出来\"的问题。"
            msg = obj.get("message")
            if isinstance(msg, str) and ("无" in msg or "未" in msg):
                return line  # 备注与"没有变更"同义，不重复
            return _tail_note(obj, line)
        return _tail_note(obj, f"查了变更记录{ds_tag}{window}：找到 {total} 条变更。")

    if "topics" in obj:
        topics = obj.get("topics") or []
        names = []
        for item in topics[:5]:
            if isinstance(item, dict):
                name = str(item.get("topic_name") or item.get("topic_id") or "")
                if name:
                    names.append(name)
        line = f"日志库里找到 {len(topics)} 个相关日志主题"
        if names:
            line += "：" + "、".join(names)
        return _tail_note(obj, line + "。")

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
