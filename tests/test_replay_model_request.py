import asyncio
import hashlib
import json

import httpx
import pytest

from scripts.replay_model_request import prepare, execute


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setenv('LLM_API_BASE', 'https://www.rightapi.ai/v1')
    monkeypatch.setenv('AGENT_MODEL', 'glm-5.3-flash')
    monkeypatch.setenv('LLM_API_KEY', 'synthetic-private-key')
    source = tmp_path / 'prior'
    (source / 'model-inputs').mkdir(parents=True)
    body = {'model': 'glm-5.3-flash', 'max_tokens': 256, 'stream': False,
            'messages': [{'role': 'system', 'content': 'historical-evidence'}],
            'tools': [{'type': 'function', 'function': {'name': 'decision'}}]}
    input_file = source / 'model-inputs/1.json'
    input_file.write_text(json.dumps(body), encoding='utf-8')
    ledger = source / 'cost.json'
    ledger.write_text(json.dumps({'limit_cny': 5, 'reserved_cny': 0, 'requests': [
        {'number': 1, 'reserved_cny': 0, 'status': 'ReadTimeout', 'model': 'glm-5.3-flash',
         'input_file': 'model-inputs/1.json',
         'input_sha256': hashlib.sha256(input_file.read_bytes()).hexdigest()}]}), encoding='utf-8')
    supplement = tmp_path / 'supplement.json'
    supplement.write_text(json.dumps({'user_authorized_cost_attribution': {
        'amount_display_currency': '0.104769', 'currency_symbol': '$',
        'method': 'entire_account_cumulative_amount_as_user_accepted_estimate',
        'exact_scenario_bill_verified': False}}), encoding='utf-8')
    output = tmp_path / 'replay'
    plan = prepare(ledger, 1, supplement, output)
    return plan, ledger, input_file, supplement, body


@pytest.mark.asyncio
async def test_one_attempt_records_metadata_without_running_tools_or_copying_secrets(prepared):
    plan, ledger, input_file, supplement, body = prepared
    before = ledger.read_bytes()
    calls = []
    def respond(request):
        calls.append(request)
        assert json.loads(request.content) == body
        assert request.content == json.dumps(body).encode()
        assert request.headers['authorization'] == 'Bearer synthetic-private-key'
        assert request.extensions['timeout']['read'] == 60
        return httpx.Response(200, json={'model': 'glm-5.3-flash',
            'choices': [{'index': 0, 'finish_reason': 'tool_calls', 'message': {
                'tool_calls': [{'function': {'name': 'must-not-execute', 'arguments': 'secret-answer'}}]}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 20}})
    assert await execute(plan, transport=httpx.MockTransport(respond)) == 0
    assert len(calls) == 1
    with pytest.raises(FileExistsError):
        await execute(plan, transport=httpx.MockTransport(respond))
    assert len(calls) == 1 and ledger.read_bytes() == before
    result = json.loads((plan.parent / 'attempt.json').read_text())
    assert result['http_status'] == 200 and result['response_metadata']['choices'][0]['tool_call_count'] == 1
    assert result['diagnosis_evaluated'] is False and result['supplier_bill_cny'] is None
    assert result['wire_body_sha256'] == hashlib.sha256(json.dumps(body).encode()).hexdigest()
    for file in plan.parent.rglob('*'):
        if file.is_file():
            text = file.read_text(encoding='utf-8')
            assert 'synthetic-private-key' not in text and 'secret-answer' not in text


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['timeout', '429', 'redirect', 'bad_json'])
async def test_failures_stop_after_one_attempt_and_keep_diagnostics(prepared, mode):
    plan, *_ = prepared
    calls = []
    def respond(request):
        calls.append(request)
        if mode == 'timeout':
            raise httpx.ReadTimeout('never-save-secret-message', request=request)
        if mode == '429':
            return httpx.Response(429)
        if mode == 'redirect':
            return httpx.Response(307, headers={'location': 'https://elsewhere.invalid/'})
        return httpx.Response(200, content=b'not-json')
    assert await execute(plan, transport=httpx.MockTransport(respond)) == 1
    assert len(calls) == 1
    text = (plan.parent / 'attempt.json').read_text()
    assert 'never-save-secret-message' not in text
    result = json.loads(text)
    assert result['ended_at'] and result['elapsed_ms'] >= 0
    if mode == 'timeout':
        assert result['error_type'] == 'ReadTimeout' and result['failure_stage'] == 'transport_unknown'


@pytest.mark.asyncio
@pytest.mark.parametrize('changed', ['ledger', 'input', 'supplement', 'plan', 'endpoint', 'model'])
async def test_stale_or_changed_conditions_block_before_network(prepared, monkeypatch, changed):
    plan, ledger, input_file, supplement, _ = prepared
    if changed in {'ledger', 'input', 'supplement'}:
        path = {'ledger': ledger, 'input': input_file, 'supplement': supplement}[changed]
        path.write_bytes(path.read_bytes() + b' ')
    elif changed == 'plan':
        value = json.loads(plan.read_text())
        value['max_attempts'] = 2
        plan.write_text(json.dumps(value), encoding='utf-8')
    else:
        monkeypatch.setenv('LLM_API_BASE' if changed == 'endpoint' else 'AGENT_MODEL',
                           'https://elsewhere.invalid/v1' if changed == 'endpoint' else 'other-model')
    def never(request):
        pytest.fail('changed preparation must not send')
    with pytest.raises(ValueError):
        await execute(plan, transport=httpx.MockTransport(never))
    assert not (plan.parent / 'attempt.json').exists()


