"""Deterministic observations, never a causal classifier."""
import json
from datetime import datetime


FAULT_LABELS = {
    'service_not_running': '配置服务当前未运行',
    'configured_process_not_observed': '本次可枚举范围内未发现配置进程',
    'port_not_listening': '指定端口未监听',
    'expected_port_not_listening': '期望端口未监听',
    'dependency_tcp_failed': '配置依赖 TCP 探测失败',
    'dependency_http_failed': 'HTTP 探测返回失败状态',
    'port_owner_mismatch': '监听端口归属与服务 PID 不符',
    'configuration_error_log_matches_snapshot': '配置错误日志与当前独立配置快照字段及哈希一致',
}


def observation_scope(value):
    payload = value.get('payload') or {}
    keys = ('service', 'dependency', 'path', 'local_port', 'listening_only',
            'sort_by', 'channels', 'since_minutes', 'limit', 'line_limit')
    return (value.get('target_id'), value.get('operation'),
            tuple((key, json.dumps(payload[key], sort_keys=True, ensure_ascii=False))
                  for key in keys if key in payload))


def current_probe_records(records):
    """Select latest per query from records already validated by evidence_index."""
    latest = {}
    for key, record in records.items():
        value = json.loads(record['payload'])
        if value.get('data_source') != 'probe_target':
            continue
        when = datetime.fromisoformat(value['collected_at'].replace('Z', '+00:00'))
        scope = observation_scope(value)
        if scope not in latest or when >= latest[scope][0]:
            latest[scope] = (when, key, record)
    return {key: record for _, key, record in latest.values()}


def in_business_scope(value, scope, records=None):
    scope = scope or {}
    if scope.get('target_id') and value.get('target_id') != scope['target_id']:
        return False
    if scope.get('status') in {'ambiguous', 'unmatched', 'invalid_catalog'}:
        return False
    payload, operation = value.get('payload', {}), value.get('operation')
    if scope.get('status') == 'host_overview':
        return operation != 'dependency_probe'
    if scope.get('status') != 'resolved':
        return True
    if operation == 'dependency_probe':
        return payload.get('dependency') in scope.get('allowed_dependencies', [])
    if operation in {'services', 'processes', 'text_logs', 'event_logs', 'configuration'}:
        return payload.get('service') in scope.get('allowed_services', [])
    if operation == 'ports':
        expected = {p for service in scope.get('services', {}).values()
                    for p in service.get('expected_ports', [])}
        # A loopback dependency port is in scope only when it came from a
        # validated observation of an explicitly allowed dependency.
        for record in (records or {}).values():
            raw = json.loads(record['payload'])
            if raw.get('operation') != 'dependency_probe':
                continue
            dependency = raw.get('payload') or {}
            port, host = dependency.get('port'), str(dependency.get('host', '')).lower()
            if (dependency.get('dependency') in scope.get('allowed_dependencies', [])
                    and host in {'localhost', '127.0.0.1', '::1'}
                    and type(port) is int and 1 <= port <= 65535):
                expected.add(port)
        return payload.get('local_port') in expected
    return True


def observation_clues(records, scope=None):
    clues = []
    scope = scope or {}
    records = current_probe_records(records)
    configured = {}
    for record in records.values():
        value = json.loads(record['payload'])
        if (value.get('operation') == 'inventory' and not value.get('truncated')
                and not value.get('payload', {}).get('error')):
            configured.update(value.get('payload', {}).get('configured_services', {}))
    for evidence_id, record in records.items():
        raw = json.loads(record['payload'])
        if raw.get('data_source') != 'probe_target' or not in_business_scope(raw, scope, records):
            continue
        payload, operation = raw.get('payload', {}), raw.get('operation')
        codes = []
        if payload.get('error'):
            codes.append('query_unavailable')
        if raw.get('truncated'):
            codes.append('truncated_observation')
        complete = not payload.get('error') and not raw.get('truncated')
        if complete and operation == 'services' and payload.get('state') in {'stopped', 'paused', 'stop_pending'}:
            codes.append('service_not_running')
        if (complete and operation == 'processes' and payload.get('service')
                and configured.get(payload['service'], {}).get('process_names')
                and payload.get('skipped_count') == 0 and payload.get('processes') == []):
            codes.append('configured_process_not_observed')
        if complete and operation == 'ports' and payload.get('local_port') and isinstance(payload.get('ports'), list):
            if not any(row.get('status') == 'LISTEN' and (row.get('local') or {}).get('port') == payload['local_port']
                       for row in payload['ports']):
                codes.append('port_not_listening')
        if complete and operation == 'dependency_probe':
            if payload.get('tcp') == 'failed':
                codes.append('dependency_tcp_failed')
            if payload.get('http', {}).get('status', 200) >= 400:
                codes.append('dependency_http_failed')
            if payload.get('http', {}).get('error'):
                codes.append('dependency_http_unavailable')
        related = []
        if operation == 'ports' and complete and isinstance(payload.get('ports'), list):
            for service in scope.get('services', {}).values():
                for port in service.get('expected_ports', []):
                    listeners = [r for r in payload.get('ports', []) if r.get('local', {}) and r['local'].get('port') == port and r.get('status') == 'LISTEN']
                    if payload.get('local_port') in (None, port) and not listeners:
                        codes.append('expected_port_not_listening')
                    if listeners:
                        service_records = [(key, json.loads(r['payload'])) for key, r in records.items()
                            if r.get('provenance', {}).get('operation') == 'services'
                            and json.loads(r['payload']).get('payload', {}).get('service') == service.get('probe_service')
                            and not json.loads(r['payload']).get('truncated')
                            and not json.loads(r['payload']).get('payload', {}).get('error')]
                        service_pid = service_records[-1][1]['payload'].get('pid') if service_records else None
                        if service_pid and all(p.get('pid') is not None and p['pid'] != service_pid for p in listeners):
                            codes.append('port_owner_mismatch')
                            key, value = service_records[-1]
                            related.append({'evidence_id': key, 'quote': json.dumps(value['payload'], ensure_ascii=False)[:600]})
        for code in dict.fromkeys(codes):
            clues.append({'code': code, 'evidence_id': evidence_id, 'target_id': raw['target_id'],
                          'collected_at': raw['collected_at'], 'operation': operation,
                          'scope': {k: payload[k] for k in ('service', 'dependency', 'local_port') if k in payload},
                          'raw_hash': raw['raw_hash'], 'data_source': raw['data_source'],
                          'complete': complete, 'causal': False,
                          'summary': FAULT_LABELS.get(code, code),
                          'related_evidence': related if code == 'port_owner_mismatch' else [],
                          'quote': json.dumps(payload, ensure_ascii=False)[:600]})
    return clues
