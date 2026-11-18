"""Read existing Spring Actuator observations through a registered container loopback.

No endpoint is enabled here. Missing, masked or ambiguous data fails closed.
"""
import base64
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from src.probe.protocol import MAX_TEXT_BYTES
from .config import ProbeConfigError

PREFIXES = ('spring.datasource', 'spring.data.redis', 'spring.data.mongodb',
            'spring.rabbitmq', 'spring.elasticsearch', 'server')
KINDS = {'spring_database': ('spring.datasource', 'db'),
         'spring_cache': ('spring.data.redis', 'redis')}


def _identity(cfg):
    from .docker_readonly import docker
    raw = json.loads(docker('inspect', '--type', 'container', '--format',
        '{"id":{{json .Id}},"started_at":{{json .State.StartedAt}},'
        '"pid":{{json .State.Pid}},"running":{{json .State.Running}}}', cfg.docker_container))
    if (raw.get('running') is not True or type(raw.get('pid')) is not int or raw['pid'] <= 0
            or not re.fullmatch(r'[a-f0-9]{64}', str(raw.get('id', '')))
            or not _time(raw.get('started_at'))):
        raise ProbeConfigError('Spring runtime identity unavailable')
    return {key: raw[key] for key in ('id', 'started_at', 'pid')}


def _time(value):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except ValueError:
        return None


def _get(cfg, path):
    from .docker_readonly import docker
    if (not cfg.spring_management_port or path not in {
            '/actuator/configprops', '/actuator/health/db', '/actuator/health/redis',
            '/actuator/httpexchanges'}):
        raise ProbeConfigError('Spring observation endpoint is not registered')
    # The port comes from the local allow-list; caller input cannot form a URL.
    url = f'http://127.0.0.1:{cfg.spring_management_port}{path}'
    snippet = ('import java.net.*; import java.io.*; import java.util.*;\n'
        f'HttpURLConnection c=(HttpURLConnection)new URL({json.dumps(url)}).openConnection();\n'
        'c.setRequestMethod("GET"); c.setInstanceFollowRedirects(false); '
        'c.setConnectTimeout(1500); c.setReadTimeout(3000);\n'
        'int status=c.getResponseCode(); '
        'InputStream stream=status>=400?c.getErrorStream():c.getInputStream(); '
        'byte[] body=stream==null?new byte[0]:stream.readNBytes(1048577); '
        'if(stream!=null)stream.close(); c.disconnect(); '
        'System.out.println("PROBE_HTTP="+status+";"+Base64.getEncoder().encodeToString(body));\n')
    output = docker('exec', '-i', cfg.docker_container, 'jshell', '--execution', 'local',
        '--feedback', 'silent', '-', input=snippet.encode(), timeout=7).decode('utf-8', errors='replace')
    matches = re.findall(r'PROBE_HTTP=([0-9]{3});([A-Za-z0-9+/=]*)', output)
    if len(matches) != 1:
        raise ProbeConfigError('Spring observation response unavailable')
    status, encoded = matches[0]
    raw = base64.b64decode(encoded, validate=True)
    if len(raw) > 1048576 or (int(status) != 200 and not (int(status) == 503 and '/health/' in path)):
        raise ProbeConfigError('Spring observation endpoint unavailable or response exceeds limit')
    try:
        document = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ProbeConfigError('Spring observation response is not JSON') from exc
    if not isinstance(document, dict):
        raise ProbeConfigError('Spring observation response is not an object')
    return document


def _bound(document, prefix):
    contexts = document.get('contexts')
    if not isinstance(contexts, dict) or any(not isinstance(context, dict)
            or not isinstance(context.get('beans'), dict) for context in contexts.values()):
        raise ProbeConfigError('Spring bound configuration response is invalid')
    beans = [bean for context in contexts.values()
        for bean in (context.get('beans') or {}).values()
        if isinstance(bean, dict) and bean.get('prefix') == prefix
        and isinstance(bean.get('properties'), dict)]
    if len(beans) != 1:
        raise ProbeConfigError('Spring bound configuration missing or ambiguous')
    return beans[0]['properties']


