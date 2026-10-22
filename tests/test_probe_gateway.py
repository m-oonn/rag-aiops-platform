import pytest
import threading
import json
from fastapi.testclient import TestClient

from mcp_servers.probe_gateway import ProbeGateway
from src.probe.protocol import hello


def test_gateway_rejects_wrong_target_and_unknown_capability():
    gateway = ProbeGateway(target_id="windows-local-01", token="token")
    with pytest.raises(PermissionError):
        gateway.register_hello({**hello(target_id="other", hostname="PC"), "type": "hello"})
    with pytest.raises(ValueError):
        gateway.register_hello({**hello(target_id="windows-local-01", hostname="PC"), "capabilities": ["exec"]})


@pytest.mark.asyncio
async def test_filtered_port_query_rejects_legacy_probe_without_filter_confirmation(monkeypatch):
    from mcp_servers import probe_gateway as module
    from unittest.mock import AsyncMock
    monkeypatch.setattr(module, '_tool', AsyncMock(return_value={
        'data_source': 'probe_target', 'payload': {'ports': []}}))
    with pytest.raises(ValueError, match='did not confirm port filters'):
        await module.probe_port_snapshot.fn(local_port=23456, listening_only=True)


def test_gateway_authentication_and_offline_status():
    gateway = ProbeGateway(target_id="windows-local-01", token="token")
    assert gateway.authenticate("Bearer token")
    assert not gateway.authenticate("Bearer wrong")
    status = gateway.status()
    assert status["status"] == "offline"
    assert status["stale"] is True


@pytest.mark.asyncio
async def test_evidence_list_returns_bounded_metadata_not_history_payloads(monkeypatch):
    from mcp_servers import probe_gateway as module
    from src.probe.protocol import utc_now
    gateway = ProbeGateway(target_id='windows-local-01', token='token')
    gateway.evidence = [{'target_id': gateway.target_id, 'operation': 'ports',
                         'collected_at': utc_now(), 'payload': {'content': 'private-log' * 100000}}]
    gateway.baseline = {'collected_at': utc_now(), 'resources': {'payload': {
        'cpu_percent': 12, 'memory': {'percent': 40}, 'network': {'secret': 'must-not-include'}}}}
    monkeypatch.setattr(module, 'gateway', gateway)
    result = await module.probe_list_evidence.fn()
    assert result['baseline_summary']['cpu_percent'] == 12
    assert result['evidence'][0]['operation'] == 'ports'
    assert result['data_source'] == 'gateway_summary'
    assert 'private-log' not in json.dumps(result)
    assert 'must-not-include' not in json.dumps(result)
    assert len(json.dumps(result)) < 3000


def test_gateway_accepts_baseline_only_for_registered_target():
    gateway = ProbeGateway(target_id="windows-local-01", token="token")
    gateway.register_hello(hello(target_id="windows-local-01", hostname="PC"))
    import asyncio
    asyncio.run(gateway.handle_message({"type": "event", "method": "baseline.report",
                                        "params": {"target_id": "windows-local-01", "collected_at": "2026-10-16T00:00:00Z"}}))
    assert gateway.baseline["target_id"] == "windows-local-01"


@pytest.mark.asyncio
async def test_evidence_list_exposes_bounded_historical_baseline_comparisons(monkeypatch):
    from mcp_servers import probe_gateway as module
    from src.agent.aiops import run_store
    from src.probe.protocol import utc_now
    gateway = ProbeGateway(target_id='windows-local-01', token='token')
    gateway.evidence = [{'operation': 'ports', 'collected_at': utc_now()}]
    requests = []
    def snapshots(target_id, *, limit):
        requests.append((target_id, limit))
        return [{'target_id': target_id, 'kind': 'baseline', 'collected_at': utc_now(),
                 'raw_hash': 'sha256:baseline', 'fresh': True, 'payload': {
                     'collected_at': utc_now(), 'resources': {'payload': {
                         'cpu_percent': cpu, 'memory': {'percent': 42},
                         'disks': [{'mountpoint': 'C:', 'percent': 80, 'free': 123456}],
                         'network': {'secret': 'must-not-include'}}},
                     'processes': {'payload': {'processes': [{'name': 'private-process'}]}, 'truncated': True},
                     'ports': {'payload': {'ports': [{'remote': 'private-address'}]}, 'truncated': True}}}
                for cpu in (15, 85)]
    monkeypatch.setattr(module, 'gateway', gateway)
    monkeypatch.setattr(run_store, 'list_probe_snapshots', snapshots)
    result = await module.probe_list_evidence.fn(limit=100)
    assert requests == [(gateway.target_id, 10)]
    history = result['baseline_history']
    assert [item['cpu_percent'] for item in history] == [15, 85]
    assert history[0]['disks'][0]['free'] == 123456
    assert history[0]['processes_truncated'] is True
    assert all(item['historical'] and not item['current'] for item in history)
    assert 'must-not-include' not in json.dumps(result)
    assert 'private-process' not in json.dumps(result)
    assert 'private-address' not in json.dumps(result)


