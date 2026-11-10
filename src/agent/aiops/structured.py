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
import traceback
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, TypeVar

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ValidationError
from langchain_core.exceptions import OutputParserException

from src.agent.aiops_llm import ainvoke_with_retry

_T = TypeVar("_T", bound=BaseModel)
_decision_capture: ContextVar[list | None] = ContextVar('decision_capture', default=None)


@contextmanager
def capture_decision_output():
    """Opt-in decoded arguments, not provider bodies or reasoning; task-local."""
    rows = []
    token = _decision_capture.set(rows)
    try:
        yield rows
    finally:
        _decision_capture.reset(token)


def _capture_arguments(schema, stage, arguments):
    rows = _decision_capture.get()
    if rows is None:
        return None
    from src.probe.protocol import redact
    presence = ('unknown' if not isinstance(arguments, dict) else
                'omitted' if 'alternatives' not in arguments else
                'empty' if arguments['alternatives'] == [] else
                'nonempty' if isinstance(arguments['alternatives'], list) else 'invalid')
    row = {'stage': stage, 'schema': schema.__name__, 'alternatives_presence': presence,
           'decoded_arguments': redact(arguments), 'status': 'received'}
    rows.append(row)
    return row


def _tool_arguments(raw, schema):
    name = schema.model_json_schema().get('title', schema.__name__)
    for call in getattr(raw, 'tool_calls', []) or []:
        if call.get('name') == name:
            return call.get('args')
    # Invalid tool JSON is deliberately not retained as free text.
    return None


class StructuredOutputError(ValueError):
    """Both structured and JSON output failed validation; contains no model text."""

    def __init__(self, message: str, *, code: str = 'invalid_output'):
        super().__init__(message)
        self.code = code


def _unknown_tool_name(error: Exception) -> bool:
    """True when the tool parser rejected a tool name it was never given.

    A model may answer the decision contract with a call to a tool it can see in
    the conversation (for example the evidence reader).  LangChain's tool parser
    then looks the name up in its own schema dictionary and raises a bare
    KeyError from `parse_result`, which says nothing about the model text but does
    mean the output did not follow the requested schema.  Treating it as a format
    failure keeps one malformed turn from aborting the whole investigation; the
    plain JSON fallback below still has to satisfy the same schema.
    """
    if not isinstance(error, KeyError):
        return False
    frames = traceback.extract_tb(error.__traceback__)
    return any(frame.name == 'parse_result' and 'output_parsers' in frame.filename
               for frame in frames)


def _format_failure(error: Exception) -> bool:
    if isinstance(error, (ValidationError, OutputParserException, _json.JSONDecodeError, NotImplementedError)):
        return True
    if _unknown_tool_name(error):
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
    *,
    format_fallback: bool = True,
    max_attempts: int | None = None,
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
    row = None
    try:
        capture = _decision_capture.get() is not None
        structured_llm = llm.with_structured_output(schema, method="function_calling",
                                                   **({'include_raw': True} if capture else {}))
        chain = prompt | structured_llm
        result = await ainvoke_with_retry(chain, prompt_input, label="structured.function_calling",
            **({'max_attempts': max_attempts} if max_attempts is not None else {}))
        if capture and isinstance(result, dict) and 'raw' in result:
            row = _capture_arguments(schema, 'function_calling', _tool_arguments(result['raw'], schema))
            if result.get('parsing_error') is not None:
                raise result['parsing_error']
            result = result.get('parsed')
        elif capture:
            row = _capture_arguments(schema, 'function_calling', None)
        parsed = result if isinstance(result, schema) else schema.model_validate(result)
        if row is not None:
            from src.probe.protocol import redact
            row.update(status='parsed', parsed_proposal=redact(parsed.model_dump()))
        return parsed
    except Exception as e:
        if row is not None:
            row.update(status='rejected', failure=_failure_details(e, schema))
        if not _format_failure(e):
            raise
        if not format_fallback:
            raise StructuredOutputError('Model output did not match the required schema') from None
        logger.warning(
            f"[structured] schema={schema.__name__} stage=function_calling 格式失败,降级: {_failure_details(e, schema)}"
        )

    # ── 策略2: 降级——纯 LLM + regex 抠 JSON ──
    fields_desc = _format_fields_for_prompt(schema)
    hint_msg = f"{_JSON_SYSTEM_HINT}{fields_desc}"
    json_prompt = ChatPromptTemplate.from_messages(
        [*prompt.messages, ("system", hint_msg)]
    ).partial(**prompt.partial_variables)
    raw = await ainvoke_with_retry(
        json_prompt | llm, prompt_input, label="structured.json_fallback"
    )
    metadata = getattr(raw, 'response_metadata', {}) or {}
    choices = metadata.get('choices') or []
    finish_reason = choices[0].get('finish_reason') if choices else metadata.get('finish_reason')
    if finish_reason == 'length':
        row = _capture_arguments(schema, 'json_fallback', None)
        if row is not None:
            row.update(status='rejected', failure={'code': 'output_truncated'})
        raise StructuredOutputError('Model output was truncated at the token limit', code='output_truncated')
    content = getattr(raw, "content", "") or str(raw)
    content = content.strip()

    row = None
    try:
        obj = _extract_json_object(content)
        row = _capture_arguments(schema, 'json_fallback', obj)
        parsed = schema.model_validate(obj)
        if row is not None:
            from src.probe.protocol import redact
            row.update(status='parsed', parsed_proposal=redact(parsed.model_dump()))
        return parsed
    except (ValueError, ValidationError) as exc:
        if row is None:
            row = _capture_arguments(schema, 'json_fallback', None)
        if row is not None:
            row.update(status='rejected', failure=_failure_details(exc, schema))
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
