from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel

from src.agent.aiops import structured as module


class Answer(BaseModel):
    value: str


class NestedCitation(BaseModel):
    evidence_id: str
    quote: str


class NestedDecision(BaseModel):
    citation: NestedCitation


class MappedDecision(BaseModel):
    value: str
    metadata: dict[str, Answer]


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


@pytest.mark.asyncio
@pytest.mark.parametrize('result', [None, {'value': 42}])
async def test_single_composition_disables_format_and_outer_retry(monkeypatch, result):
    invoke = AsyncMock(return_value=result)
    monkeypatch.setattr(module, 'ainvoke_with_retry', invoke)
    with pytest.raises(module.StructuredOutputError):
        await module.ainvoke_structured(fake_llm(), Answer,
            ChatPromptTemplate.from_template('{input}'), {'input': 'check'},
            format_fallback=False, max_attempts=1)
    invoke.assert_awaited_once()
    assert invoke.await_args.kwargs['max_attempts'] == 1


@pytest.mark.asyncio
async def test_json_fallback_preserves_partial_prompt_variables(monkeypatch):
    llm = RunnableLambda(lambda _: None)
    llm.with_structured_output = Mock(return_value=RunnableLambda(lambda _: None))
    invoke = AsyncMock(side_effect=[None, SimpleNamespace(content='{"value":"ok"}')])
    monkeypatch.setattr(module, 'ainvoke_with_retry', invoke)
    prompt = ChatPromptTemplate.from_messages([
        ('system', 'Contract: {contract}'), ('user', '{input}')
    ]).partial(contract='bound')

    result = await module.ainvoke_structured(llm, Answer, prompt, {'input': 'check'})

    assert result == Answer(value='ok')
    fallback_chain = invoke.await_args_list[1].args[0]
    rendered = fallback_chain.first.invoke({'input': 'check'})
    assert 'Contract: bound' in rendered.to_string()


@pytest.mark.asyncio
async def test_json_fallback_classifies_truncated_response_before_parsing(monkeypatch):
    llm = RunnableLambda(lambda _: None)
    llm.with_structured_output = Mock(return_value=RunnableLambda(lambda _: None))
    invoke = AsyncMock(side_effect=[None, SimpleNamespace(content='{"value":',
        response_metadata={'choices': [{'finish_reason': 'length'}]})])
    monkeypatch.setattr(module, 'ainvoke_with_retry', invoke)

    with pytest.raises(module.StructuredOutputError) as raised:
        await module.ainvoke_structured(llm, Answer, ChatPromptTemplate.from_template('{input}'), {'input': 'check'})

    assert raised.value.code == 'output_truncated'
    assert invoke.await_count == 2


@pytest.mark.asyncio
async def test_schema_failures_log_stage_and_field_without_model_values(monkeypatch):
    import json
    from src.utils.logger import logger
    warning = Mock()
    monkeypatch.setattr(logger, 'warning', warning)
    llm = RunnableLambda(lambda _: None)
    llm.with_structured_output = Mock(return_value=RunnableLambda(lambda _: None))
    invoke = AsyncMock(side_effect=[{'value': {'password': 'private-value'}},
        SimpleNamespace(content='{"value": {"token": "private-value"}}')])
    monkeypatch.setattr(module, 'ainvoke_with_retry', invoke)
    with pytest.raises(module.StructuredOutputError):
        await module.ainvoke_structured(llm, Answer, ChatPromptTemplate.from_template('{input}'), {'input': 'check'})
    messages = [str(call.args[0]) for call in warning.call_args_list]
    assert len(messages) == 2
    assert 'stage=function_calling' in messages[0] and 'stage=json_fallback' in messages[1]
    assert all('Answer' in message and 'string_type' in message and 'value' in message for message in messages)
    assert 'private-value' not in json.dumps(messages)
    assert 'password' not in json.dumps(messages) and 'token' not in json.dumps(messages)


def test_failure_details_only_include_schema_field_names_and_error_codes():
    import json
    from pydantic import ValidationError
    error = ValidationError.from_exception_data('secret-title', [
        {'type': 'missing', 'loc': ('value', 'secret-dynamic-key'), 'input': {'password': 'private-value'}}])
    details = module._failure_details(error, Answer)
    encoded = json.dumps(details)
    assert 'value' in encoded and 'missing' in encoded
    assert all(secret not in encoded for secret in ('secret-title', 'secret-dynamic-key', 'password', 'private-value'))


def test_fallback_schema_includes_nested_types():
    from src.agent.aiops.strategies.investigation import InvestigationDecision
    rendered = module._format_fields_for_prompt(InvestigationDecision).replace('{{', '{').replace('}}', '}')
    import json
    schema = json.loads(rendered)
    assert 'Citation' in schema['$defs']
    assert 'Alternative' in schema['$defs']


def test_nested_validation_failure_keeps_safe_field_path_without_input_values():
    import json
    from pydantic import ValidationError

    try:
        NestedDecision.model_validate({'citation': {'evidence_id': {'secret': 'token'},
            'quote': 123}})
    except ValidationError as error:
        details = module._failure_details(error, NestedDecision)
    else:
        raise AssertionError('fixture must fail validation')

    assert details['error_type'] == 'ValidationError'
    assert {'citation', 'evidence_id'} <= set(details['issues'][0]['path'])
    assert any(issue['path'] == ['citation', 'quote'] and issue['code'] == 'string_type'
               for issue in details['issues'])
    encoded = json.dumps(details, ensure_ascii=False)
    assert 'secret' not in encoded and 'token' not in encoded


def test_dynamic_dictionary_key_matching_another_field_is_still_redacted():
    from pydantic import ValidationError
    with pytest.raises(ValidationError) as raised:
        MappedDecision.model_validate({'value': 'ok', 'metadata': {'value': {'value': []}}})
    details = module._failure_details(raised.value, MappedDecision)
    assert details['issues'][0]['path'] == ['metadata', '<field>', 'value']


def test_real_decision_list_and_optional_reference_paths_stay_useful():
    from pydantic import ValidationError
    from src.agent.aiops.strategies.investigation import InvestigationDecision
    with pytest.raises(ValidationError) as raised:
        InvestigationDecision.model_validate({'hypothesis': 'private-value',
            'alternatives': [{'explanation': 'private-claim', 'status': 'private-wrong-status',
                'check': {'next_check': 'x', 'next_tools': [22]}}]})
    details = module._failure_details(raised.value, InvestigationDecision)
    assert any(item['path'] == ['alternatives', 0, 'status'] for item in details['issues'])
    assert any(item['path'] == ['alternatives', 0, 'check', 'next_tools', 0] for item in details['issues'])
    assert 'private' not in str(details)


@pytest.mark.asyncio
async def test_failure_traceback_cannot_expose_fallback_response(monkeypatch):
    import traceback
    llm = RunnableLambda(lambda _: None)
    llm.with_structured_output = Mock(return_value=RunnableLambda(lambda _: None))
    invoke = AsyncMock(side_effect=[None, SimpleNamespace(content='private-response-no-json')])
    monkeypatch.setattr(module, 'ainvoke_with_retry', invoke)
    with pytest.raises(module.StructuredOutputError) as raised:
        await module.ainvoke_structured(llm, Answer, ChatPromptTemplate.from_template('{input}'), {'input': 'x'})
    rendered = ''.join(traceback.format_exception(raised.value))
    assert 'private-response-no-json' not in rendered