@pytest.mark.asyncio
async def test_evidence_list_recovers_stale_summary_after_gateway_restart(monkeypatch):
    from mcp_servers import probe_gateway as module
    from src.agent.aiops import run_store
    old_time = '2020-01-01T00:00:00Z'
    monkeypatch.setattr(module, 'gateway', ProbeGateway(target_id='restart-target', token='token'))
    monkeypatch.setattr(run_store, 'list_probe_snapshots', lambda *args, **kwargs: [{
        'target_id': 'restart-target', 'kind': 'baseline', 'collected_at': old_time,
        'raw_hash': 'sha256:old', 'fresh': False, 'payload': {'collected_at': old_time,
            'resources': {'payload': {'cpu_percent': 90}}}}])
    result = await module.probe_list_evidence.fn()
    assert result['status']['status'] == 'offline'
    assert result['baseline_summary']['cpu_percent'] == 90
    assert result['baseline_summary']['fresh'] is False
    assert result['baseline_summary']['current'] is False
    assert result['baseline_history'][0]['collected_at'] == old_time


def test_gateway_detach_marks_target_offline_and_fails_pending_requests():
    import asyncio

    class FakeWebSocket:
        async def send_json(self, message):
            return None

    async def scenario():
        gateway = ProbeGateway(target_id="windows-local-01", token="token")
        await gateway.attach(FakeWebSocket())
        gateway.register_hello(hello(target_id="windows-local-01", hostname="PC"))
        pending = asyncio.get_running_loop().create_future()
        gateway._pending["req-1"] = pending

        await gateway.detach()

        assert gateway.status()["status"] == "offline"
        assert gateway.status()["stale"] is True
        assert pending.done()
        with pytest.raises(ConnectionError):
            pending.result()

    asyncio.run(scenario())


def test_gateway_rejects_a_second_connected_probe():
    import asyncio

    async def scenario():
        gateway = ProbeGateway(target_id="windows-local-01", token="token")
        await gateway.attach(object())
        with pytest.raises(RuntimeError, match="already connected"):
            await gateway.attach(object())
        await gateway.detach()

    asyncio.run(scenario())


@pytest.mark.parametrize('tool_name,arguments,operation,params', [
    ('probe_process_snapshot', {'sort_by': 'cpu'}, 'processes', {'sort_by': 'cpu'}),
    ('probe_port_snapshot', {'local_port': 23456, 'listening_only': True},
     'ports', {'limit': 256, 'local_port': 23456, 'listening_only': True}),
])
def test_mcp_call_round_trips_to_connected_probe(monkeypatch, tool_name, arguments, operation, params):
    """Exercise the real MCP HTTP -> gateway -> WebSocket -> MCP path."""
    from mcp_servers import probe_gateway as module
    import importlib
    module = importlib.reload(module)

    module.gateway.websocket = None
    module.gateway.hello = None
    module.gateway.token = "roundtrip-token"
    probe_result = {
        "target_id": "windows-local-01",
        "platform": "windows",
        "operation": operation,
        "collected_at": "2026-10-16T00:00:00Z",
        "collector_version": "1.0.0",
        "data_source": "probe_target",
        "payload": {"hostname": "test-pc", **({'local_port': 23456, 'listening_only': True} if operation == 'ports' else {})},
        "raw_hash": "sha256:test",
    }
    ready = threading.Event()
    received = {}

    with TestClient(module.app) as client:
        def probe_client():
            with client.websocket_connect(
                "/probe/ws", headers={"Authorization": "Bearer roundtrip-token"}
            ) as websocket:
                websocket.send_json(hello(target_id="windows-local-01", hostname="test-pc"))
                received["ack"] = websocket.receive_json()
                ready.set()
                request = websocket.receive_json()
                received["request"] = request
                websocket.send_json({"id": request["id"], "result": probe_result})

        thread = threading.Thread(target=probe_client, daemon=True)
        thread.start()
        assert ready.wait(5)

        headers = {
            "Authorization": "Bearer roundtrip-token",
            "Accept": "application/json, text/event-stream",
        }
        initialize = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            },
        )
        assert initialize.status_code == 200
        session_id = initialize.headers.get("mcp-session-id")
        assert session_id
        headers["Mcp-Session-Id"] = session_id
        client.post(
            "/mcp",
            headers=headers,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        call = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            },
        )
        assert call.status_code == 200
        assert "test-pc" in call.text
        thread.join(timeout=5)
        assert received["ack"]["type"] == "hello.ack"
        assert received["request"]["method"] == 'probe.' + operation
        assert received['request']['params'] == params

