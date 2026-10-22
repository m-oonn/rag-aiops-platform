"""Probe protocol primitives shared by the Windows client and gateway."""
from __future__ import annotations

import hashlib
import json
import re
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

PROTOCOL_VERSION = "probe.v1"
OPERATIONS = {
    "inventory", "resources", "services", "processes", "ports",
    "event_logs", "text_logs", "dependency_probe",
}
CAPABILITIES = tuple(sorted(OPERATIONS))
MAX_PROCESS_ROWS = 256
MAX_PORT_ROWS = 256
MAX_EVENT_ROWS = 200
MAX_TEXT_BYTES = 16 * 1024
MAX_REQUEST_ID = 128
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


class RequestIdTracker:
    """Bounded replay guard for requests received by a probe.

    A probe processes one websocket stream at a time, so an in-memory bounded
    set is sufficient.  Keeping only recent IDs prevents a long-lived service
    from growing without bound while still rejecting accidental or malicious
    request replay during the active connection.
    """

    def __init__(self, max_ids: int = 1024):
        if max_ids < 1:
            raise ValueError("max_ids must be positive")
        self.max_ids = max_ids
        self._ids: OrderedDict[str, None] = OrderedDict()

    def remember(self, request_id: str) -> bool:
        """Remember *request_id* and return False when it was already seen."""
        if request_id in self._ids:
            return False
        self._ids[request_id] = None
        while len(self._ids) > self.max_ids:
            self._ids.popitem(last=False)
        return True


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def raw_hash(payload: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def evidence(*, target_id: str, operation: str, payload: Any, collected_at: str | None = None, truncated: bool = False) -> dict[str, Any]:
    if operation not in OPERATIONS:
        raise ValueError(f"unsupported operation: {operation}")
    return {
        "target_id": target_id,
        "platform": "windows",
        "operation": operation,
        "collected_at": collected_at or utc_now(),
        "collector_version": "1.0.0",
        "data_source": "probe_target",
        "payload": payload,
        "raw_hash": raw_hash(payload),
        **({"truncated": True} if truncated else {}),
    }


def hello(*, target_id: str, hostname: str, agent_version: str = "1.0.0", capabilities: list[str] | None = None) -> dict[str, Any]:
    caps = sorted(set(capabilities or CAPABILITIES))
    unknown = set(caps) - set(CAPABILITIES)
    if unknown:
        raise ValueError(f"unknown capabilities: {sorted(unknown)}")
    return {"type": "hello", "protocol": PROTOCOL_VERSION, "target_id": target_id,
            "hostname": hostname, "platform": "windows", "agent_version": agent_version,
            "capabilities": caps}


def validate_port_filters(local_port: Any = None, listening_only: Any = False) -> None:
    if local_port is not None and (type(local_port) is not int or not 1 <= local_port <= 65535):
        raise ValueError("local_port must be an integer between 1 and 65535")
    if type(listening_only) is not bool:
        raise ValueError("listening_only must be a boolean")


def validate_request(message: Any) -> tuple[str, str, dict[str, Any]]:
    if not isinstance(message, dict) or not isinstance(message.get("id"), str):
        raise ValueError("request id is required")
    request_id = message["id"]
    if not REQUEST_ID_RE.fullmatch(request_id):
        raise ValueError("invalid request id")
    method = message.get("method")
    if not isinstance(method, str) or not method.startswith("probe.") or method[6:] not in OPERATIONS:
        raise ValueError("unsupported probe method")
    params = message.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    if method == 'probe.ports':
        validate_port_filters(params.get('local_port'), params.get('listening_only', False))
    return request_id, method[6:], params


def redact(value: Any) -> Any:
    """Recursively remove common credential fields from stored summaries."""
    secret_names = {"token", "password", "pwd", "secret", "authorization", "cookie",
                    "private_key", "connection_string", "proxy_authorization", "set_cookie",
                    "api_key", "access_token", "refresh_token"}
    if isinstance(value, dict):
        return {str(k): ("[REDACTED]" if str(k).lower().replace('-', '_') in secret_names
                        else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"(?s)-----BEGIN ([A-Z ]*PRIVATE KEY)-----.*?-----END \1-----",
                       '[REDACTED]', value)
        value = re.sub(r"(?i)(\b(?:[a-z][a-z0-9+.-]*)://[^\s/@:]+:)[^\s/@]+(@)",
                       r"\1[REDACTED]\2", value)
        # Headers may contain several cookie values or an authorization scheme.
        value = re.sub(r"(?im)(\b(?:proxy-authorization|authorization|set-cookie|cookie)\s*[:=]\s*)[^\r\n]+",
                       r"\1[REDACTED]", value)
        value = re.sub(r'''(?i)(\b(?:password|pwd|token|secret|api[_-]?key|access[_-]?token|refresh[_-]?token)["']?\s*[:=]\s*)(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;}&]+)''',
                       r"\1[REDACTED]", value)
        return re.sub(r"(?i)(bearer\s+)[^\s,;]+", r"\1[REDACTED]", value)
    return value

