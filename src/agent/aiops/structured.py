"""结构化输出工具——带 JSON 解析降级。

问题: 用 with_structured_output(method="json_object") 时,qwen-max 兼容模式要求
user prompt 中出现 "json" 关键词,否则 400 报错(InternalError.Algo.InvalidParameter)。
方案:
  - 首选: with_structured_output(method="function_calling") — qwen-max 支持,稳定
  - 降级: 纯 LLM + regex 抠 JSON

调用方可像用 with_structured_output 一样调用 `ainvoke_structured(llm, schema, prompt_dict)`。
"""

import json as _json
import re as _re
from typing import Any, TypeVar

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

_T = TypeVar("_T", bound=BaseModel)

_JSON_SYSTEM_HINT = (
    "你必须只输出一个合法的 JSON 对象。"
    "不要包含任何解释、markdown 围栏、代码块或额外文本。"
    "只输出 JSON。"
    "例如,对于 Plan 类型,你应该输出: {\"steps\": [\"步骤1\", \"步骤2\"]}"
    "对于 Act 类型,你应该输出: {\"action\": \"continue\", \"new_steps\": []}"
    "对于 Response 类型,你应该输出: {\"response\": \"你的回答文本\"}"
    "\n以下是你需要输出的 JSON 格式:\n"
)


async def ainvoke_structured(
    llm: ChatOpenAI,
    schema: type[_T],
    prompt: ChatPromptTemplate,
    prompt_input: dict[str, Any],
) -> _T:
    """调 LLM 出结构化输出,首选 function_calling,失败降级手动 JSON。

    Args:
        llm: ChatOpenAI 实例(不用预先 with_structured_output)。
        schema: Pydantic 模型类。
        prompt: ChatPromptTemplate。
        prompt_input: prompt.invoke() 的参数。

    Returns:
        已校验的 Pydantic 实例。
    """
    from src.utils.logger import logger

    # ── 策略1: with_structured_output(method="function_calling") ──
    try:
        structured_llm = llm.with_structured_output(schema, method="function_calling")
        chain = prompt | structured_llm
        result = await chain.ainvoke(prompt_input)
        if isinstance(result, schema):
            return result
        return schema.model_validate(result)
    except Exception as e:
        logger.warning(
            f"[structured] function_calling 失败,降级: {type(e).__name__}: {e}"
        )

    # ── 策略2: 降级——纯 LLM + regex 抠 JSON ──
    fields_desc = _format_fields_for_prompt(schema)
    hint_msg = f"{_JSON_SYSTEM_HINT}{fields_desc}"
    json_prompt = ChatPromptTemplate.from_messages(
        [*prompt.messages, ("system", hint_msg)]
    )
    raw = await (json_prompt | llm).ainvoke(prompt_input)
    content = getattr(raw, "content", "") or str(raw)
    content = content.strip()

    obj = _extract_json_object(content)
    return schema.model_validate(obj)


def _format_fields_for_prompt(schema: type[BaseModel]) -> str:
    lines = ["{"]
    for name, field in schema.model_fields.items():
        ann = str(field.annotation)
        desc = field.description or ""
        lines.append(f'  "{name}": {ann},  // {desc}')
    lines.append("}")
    return "\n".join(lines)


def _extract_json_object(text: str) -> dict[str, Any]:
    """从文本中抠第一个 JSON 对象。"""
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"未找到 JSON 对象: {text[:200]}")
    return _json.loads(text[start : end + 1])