def test_preparation_is_local_and_does_not_override_resume_guard(prepared):
    from scripts.evaluate_windows_probe import read_cost_ledger
    plan, ledger, *_ = prepared
    value = json.loads(plan.read_text())
    assert value['max_attempts'] == 1 and value['timeout_seconds'] == 60
    assert value['purpose'] == 'historical_request_transport_diagnostic'
    assert not (plan.parent / 'attempt.json').exists()
    with pytest.raises(RuntimeError, match='uncertain cost'):
        read_cost_ledger(ledger, for_resume=True)


def test_existing_preparation_is_not_overwritten(prepared):
    plan, ledger, _, supplement, _ = prepared
    before = plan.read_bytes()
    with pytest.raises(FileExistsError):
        prepare(ledger, 1, supplement, plan.parent)
    assert plan.read_bytes() == before


@pytest.mark.asyncio
async def test_cancellation_remains_recorded_and_consumes_plan(prepared):
    plan, *_ = prepared
    async def cancel(request):
        raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await execute(plan, transport=httpx.MockTransport(cancel))
    row = json.loads((plan.parent / 'attempt.json').read_text())
    assert row['error_type'] == 'CancelledError' and row['ended_at']
    with pytest.raises(FileExistsError):
        await execute(plan, transport=httpx.MockTransport(cancel))


@pytest.mark.asyncio
async def test_missing_credential_blocks_before_attempt_file(prepared, monkeypatch):
    plan, *_ = prepared
    monkeypatch.delenv('LLM_API_KEY')
    with pytest.raises(ValueError, match='profile'):
        await execute(plan)
    assert not (plan.parent / 'attempt.json').exists()


@pytest.mark.asyncio
async def test_120_second_comparison_keeps_request_body_and_single_attempt(prepared):
    original, ledger, _, supplement, body = prepared
    before = {p: p.read_bytes() for p in (original, ledger)}
    plan = prepare(ledger, 1, supplement, original.parent.parent / 'longer', timeout_seconds=120)
    calls = []
    def respond(request):
        calls.append(request)
        assert set(request.extensions['timeout'].values()) == {120}
        assert request.content == json.dumps(body).encode()
        raise httpx.ReadTimeout('offline simulated timeout', request=request)
    assert await execute(plan, transport=httpx.MockTransport(respond)) == 1
    assert len(calls) == 1
    value = json.loads((plan.parent / 'attempt.json').read_text())
    assert value['timeout_seconds'] == 120 and value['status'] == 'ReadTimeout'
    assert all(p.read_bytes() == data for p, data in before.items())


@pytest.mark.parametrize('timeout', [0, -1, 61, 121, True, 120.0])
def test_unsupported_timeout_rejected_before_preparation(prepared, timeout):
    original, ledger, _, supplement, _ = prepared
    output = original.parent.parent / 'invalid'
    with pytest.raises(ValueError, match='timeout'):
        prepare(ledger, 1, supplement, output, timeout_seconds=timeout)
    assert not output.exists()


@pytest.mark.asyncio
async def test_minimal_schema_control_changes_only_function_parameters(prepared):
    original, ledger, _, supplement, body = prepared
    # The timeout fixture uses a generic name; match the audited historical role.
    input_file = ledger.parent / 'model-inputs/1.json'
    body['tools'][0]['function'] = {'name': 'InvestigationDecision',
        'parameters': {'type': 'object', 'properties': {
            'hypothesis': {'type': 'string'}, 'next_check': {'type': 'string', 'default': ''}},
            'required': ['hypothesis']}}
    body['tool_choice'] = {'type': 'function', 'function': {'name': 'InvestigationDecision'}}
    input_file.write_text(json.dumps(body), encoding='utf-8')
    value = json.loads(ledger.read_text())
    value['requests'][0]['input_sha256'] = hashlib.sha256(input_file.read_bytes()).hexdigest()
    ledger.write_text(json.dumps(value), encoding='utf-8')
    plan = prepare(ledger, 1, supplement, original.parent.parent / 'minimal',
                   timeout_seconds=120, schema_variant='hypothesis_only')
    calls = []
    def respond(request):
        calls.append(request)
        sent = json.loads(request.content)
        params = sent['tools'][0]['function']['parameters']
        assert params == {'type': 'object', 'properties': {'hypothesis': {'type': 'string'}},
                          'required': ['hypothesis']}
        sent['tools'][0]['function']['parameters'] = body['tools'][0]['function']['parameters']
        assert sent == body
        assert request.extensions['timeout']['read'] == 120
        return httpx.Response(200, json={'choices': [], 'usage': {}})
    assert await execute(plan, transport=httpx.MockTransport(respond)) == 0
    assert len(calls) == 1
    row = json.loads((plan.parent / 'attempt.json').read_text())
    assert row['schema_variant'] == 'hypothesis_only'
    assert row['replay_input_sha256'] != row['input_sha256']
    assert (plan.parent / 'request.json').is_file()
    assert 'historical-evidence' in (plan.parent / 'request.json').read_text()
    tampered = prepare(ledger, 1, supplement, original.parent.parent / 'tampered',
                       schema_variant='hypothesis_only')
    derived = tampered.parent / 'request.json'
    derived.write_bytes(derived.read_bytes() + b' ')
    with pytest.raises(ValueError, match='Derived'):
        await execute(tampered, transport=httpx.MockTransport(respond))
    assert len(calls) == 1 and not (tampered.parent / 'attempt.json').exists()


