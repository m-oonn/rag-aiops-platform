"""Allowlisted response metadata for non-streaming evaluation HTTP attempts."""
from datetime import datetime, timezone
import re
import time


def _identifier(value):
    if (isinstance(value, str) and len(value) <= 200
            and re.fullmatch(r'[A-Za-z0-9_.:/-]+', value)
            and not value.lower().startswith(('sk-', 'bearer'))):
        return value
    return None


def _usage(value):
    if not isinstance(value, dict):
        return {}
    result = {key: value[key] for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')
              if type(value.get(key)) is int and value[key] >= 0}
    for key, fields in {'prompt_tokens_details': ('cached_tokens', 'audio_tokens'),
            'completion_tokens_details': ('reasoning_tokens', 'audio_tokens',
                'accepted_prediction_tokens', 'rejected_prediction_tokens')}.items():
        details = value.get(key)
        if isinstance(details, dict):
            result[key] = {name: details[name] for name in fields
                           if type(details.get(name)) is int and details[name] >= 0}
    return result


async def record_model_response(transport, request, row, save):
    """Observe one attempt without retrying or copying response bodies/headers."""
    started = time.perf_counter()
    row.update(started_at=datetime.now(timezone.utc).isoformat(), ended_at=None, elapsed_ms=None,
        diagnostic_version=1, failure_stage=None, error_type=None,
        response_metadata={'request_id': None, 'completion_id': None, 'choices': None},
        response_headers_ms=None, response_body_ms=None)
    phase = 'transport_unknown'
    previous_trace = request.extensions.get('trace')

    async def trace(name, info):
        nonlocal phase
        # Event names identify transport stages; info may contain credentials.
        stages = {'wait_for_connection': 'connection_pool', 'connect_tcp': 'connect',
            'start_tls': 'tls', 'send_request_headers': 'send_request',
            'send_request_body': 'send_request', 'receive_response_headers': 'wait_response_headers',
            'receive_response_body': 'read_response_body'}
        parts = name.split('.')
        if len(parts) >= 2 and parts[-1] == 'started' and parts[-2] in stages:
            phase = stages[parts[-2]]
        if previous_trace is not None:
            await previous_trace(name, info)

    request.extensions['trace'] = trace
    save()
    try:
        response = await transport.handle_async_request(request)
        row.update(status='returned', http_status=response.status_code,
                   response_headers_ms=(time.perf_counter() - started) * 1000)
        row['response_metadata']['request_id'] = _identifier(
            response.headers.get('x-request-id') or response.headers.get('request-id'))
        phase = 'read_response_body'
        await response.aread()
        row['response_body_ms'] = (time.perf_counter() - started) * 1000
        if response.status_code == 200:
            phase = 'response_parse'
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError('Model response must be a JSON object')
            row.update(usage=_usage(data.get('usage')), served_model=_identifier(data.get('model')))
            metadata = row['response_metadata']
            metadata['completion_id'] = _identifier(data.get('id'))
            choices = data.get('choices')
            if isinstance(choices, list):
                metadata['choices'] = []
                for choice in choices:
                    if not isinstance(choice, dict):
                        continue
                    message = choice.get('message')
                    calls = message.get('tool_calls') if isinstance(message, dict) else None
                    reason = choice.get('finish_reason')
                    metadata['choices'].append({
                        'index': choice.get('index') if type(choice.get('index')) is int else None,
                        'finish_reason': reason if isinstance(reason, str) and reason in {
                            'stop', 'length', 'tool_calls', 'function_call', 'content_filter'} else None,
                        'tool_call_count': len(calls) if isinstance(calls, list) else (
                            0 if isinstance(message, dict) and 'tool_calls' not in message else None)})
        return response
    except BaseException as exc:
        row.update(status=type(exc).__name__, error_type=type(exc).__name__, failure_stage=phase)
        raise
    finally:
        row.update(ended_at=datetime.now(timezone.utc).isoformat(),
                   elapsed_ms=(time.perf_counter() - started) * 1000)
        if previous_trace is None:
            request.extensions.pop('trace', None)
        else:
            request.extensions['trace'] = previous_trace
        save()
