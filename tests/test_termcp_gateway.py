import json

import httpx
import pytest
import pytest_asyncio

from mcp_servers import termcp_gateway as gateway


@pytest_asyncio.fixture
async def gateway_client(monkeypatch):
    calls = []
    approval = {"approval_mode": True, "pending_count": 0, "requests": []}

    async def upstream(request):
        calls.append(request)
        path = request.url.path
        if path == "/stream":
            rpc = json.loads(request.content)
            method = rpc["method"]
            if method == "tools/list":
                result = {"tools": [{"name": "shell_input"}, {"name": "forward"}]}
            elif rpc.get("params", {}).get("name") == "session_start":
                value = {"session_id": "s1", "shell_id": "sh1"}
                result = {"content": [{"type": "text", "text": json.dumps(value)}]}
            else:
                result = {"content": [{"type": "text", "text": '{"review_pending":true}'}]}
            data = {"jsonrpc": "2.0", "id": rpc["id"], "result": result}
            return httpx.Response(200, text=f"event: message\ndata: {json.dumps(data)}\n\n",
                                  headers={"content-type": "text/event-stream", "mcp-session-id": "mcp1"})
        if path == "/api/sessions":
            return httpx.Response(200, json={"sessions": [{"id": "s1", "ssh_config": "test-target"}]})
        if path == "/api/sessions/s1/shells":
            return httpx.Response(200, json={"shells": [{"id": "sh1"}]})
        if path.endswith("/approval"):
            return httpx.Response(200, json=approval)
        if path.startswith("/api/sessions/"):
            return httpx.Response(200, json={"ssh_config": "test-target" if path.endswith("s1") else "production"})
        return httpx.Response(404)

    monkeypatch.setattr(gateway, "TERMCP_TOKEN", "test-only-token")
    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as upstream_client:
        gateway.app.state.client = upstream_client
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway.app), base_url="http://gateway") as client:
            yield client, calls, approval


def rpc(name, arguments):
    return {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}


@pytest.mark.asyncio
@pytest.mark.parametrize("name,args", [
    ("forward", {}), ("ssh_config", {}),
    ("session_start", {"ssh_config": "production"}),
    ("session_start", {"ssh_config": "test-target", "command": "bash"}),
    ("shell_open", {"session_id": "s1", "args": ["-c", "id"]}),
    ("shell_key", {"shell_id": "sh1", "key": "enter", "repeat": 2}),
    ("shell_input", {"shell_id": "sh1", "text": "id\n"}),
])
async def test_gateway_denies_unapproved_tool_paths(gateway_client, name, args):
    client, calls, _ = gateway_client
    response = await client.post("/mcp", json=rpc(name, args))
    assert response.status_code == 403
    assert calls == []


@pytest.mark.asyncio
async def test_gateway_handles_sse_session_start_enforces_ttl_and_filters_discovery(gateway_client):
    client, calls, _ = gateway_client
    response = await client.post("/mcp", json=rpc("session_start", {"ssh_config": "test-target"}))
    assert response.status_code == 200
    assert response.headers["mcp-session-id"] == "mcp1"
    policy = [c for c in calls if c.method == "PATCH"]
    assert len(policy) == 1
    assert json.loads(policy[0].content) == {"enabled": True, "timeout_seconds": 1800}
    assert calls[0].url.path == "/stream"
    response = await client.post("/mcp", json={"id": 2, "method": "tools/list"})
    assert response.json()["result"]["tools"] == [{"name": "shell_input"}]


@pytest.mark.asyncio
async def test_gateway_denies_write_when_review_is_off_and_other_host_queries(gateway_client):
    client, calls, approval = gateway_client
    approval["approval_mode"] = False
    response = await client.post("/mcp", json=rpc("shell_input", {"shell_id": "sh1", "text": "id"}))
    assert response.status_code == 409
    assert all(c.url.path != "/stream" for c in calls)
    assert (await client.get("/api/sessions/prod/approval")).status_code == 403
    assert (await client.post("/api/approvals/req1/approve", json={})).status_code == 404
    assert (await client.patch("/api/sessions/s1/approval", json={"enabled": False})).status_code == 405


@pytest.mark.asyncio
async def test_gateway_refuses_json_rpc_batch(gateway_client):
    client, calls, _ = gateway_client
    assert (await client.post("/mcp", json=[rpc("forward", {})])).status_code == 403
    assert not calls
