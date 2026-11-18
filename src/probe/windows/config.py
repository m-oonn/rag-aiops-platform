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
    config_file: str | None = None
    config_keys: tuple[str, ...] = ()
    docker_container: str | None = None
    docker_django: bool = False
    docker_spring: bool = False
    spring_management_port: int | None = None
    log_since: str = '10m'
    static_resources: tuple[str, ...] = ()
    expected_static_mounts: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DependencyConfig:
    host: str
    port: int
    health_scheme: str | None = None
    health_path: str = "/health"
    source_service: str | None = None
    probe_kind: str = 'tcp'
    cache_alias: str = 'default'
    http_timeout_seconds: int = 3
    bearer_token_file: str | None = None


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


SPRING_PUBLIC_CONFIG_KEYS = frozenset({
    'server.address', 'server.port',
    'spring.datasource.url',
    'spring.data.redis.host', 'spring.data.redis.port', 'spring.data.redis.database',
    'spring.data.redis.timeout',
    'spring.data.mongodb.host', 'spring.data.mongodb.port', 'spring.data.mongodb.database',
    'spring.rabbitmq.host', 'spring.rabbitmq.port', 'spring.rabbitmq.virtual-host',
    'spring.elasticsearch.uris',
})


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
    source = raw.get('source_service')
    kind = raw.get('probe_kind', 'tcp')
    cache_alias = raw.get('cache_alias', 'default')
    if source is not None and (not isinstance(source, str) or not source):
        raise ProbeConfigError('source_service must be a configured Docker service')
    if kind not in {'tcp', 'django_database', 'django_cache', 'celery', 'spring_database', 'spring_cache'} or (kind != 'tcp' and not source):
        raise ProbeConfigError('invalid fixed dependency probe kind')
    if not isinstance(cache_alias, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', cache_alias):
        raise ProbeConfigError('invalid cache alias')
    timeout = raw.get('http_timeout_seconds', 3)
    if type(timeout) is not int or not 1 <= timeout <= 10:
        raise ProbeConfigError('http_timeout_seconds must be an integer from 1 to 10')
    token_file = raw.get('bearer_token_file')
    if token_file is not None:
        if source or scheme is None or host not in {'127.0.0.1', '::1', 'localhost'}:
            raise ProbeConfigError('bearer authentication requires a loopback HTTP dependency')
        token_file = _validate_path_pattern(token_file)
        if any(c in token_file for c in '*?['):
            raise ProbeConfigError('bearer_token_file must be an exact local file')
    return DependencyConfig(host.strip(), port, scheme, path, source, kind, cache_alias, timeout, token_file)


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
        if kind not in ('windows_service', 'process', 'docker'):
            raise ProbeConfigError(f'services.{name}.kind must be windows_service, process or docker')
        container = table.get('docker_container')
        django = table.get('docker_django', False)
        spring = table.get('docker_spring', False)
        management_port = table.get('spring_management_port')
        if management_port is not None and (not spring or type(management_port) is not int
                or not 1 <= management_port <= 65535):
            raise ProbeConfigError('spring_management_port requires a Spring service and a valid port')
        since = table.get('log_since', '10m')
        resources = _string_tuple(table.get('static_resources'), f'services.{name}.static_resources')
        mounts = table.get('expected_static_mounts') or {}
        if (len(resources) > 16 or any(not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_./-]{0,255}', p)
                or '..' in p.split('/') or '' in p.split('/') for p in resources)):
            raise ProbeConfigError('static resources must be bounded relative resource names')
        if (not isinstance(mounts, dict) or len(mounts) > 16 or any(
                not isinstance(dest, str) or not dest.startswith('/') or '..' in dest.split('/')
                or not isinstance(source, str) or not os.path.isabs(source)
                for dest, source in mounts.items())):
            raise ProbeConfigError('static mounts require fixed absolute destinations and local sources')
        if (resources or mounts) and (kind != 'docker' or not django):
            raise ProbeConfigError('static observations require a Docker Django adapter')
        if kind == 'docker' and (not isinstance(container, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', container)):
            raise ProbeConfigError('Docker service requires an exact container name')
        if type(django) is not bool or (django and kind != 'docker'):
            raise ProbeConfigError('docker_django requires a Docker service')
        if type(spring) is not bool or (spring and (kind != 'docker' or django)):
            raise ProbeConfigError('docker_spring requires a non-Django Docker service')
        if not isinstance(since, str) or not re.fullmatch(r'(?:[1-9][0-9]{0,3}[smh]|[0-9T:.+Z-]{20,40})', since):
            raise ProbeConfigError('invalid Docker log time boundary')
        config_file = table.get('config_file')
        config_keys = _string_tuple(table.get('config_keys'), f'services.{name}.config_keys')
        if kind != 'docker' and bool(config_file) != bool(config_keys):
            raise ProbeConfigError('config_file and config_keys must be configured together')
        if config_file is not None:
            config_file = _validate_path_pattern(config_file)
            if any(char in config_file for char in '*?['):
                raise ProbeConfigError('configuration file must be an exact path')
        if spring and (not config_file or not config_keys or
                       any(key not in SPRING_PUBLIC_CONFIG_KEYS for key in config_keys)):
            raise ProbeConfigError('docker_spring requires a registered file and public configuration keys')
        services[name] = ServiceConfig(
            service_name=str(table.get("service_name") or name) if kind == 'windows_service' else '',
            kind=kind,
            process_names=_string_tuple(table.get("process_names"), f"services.{name}.process_names"),
            process_args=_string_tuple(table.get("process_args"), f"services.{name}.process_args"),
            config_file=config_file, config_keys=config_keys,
            docker_container=container, docker_django=django, docker_spring=spring,
            spring_management_port=management_port, log_since=since,
            static_resources=resources, expected_static_mounts=mounts,
            log_channels=_string_tuple(table.get("log_channels"), f"services.{name}.log_channels"),
            log_providers=_string_tuple(table.get("log_providers"), f"services.{name}.log_providers"),
            text_logs=((f'docker://{container}/stdout',) +
                ((f'docker://{container}/http-exchanges',) if management_port else ()) if kind == 'docker' else
                tuple(_validate_path_pattern(x) for x in _string_tuple(table.get("text_logs"), f"services.{name}.text_logs"))),
        )
    dependencies = {name: _validate_dependency(name, value) for name, value in (raw.get("dependencies") or {}).items()}
    for dep in dependencies.values():
        if dep.source_service and (dep.source_service not in services or services[dep.source_service].kind != 'docker'):
            raise ProbeConfigError('dependency source must be an allowed Docker service')
        if dep.probe_kind in {'spring_database', 'spring_cache'}:
            service = services[dep.source_service]
            required = ({'spring.datasource.url'} if dep.probe_kind == 'spring_database' else
                        {'spring.data.redis.host', 'spring.data.redis.port'})
            if not service.docker_spring or not service.spring_management_port or not required <= set(service.config_keys):
                raise ProbeConfigError('Spring application probe requires registered management port and endpoint keys')
        elif dep.probe_kind != 'tcp' and not services[dep.source_service].docker_django:
            raise ProbeConfigError('application probe requires a configured Django adapter')
    return ProbeConfig(target_id, gateway_url, token_file, Path(ca) if ca else None, interval, services, dependencies)


def allowed_text_path(config: ProbeConfig, service: str, requested: str, *, patterns=None) -> bool:
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
    for pattern in cfg.text_logs if patterns is None else patterns:
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

