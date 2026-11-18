"""Narrow causal contracts for current availability of explicitly registered services.

Inputs have already passed freshness, hash, target and business-scope validation.
No scenario names, controller state or inferred shutdown history are accepted.
"""
import json
from urllib.parse import urlsplit


def public_cause(code, subject):
    """Bound the published statement to the verified contract, not model prose."""
    statements = {
        'registered_service_stopped': f'{subject} 当前已停止，本轮与其真实端口或网络映射对应的访问失败。',
        'registered_host_rejected': f'{subject} 实际加载的主机访问规则拒绝了本轮探测网址。',
        'registered_dependency_endpoint_mismatch': f'{subject} 加载的依赖端点连接失败，同一消费者可连接登记端点；本轮实际业务访问失败。',
        'registered_authentication_rejected': f'{subject} 使用的数据库身份验证被拒绝，TCP 可达，另一登记消费者可在同端点查询；本轮实际业务访问失败。',
        'registered_static_mount_mismatch': f'{subject} 的静态资源目录挂载与登记不符；登记目录中的资源存在，但应用未找到该资源，对应资源访问返回404。',
    }
    if code not in statements:
        return None
    return {'conclusion': statements[code],
            'scope': '仅限本轮主引用记录中的对象、端点与实际操作；未检查的业务、其他故障及变更或停止历史仍未知。'}


def configuration_chains(records, resolution):
    """Verify a loaded consumer setting against its actual failed operation.

    The registry identifies objects and expected endpoints. It never supplies
    a fault label. Startup environment snapshots cannot pass these contracts.
    """
    if resolution.get('status') != 'resolved':
        return []
    rows = []
    for ident, record in records.items():
        raw = json.loads(record['payload'])
        body = raw.get('payload') or {}
        if raw.get('data_source') == 'probe_target' and not raw.get('truncated') and not body.get('error'):
            rows.append((ident, raw, body))
    mapping = resolution.get('dependency_services') or {}
    chains = []
    for cid, config_raw, config in rows:
        source = config.get('service')
        if (config_raw.get('operation') != 'configuration'
                or config.get('source') != 'running_container_django_settings'
                or source not in resolution.get('allowed_services', [])):
            continue
        same = [(i, raw, body) for i, raw, body in rows
                if raw.get('target_id') == config_raw.get('target_id')]
        consumers = [(i, body) for i, raw, body in same
            if raw.get('operation') == 'dependency_probe'
            and mapping.get(body.get('dependency')) == source]
        values = config.get('values') or {}
        for mount in config.get('static_mounts') or []:
            if not isinstance(mount, dict):
                continue
            destination = mount.get('destination')
            expected = mount.get('registered_source')
            if (destination not in values.get('static_directories', []) or not expected
                    or mount.get('actual_source') == expected):
                continue
            for resource, found in (values.get('static_files') or {}).items():
                if (not isinstance(found, dict) or found.get('found') is not False
                        or mount.get('registered_resources_present', {}).get(resource) is not True):
                    continue
                static_url = values.get('static_url')
                if not isinstance(static_url, str) or not static_url.startswith('/'):
                    continue
                path = static_url.rstrip('/') + '/' + resource
                for hid, body in consumers:
                    http = body.get('http') or {}
                    if http.get('status') == 404 and urlsplit(http.get('url') or '').path == path:
                        chains.append({'code': 'registered_static_mount_mismatch', 'subject': source,
                            'evidence_ids': [cid, hid], 'limitation':
                            '仅确认该登记资源的目录挂载差异、查找失败与404；不外推其他资源、业务或变更历史。'})
        for hid, http_body in consumers:
            http = http_body.get('http') or {}
            host = urlsplit(http.get('url') or '').hostname
            rules = config.get('values', {}).get('allowed_hosts')
            if (http.get('status') == 400 and http.get('exception_type') == 'DisallowedHost'
                    and host and isinstance(rules, list) and '*' not in rules
                    and not any(host == rule or (rule.startswith('.') and
                        (host == rule[1:] or host.endswith(rule))) for rule in rules)):
                chains.append({'code': 'registered_host_rejected', 'subject': source,
                    'evidence_ids': [cid, hid], 'limitation':
                    '仅确认所探测网址的主机名被应用拒绝；其他域名、业务和配置变更历史未核验。'})
        for did, raw, dep in same:
            kind = dep.get('probe_kind')
            if (raw.get('operation') != 'dependency_probe' or dep.get('source_service') != source
                    or kind not in {'django_database', 'django_cache'} or dep.get('query') != 'failed'):
                continue
            values = config.get('values') or {}
            loaded = (values.get('database') or {} if kind == 'django_database' else
                      (values.get('caches') or {}).get(dep.get('cache_alias'), {}))
            endpoint = (dep.get('host'), str(dep.get('port')))
            if endpoint != (loaded.get('host'), str(loaded.get('port'))):
                continue
            subject = mapping.get(dep.get('dependency'))
            if subject not in resolution.get('allowed_services', []):
                continue
            failures = [i for i, body in consumers if type((body.get('http') or {}).get('status')) is int
                        and body['http']['status'] >= 500]
            if not failures:
                continue
            for rid, registered_raw, registered in same:
                if (registered_raw.get('operation') != 'dependency_probe'
                        or registered.get('source_service') not in resolution.get('allowed_services', [])
                        or mapping.get(registered.get('dependency')) != subject
                        or registered.get('tcp') != 'ok'):
                    continue
                registered_endpoint = (registered.get('host'), str(registered.get('port')))
                if (dep.get('tcp') == 'failed' and endpoint != registered_endpoint
                        and registered_endpoint == (dep.get('registered_host'), str(dep.get('registered_port')))
                        and registered.get('source_service') == source):
                    chains.append({'code': 'registered_dependency_endpoint_mismatch', 'subject': source,
                        'evidence_ids': [cid, did, rid, failures[0]], 'limitation':
                        '只确认应用加载端点失败而登记端点从同一消费者可达；不确认配置变更者或未测业务。'})
                if (kind == 'django_database' and dep.get('tcp') == 'ok'
                        and dep.get('error_category') == 'authentication_rejected'
                        and registered.get('probe_kind') == 'django_database' and registered.get('query') == 'ok'
                        and registered.get('source_service') != source and endpoint == registered_endpoint):
                    chains.append({'code': 'registered_authentication_rejected', 'subject': source,
                        'evidence_ids': [cid, did, rid, failures[0]], 'limitation':
                        '只确认本应用所用身份验证被拒绝；另一登记消费者可正常查询。不公开凭据，也不推断具体哪项凭据或服务器策略被改动。'})
    unique = {}
    for chain in chains:
        unique.setdefault((chain['code'], chain['subject']), chain)
    return list(unique.values())


