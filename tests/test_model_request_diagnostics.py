"""No network: actual HTTPX response parsing and simulated transport phases."""
import asyncio
import json

import httpx
import pytest

from scripts.model_request_diagnostics import record_model_response


@pytest.mark.asyncio
@pytest.mark.parametrize('reason', ['stop', 'length', 'tool_calls', None])
async def test_response_metadata_is_allowlisted_and_preserves_unknowns(tmp_path, reason):
    row = {}
    calls = []
    path = tmp_path / 'attempt.json'
    def save():
        path.write_text(json.dumps(row), encoding='utf-8')
    async def respond(request):
        calls.append(request)
        return httpx.Response(200, headers={'x-request-id': 'req-test-1',
            'authorization': 'Bearer never-save-this', 'set-cookie': 'private-cookie'}, json={
            'id': 'chatcmpl-test', 'model': 'glm-5.3-flash',
            'usage': {'prompt_tokens': 10, 'completion_tokens': 256, 'total_tokens': 266,
                'private': 'never-save-this', 'completion_tokens_details': {'reasoning_tokens': 5, 'private': 'secret'}},
            'choices': [{'index': 0, 'finish_reason': reason, 'message': {'content': 'private-answer',
                **({'tool_calls': [{'function': {'name': 'private-tool', 'arguments': 'secret'}}]}
                   if reason == 'tool_calls' else {})}}]})
    request = httpx.Request('POST', 'https://offline.test/chat/completions')
    transport = httpx.MockTransport(respond)
    response = await record_model_response(transport, request, row, save)
    assert response.json()['choices'][0]['message']['content'] == 'private-answer'
    saved = json.loads(path.read_text())
    assert len(calls) == 1 and saved == row
    assert saved['response_metadata'] == {'request_id': 'req-test-1', 'completion_id': 'chatcmpl-test',
        'choices': [{'index': 0, 'finish_reason': reason, 'tool_call_count': int(reason == 'tool_calls')}]}
    assert saved['served_model'] == 'glm-5.3-flash'
    assert saved['usage'] == {'prompt_tokens': 10, 'completion_tokens': 256, 'total_tokens': 266,
        'completion_tokens_details': {'reasoning_tokens': 5}}
    assert saved['status'] == 'returned' and saved['failure_stage'] is None
    assert 0 <= saved['response_headers_ms'] <= saved['response_body_ms'] <= saved['elapsed_ms']
    assert saved['started_at'] and saved['ended_at']
    assert 'trace' not in request.extensions
    for private in ['never-save-this', 'private-cookie', 'private-answer', 'private-tool', 'secret']:
        assert private not in path.read_text()
    await transport.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('during_body', [False, True])
async def test_actual_httpcore_events_identify_read_phase_without_network(during_body):
    import httpcore
    from httpcore._backends.mock import AsyncMockStream
    row, connections = {}, []
    class Stream(AsyncMockStream):
        async def read(self, max_bytes, timeout=None):
            if self._buffer:
                return self._buffer.pop(0)
            raise httpcore.ReadTimeout('private memory transport timeout')
    class Backend(httpcore.AsyncNetworkBackend):
        async def connect_tcp(self, host, port, **kwargs):
            connections.append((host, port))
            return Stream([b'HTTP/1.1 200 OK\r\nContent-Length: 20\r\nx-request-id: req-core\r\n\r\n'] if during_body else [])
    transport = httpx.AsyncHTTPTransport()
    # Test-only substitution: keep real HTTPX/httpcore protocol and trace code.
    transport._pool = httpcore.AsyncConnectionPool(network_backend=Backend())
    try:
        with pytest.raises(httpx.ReadTimeout):
            await record_model_response(transport, httpx.Request('POST', 'http://offline.test'), row, lambda: None)
        assert row['failure_stage'] == ('read_response_body' if during_body else 'wait_response_headers')
        assert len(connections) == 1 and row['error_type'] == 'ReadTimeout'
        assert (row.get('http_status') == 200) is during_body
        assert row['response_metadata']['request_id'] == ('req-core' if during_body else None)
        assert 'private' not in json.dumps(row)
    finally:
        await transport.aclose()


