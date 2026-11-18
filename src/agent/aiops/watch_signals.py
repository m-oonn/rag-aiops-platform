"""Explicit local Probe adapters. Missing measurements stay unknown."""
import json
import math
from datetime import datetime

from src.probe.protocol import redact


def parse_checks(value: str, services: list[str]) -> dict:
    checks = json.loads(value or "{}")
    if not isinstance(checks, dict) or set(checks) - set(services):
        raise ValueError("Probe checks must name explicitly watched services")
    for check in checks.values():
        if not isinstance(check, dict):
            raise ValueError("invalid Probe check")
        if check.get("kind") == "http":
            allowed, reference, limit = {"kind", "dependency", "max_elapsed_ms"}, "dependency", "max_elapsed_ms"
        elif check.get("kind") == "desktop":
            allowed, reference, limit = {"kind", "path", "max_event_loop_lag_ms"}, "path", "max_event_loop_lag_ms"
        else:
            raise ValueError("unknown Probe check kind")
        if set(check) != allowed or not isinstance(check[reference], str) or not check[reference].strip():
            raise ValueError("Probe check requires an exact configured reference and threshold")
        number = check[limit]
        if type(number) not in (int, float) or not math.isfinite(number) or number <= 0:
            raise ValueError("invalid Probe threshold")
    return checks


def classify_probe_check(raw: dict, check: dict) -> dict:
    unknown = {"data_source": "unavailable", "samples": [], "error": "Probe signal incomplete or unavailable"}
    if not isinstance(raw, dict) or raw.get("data_source") != "probe_target" or raw.get("platform") != "windows":
        return unknown
    body = raw.get("payload") or {}
    if body.get("error") or raw.get("truncated"):
        return unknown
    source_time = raw.get("collected_at")
    rule = redact(check)
    if check["kind"] == "http":
        if raw.get("operation") != "dependency_probe" or body.get("dependency") != check["dependency"]:
            return unknown
        http = body.get("http") or {}
        status, elapsed = http.get("status"), body.get("elapsed_ms")
        if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0:
            return unknown
        if type(status) is not int and not http.get("error"):
            return unknown
        bad = bool(http.get("error")) or not (200 <= status < 400) or elapsed > check["max_elapsed_ms"]
        kind = "business_http"
        measurement = {"http_status": status, "elapsed_ms": elapsed, "http_error": bool(http.get("error"))}
    else:
        if raw.get("operation") != "text_logs":
            return unknown
        lines = body.get("lines") or []
        try:
            try:
                snapshot = json.loads("\n".join(lines))
            except ValueError:
                snapshot = json.loads(lines[-1])
            if snapshot.get("simulation") is not False:
                return unknown
            errors, lag = snapshot.get("errors"), snapshot.get("event_loop_lag_ms")
            if not isinstance(errors, list) or any(not isinstance(row, str) for row in errors):
                return unknown
            if errors:
                bad = True
            elif (snapshot.get("window_complete") is True and type(lag) in (int, float)
                  and math.isfinite(lag) and lag >= 0):
                bad = lag > check["max_event_loop_lag_ms"]
            else:
                return unknown
            source_time = snapshot["recorded_at"]
            kind = "desktop_runtime"
            measurement = {"error_count": len(errors), "window_complete": snapshot.get("window_complete") is True,
                           "event_loop_lag_ms": lag if type(lag) in (int, float) and math.isfinite(lag) else None}
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            return unknown
    try:
        timestamp = datetime.fromisoformat(source_time.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            return unknown
    except (AttributeError, ValueError, TypeError):
        return unknown
    return {"data_source": "windows_probe", "signal_kind": kind, "rule": rule, "evidence": redact(raw),
            "measurement": measurement,
            "samples": [{"series_key": kind + ":" + (check.get("dependency") or check.get("path")),
                         "sample_time_unix": timestamp.timestamp(), "value": 0.0 if bad else 1.0}]}


def poll_probe_check(collector, service_name: str, check: dict) -> dict:
    try:
        if check["kind"] == "http":
            raw = collector.dependency_probe(check["dependency"])
        else:
            raw = collector.text_logs(service_name, check["path"], lines=100)
        return classify_probe_check(raw, check)
    except Exception as exc:
        return {"data_source": "unavailable", "samples": [], "error": type(exc).__name__}
