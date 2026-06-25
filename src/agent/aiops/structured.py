"""结构化输出工具——带 JSON 解析降级。

问题: deepseek-v3 通过 DashScope compatible-mode 调用 with_structured_output
时偶发返回纯文本(带 markdown 解释)而非 JSON → Pydantic 校验失败。此工具提供
两层策略:
  1) 首选: with_structured_output(原生 tool_calling → JSONSchema)
  2) 降级: 纯 LLM 调用 + 正则抠 JSON(遇 `{` 和 `}` 之间的内容)

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
    "你必须只输出一个 JSON 对象,不要包含任何解释、markdown 围栏、代码块或额外文本。"
    "只输出合法的 JSON。"
)


async def ainvoke_structured(
    llm: ChatOpenAI,
    schema: type[_T],
    prompt: ChatPromptTemplate,
    prompt_input: dict[str, Any],
) -> _T:
    """用 with_structured_output 调 LLM,失败时自动降级为手动 JSON 解析。

    Args:
        llm: 已创建的 ChatOpenAI 实例(不需要配 structured_output)。
        schema: Pydantic 模型类(含字段定义,用于构造 JSON instruction + 校验)。
        prompt: ChatPromptTemplate。
        prompt_input: prompt.invoke() 的参数字典。

    Returns:
        已校验的 Pydantic 实例。

    Raises:
        RuntimeError: 原生调用和降级都失败时。
    """
    # ── 策略1: with_structured_output ──
    try:
        structured_llm = llm.with_structured_output(schema)
        chain = prompt | structured_llm
        result = await chain.ainvoke(prompt_input)
        if isinstance(result, schema):
            return result
        # 如果 result 是 dict,校验
        return schema.model_validate(result)
    except Exception as e:
        from src.utils.logger import logger

        logger.warning(
            f"[structured] with_structured_output 失败,降级手动 JSON: {type(e).__name__}: {e}"
        )

    # ── 策略2: 降级——纯 LLM 调 + JSON 抠取 ──
    try:
        # 把 JSON schema 要求塞进 system message 末尾
        fields_desc = _format_fields_for_prompt(schema)
        hint_msg = (
            f"{_JSON_SYSTEM_HINT}\n\n"
            f"输出 JSON 结构:\n{fields_desc}"
        )

        # 构造带 JSON 指令的 prompt: 在原有 prompt 基础上追加 system hint
        # 使用 ChatPromptTemplate 拼接
        json_prompt = ChatPromptTemplate.from_messages(
            [
                *prompt.messages,
                ("system", hint_msg),
            ]
        )
        chain2 = json_prompt | llm
        raw = await chain2.ainvoke(prompt_input)
        content = getattr(raw, "content", "") or str(raw)
        content = content.strip()

        # 抠 JSON
        obj = _extract_json_object(content)
        return schema.model_validate(obj)
    except Exception as e2:
        raise RuntimeError(
            f"结构化输出两策略均失败: strategy1={type(e).__name__}: {e}, "
            f"strategy2={type(e2).__name__}: {e2}"
        ) from e2


def _format_fields_for_prompt(schema: type[BaseModel]) -> str:
    """把 Pydantic 模型字段格式化成 LLM 友好的 JSON 结构描述。"""
    lines = ["{"]
    for name, field in schema.model_fields.items():
        ann = str(field.annotation)
        desc = field.description or ""
        lines.append(f'  "{name}": {ann},  // {desc}')
    lines.append("}")
    return "\n".join(lines)


def _extract_json_object(text: str) -> dict[str, Any]:
    """从文本中抠出第一个 JSON 对象。"""
    # 去掉 markdown 围栏
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]

    # 从第一个 { 到最后一个 }
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"未找到 JSON 对象: {text[:200]}")
    candidate = text[start : end + 1]
    return _json.loads(candidate)
