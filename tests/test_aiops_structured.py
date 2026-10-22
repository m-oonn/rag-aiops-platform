from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel

from src.agent.aiops import structured as module


class Answer(BaseModel):
    value: str


def fake_llm():
    llm = Mock()
    llm.with_structured_output.return_value = RunnableLambda(lambda _: None)
    return llm


@pytest.mark.asyncio
@pytest.mark.parametrize('status_code', [None, 401, 402, 403])
async def test_transport_or_authorization_error_does_not_start_json_fallback(monkeypatch, status_code):
    error = ConnectionError('never expose secret')
    error.status_code = status_code
    invoke = AsyncMock(side_effect=error)
    monkeypatch.setattr(module, 'ainvoke_with_retry', invoke)
    with pytest.raises(ConnectionError):
        await module.ainvoke_structured(fake_llm(), Answer, ChatPromptTemplate.from_template('{input}'), {'input': 'check'})
    assert invoke.await_count == 1


@pytest.mark.asyncio
async def test_invalid_json_has_distinct_safe_error(monkeypatch):
    llm = RunnableLambda(lambda _: None)
    llm.with_structured_output = Mock(return_value=RunnableLambda(lambda _: None))
    invoke = AsyncMock(side_effect=[None, SimpleNamespace(content='{"value": "secret truncated')])
    monkeypatch.setattr(module, 'ainvoke_with_retry', invoke)
    with pytest.raises(module.StructuredOutputError) as exc:
        await module.ainvoke_structured(llm, Answer, ChatPromptTemplate.from_template('{input}'), {'input': 'check'})
    assert 'secret' not in str(exc.value)
    assert invoke.await_count == 2


def test_fallback_schema_includes_nested_types():
    from src.agent.aiops.strategies.investigation import InvestigationDecision
    rendered = module._format_fields_for_prompt(InvestigationDecision).replace('{{', '{').replace('}}', '}')
    import json
    schema = json.loads(rendered)
    assert 'Citation' in schema['$defs']
    assert 'Alternative' in schema['$defs']