def test_unknown_schema_variant_is_rejected_locally(prepared):
    original, ledger, _, supplement, _ = prepared
    with pytest.raises(ValueError, match='schema variant'):
        prepare(ledger, 1, supplement, original.parent.parent / 'invalid-variant',
                schema_variant='remove_all_tools')


@pytest.mark.asyncio
async def test_user_agent_control_changes_only_one_header(prepared):
    original, ledger, _, supplement, body = prepared
    before = ledger.read_bytes()
    plan = prepare(ledger, 1, supplement, original.parent.parent / 'agent-ua',
                   timeout_seconds=120, user_agent_variant='agent')
    calls = []
    def respond(request):
        calls.append(request)
        assert request.headers['user-agent'] == 'Python-urllib/3.13'
        assert request.headers['accept'] == '*/*'
        assert not any(name.startswith('x-stainless-') for name in request.headers)
        assert request.content == json.dumps(body).encode()
        assert request.extensions['timeout']['read'] == 120
        return httpx.Response(200, json={'choices': [], 'usage': {}})
    assert await execute(plan, transport=httpx.MockTransport(respond)) == 0
    assert len(calls) == 1 and ledger.read_bytes() == before
    result = json.loads((plan.parent / 'attempt.json').read_text())
    assert result['user_agent_variant'] == 'agent'
    assert result['user_agent'] == 'Python-urllib/3.13'
    assert result['wire_body_sha256'] == hashlib.sha256(json.dumps(body).encode()).hexdigest()


def test_unsupported_user_agent_variant_is_rejected_locally(prepared):
    original, ledger, _, supplement, _ = prepared
    with pytest.raises(ValueError, match='User-Agent'):
        prepare(ledger, 1, supplement, original.parent.parent / 'invalid-ua',
                user_agent_variant='arbitrary-header')


@pytest.mark.asyncio
async def test_custom_transport_bypasses_environment_proxy_routes(monkeypatch):
    # Synthetic endpoints only: inspect routing without opening a connection.
    for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY',
                 'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('HTTPS_PROXY', 'http://127.0.0.1:9')
    url = httpx.URL('https://offline.invalid/v1/chat/completions')
    inner = httpx.AsyncHTTPTransport(retries=0)
    class Custom(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            pytest.fail('no real HTTP allowed')
        async def aclose(self):
            await inner.aclose()
    async with httpx.AsyncClient(transport=Custom()) as custom, httpx.AsyncClient() as default:
        assert custom._transport_for_url(url) is custom._transport
        assert custom._mounts == {}
        assert type(inner._pool).__name__ == 'AsyncConnectionPool'
        assert default._transport_for_url(url) is not default._transport


@pytest.mark.asyncio
async def test_current_sdk_generates_and_parses_decision_tool_offline():
    from langchain_openai import ChatOpenAI
    from langchain_core.utils.function_calling import convert_to_openai_tool
    from src.agent.aiops.strategies.investigation import InvestigationDecision
    from jsonschema import Draft202012Validator
    tool = convert_to_openai_tool(InvestigationDecision)
    schema = tool['function']['parameters']
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate({'hypothesis': 'offline'})
    calls = []
    def respond(request):
        calls.append(request)
        body = json.loads(request.content)
        assert body['tools'] == [tool]
        assert body['tool_choice'] == {'type': 'function', 'function': {'name': 'InvestigationDecision'}}
        assert body['parallel_tool_calls'] is False
        assert request.headers['user-agent'] == 'Python-urllib/3.13'
        return httpx.Response(200, json={'id': 'offline', 'model': 'glm-5.3-flash',
            'choices': [{'index': 0, 'finish_reason': 'tool_calls', 'message': {'role': 'assistant',
                'content': None, 'tool_calls': [{'id': 'call-offline', 'type': 'function',
                'function': {'name': 'InvestigationDecision', 'arguments': '{"hypothesis":"offline"}'}}]}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        llm = ChatOpenAI(model='glm-5.3-flash', api_key='synthetic-key',
            base_url='https://offline.invalid/v1', max_retries=0, max_tokens=256,
            http_async_client=client, default_headers={'User-Agent': 'Python-urllib/3.13'})
        result = await llm.with_structured_output(InvestigationDecision, method='function_calling').ainvoke('offline')
    assert len(calls) == 1 and result.hypothesis == 'offline'
