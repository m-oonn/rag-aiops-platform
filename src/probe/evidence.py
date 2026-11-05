"""Deterministic validation for Probe evidence before it reaches the judge."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .protocol import OPERATIONS, raw_hash


class EvidenceValidationError(ValueError):
    pass


PROBE_TOOL_OPERATIONS = {
    'probe_inventory': 'inventory', 'probe_resource_snapshot': 'resources',
    'probe_service_status': 'services', 'probe_process_snapshot': 'processes',
    'probe_port_snapshot': 'ports', 'probe_event_log': 'event_logs',
    'probe_text_log': 'text_logs', 'probe_dependency_probe': 'dependency_probe',
    'probe_config_snapshot': 'configuration',
}


def diagnostic_fingerprint(item: dict[str, Any]) -> str:
    """Compare observations without treating probe duration jitter as a state change."""
    payload = dict(item.get('payload') or {})
    if item.get('operation') == 'dependency_probe':
        payload.pop('elapsed_ms', None)
    return raw_hash({'payload': payload, 'truncated': bool(item.get('truncated'))})


def validate_tool_evidence(result: Any, *, tool_name: str, target_id: str, now: datetime | None = None) -> dict[str, Any]:
    """Decode one MCP return and bind its evidence operation to the invoked tool."""
    import json
    value = result
    for _ in range(5):
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError as exc:
                raise EvidenceValidationError('Probe tool did not return JSON evidence') from exc
        elif isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict) and value[0].get('type') == 'text':
            value = value[0].get('text')
        else:
            break
    return validate_evidence(value, target_id=target_id, expected_operation=PROBE_TOOL_OPERATIONS[tool_name], now=now)


def validate_observation_window(item: dict[str, Any], boundary: str) -> None:
    """Strict evaluation boundary for the disposable application's timestamped logs."""
    import json
    start = datetime.fromisoformat(boundary.replace('Z', '+00:00'))
    end = datetime.fromisoformat(str(item.get('collected_at')).replace('Z', '+00:00'))
    if start.tzinfo is None or end.tzinfo is None or end < start:
        raise EvidenceValidationError('Probe observation predates this run boundary or lacks timezone')
    payload = item.get('payload') or {}
    if item['operation'] == 'event_logs':
        times = [event.get('collected_at') for event in payload.get('events') or []]
    elif item['operation'] == 'text_logs':
        times = [json.loads(line).get('at') for line in payload.get('lines') or []]
    else:
        times = []
    for value in times:
        observed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if observed.tzinfo is None or observed < start:
            raise EvidenceValidationError('Probe log row predates this run boundary or lacks timezone')
        if observed > end:
            raise EvidenceValidationError('Probe log row is later than collection')


def validate_evidence(item: dict[str, Any], *, target_id: str, now: datetime | None = None,
                      max_age_seconds: int = 180, expected_operation: str | None = None) -> dict[str, Any]:
    if not isinstance(item, dict) or item.get("target_id") != target_id:
        raise EvidenceValidationError("evidence target_id does not match the active target")
    operation = item.get("operation")
    if item.get('data_source') != 'probe_target' or item.get('platform') != 'windows':
        raise EvidenceValidationError('evidence is not from the Windows Probe')
    if expected_operation is not None and operation != expected_operation:
        raise EvidenceValidationError('evidence operation does not match the invoked tool')
    if operation not in OPERATIONS:
        raise EvidenceValidationError("evidence operation is not allow-listed")
    collected = item.get("collected_at")
    try:
        timestamp = datetime.fromisoformat(str(collected).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError) as exc:
        raise EvidenceValidationError("evidence collected_at is invalid") from exc
    current = now or datetime.now(timezone.utc)
    if (current - timestamp).total_seconds() > max_age_seconds:
        raise EvidenceValidationError("evidence is expired")
    if (timestamp - current).total_seconds() > 30:
        raise EvidenceValidationError("evidence timestamp is in the future")
    expected = raw_hash(item.get("payload"))
    if item.get("raw_hash") != expected:
        raise EvidenceValidationError("evidence raw_hash mismatch")
    return item

