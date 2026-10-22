"""AIOps-only MCP gateway; no approval decision or profile management routes."""

import json
import os
import re
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.background import BackgroundTask

TERMCP_URL = os.getenv("TERMCP_INTERNAL_URL", "http://termcp:18765").rstrip("/")
TERMCP_TOKEN = os.getenv("TERMCP_TOKEN", "")
SSH_PROFILE = os.getenv("TERMCP_SSH_PROFILE", "test-target")
APPROVAL_TTL = 1800
SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
ALLOWED_TOOLS = {"session_start", "session_list", "shell_open", "shell_list", "shell_input", "shell_key", "shell_output"}
ALLOWED_METHODS = {"initialize", "ping", "tools/list", "tools/call", "notifications/initialized", "notifications/cancelled"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, read=35.0)) as client:
        app.state.client = client
        yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


async def _termcp_request(client: httpx.AsyncClient, method: str, path: str, **kwargs):
    try:
        response = await client.request(method, f"{TERMCP_URL}{path}",
                                        headers={"Authorization": f"Bearer {TERMCP_TOKEN}"}, **kwargs)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "Cannot verify Termcp state") from exc


def _validate_id(value):
    if not isinstance(value, str) or not SESSION_ID.fullmatch(value):
        raise HTTPException(400, "Only bare Termcp ids are accepted")


async def _target_session(client, session_id):
    _validate_id(session_id)
    session = await _termcp_request(client, "GET", f"/api/sessions/{session_id}")
    if not isinstance(session, dict) or session.get("ssh_config") != SSH_PROFILE:
        raise HTTPException(403, "Session is outside the configured test target")
    return session


async def _shell_session(client, shell_id):
    _validate_id(shell_id)
    payload = await _termcp_request(client, "GET", "/api/sessions")
    for session in payload.get("sessions", []):
        if session.get("ssh_config") != SSH_PROFILE:
            continue
        session_id = session.get("id")
        _validate_id(session_id)
        shells = await _termcp_request(client, "GET", f"/api/sessions/{session_id}/shells")
        if any(shell.get("id") == shell_id for shell in shells.get("shells", [])):
            return session_id
    raise HTTPException(403, "Shell is outside the configured test target")


def _check_arguments(name, args):
    if name not in ALLOWED_TOOLS or not isinstance(args, dict):
        raise HTTPException(403, "Tool is disabled by the Termcp gateway")
    if name in {"session_start", "shell_open"}:
        if args.get("command") or args.get("args") or args.get("mode", "pty") != "pty":
            raise HTTPException(403, "Only an interactive shell without startup commands is allowed")
    if name == "session_start" and args.get("ssh_config") != SSH_PROFILE:
        raise HTTPException(403, "Only test-target is allowed")
    if name == "shell_key" and (args.get("key") != "enter" or args.get("repeat", 1) != 1):
        raise HTTPException(403, "Only one Enter may submit a reviewed command")
    if name == "shell_input":
        text = args.get("text")
        if not isinstance(text, str) or any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
            raise HTTPException(403, "Submit one command line without control characters")
    if name == "shell_output":
        if args.get("timeout", 3) > 15 or args.get("max_bytes", 8192) not in range(1, 16385):
            raise HTTPException(403, "Output read limits exceeded")


