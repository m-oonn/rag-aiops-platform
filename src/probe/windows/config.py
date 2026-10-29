"""Strict local configuration for the Windows probe.

The probe treats this file as an allow-list.  Values received from the
gateway can only refer to names declared here; the agent never edits it.
"""
from __future__ import annotations

import fnmatch
import ipaddress
import os
import tomllib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_CONFIG_DIR = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "RagAIOpsProbe"


class ProbeConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ServiceConfig:
    service_name: str
    process_names: tuple[str, ...] = ()
    log_channels: tuple[str, ...] = ()
    log_providers: tuple[str, ...] = ()
    text_logs: tuple[str, ...] = ()
    kind: str = 'windows_service'
    process_args: tuple[str, ...] = ()


@dataclass(frozen=True)
class DependencyConfig:
    host: str
    port: int
    health_scheme: str | None = None
    health_path: str = "/health"


@dataclass(frozen=True)
class ProbeConfig:
    target_id: str
    gateway_url: str
    token_file: Path
    tls_ca_file: Path | None = None
    baseline_interval_seconds: int = 60
    services: dict[str, ServiceConfig] = field(default_factory=dict)
    dependencies: dict[str, DependencyConfig] = field(default_factory=dict)

    def service(self, name: str) -> ServiceConfig:
        if name not in self.services:
            raise ProbeConfigError(f"service is not configured: {name}")
        return self.services[name]

    def dependency(self, name: str) -> DependencyConfig:
        if name not in self.dependencies:
            raise ProbeConfigError(f"dependency is not configured: {name}")
        return self.dependencies[name]


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(x, str) and x.strip() for x in value):
        raise ProbeConfigError(f"{field_name} must be a list of non-empty strings")
    return tuple(x.strip() for x in value)


def _validate_path_pattern(pattern: str) -> str:
    # Absolute paths are required.  Reject traversal even when a wildcard is used.
    if not isinstance(pattern, str) or not pattern.strip():
        raise ProbeConfigError("text log path must be a non-empty string")
    candidate = pattern.strip()
    if ".." in Path(candidate).parts:
        raise ProbeConfigError("text log path traversal is forbidden")
    if not os.path.isabs(candidate):
        raise ProbeConfigError("text log paths must be absolute")
    path = Path(candidate)
    if path.anchor.startswith("\\\\") or any(":" in part for part in path.parts[1:]):
        raise ProbeConfigError("network paths and alternate streams are forbidden")
    if any(char in str(path.parent) for char in "*?["):
        raise ProbeConfigError("only the log filename may contain wildcards")
    return candidate


def _validate_dependency(name: str, raw: Any) -> DependencyConfig:
    if not isinstance(raw, dict):
        raise ProbeConfigError(f"dependencies.{name} must be a table")
    host = raw.get("host")
    port = raw.get("port")
    if not isinstance(host, str) or not host.strip() or isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ProbeConfigError(f"dependencies.{name} has invalid host/port")
    host = host.strip()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?\.?", host):
            raise ProbeConfigError("dependency host must be an IP address or DNS name")
    scheme = raw.get("health_scheme")
    if scheme is not None and scheme not in {"http", "https"}:
        raise ProbeConfigError("health_scheme must be http or https")
    path = raw.get("health_path", "/health")
    if not isinstance(path, str) or not path.startswith("/") or path.startswith("//") or any(ord(c) < 32 or c in "\\#" for c in path):
        raise ProbeConfigError("health_path must be a local URL path")
    return DependencyConfig(host.strip(), port, scheme, path)


def load_config(path: str | Path) -> ProbeConfig:
    path = Path(path)
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise ProbeConfigError(f"configuration file does not exist: {path}") from exc
    if not isinstance(raw, dict):
        raise ProbeConfigError("configuration must be a TOML table")
    target_id = raw.get("target_id")
    gateway_url = raw.get("gateway_url")
    if not isinstance(target_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", target_id):
        raise ProbeConfigError("target_id is required")
    if not isinstance(gateway_url, str) or urlparse(gateway_url).scheme not in {"ws", "wss"}:
        raise ProbeConfigError("gateway_url must use ws:// or wss://")
    gateway = urlparse(gateway_url)
    if not gateway.hostname or gateway.username or gateway.password or gateway.fragment:
        raise ProbeConfigError("gateway_url must have a host and no credentials or fragment")
    if gateway.scheme == "ws":
        try:
            loopback = ipaddress.ip_address(gateway.hostname).is_loopback
        except ValueError:
            loopback = False
        if not loopback:
            raise ProbeConfigError("plaintext ws is allowed only for a loopback IP")
    interval = raw.get("baseline_interval_seconds", 60)
    if not isinstance(interval, int) or not 30 <= interval <= 300:
        raise ProbeConfigError("baseline_interval_seconds must be between 30 and 300")
    token_file = Path(raw.get("token_file", DEFAULT_CONFIG_DIR / "token"))
    ca = raw.get("tls_ca_file")
    services: dict[str, ServiceConfig] = {}
    for name, table in (raw.get("services") or {}).items():
        if not isinstance(name, str) or not isinstance(table, dict):
            raise ProbeConfigError("services must be TOML tables")
        kind = table.get('kind', 'windows_service')
        if kind not in ('windows_service', 'process'):
            raise ProbeConfigError(f'services.{name}.kind must be windows_service or process')
        services[name] = ServiceConfig(
            service_name=str(table.get("service_name") or name) if kind == 'windows_service' else '',
            kind=kind,
            process_names=_string_tuple(table.get("process_names"), f"services.{name}.process_names"),
            process_args=_string_tuple(table.get("process_args"), f"services.{name}.process_args"),
            log_channels=_string_tuple(table.get("log_channels"), f"services.{name}.log_channels"),
            log_providers=_string_tuple(table.get("log_providers"), f"services.{name}.log_providers"),
            text_logs=tuple(_validate_path_pattern(x) for x in _string_tuple(table.get("text_logs"), f"services.{name}.text_logs")),
        )
    dependencies = {name: _validate_dependency(name, value) for name, value in (raw.get("dependencies") or {}).items()}
    return ProbeConfig(target_id, gateway_url, token_file, Path(ca) if ca else None, interval, services, dependencies)


def allowed_text_path(config: ProbeConfig, service: str, requested: str) -> bool:
    """Match a fixed directory and filename; links/reparse paths fail closed."""
    cfg = config.service(service)
    try:
        _validate_path_pattern(requested)
    except (ProbeConfigError, ValueError):
        return False
    requested_path = Path(requested)
    try:
        if any(p.is_symlink() or (p.lstat().st_file_attributes & 0x400 if os.name == "nt" else False)
               for p in (requested_path, *requested_path.parents) if p.exists()):
            return False
    except OSError:
        return False
    for pattern in cfg.text_logs:
        configured = Path(pattern)
        try:
            if any(p.is_symlink() or (p.lstat().st_file_attributes & 0x400 if os.name == "nt" else False)
                   for p in configured.parents if p.exists()):
                continue
            # Windows handle paths expand 8.3 directory aliases to long names.
            requested_parent = os.path.normcase(str(requested_path.parent.resolve(strict=True)))
            configured_parent = os.path.normcase(str(configured.parent.resolve(strict=True)))
        except (OSError, RuntimeError, ValueError):
            continue
        if (requested_parent == configured_parent
                and fnmatch.fnmatch(os.path.normcase(requested_path.name), os.path.normcase(configured.name))):
            return True
    return False