def _configuration(cfg, document, identity):
    from .docker_readonly import _spring_value
    values, missing, hashes = {}, [], {}
    for prefix in PREFIXES:
        keys = [key for key in cfg.config_keys if key.startswith(prefix + '.')]
        if not keys:
            continue
        # DataSourceProperties can differ from Druid's actual bound datasource.
        properties = _bound(document, 'spring.datasource.druid' if prefix == 'spring.datasource' else prefix)
        public = {}
        for key in keys:
            nested = properties
            for part in reversed(prefix.split('.')):
                nested = {part: nested}
            try:
                value, present = _spring_value(nested, key)
            except (TypeError, ValueError) as exc:
                raise ProbeConfigError('Spring public runtime field is invalid') from exc
            if not present or value is None or '*' in str(value):
                missing.append(key)
            else:
                public[key] = value
        values.update(public)
        hashes[prefix] = hashlib.sha256(json.dumps(public, sort_keys=True).encode()).hexdigest()
    if missing:
        raise ProbeConfigError('Spring public runtime fields missing or masked')
    return {'source': 'running_spring_configprops', 'values': values,
        'runtime_effective_values_confirmed': False, 'bound_configuration_confirmed': True,
        'runtime_identity': identity,
        'binding_hashes': hashes, 'missing_keys': [],
        'source_sha256': hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest(),
        'limitation': '仅观察容器中的唯一配置Bean公开字段，未核验JVM启动身份；尚未证明业务实际使用哪个连接工厂或数据源，也未关联具体失败请求。'}


def configuration(cfg):
    before = _identity(cfg)
    result = _configuration(cfg, _get(cfg, '/actuator/configprops'), before)
    if before != _identity(cfg):
        raise ProbeConfigError('Spring runtime changed during observation')
    return result


def _tcp(cfg, host, port):
    from .docker_readonly import docker
    if (not isinstance(host, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,253}', host)
            or type(port) is not int or not 1 <= port <= 65535):
        raise ProbeConfigError('Spring runtime endpoint is invalid')
    snippet = ('import java.net.*;\nSocket socket=new Socket();\n'
        f'try {{ socket.connect(new InetSocketAddress({json.dumps(host)},{port}),1500); '
        'System.out.println("PROBE_TCP=ok"); } '
        'catch (Exception e) { System.out.println("PROBE_TCP=failed"); } '
        'finally { try { socket.close(); } catch (Exception e) {} }\n')
    output = docker('exec', '-i', cfg.docker_container, 'jshell', '--execution', 'local',
        '--feedback', 'silent', '-', input=snippet.encode(), timeout=5).decode('utf-8', errors='replace')
    matches = re.findall(r'PROBE_TCP=(ok|failed)', output)
    if len(matches) != 1:
        raise ProbeConfigError('Spring endpoint TCP observation unavailable')
    return matches[0]