def _rpc_payload(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        payload = None
        # Finite POST responses may use SSE; GET streams are forwarded separately.
        for line in response.text.splitlines():
            if line.startswith("data:"):
                try:
                    item = json.loads(line[5:].strip())
                except ValueError:
                    continue
                if isinstance(item, dict) and ("result" in item or "error" in item):
                    payload = item
    if not isinstance(payload, dict):
        raise HTTPException(502, "Invalid Termcp MCP response")
    return payload


def _tool_value(payload):
    result = payload.get("result") or {}
    if result.get("isError") or payload.get("error"):
        return None
    for item in result.get("content", []):
        if item.get("type") == "text":
            try:
                return json.loads(item["text"])
            except ValueError:
                continue
    return result.get("structuredContent")


@app.api_route("/mcp", methods=["GET", "POST", "DELETE"])
async def proxy_mcp(request: Request):
    if not TERMCP_TOKEN:
        raise HTTPException(503, "Termcp token is not configured")
    client = request.app.state.client
    body = await request.body()
    rpc = None
    name = None
    args = {}
    if body:
        try:
            rpc = json.loads(body)
        except ValueError:
            raise HTTPException(400, "Invalid MCP request")
        if not isinstance(rpc, dict) or rpc.get("method") not in ALLOWED_METHODS:
            raise HTTPException(403, "MCP method or batch is disabled")
        params = rpc.get("params") or {}
        if not isinstance(params, dict):
            raise HTTPException(400, "Invalid MCP parameters")
        if rpc["method"] == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            _check_arguments(name, args)
            if name in {"shell_open", "shell_list"}:
                await _target_session(client, args.get("session_id"))
            if name in {"shell_input", "shell_key", "shell_output"}:
                session_id = await _shell_session(client, args.get("shell_id"))
                if name != "shell_output":
                    approval = await _termcp_request(client, "GET", f"/api/sessions/{session_id}/approval")
                    if approval.get("approval_mode") is not True or approval.get("pending_count") != 0:
                        raise HTTPException(409, "Review is disabled or another command is pending")

    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in {"host", "content-length", "authorization", "cookie", "accept-encoding"}}
    headers["Authorization"] = f"Bearer {TERMCP_TOKEN}"
    headers["Accept-Encoding"] = "identity"
    upstream_request = client.build_request(request.method, f"{TERMCP_URL}/stream",
                                            params=request.query_params, content=body, headers=headers)
    try:
        upstream = await client.send(upstream_request, stream=True)
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Termcp MCP is unavailable") from exc
    response_headers = {k: v for k, v in upstream.headers.items()
                        if k.lower() in {"content-type", "mcp-session-id", "mcp-protocol-version", "cache-control"}}
    if request.method == "GET":
        return StreamingResponse(upstream.aiter_raw(), status_code=upstream.status_code,
                                 headers=response_headers, background=BackgroundTask(upstream.aclose))
    try:
        await upstream.aread()
    finally:
        await upstream.aclose()
    if not upstream.content or not upstream.is_success:
        return Response(upstream.content, status_code=upstream.status_code, headers=response_headers)
    payload = _rpc_payload(upstream)
    if name == "session_start":
        value = _tool_value(payload)
        if value is not None:
            if not isinstance(value, dict):
                raise HTTPException(502, "Invalid new session response")
            session_id = value.get("session_id")
            await _target_session(client, session_id)
            await _termcp_request(client, "PATCH", f"/api/sessions/{session_id}/approval",
                                 json={"enabled": True, "timeout_seconds": APPROVAL_TTL})
    if rpc and rpc["method"] == "tools/list" and "result" in payload:
        payload["result"]["tools"] = [tool for tool in payload["result"].get("tools", [])
                                      if tool.get("name") in ALLOWED_TOOLS]
    if name == "session_list":
        value = _tool_value(payload)
        if isinstance(value, dict):
            value["sessions"] = [s for s in value.get("sessions", []) if s.get("ssh_config") == SSH_PROFILE]
            payload["result"] = {"content": [{"type": "text", "text": json.dumps(value)}]}
    response_headers.pop("content-type", None)
    return JSONResponse(payload, headers=response_headers)


@app.get("/api/sessions/{session_id}/approval")
async def read_approval_state(session_id: str, request: Request):
    if not TERMCP_TOKEN:
        raise HTTPException(503, "Termcp token is not configured")
    client = request.app.state.client
    await _target_session(client, session_id)
    return await _termcp_request(client, "GET", f"/api/sessions/{session_id}/approval")