def test_unpriced_requests_count_unknown_usage_without_inventing_cost(tmp_path):
    from scripts.evaluate_autonomous_investigation import PaidRequestBudget
    budget = PaidRequestBudget(tmp_path, allow_unpriced_models=True)
    budget.ledger = [{'reserved_cny': 0, 'pricing_verified': False, 'status': 'ReadTimeout'},
        {'reserved_cny': 0, 'pricing_verified': False, 'http_status': 200,
            'usage': {'prompt_tokens': 10, 'completion_tokens': 2}}]
    before = json.dumps(budget.ledger)
    summary = budget.cost_summary()
    assert summary['usage_unknown_requests'] == 1 and summary['pricing_unknown_requests'] == 2
    assert summary['estimated_cny_peak'] is None
    assert json.dumps(budget.ledger) == before


@pytest.mark.asyncio
@pytest.mark.parametrize('data', [{}, {'choices': []}, {'choices': [None, {'message': {'tool_calls': None}}]},
    {'id': 'sk-never-save', 'model': {'private': 'secret'}, 'usage': {'prompt_tokens': True, 'completion_tokens': -1}}])
async def test_missing_or_invalid_metadata_is_unknown_not_invented(data):
    row = {}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=data))
    await record_model_response(transport, httpx.Request('POST', 'https://offline.test'), row, lambda: None)
    metadata = row['response_metadata']
    assert metadata['request_id'] is None and metadata['completion_id'] is None
    assert row['served_model'] is None and row['usage'] == {}
    if isinstance(data.get('choices'), list):
        assert metadata['choices'] == ([] if not data['choices'] else [
            {'index': None, 'finish_reason': None, 'tool_call_count': None}])
    else:
        assert metadata['choices'] is None
    await transport.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('phase,error', [('connection.connect_tcp', httpx.ConnectTimeout),
    ('connection.start_tls', httpx.ConnectError), ('http11.send_request_body', httpx.WriteTimeout),
    ('http11.receive_response_headers', httpx.ReadTimeout),
    ('http2.receive_response_headers', httpx.ReadTimeout), (None, httpx.ReadTimeout),
    (None, asyncio.CancelledError)])
async def test_transport_failures_save_observed_stage_without_exception_text(tmp_path, phase, error):
    row, calls, traces = {}, [], []
    path = tmp_path / 'failure.json'
    async def previous_trace(name, info):
        traces.append(name)
    class Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            calls.append(request)
            if phase:
                await request.extensions['trace'](phase + '.started', {'private': 'never-save-this'})
            raise error('private exception message')
    request = httpx.Request('POST', 'https://offline.test', extensions={'trace': previous_trace})
    with pytest.raises(error):
        await record_model_response(Transport(), request, row,
            lambda: path.write_text(json.dumps(row), encoding='utf-8'))
    expected = {'connection.connect_tcp': 'connect', 'connection.start_tls': 'tls',
        'http11.send_request_body': 'send_request', 'http11.receive_response_headers': 'wait_response_headers',
        'http2.receive_response_headers': 'wait_response_headers', None: 'transport_unknown'}
    assert row['failure_stage'] == expected[phase]
    assert row['status'] == row['error_type'] == error.__name__
    assert row['elapsed_ms'] >= 0 and row['ended_at']
    assert len(calls) == 1 and request.extensions['trace'] is previous_trace
    assert traces == ([phase + '.started'] if phase else [])
    assert 'private' not in path.read_text() and 'http_status' not in row


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['body', 'json', 'shape', 'http_error'])
async def test_response_failures_preserve_received_headers_and_not_body(failure):
    row = {}
    class BrokenBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'partial private body'
            raise httpx.ReadTimeout('private read error')
    async def respond(request):
        kwargs = {'stream': BrokenBody()} if failure == 'body' else {'content': b'private invalid json'}
        if failure == 'shape':
            kwargs = {'json': []}
        return httpx.Response(503 if failure == 'http_error' else 200, headers={'request-id': 'req-2'}, **kwargs)
    transport = httpx.MockTransport(respond)
    if failure == 'http_error':
        response = await record_model_response(transport, httpx.Request('POST', 'https://offline.test'), row, lambda: None)
        assert response.status_code == 503 and row['status'] == 'returned'
        assert row['failure_stage'] is None
    else:
        with pytest.raises(httpx.ReadTimeout if failure == 'body' else ValueError):
            await record_model_response(transport, httpx.Request('POST', 'https://offline.test'), row, lambda: None)
        assert row['failure_stage'] == ('read_response_body' if failure == 'body' else 'response_parse')
    assert row['response_metadata']['request_id'] == 'req-2'
    assert row['http_status'] == (503 if failure == 'http_error' else 200)
    assert row['response_headers_ms'] is not None
    assert (row['response_body_ms'] is None) == (failure == 'body')
    assert 'private' not in json.dumps(row)
    await transport.aclose()
