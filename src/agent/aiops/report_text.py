"""报告层步骤结果可读化。

executor 偶尔会把工具的原始返回（形如 `[{"type": "text", "text": "..."}]` 的
ToolMessage 数组）当作步骤结果文本存入 past_steps；组装报告"关键证据"或喂给
报告 LLM 前，先在这里解包出 text 内容，避免原始 JSON 直出到报告或被长度截断
截成非法片段。只做展示层清洗，不影响 executor 保存的原始证据。
"""

import json
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
