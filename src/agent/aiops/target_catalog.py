"""Business references never grant collector permissions."""
import json
import re
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class BusinessService(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    aliases: list[str] = Field(default_factory=list)
    entries: dict[str, str] = Field(default_factory=dict)  # registered URL -> dependency alias
    probe_service: str | None = None
    expected_ports: list[int] = Field(default_factory=list)
    log_refs: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    dependency_services: dict[str, str] = Field(default_factory=dict)


class TargetCatalog(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    version: int
    target_id: str
    services: dict[str, BusinessService]


def normalized_url(value):
    url = urlsplit(value)
    if url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('entry must be an HTTP URL without credentials, query or fragment')
    port = url.port or (443 if url.scheme == 'https' else 80)
    return (url.scheme, url.hostname.lower(), port, url.path.rstrip('/') or '/')


def resolve_target(raw, query, inventory, target_id, aliases='{}'):
    """Only exact configured identifiers resolve; suggestions cannot execute."""
    result = {'status': 'host_overview', 'target_id': target_id, 'services': {}, 'candidates': [], 'mismatches': []}
    if not str(raw or '').lstrip().startswith('{'):
        return {**result, 'status': 'legacy_reference'}
    try:
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get('version') != 1:
            return {**result, 'status': 'legacy_reference'}
        catalog = TargetCatalog.model_validate(value)
        if catalog.target_id != target_id or catalog.version != 1:
            raise ValueError('catalog target mismatch')
        for service in catalog.services.values():
            if any(isinstance(p, bool) or not 1 <= p <= 65535 for p in service.expected_ports):
                raise ValueError('invalid expected port')
            for url in service.entries:
                normalized_url(url)
    except (ValueError, TypeError, ValidationError):
        return {**result, 'status': 'invalid_catalog', 'mismatches': ['目标目录无效或目标不一致；只作为参考，不授权执行']}
    try:
        alias_table = json.loads(aliases)
    except (ValueError, TypeError):
        alias_table = {}
    exact, fuzzy = [], []
    urls = re.findall(r'https?://[^\s，。；、<>]+', query)
    for name, service in catalog.services.items():
        names = [name, *service.aliases]
        for spoken, mapping in alias_table.items() if isinstance(alias_table, dict) else []:
            if isinstance(mapping, dict):
                values = [v for value in mapping.values() for v in
                          (value if isinstance(value, list) else [value]) if isinstance(v, str)]
                if name in values or spoken == name:
                    names.append(spoken)
        name_query = re.sub(r'https?://[^\s，。；、<>]+', '', query)
        mentioned = any(re.search(r'(?<![\w-])' + re.escape(n) + r'(?![\w-])', name_query, re.I) if n.isascii()
                        else n in name_query for n in names if n)
        url_match = False
        for url in urls:
            try:
                url_match |= any(normalized_url(url) == normalized_url(entry) for entry in service.entries)
            except ValueError:
                pass
        if url_match or (mentioned and not urls):
            exact.append(name)
        elif any(n.lower() in query.lower() or query.lower() in n.lower() for n in names if n and query):
            fuzzy.append(name)
    if len(exact) != 1:
        overview = any(word in query.lower() for word in ('本机', '整机', '主机概况', '运行概况', 'host overview', 'local machine'))
        status = 'ambiguous' if len(exact) > 1 else 'host_overview' if overview and not urls and not fuzzy else 'unmatched'
        return {**result, 'status': status, 'candidates': exact or fuzzy}
    name = exact[0]
    service = catalog.services[name]
    result.update(status='resolved', service=name, services={name: service.model_dump()})
    if not inventory:
        result['mismatches'].append('Probe inventory 不可用；业务关系尚未现场核实')
    else:
        configured_services = inventory.get('configured_services', {})
        configured_dependencies = inventory.get('configured_dependencies', [])
        if service.probe_service and service.probe_service not in configured_services:
            result['mismatches'].append('业务服务未列入 Probe 服务白名单')
        if any(not configured_services.get(ref, {}).get('text_logs_available') for ref in service.log_refs):
            result['mismatches'].append('业务日志引用缺少已公布的文本日志权限；具体路径仍由 Probe 核验')
        if any(dep not in configured_dependencies for dep in [*service.dependencies, *service.entries.values()]):
            result['mismatches'].append('业务依赖或入口探测未列入 Probe 依赖白名单')
    configured = (inventory or {}).get('configured_services', {})
    result['allowed_services'] = sorted({name for name in [service.probe_service, *service.log_refs] if name in configured})
    result['allowed_dependencies'] = sorted(set([*service.dependencies, *service.entries.values()]) & set((inventory or {}).get('configured_dependencies', [])))
    result['dependency_services'] = {dep: ref for dep, ref in service.dependency_services.items()
        if dep in result['allowed_dependencies'] and ref in configured}
    result['allowed_services'] = sorted(set(result['allowed_services']) | set(result['dependency_services'].values()))
    # Retain registered ports for explicitly mapped, allow-listed dependency services.
    for related_name, related in catalog.services.items():
        if related.probe_service in result['dependency_services'].values():
            result['services'][related_name] = related.model_dump()
    if len(result['dependency_services']) != len(service.dependency_services):
        result['mismatches'].append('部分依赖服务映射未同时满足业务范围和 Probe 白名单，不能执行对应检查')
    return result
