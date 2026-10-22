"""Fixed, read-only Windows observation operations."""
from __future__ import annotations

import fnmatch
import glob
import os
import platform
import socket
import time
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from src.probe.protocol import validate_port_filters
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from urllib.error import HTTPError

import psutil

from src.probe.protocol import (
    MAX_EVENT_ROWS, MAX_PORT_ROWS, MAX_PROCESS_ROWS, MAX_TEXT_BYTES, evidence, redact,
)
from .config import ProbeConfig, ProbeConfigError, allowed_text_path


def _safe_dt(value: Any) -> str | None:
    if isinstance(value, datetime):
        # Legacy Event Log returns a naive Windows LOCAL time.
        if value.tzinfo is None:
            value = value.astimezone()
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return None


class WindowsCollector:
    def __init__(self, config: ProbeConfig, *, collector_version: str = "1.0.0"):
        self.config = config
        self.collector_version = collector_version

    def _evidence(self, operation: str, payload: Any, *, truncated: bool = False) -> dict[str, Any]:
        result = evidence(target_id=self.config.target_id, operation=operation, payload=redact(payload), truncated=truncated)
        result["collector_version"] = self.collector_version
        return result

    def inventory(self) -> dict[str, Any]:
        return self._evidence("inventory", {
            "hostname": socket.gethostname(),
            "os": platform.platform(aliased=True),
            "system": platform.system(),
            "release": platform.release(),
            "probe_version": self.collector_version,
            "target_id": self.config.target_id,
            "configured_services": {name: {"kind": cfg.kind,
                "service_name": cfg.service_name if cfg.kind == 'windows_service' else None,
                "process_names": list(cfg.process_names), "event_logs_available": bool(cfg.log_channels),
                "text_logs_available": bool(cfg.text_logs),
                "text_logs": list(cfg.text_logs)} for name, cfg in self.config.services.items()},
            "configured_dependencies": sorted(self.config.dependencies),
        })

    def resources(self) -> dict[str, Any]:
        vm = psutil.virtual_memory()
        disks = []
        seen = set()
        for part in psutil.disk_partitions(all=False):
            if part.mountpoint in seen:
                continue
            seen.add(part.mountpoint)
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disks.append({"mountpoint": part.mountpoint, "fstype": part.fstype,
                              "total": usage.total, "used": usage.used, "free": usage.free,
                              "percent": usage.percent})
            except (OSError, PermissionError):
                disks.append({"mountpoint": part.mountpoint, "error": "unavailable"})
        return self._evidence("resources", {
            "cpu_percent": psutil.cpu_percent(interval=0.1),
            "cpu_count": psutil.cpu_count(),
            "memory": {"total": vm.total, "available": vm.available, "used": vm.used, "percent": vm.percent},
            "disks": disks,
            "network": {name: stats._asdict() for name, stats in psutil.net_io_counters(pernic=True).items()},
        })

    def services(self, name: str) -> dict[str, Any]:
        cfg = self.config.service(name)
        if cfg.kind == 'process':
            return self._evidence('services', {'service': name, 'kind': cfg.kind,
                'state': 'not_applicable', 'reason': 'process application; use process and entry observations'})
        payload: dict[str, Any] = {"service": name, "service_name": cfg.service_name}
        try:
            import win32service
            manager = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
            handle = win32service.OpenService(manager, cfg.service_name, win32service.SERVICE_QUERY_STATUS)
            try:
                status = win32service.QueryServiceStatusEx(handle)
                state_map = {
                    win32service.SERVICE_STOPPED: "stopped", win32service.SERVICE_START_PENDING: "start_pending",
                    win32service.SERVICE_STOP_PENDING: "stop_pending", win32service.SERVICE_RUNNING: "running",
                    win32service.SERVICE_CONTINUE_PENDING: "continue_pending", win32service.SERVICE_PAUSE_PENDING: "pause_pending",
                    win32service.SERVICE_PAUSED: "paused",
                }
                payload.update({"state": state_map.get(status["CurrentState"], str(status["CurrentState"])),
                                "status_code": status["CurrentState"], "pid": status.get("ProcessId")})
            finally:
                win32service.CloseServiceHandle(handle)
                win32service.CloseServiceHandle(manager)
        except ImportError:
            payload["error"] = "pywin32 unavailable"
        except Exception as exc:
            payload["state"] = "unavailable"
            payload["error"] = type(exc).__name__
        return self._evidence("services", payload)

    def processes(self, name: str | None = None, *, sort_by: str = 'memory') -> dict[str, Any]:
        if sort_by not in {'memory', 'cpu'}:
            raise ProbeConfigError('sort_by must be memory or cpu')
        allowed = set(self.config.service(name).process_names) if name else None
        rows = []
        sampled = []
        inspected = skipped = 0
        for proc in psutil.process_iter(["pid", "name", "memory_info"]):
            inspected += 1
            try:
                pname = proc.info.get("name") or ""
                if allowed is not None and not any(fnmatch.fnmatch(pname.lower(), x.lower()) for x in allowed):
                    continue
                mem = proc.info.get("memory_info")
                row = {"pid": proc.info.get("pid"), "name": pname, "cpu_percent": None,
                       "memory_bytes": getattr(mem, "rss", None)}
                if os.name == 'nt' and row['pid'] == 0:
                    row['cpu_role'] = 'idle_time_not_workload'
                rows.append(row)
                try:
                    # Each worker is fresh; the first nonblocking CPU read is not a measurement.
                    proc.cpu_percent(interval=None)
                    sampled.append((proc, row))
                except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
                    row['cpu_error'] = type(exc).__name__
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                skipped += 1
        if sampled:
            time.sleep(0.1)
            for proc, row in sampled:
                try:
                    row['cpu_percent'] = proc.cpu_percent(interval=None)
                except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
                    row['cpu_error'] = type(exc).__name__
        key = 'memory_bytes' if sort_by == 'memory' else 'cpu_percent'
        rows.sort(key=lambda row: (row[key] is not None, row[key] or 0), reverse=True)
        return self._evidence("processes", {"service": name, "processes": rows[:MAX_PROCESS_ROWS],
            'sort_by': sort_by, 'selection': 'top_accessible_processes',
            'inspected_count': inspected, 'matched_count': len(rows), 'skipped_count': skipped,
            'memory_unavailable_count': sum(row['memory_bytes'] is None for row in rows),
            'cpu_unavailable_count': sum(row['cpu_percent'] is None for row in rows),
            'memory_basis': 'working_set_rss_bytes_not_unique_or_total_host_memory',
            "cpu_sample_interval_seconds": 0.1 if sampled else None,
            "cpu_percent_basis": "100_per_logical_core"}, truncated=len(rows) > MAX_PROCESS_ROWS)

    def ports(self, *, limit: int = MAX_PORT_ROWS, local_port: int | None = None,
              listening_only: bool = False) -> dict[str, Any]:
        validate_port_filters(local_port, listening_only)
        limit = max(1, min(int(limit), MAX_PORT_ROWS))
        rows = []
        truncated = False
        try:
            connections = psutil.net_connections(kind="inet")
        except (psutil.AccessDenied, OSError) as exc:
            return self._evidence("ports", {"error": type(exc).__name__, "ports": [],
                "local_port": local_port, "listening_only": listening_only, "limit": limit})
        matches = [conn for conn in connections
            if (local_port is None or (conn.laddr and conn.laddr.port == local_port))
            and (not listening_only or conn.status == psutil.CONN_LISTEN)]
        for conn in matches:
            if len(rows) >= limit:
                truncated = True
                break
            local = conn.laddr
            remote = conn.raddr
            rows.append({"family": str(conn.family), "type": str(conn.type), "status": conn.status,
                         "local": {"host": local.ip, "port": local.port} if local else None,
                         "remote": {"host": remote.ip, "port": remote.port} if remote else None,
                         "pid": conn.pid})
        return self._evidence("ports", {"ports": rows, "local_port": local_port,
            "listening_only": listening_only, "limit": limit,
            "matched_count": len(matches)}, truncated=truncated)

    def event_logs(self, name: str, *, since_minutes: int = 60, limit: int = MAX_EVENT_ROWS) -> dict[str, Any]:
        cfg = self.config.service(name)
        if since_minutes < 1 or since_minutes > 24 * 60:
            raise ProbeConfigError("since_minutes must be between 1 and 1440")
        limit = max(1, min(int(limit), MAX_EVENT_ROWS))
        payload: dict[str, Any] = {"service": name, "channels": list(cfg.log_channels),
                                   "since_minutes": since_minutes, "limit": limit, "events": []}
        if not cfg.log_channels:
            payload["error"] = "no event channels configured"
            return self._evidence("event_logs", payload)
        try:
            import win32evtlog
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
            for channel in cfg.log_channels:
                handle = win32evtlog.OpenEventLog(None, channel)
                try:
                    flags = win32evtlog.EVENTLOG_BACKWARDS_READ | win32evtlog.EVENTLOG_SEQUENTIAL_READ
                    reached_cutoff = False
                    for batch in iter(lambda: win32evtlog.ReadEventLog(handle, flags, 0), []):
                        for event in batch:
                            created = _safe_dt(getattr(event, "TimeGenerated", None))
                            if not created:
                                continue
                            if datetime.fromisoformat(created.replace("Z", "+00:00")) < cutoff:
                                reached_cutoff = True
                                break
                            provider = getattr(event, "SourceName", None)
                            if cfg.log_providers and provider not in cfg.log_providers:
                                continue
                            row = {"channel": channel, "provider": provider,
                                                      "event_id": getattr(event, "EventID", None),
                                                      "level": getattr(event, "EventType", None),
                                                      "collected_at": created,
                                                      "strings": list(getattr(event, "StringInserts", None) or [])[:20]}
                            if len(json.dumps(row, ensure_ascii=False).encode("utf-8")) + len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > MAX_TEXT_BYTES:
                                return self._evidence("event_logs", payload, truncated=True)
                            payload["events"].append(row)
                            if len(payload["events"]) >= limit:
                                return self._evidence("event_logs", payload, truncated=True)
                        if reached_cutoff:
                            break
                finally:
                    win32evtlog.CloseEventLog(handle)
        except ImportError:
            payload["error"] = "pywin32 unavailable"
        except Exception as exc:
            payload["error"] = type(exc).__name__
        return self._evidence("event_logs", payload)

    def text_logs(self, name: str, path: str, *, lines: int = 100) -> dict[str, Any]:
        if not allowed_text_path(self.config, name, path):
            raise ProbeConfigError("text log path is outside the configured allow-list")
        lines = max(1, min(int(lines), 1000))
        matches = glob.iglob(path) if any(x in path for x in "*?[") else iter([path])
        selected_path = next(matches, None)
        if selected_path is None:
            return self._evidence("text_logs", {"service": name, "path": path,
                                                 "line_limit": lines, "error": "file not found"})
        if not allowed_text_path(self.config, name, selected_path):
            raise ProbeConfigError("matched log file is outside the configured allow-list")
        with open(selected_path, "rb") as handle:
            # Validate the opened handle, so a link swapped during open cannot escape.
            if os.name == "nt":
                import msvcrt
                import win32file
                actual = win32file.GetFinalPathNameByHandle(msvcrt.get_osfhandle(handle.fileno()), 0)
                if actual.startswith('\\\\?\\'):
                    actual = actual[4:]
            else:
                actual = str(Path(f"/proc/self/fd/{handle.fileno()}").resolve(strict=True))
            if not allowed_text_path(self.config, name, actual):
                raise ProbeConfigError("opened log file is outside the configured allow-list")
            size = handle.seek(0, os.SEEK_END)
            handle.seek(max(0, size - MAX_TEXT_BYTES))
            raw = handle.read(MAX_TEXT_BYTES)
        text = redact(raw.decode("utf-8", errors="replace")).splitlines()
        selected = text[-lines:]
        return self._evidence("text_logs", {"service": name, "path": actual,
                                             "line_limit": lines, "lines": selected},
                              truncated=size > MAX_TEXT_BYTES or len(text) > lines or any(x in path for x in "*?["))

    def dependency_probe(self, name: str) -> dict[str, Any]:
        cfg = self.config.dependency(name)
        result: dict[str, Any] = {"dependency": name, "host": cfg.host, "port": cfg.port}
        started = time.monotonic()
        try:
            result["dns"] = socket.gethostbyname_ex(cfg.host)[2]
        except OSError as exc:
            result["dns_error"] = type(exc).__name__
        try:
            with socket.create_connection((cfg.host, cfg.port), timeout=3):
                result["tcp"] = "ok"
        except OSError as exc:
            result["tcp"] = "failed"
            result["tcp_error"] = type(exc).__name__
        if cfg.health_scheme:
            host = f"[{cfg.host}]" if ":" in cfg.host else cfg.host
            url = f"{cfg.health_scheme}://{host}:{cfg.port}{cfg.health_path}"
            try:
                req = Request(url, method="GET", headers={"Accept": "application/json"})
                class _NoRedirect(HTTPRedirectHandler):
                    def redirect_request(self, req, fp, code, msg, headers, newurl):
                        return None
                try:
                    response = build_opener(ProxyHandler({}), _NoRedirect()).open(req, timeout=3)
                except HTTPError as exc:
                    # An HTTP error is still a response from the configured server.
                    response = exc
                with response:
                    body = response.read(1025)
                    result["http"] = {"status": response.code,
                        "body_prefix": body[:1024].decode("utf-8", errors="replace"),
                        "truncated": len(body) > 1024}
            except Exception as exc:
                result["http"] = {"error": type(exc).__name__}
        result["elapsed_ms"] = round((time.monotonic() - started) * 1000, 1)
        return self._evidence("dependency_probe", result,
                              truncated=bool((result.get('http') or {}).get('truncated')))

    def baseline(self) -> dict[str, Any]:
        return {
            "target_id": self.config.target_id,
            "collected_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "resources": self.resources(),
            "services": {name: self.services(name) for name in self.config.services},
            "processes": self.processes(),
            "ports": self.ports(),
        }

    def collect(self, operation: str, params: dict[str, Any]) -> dict[str, Any]:
        if operation == "inventory": return self.inventory()
        if operation == "resources": return self.resources()
        if operation == "services": return self.services(str(params.get("service")))
        if operation == "processes": return self.processes(params.get("service"), sort_by=params.get('sort_by', 'memory'))
        if operation == "ports": return self.ports(limit=params.get("limit", MAX_PORT_ROWS),
            local_port=params.get('local_port'), listening_only=params.get('listening_only', False))
        if operation == "event_logs": return self.event_logs(str(params.get("service")), since_minutes=params.get("since_minutes", 60), limit=params.get("limit", MAX_EVENT_ROWS))
        if operation == "text_logs": return self.text_logs(str(params.get("service")), str(params.get("path")), lines=params.get("lines", 100))
        if operation == "dependency_probe": return self.dependency_probe(str(params.get("dependency")))
        raise ProbeConfigError(f"unsupported operation: {operation}")

