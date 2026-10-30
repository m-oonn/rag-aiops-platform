"""结构化输出工具——带 JSON 解析降级。

问题: 用 with_structured_output(method="json_object") 时,qwen-max 兼容模式要求
user prompt 中出现 "json" 关键词,否则 400 报错(InternalError.Algo.InvalidParameter)。
方案:
  - 首选: with_structured_output(method="function_calling") — qwen-max 支持,稳定
  - 降级: 纯 LLM + regex 抠 JSON

调用方可像用 with_structured_output 一样调用 `ainvoke_structured(llm, schema, prompt_dict)`。
"""

import json as _json
import re
from typing import Any, TypeVar

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ValidationError
from langchain_core.exceptions import OutputParserException

from src.agent.aiops_llm import ainvoke_with_retry

_T = TypeVar("_T", bound=BaseModel)


class StructuredOutputError(ValueError):
    """Both structured and JSON output failed validation; contains no model text."""


def _format_failure(error: Exception) -> bool:
    if isinstance(error, (ValidationError, OutputParserException, _json.JSONDecodeError, NotImplementedError)):
        return True
    # Some compatible APIs reject the function-call format but support plain JSON.
    return (getattr(error, 'status_code', None) == 400
            and any(term in str(error).lower() for term in
                    ('tool_choice', 'function_call', 'response_format', 'structured_output')))


def _failure_details(error: Exception, schema: type[BaseModel]) -> dict:
    """Keep schema locations/codes; never log rejected inputs or parser text."""
    definition = schema.model_json_schema()

    def variants(node):
        if '$ref' in node:
            node = definition.get('$defs', {}).get(node['$ref'].rsplit('/', 1)[-1], {})
        yield node
        for branch in node.get('anyOf', []):
            yield from variants(branch)

    def safe_path(location):
        nodes, path = [definition], []
        for part in location:
            expanded = [variant for node in nodes for variant in variants(node)]
            if type(part) is int:
                children = [node['items'] for node in expanded if isinstance(node.get('items'), dict)]
                path.append(part if children and 0 <= part <= 10000 else '<field>')
            else:
                children = [node['properties'][part] for node in expanded
                            if isinstance(part, str) and part in node.get('properties', {})]
                path.append(part if children else '<field>')
                if not children:
                    children = [node['additionalProperties'] for node in expanded
                                if isinstance(node.get('additionalProperties'), dict)]
            nodes = children
        return path

    issues = []
    if isinstance(error, ValidationError):
        for item in error.errors(include_input=False, include_context=False, include_url=False)[:12]:
            issues.append({'path': safe_path(item['loc']),
                'code': item['type'] if re.fullmatch(r'[a-z_]{1,64}', item['type']) else 'validation_error'})
    return {'error_type': type(error).__name__, 'issues': issues}

_JSON_SYSTEM_HINT = (
    "你必须只输出一个合法的 JSON 对象。"
    "不要包含任何解释、markdown 围栏、代码块或额外文本。"
    "只输出 JSON。"
    "例如,对于 Plan 类型,你应该输出: {{\"steps\": [\"步骤1\", \"步骤2\"]}}"
    "对于 Act 类型,你应该输出: {{\"action\": \"continue\", \"new_steps\": []}}"
    "对于 Response 类型,你应该输出: {{\"response\": \"你的回答文本\"}}"
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
        result = await ainvoke_with_retry(
            chain, prompt_input, label="structured.function_calling"
        )
        if isinstance(result, schema):
            return result
        return schema.model_validate(result)
    except Exception as e:
        if not _format_failure(e):
            raise
        logger.warning(
            f"[structured] schema={schema.__name__} stage=function_calling 格式失败,降级: {_failure_details(e, schema)}"
        )

    # ── 策略2: 降级——纯 LLM + regex 抠 JSON ──
    fields_desc = _format_fields_for_prompt(schema)
    hint_msg = f"{_JSON_SYSTEM_HINT}{fields_desc}"
    json_prompt = ChatPromptTemplate.from_messages(
        [*prompt.messages, ("system", hint_msg)]
    )
    raw = await ainvoke_with_retry(
        json_prompt | llm, prompt_input, label="structured.json_fallback"
    )
    content = getattr(raw, "content", "") or str(raw)
    content = content.strip()

    try:
        obj = _extract_json_object(content)
        return schema.model_validate(obj)
    except (ValueError, ValidationError) as exc:
        logger.warning(
            f"[structured] schema={schema.__name__} stage=json_fallback 校验失败: {_failure_details(exc, schema)}"
        )
        raise StructuredOutputError('Model output did not match the required schema') from None


def _format_fields_for_prompt(schema: type[BaseModel]) -> str:
    # 对 LangChain PromptTemplate 转义花括号，避免 JSON 示例被当成变量
    return _json.dumps(schema.model_json_schema(), ensure_ascii=False).replace("{", "{{").replace("}", "}}")


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