def dependency(service, cfg):
    prefix, component = KINDS[cfg.probe_kind]
    before = _identity(service)
    config = _configuration(service, _get(service, '/actuator/configprops'), before)
    values = config['values']
    if cfg.probe_kind == 'spring_database':
        loaded = values['spring.datasource.url']
        host, port = loaded['host'], loaded['port']
    else:
        host, port = values['spring.data.redis.host'], values['spring.data.redis.port']
    health = _get(service, '/actuator/health/' + component)
    if health.get('status') not in {'UP', 'DOWN'} or health.get('components'):
        raise ProbeConfigError('Spring component health is unavailable or ambiguous')
    details = health.get('details') or {}
    if not isinstance(details, dict):
        raise ProbeConfigError('Spring component health details are invalid')
    error = str(details.get('error') or '')
    query = 'ok' if health['status'] == 'UP' else 'failed'
    tcp = _tcp(service, host, port)
    registered_tcp = tcp if (host, port) == (cfg.host, cfg.port) else _tcp(service, cfg.host, cfg.port)
    if before != _identity(service):
        raise ProbeConfigError('Spring runtime changed during observation')
    return {'source_service': cfg.source_service, 'probe_kind': cfg.probe_kind,
        'probe_origin': 'running_spring_health_component', 'host': host, 'port': port,
        'endpoint_source': 'configuration_properties_bean',
        'health_endpoint_binding_confirmed': False,
        'registered_host': cfg.host, 'registered_port': cfg.port, 'registered_tcp': registered_tcp,
        'tcp': tcp, 'query': 'unknown', 'health_query': query, 'health_component': component,
        'runtime_identity': before, 'binding_hash': config['binding_hashes'][prefix],
        **({'health_error_category': 'authentication_rejected' if cfg.probe_kind == 'spring_database'
            and ('Access denied for user' in error or 'SQLInvalidAuthorizationSpecException' in error)
            else 'connection_or_query_failed'} if query == 'failed' else {}),
        'limitation': '健康组件操作与配置Bean端点TCP分别观察；未证明两者使用同一连接工厂，也未关联具体业务请求。未重放下单。'}


def request_logs(cfg, lines, *, contains=''):
    before = _identity(cfg)
    document = _get(cfg, '/actuator/httpexchanges')
    if not isinstance(document.get('exchanges'), list):
        raise ProbeConfigError('Spring recorded HTTP exchanges unavailable')
    now = datetime.now(timezone.utc)
    duration = re.fullmatch(r'([1-9][0-9]{0,3})([smh])', cfg.log_since)
    since = (now-timedelta(seconds=int(duration[1]) * {'s': 1, 'm': 60, 'h': 3600}[duration[2]])
             if duration else _time(cfg.log_since))
    if since is None:
        raise ProbeConfigError('Spring request log time boundary is invalid or lacks a timezone')
    window_start = max(now-timedelta(seconds=180), _time(before['started_at']), since)
    events = []
    for item in document['exchanges']:
        if not isinstance(item, dict):
            continue
        at = _time(item.get('timestamp'))
        if not at or not window_start <= at <= now:
            continue
        request, response = item.get('request') or {}, item.get('response') or {}
        if not isinstance(request, dict) or not isinstance(response, dict):
            continue
        method, status = request.get('method'), response.get('status')
        try:
            path = urlsplit(str(request.get('uri') or '')).path
        except ValueError:
            continue
        if (not isinstance(method, str) or method not in {'GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'}
                or type(status) is not int or not 100 <= status <= 599
                or not path.startswith('/') or len(path) > 512 or any(ord(c) < 32 for c in path)):
            continue
        # Never return body, query, headers, principal or session.
        event = {'at': at.isoformat(), 'method': method, 'path': path, 'status': status}
        events.append(json.dumps(event, ensure_ascii=False))
    if before != _identity(cfg):
        raise ProbeConfigError('Spring runtime changed during observation')
    events.sort()
    matched = [event for event in events if contains in event] if contains else events
    selected = matched[-lines:]
    truncated = len(matched) > lines
    while len('\n'.join(selected).encode()) > MAX_TEXT_BYTES:
        selected.pop(0)
        truncated = True
    return {'path': f'docker://{cfg.docker_container}/http-exchanges', 'line_limit': lines,
        'since': cfg.log_since, 'window_start': window_start.isoformat(),
        'source': 'spring_http_exchanges', 'runtime_identity': before, 'lines': selected,
        **({'contains': contains} if contains else {}), 'covers_full_history': False,
        'limitation': '只读最近180秒内且不早于登记日志起点及容器启动的既有请求；未核验JVM身份或请求依赖链。空结果不证明业务正常，未重放业务请求。'}, truncated
