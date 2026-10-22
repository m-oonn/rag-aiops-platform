import json

import pytest

from src.probe.protocol import RequestIdTracker, evidence, hello, redact, validate_request


def test_hello_and_request_validation():
    msg = hello(target_id="windows-local-01", hostname="PC")
    assert msg["protocol"] == "probe.v1"
    request_id, op, params = validate_request({"id": "req-1", "method": "probe.resources", "params": {}})
    assert (request_id, op, params) == ("req-1", "resources", {})


@pytest.mark.parametrize("message", [
    {"id": "req", "method": "probe.exec", "params": {}},
    {"id": "bad id", "method": "probe.resources", "params": {}},
    {"id": "req", "method": "probe.resources", "params": []},
])
def test_unsupported_or_malformed_requests_are_rejected(message):
    with pytest.raises(ValueError):
        validate_request(message)


@pytest.mark.parametrize('params', [{'local_port': 0}, {'local_port': True},
    {'local_port': 65536}, {'local_port': '80'}, {'listening_only': 'false'}])
def test_invalid_port_filters_rejected_in_protocol(params):
    with pytest.raises(ValueError):
        validate_request({'id': 'port-1', 'method': 'probe.ports', 'params': params})


def test_request_id_tracker_rejects_replay_and_evicts_old_ids():
    tracker = RequestIdTracker(max_ids=2)
    assert tracker.remember("req-1")
    assert tracker.remember("req-2")
    assert not tracker.remember("req-1")
    assert tracker.remember("req-3")
    # req-1 was evicted after the bounded window advanced.
    assert tracker.remember("req-1")


def test_evidence_hash_is_stable_and_secrets_are_redacted():
    item = evidence(target_id="t", operation="inventory", payload={"password": "secret", "ok": 1})
    assert item["raw_hash"].startswith("sha256:")
    safe = redact(item)
    assert safe["payload"]["password"] == "[REDACTED]"
    assert "secret" not in json.dumps(safe)


@pytest.mark.parametrize('text', [
    'Authorization: Basic hidden-credential',
    'Cookie: session=hidden-credential; csrf=hidden-credential',
    'Set-Cookie: session=hidden-credential; HttpOnly',
    'Password = "hidden-credential with spaces"; Database=orders',
    '{"password": "hidden-credential", "status": "failed"}',
    'postgresql://user:hidden-credential@localhost/orders',
    '-----BEGIN PRIVATE KEY-----\nhidden-credential\n-----END PRIVATE KEY-----',
])
def test_log_text_credentials_are_redacted(text):
    assert 'hidden-credential' not in redact(text)
    assert '[REDACTED]' in redact(text)


def test_redaction_keeps_operational_data_and_is_idempotent():
    payload = {'message': 'connection refused: localhost:5432', 'cpu_percent': 12.5,
               'headers': {'Proxy-Authorization': 'secret', 'Set-Cookie': 'secret'}}
    safe = redact(payload)
    assert safe['message'] == payload['message']
    assert safe['cpu_percent'] == 12.5
    assert safe['headers'] == {'Proxy-Authorization': '[REDACTED]', 'Set-Cookie': '[REDACTED]'}
    assert redact(safe) == safe

