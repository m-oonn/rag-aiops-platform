"""Gateway between the outbound Windows Probe and AIOps MCP clients.

The gateway has no shell or write operation.  It only forwards allow-listed
observation requests to a registered, connected probe and exposes the latest
evidence through read-only MCP tools.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import os
import time
import logging
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse
from fastmcp import FastMCP

from src.probe.protocol import CAPABILITIES, OPERATIONS, validate_request, validate_port_filters

STALE_SECONDS = int(os.getenv("PROBE_STALE_SECONDS", "180"))
BASELINE_CLEANUP_INTERVAL_SECONDS = 60
TARGET_ID = os.getenv("PROBE_TARGET_ID", "windows-local-01")
TOKEN = os.getenv("PROBE_TOKEN", "")
logger = logging.getLogger(__name__)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _fresh(collected_at: str | None, max_age: int = STALE_SECONDS) -> bool:
    if not collected_at:
        return False
    try:
        value = datetime.fromisoformat(collected_at.replace("Z", "+00:00"))
        return -30 <= (datetime.now(timezone.utc) - value).total_seconds() <= max_age
    except (ValueError, TypeError):
        return False


class ProbeGateway:
    def __init__(self, *, target_id: str = TARGET_ID, token: str = TOKEN):
        self.target_id = target_id
        self.token = token
        self.websocket: WebSocket | None = None
        self.hello: dict[str, Any] | None = None
        self.connected_at: str | None = None
        self.last_seen: str | None = None
        self.baseline: dict[str, Any] | None = None
        self.evidence: list[dict[str, Any]] = []
        self._pending: dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()

    def authenticate(self, auth_header: str | None) -> bool:
        expected = f"Bearer {self.token}"
        return bool(self.token) and bool(auth_header) and hmac.compare_digest(auth_header, expected)

    def register_hello(self, message: dict[str, Any]) -> None:
        if message.get("type") != "hello" or message.get("protocol") != "probe.v1":
            raise ValueError("invalid hello")
        if message.get("target_id") != self.target_id:
            raise PermissionError("target_id does not match token")
        if message.get("platform") != "windows":
            raise ValueError("only windows probes are supported")
        capabilities = set(message.get("capabilities") or [])
        if not capabilities.issubset(set(CAPABILITIES)):
            raise ValueError("hello contains an unsupported capability")
        self.hello = message
        self.last_seen = _utc()
        self.connected_at = self.last_seen
        try:
            from src.agent.aiops.run_store import upsert_probe_target
            upsert_probe_target(self.target_id, platform="windows", hostname=message.get("hostname"),
                                agent_version=message.get("agent_version"), capabilities=sorted(capabilities),
                                status="online")
        except Exception:
            logger.exception("Probe target persistence failed")

    async def attach(self, websocket: WebSocket) -> None:
        async with self._lock:
            if self.websocket is not None:
                raise RuntimeError("target already connected")
            self.websocket = websocket

    async def detach(self) -> None:
        async with self._lock:
            self.websocket = None
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(ConnectionError("probe disconnected"))
            self._pending.clear()
        try:
            from src.agent.aiops.run_store import upsert_probe_target
            if self.hello:
                upsert_probe_target(self.target_id, platform="windows", hostname=self.hello.get("hostname"),
                                    agent_version=self.hello.get("agent_version"), capabilities=self.hello.get("capabilities"),
                                    status="offline")
        except Exception:
            logger.exception("Probe offline status persistence failed")

    async def handle_message(self, message: dict[str, Any]) -> None:
        self.last_seen = _utc()
        if message.get("type") == "baseline.report" or (message.get("type") == "event" and message.get("method") == "baseline.report"):
            self.baseline = message.get("params") or {}
            if self.baseline.get("target_id") not in {None, self.target_id}:
                raise PermissionError("baseline target_id does not match the connected target")
            self.baseline["received_at"] = self.last_seen
            try:
                from src.agent.aiops.run_store import save_probe_snapshot, upsert_probe_target
                from src.probe.protocol import raw_hash
                save_probe_snapshot(self.target_id, "baseline", self.baseline, raw_hash(self.baseline))
                if self.hello:
                    upsert_probe_target(self.target_id, platform="windows", hostname=self.hello.get("hostname"),
                                        agent_version=self.hello.get("agent_version"),
                                        capabilities=self.hello.get("capabilities"), status="online")
            except Exception:
                logger.exception("Probe baseline persistence failed")
            return
        request_id = message.get("id")
        if request_id and request_id in self._pending:
            future = self._pending.pop(request_id)
            if not future.done():
                if "error" in message:
                    future.set_exception(RuntimeError(str(message["error"])))
                else:
                    result = message.get("result") or {}
                    self.evidence.append(result)
                    self.evidence = self.evidence[-500:]
                    future.set_result(result)

    async def request(self, operation: str, params: dict[str, Any] | None = None, timeout: float = 15.0) -> dict[str, Any]:
        if operation not in OPERATIONS:
            raise ValueError("operation is not allow-listed")
        ws = self.websocket
        if ws is None or not self.hello:
            raise ConnectionError("probe is offline")
        capabilities = set(self.hello.get("capabilities") or [])
        if operation not in capabilities:
            raise PermissionError("probe capability is not enabled")
        request_id = f"gw-{time.monotonic_ns()}"
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await ws.send_json({"id": request_id, "method": f"probe.{operation}", "params": params or {}})
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._pending.pop(request_id, None)

    def status(self) -> dict[str, Any]:
        online = self.websocket is not None and bool(self.hello)
        return {"target_id": self.target_id, "status": "online" if online else "offline",
                "stale": not _fresh((self.baseline or {}).get("collected_at")),
                "last_seen": self.last_seen, "hello": self.hello,
                "baseline": self.baseline}


gateway = ProbeGateway()
mcp = FastMCP("Probe Gateway")


async def _tool(operation: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return await gateway.request(operation, params)
    except ConnectionError as exc:
        return {"target_id": gateway.target_id, "operation": operation, "data_source": "unavailable", "error": str(exc), "stale": True}


@mcp.tool()
async def probe_inventory() -> dict[str, Any]:
    """Read the registered Windows target inventory."""
    return await _tool("inventory")


@mcp.tool()
async def probe_resource_snapshot() -> dict[str, Any]:
    """Read CPU, memory, disk and network counters from the target."""
    return await _tool("resources")


@mcp.tool()
async def probe_service_status(service: str) -> dict[str, Any]:
    """Read a configured Windows service status by its configured alias."""
    return await _tool("services", {"service": service})


@mcp.tool()
async def probe_process_snapshot(service: str | None = None, sort_by: str = 'memory') -> dict[str, Any]:
    """Top 256 accessible processes by memory (default) or cpu; configured service filter.

    Scans accessible processes before selecting. Not a complete process inventory;
    RSS can include shared memory and cannot explain all host memory use.
    """
    if sort_by not in {'memory', 'cpu'}:
        raise ValueError('sort_by must be memory or cpu')
    return await _tool("processes", {'sort_by': sort_by, **({"service": service} if service else {})})


@mcp.tool()
async def probe_port_snapshot(limit: int = 256, local_port: int | None = None,
                              listening_only: bool = False) -> dict[str, Any]:
    """Read up to 256 connections; filter by local_port/listening_only before truncation.

    A truncated result cannot prove absence. A missing PID means owner unavailable.
    Filters require an updated Probe; verify the echoed filters in the payload.
    """
    validate_port_filters(local_port, listening_only)
    result = await _tool("ports", {"limit": max(1, min(limit, 256)),
        "local_port": local_port, "listening_only": listening_only})
    if result.get('data_source') == 'probe_target' and (local_port is not None or listening_only):
        payload = result.get('payload') or {}
        if payload.get('local_port') != local_port or payload.get('listening_only') is not listening_only:
            raise ValueError('Probe did not confirm port filters; update the Probe before filtered queries')
    return result


@mcp.tool()
async def probe_event_log(service: str, since_minutes: int = 60, limit: int = 200) -> dict[str, Any]:
    """Read allow-listed Windows Event Log entries for a configured service."""
    return await _tool("event_logs", {"service": service, "since_minutes": max(1, min(since_minutes, 1440)), "limit": max(1, min(limit, 200))})


@mcp.tool()
async def probe_text_log(service: str, path: str, lines: int = 100) -> dict[str, Any]:
    """Tail an allow-listed text log path."""
    return await _tool("text_logs", {"service": service, "path": path, "lines": max(1, min(lines, 1000))})


@mcp.tool()
async def probe_dependency_probe(dependency: str) -> dict[str, Any]:
    """Perform bounded DNS/TCP/GET checks for a configured dependency."""
    return await _tool("dependency_probe", {"dependency": dependency})


def _baseline_summary(baseline: dict, *, current: bool = False) -> dict[str, Any]:
    resources = (baseline.get('resources') or {}).get('payload', {})
    services = list((baseline.get('services') or {}).items())
    disks = resources.get('disks') or []
    return {
        'collected_at': baseline.get('collected_at'),
        'fresh': _fresh(baseline.get('collected_at')),
        'current': current and _fresh(baseline.get('collected_at')),
        'historical': not current,
        'cpu_percent': resources.get('cpu_percent'),
        'memory_percent': (resources.get('memory') or {}).get('percent'),
        'disks': [{key: disk.get(key) for key in ('mountpoint', 'percent', 'free', 'error')}
                  for disk in disks[:12]],
        'summary_truncated': len(services) > 16 or len(disks) > 12,
        'services': {name: (value.get('payload') or {}).get('state')
                     for name, value in services[:16]},
        'process_count': len(((baseline.get('processes') or {}).get('payload') or {}).get('processes', [])),
        'port_count': len(((baseline.get('ports') or {}).get('payload') or {}).get('ports', [])),
        'processes_truncated': bool((baseline.get('processes') or {}).get('truncated')),
        'ports_truncated': bool((baseline.get('ports') or {}).get('truncated')),
    }


@mcp.tool()
async def probe_list_evidence(limit: int = 50) -> dict[str, Any]:
    """List metadata and up to 10 recent baseline summaries for time comparisons.

    Historical summaries are leads, not current raw evidence. Verify conclusions
    with the matching live Probe tool; list truncation cannot prove absence.
    """
    limit = max(1, min(limit, 100))
    recent = gateway.evidence[-limit:]
    history_error = None
    try:
        from src.agent.aiops.run_store import list_probe_snapshots
        snapshots = list_probe_snapshots(gateway.target_id, limit=min(limit, 10))
    except Exception:
        snapshots = []
        history_error = 'baseline_history_unavailable'
    if not recent:
        recent = snapshots
    status = gateway.status()
    live_baseline = status.pop('baseline', None)
    baseline = live_baseline or (snapshots[0].get('payload') if snapshots else {}) or {}
    baseline_summary = _baseline_summary(baseline, current=bool(live_baseline) and status['status'] == 'online')
    history = [{**_baseline_summary(item.get('payload') or {}),
                'target_id': item.get('target_id'), 'raw_hash': item.get('raw_hash')}
               for item in snapshots]
    metadata = [{key: item.get(key) for key in
                 ('target_id', 'operation', 'kind', 'collected_at', 'raw_hash', 'truncated')}
                | {'fresh': _fresh(item.get('collected_at'))} for item in recent]
    return {'target_id': gateway.target_id, 'data_source': 'gateway_summary',
            'status': status, 'baseline_summary': baseline_summary,
            'baseline_history': history, 'history_error': history_error, 'evidence': metadata,
            'details': 'Use the matching Probe tool for current raw evidence.'}


# Mount the MCP app at the ASGI root and keep `/mcp` as the app's own route.
# Mounting an app whose only route is `/` below `/mcp` makes Starlette redirect
# `/mcp` to `/mcp/` under a real Uvicorn socket; the configured MCP URL uses the
# no-slash form, so keep that exact route stable for network clients.
_mcp_app = mcp.http_app(path="/mcp")


def _cleanup_baselines() -> None:
    try:
        from src.agent.aiops.run_store import cleanup_expired_probe_snapshots
        cleanup_expired_probe_snapshots()
    except Exception:
        logger.exception("Expired Probe baseline cleanup failed; retrying next minute")


async def _baseline_retention_loop() -> None:
    while True:
        await asyncio.sleep(BASELINE_CLEANUP_INTERVAL_SECONDS)
        _cleanup_baselines()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # FastMCP's streamable HTTP manager needs its lifespan task group mounted
    # into the parent application; otherwise initialize requests fail at runtime.
    async with _mcp_app.lifespan(app):
        _cleanup_baselines()
        cleanup_task = asyncio.create_task(_baseline_retention_loop(), name="probe-baseline-retention")
        try:
            yield
        finally:
            cleanup_task.cancel()
            with suppress(asyncio.CancelledError):
                await cleanup_task


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def mcp_auth(request: Request, call_next):
    if request.url.path.startswith("/mcp"):
        if not gateway.authenticate(request.headers.get("authorization")):
            return JSONResponse({"detail": "invalid probe token"}, status_code=401)
    return await call_next(request)


@app.websocket("/probe/ws")
async def probe_ws(websocket: WebSocket):
    if not gateway.authenticate(websocket.headers.get("authorization")):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    attached = False
    try:
        raw = await websocket.receive_json()
        await gateway.attach(websocket)
        attached = True
        gateway.register_hello(raw)
        await websocket.send_json({"type": "hello.ack", "protocol": "probe.v1", "target_id": gateway.target_id})
        while True:
            message = await websocket.receive_json()
            if isinstance(message, dict) and message.get("id") and "method" in message:
                try:
                    validate_request(message)
                except ValueError as exc:
                    await websocket.send_json({"id": message.get("id"), "error": {"code": "invalid_request", "message": str(exc)}})
                    continue
            await gateway.handle_message(message)
    except WebSocketDisconnect:
        pass
    except (ValueError, PermissionError, RuntimeError) as exc:
        await websocket.close(code=4403, reason=str(exc)[:120])
    finally:
        if not attached:
            return
        await gateway.detach()


# The root mount preserves the exact public `/mcp` path created above while
# leaving the explicit `/probe/ws` route available for the outbound Probe.
app.mount("/", _mcp_app)