def stopped_service_chains(records, resolution):
    if resolution.get('status') != 'resolved':
        return []
    observations = []
    for ident, record in records.items():
        raw = json.loads(record['payload'])
        body = raw.get('payload') or {}
        if (raw.get('data_source') == 'probe_target' and not raw.get('truncated')
                and not body.get('error')):
            observations.append((ident, raw, body))
    mapping = resolution.get('dependency_services') or {}
    chains = []
    for sid, service_raw, service in observations:
        subject = service.get('service')
        if (service_raw.get('operation') != 'services' or service.get('kind') != 'docker'
                or service.get('state') != 'stopped'
                or subject not in resolution.get('allowed_services', [])):
            continue
        for did, dep_raw, dep in observations:
            if (dep_raw.get('operation') != 'dependency_probe' or dep.get('tcp') != 'failed'
                    or mapping.get(dep.get('dependency')) != subject
                    or dep_raw.get('target_id') != service_raw.get('target_id')):
                continue
            host, port = dep.get('host'), dep.get('port')
            published = any(p.get('port') == port and
                (p.get('host') == host or (p.get('host') in {'0.0.0.0', '::'}
                                         and host in {'127.0.0.1', 'localhost', '::1'}))
                for p in service.get('published_tcp_ports') or [])
            internal = (host in (service.get('network_aliases') or [])
                        and port in (service.get('exposed_tcp_ports') or [])
                        and dep.get('source_service') in resolution.get('allowed_services', []))
            if not (published or internal):
                continue
            # Internal failures need a real consumer operation, not just a socket.
            # Fixed adapters use the consumer's loaded settings for the query.
            affected = []
            if internal:
                if (dep.get('probe_kind') in {'django_database', 'django_cache'}
                        and dep.get('query') == 'failed'):
                    affected = [did]
                affected += [ident for ident, raw, body in observations
                    if raw.get('operation') == 'dependency_probe'
                    and mapping.get(body.get('dependency')) == dep.get('source_service')
                    and type((body.get('http') or {}).get('status')) is int
                    and body['http']['status'] >= 500]
                if not affected:
                    continue
            chains.append({'code': 'registered_service_stopped', 'subject': subject,
                'evidence_ids': sorted({sid, did, *affected[:1]}),
                'limitation': '只确认当前服务停止与对应访问失败；停止触发者、动机和更早历史未确认。'})
    # Several failed paths may describe one service; choose one complete chain.
    unique = {}
    for chain in chains:
        unique.setdefault(chain['subject'], chain)
    return list(unique.values())
