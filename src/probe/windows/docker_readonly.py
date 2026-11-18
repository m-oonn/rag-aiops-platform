"""Fixed Docker observations. No caller-supplied command, SQL, path or container."""
from __future__ import annotations

import json
import hashlib
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from src.probe.protocol import MAX_TEXT_BYTES, redact
from .config import ProbeConfigError


def docker(*args, timeout=9, input=None):
    try:
        result = subprocess.run(['docker', *args], capture_output=True, timeout=timeout, input=input)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProbeConfigError(f'Docker observation unavailable: {type(exc).__name__}') from exc
    if result.returncode:
        # Docker stderr may include an endpoint or credential; never return it.
        raise ProbeConfigError('Docker observation unavailable')
    return result.stdout


def state(cfg):
    raw = docker('inspect', '--type', 'container', '--format',
        '{"state":{{json .State}},"bindings":{{json .HostConfig.PortBindings}},'
        '"networks":{{json .NetworkSettings.Networks}},"exposed":{{json .Config.ExposedPorts}}}',
        cfg.docker_container)
    details = json.loads(raw)
    value = details.get('state', details)
    aliases = sorted({alias for network in (details.get('networks') or {}).values()
                      for alias in network.get('Aliases') or []})
    exposed = sorted(int(port.split('/')[0]) for port in (details.get('exposed') or {})
                     if port.endswith('/tcp') and port.split('/')[0].isdigit())
    bindings = [{'container_port': int(port.split('/')[0]), 'host': row.get('HostIp') or '0.0.0.0',
                 'port': int(row['HostPort'])}
                for port, rows in (details.get('bindings') or {}).items()
                if port.endswith('/tcp') and port.split('/')[0].isdigit()
                for row in rows or [] if str(row.get('HostPort', '')).isdigit()]
    return {'kind': 'docker', 'container': cfg.docker_container,
            'state': 'running' if value.get('Running') else 'stopped',
            'docker_status': value.get('Status'), 'pid': value.get('Pid'), 'pid_namespace': 'docker_host',
            'exit_code': value.get('ExitCode'), 'oom_killed': value.get('OOMKilled'),
            'started_at': value.get('StartedAt'), 'finished_at': value.get('FinishedAt'),
            'health': (value.get('Health') or {}).get('Status'),
            'network_aliases': aliases, 'exposed_tcp_ports': exposed, 'published_tcp_ports': bindings}


def logs(cfg, lines, *, contains=''):
    # Docker logs writes application stderr to stderr; capture both without a shell.
    source_limit = max(1001, lines + 1)
    result = subprocess.run(['docker', 'logs', '--timestamps', '--since', cfg.log_since,
                             '--tail', str(source_limit), cfg.docker_container], capture_output=True, timeout=9)
    if result.returncode:
        raise ProbeConfigError('Docker logs unavailable')
    raw = result.stdout + result.stderr
    text = redact(raw.decode('utf-8', errors='replace'))
    text = re.sub(r'(?i)(for user\s+)["\'][^"\']+["\']', r'\1[REDACTED]', text)
    observed = sorted(text.splitlines(), key=lambda row: row.partition(' ')[0])
    source_count = len(observed)
    source_window_saturated = source_count >= source_limit
    if contains:
        observed = [row for row in observed if contains in row]
    truncated = len(observed) > lines
    # A Java stack can exceed the returned line budget; keep both ends of
    # this bounded source window, not just frames after the exception header.
    head_count = lines // 2 if truncated else 0
    selected = observed[:head_count] + observed[-(lines - head_count):]
    omitted = len(observed) - len(selected)
    if len('\n'.join(selected).encode('utf-8')) > MAX_TEXT_BYTES:
        # Keep the exception header as well as the tail of a long stack.
        head, tail, used = [], [], 0
        for row in selected:
            size = len(row.encode('utf-8')) + 1
            if used + size > MAX_TEXT_BYTES // 2:
                break
            head.append(row)
            used += size
        for row in reversed(selected[len(head):]):
            size = len(row.encode('utf-8')) + 1
            if used + size > MAX_TEXT_BYTES:
                break
            tail.append(row)
            used += size
        omitted += len(selected) - len(head) - len(tail)
        selected = head + list(reversed(tail))
        truncated = True
    return {'path': f'docker://{cfg.docker_container}/stdout', 'line_limit': lines,
            'source_line_limit': source_limit,
            'since': cfg.log_since, 'lines': selected,
            **({'contains': contains, 'filtered_out_lines': source_count - len(observed),
                'source_window_saturated': source_window_saturated} if contains else {}),
            'selection': 'head_and_tail' if omitted else 'tail',
            'omitted_middle_lines': omitted,
            'covers_full_history': False}, truncated or (bool(contains) and source_window_saturated)


SETTINGS = r'''
import json, os, sys
from urllib.parse import urlsplit
from django.conf import settings as s
def endpoint(value):
    p=urlsplit(value)
    return {'host':p.hostname,'port':p.port or 6379,'database':p.path}
d=s.DATABASES['default']
import django
django.setup()
from django.contrib.staticfiles import finders
resources=json.loads(sys.argv[1])
static_files={name:{'found':bool(finders.find(name))} for name in resources}
print(json.dumps({'database':{'host':d.get('HOST'),'port':d.get('PORT'),'engine':d.get('ENGINE')},
 'caches':{k:endpoint(v.get('LOCATION','')) for k,v in s.CACHES.items()},
 'allowed_hosts':s.ALLOWED_HOSTS,'static_url':s.STATIC_URL,
 'static_directories':[str(p) for p in s.STATICFILES_DIRS],
 'broker':endpoint(s.CELERY_BROKER_URL),'settings_module':os.environ.get('DJANGO_SETTINGS_MODULE'),
 'static_files':static_files}))
'''


def configuration(cfg):
    if cfg.docker_django:
        try:
            raw = docker('exec', cfg.docker_container, 'python', '-c', SETTINGS,
                         json.dumps(cfg.static_resources))
            result = {'values': json.loads(raw), 'source': 'running_container_django_settings',
                      'container': cfg.docker_container}
            if cfg.expected_static_mounts:
                actual = json.loads(docker('inspect', '--type', 'container', '--format',
                    '{{json .Mounts}}', cfg.docker_container))
                result['static_mounts'] = []
                for destination, expected in cfg.expected_static_mounts.items():
                    matches = [m for m in actual if m.get('Destination') == destination]
                    source = matches[0].get('Source') if len(matches) == 1 else None
                    root = Path(expected).resolve()
                    exists = {name: (root / name).resolve().is_relative_to(root)
                              and (root / name).is_file() for name in cfg.static_resources}
                    result['static_mounts'].append({'destination': destination,
                        'registered_source': os.path.normcase(os.path.normpath(expected)),
                        'actual_source': os.path.normcase(os.path.normpath(source)) if source else None,
                        'registered_resources_present': exists})
            return result
        except ProbeConfigError:
            # A stopped app cannot execute settings code. Project only public
            # startup fields; never return the inspected environment itself.
            raw = docker('inspect', '--type', 'container', '--format', '{{json .Config.Env}}', cfg.docker_container)
            allowed = {'POSTGRES_HOST', 'POSTGRES_PORT', 'ALLOWED_HOSTS',
                       'REDIS_CACHE_CONFIG', 'REDIS_SESSION_CONFIG', 'REDIS_CART_CONFIG'}
            values = {}
            for entry in json.loads(raw) or []:
                key, _, value = entry.partition('=')
                if key not in allowed:
                    continue
                if key.startswith('REDIS_'):
                    endpoint = urlsplit(value)
                    values[key] = {'host': endpoint.hostname, 'port': endpoint.port or 6379,
                                   'database': endpoint.path}
                else:
                    values[key] = value
            return {'values': values, 'source': 'container_start_environment',
                    'container': cfg.docker_container,
                    'limitation': '仅为容器启动环境的公开字段；未取得运行时加载配置，不能据此证明配置已生效。'}
    if cfg.docker_spring:
        if cfg.spring_management_port:
            from .spring_readonly import configuration
            return configuration(cfg)
        return _spring_configuration(cfg)
    return {'error': 'configuration_not_configured'}


def _spring_value(document, key):
    value = document
    for part in key.split('.'):
        if not isinstance(value, dict) or part not in value:
            return None, False
        value = value[part]
    if key == 'spring.datasource.url':
        parsed = urlsplit(str(value).removeprefix('jdbc:'))
        if parsed.scheme != 'mysql' or not parsed.hostname:
            return None, True
        return {'host': parsed.hostname, 'port': parsed.port or 3306,
                'database': parsed.path.lstrip('/')}, True
    if key == 'spring.elasticsearch.uris':
        rows = value if isinstance(value, list) else str(value).split(',')
        endpoints = []
        for row in rows:
            parsed = urlsplit(str(row).strip())
            if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
                return None, True
            endpoints.append({'scheme': parsed.scheme, 'host': parsed.hostname,
                              'port': parsed.port or (443 if parsed.scheme == 'https' else 80)})
        return endpoints, True
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value, True
    return None, True


def _same_mount_source(actual, registered):
    def normalized(value):
        value = str(value).replace('\\\\?\\', '')
        marker = '/run/desktop/mnt/host/'
        if value.lower().startswith(marker):
            value = value[len(marker):]
            if re.match(r'^[A-Za-z]/', value):
                value = value[0] + ':/' + value[2:]
        return os.path.normcase(os.path.normpath(value))
    return normalized(actual) == normalized(registered)


def _spring_configuration(cfg):
    path = Path(cfg.config_file)
    try:
        if not path.is_file() or path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent.exists()):
            raise ProbeConfigError('registered Spring configuration file is unavailable')
        raw = path.read_bytes()
    except OSError as exc:
        raise ProbeConfigError('registered Spring configuration file is unavailable') from exc
    if len(raw) > MAX_TEXT_BYTES:
        raise ProbeConfigError('registered Spring configuration file exceeds the evidence limit')
    try:
        import yaml
    except ImportError as exc:
        raise ProbeConfigError('registered Spring configuration parser unavailable') from exc
    try:
        document = yaml.safe_load(raw.decode('utf-8'))
    except (UnicodeError, yaml.YAMLError) as exc:
        raise ProbeConfigError('registered Spring configuration cannot be parsed') from exc
    if not isinstance(document, dict):
        raise ProbeConfigError('registered Spring configuration must be a YAML mapping')

    mounts = json.loads(docker('inspect', '--type', 'container', '--format',
        '{{json .Mounts}}', cfg.docker_container))
    rows = [item for item in mounts if item.get('Destination') == '/app/local.yml']
    mount_matches = len(rows) == 1 and _same_mount_source(rows[0].get('Source', ''), path)
    command = json.loads(docker('inspect', '--type', 'container', '--format',
        '{{json .Config.Cmd}}', cfg.docker_container))
    configured_argument = '--spring.config.additional-location=file:/app/local.yml'
    values, missing, invalid = {}, [], []
    for key in cfg.config_keys:
        value, present = _spring_value(document, key)
        if not present:
            missing.append(key)
        elif value is None:
            invalid.append(key)
        else:
            values[key] = value
    return {'source': 'mounted_spring_config_snapshot',
            'source_sha256': hashlib.sha256(raw).hexdigest(),
            'registered_config_file': str(path), 'mount_matches_registered_file': mount_matches,
            'mount_read_only': len(rows) == 1 and rows[0].get('RW') is False,
            'startup_config_argument_present': configured_argument in command,
            'runtime_effective_values_confirmed': False,
            'values': values, 'missing_keys': missing, 'invalid_keys': invalid,
            'limitation': '这是登记配置文件及容器挂载/启动参数的只读快照，不代表应用已成功加载这些值。'}


NETWORK = r'''
import json, socket, sys, time
c=json.loads(sys.argv[1]); r={'host':c['host'],'port':c['port'],'registered_host':c['host'],'registered_port':c['port'],'source_service':c['source_service'],'probe_kind':c['probe_kind'],'cache_alias':c['cache_alias']}
started=time.monotonic()
try:
    kind=c['probe_kind']
    if kind=='django_database':
        from django.conf import settings
        import psycopg2
        d=settings.DATABASES['default']; r.update(host=d['HOST'],port=int(d.get('PORT') or 5432))
        with psycopg2.connect(host=d['HOST'],port=d.get('PORT') or 5432,dbname=d['NAME'],user=d['USER'],password=d['PASSWORD'],connect_timeout=2,options='-c statement_timeout=2000 -c default_transaction_read_only=on') as db:
            with db.cursor() as cur:
                cur.execute('SELECT 1'); r['query']='ok'
                cur.execute("SELECT wait_event_type, wait_event, count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() AND state='active' GROUP BY wait_event_type,wait_event")
                r['active_waits']=[{'type':x[0],'event':x[1],'count':x[2]} for x in cur.fetchall()]
    elif kind=='django_cache':
        from django.conf import settings
        from urllib.parse import urlsplit
        import redis
        p=urlsplit(settings.CACHES[c['cache_alias']]['LOCATION']); r.update(host=p.hostname,port=p.port or 6379)
        client=redis.Redis.from_url(settings.CACHES[c['cache_alias']]['LOCATION'],socket_connect_timeout=2,socket_timeout=2)
        r['query']='ok' if client.ping() else 'failed'
    elif kind=='celery':
        from config.celery import app
        import redis
        replies=app.control.ping(timeout=1)
        r['workers']=[key for row in replies for key in row]; r['query']='ok' if replies else 'no_worker_reply'
        client=redis.Redis.from_url(app.conf.broker_url,socket_connect_timeout=2,socket_timeout=2)
        r['queue_length']=client.llen('celery')
    with socket.create_connection((r['host'],r['port']),timeout=2): r['tcp']='ok'
except Exception as e:
    r['error_type']=type(e).__name__
    if kind!='tcp': r['query']='failed'
    r['sqlstate']=getattr(e,'pgcode',None)
    # Return a fixed error category rather than exception text containing credentials.
    r['error_category']=('authentication_rejected' if r['sqlstate'] in ('28P01','28000') or 'password authentication failed' in str(e).lower() else 'connection_or_query_failed')
    try:
        with socket.create_connection((r['host'],r['port']),timeout=2): r['tcp']='ok'
    except OSError: r['tcp']='failed'
r['elapsed_ms']=round((time.monotonic()-started)*1000,1)
print(json.dumps(r))
'''


def dependency(config, cfg):
    service = config.service(cfg.source_service)
    if cfg.probe_kind in {'spring_database', 'spring_cache'}:
        from .spring_readonly import dependency
        return dependency(service, cfg)
    params = {k: getattr(cfg, k) for k in ('host', 'port', 'source_service', 'probe_kind', 'cache_alias')}
    if service.docker_spring:
        if cfg.probe_kind != 'tcp':
            raise ProbeConfigError('Spring container only supports the fixed TCP observation')
        import time
        started = time.monotonic()
        host = json.dumps(cfg.host)
        snippet = (f'import java.net.*;\nlong started=System.nanoTime();\nSocket socket=new Socket();\n'
                   f'try {{ socket.connect(new InetSocketAddress({host},{cfg.port}),2000); '
                   'System.out.printf("PROBE_TCP=ok;elapsed_ms=%.1f%n",(System.nanoTime()-started)/1000000.0); } '
                   'catch (Exception e) { System.out.printf("PROBE_TCP=failed:%s;elapsed_ms=%.1f%n",'
                   'e.getClass().getSimpleName(),(System.nanoTime()-started)/1000000.0); }\n')
        output = docker('exec', '-i', service.docker_container, 'jshell', '--execution', 'local',
                        '--feedback', 'silent', '-', input=snippet.encode('utf-8'), timeout=7).decode('utf-8', errors='replace')
        matches = re.findall(r'PROBE_TCP=(ok|failed:[A-Za-z0-9]+);elapsed_ms=([0-9.]+)', output)
        if not matches:
            raise ProbeConfigError('Spring container TCP observation unavailable')
        status, elapsed = matches[-1]
        result = {'host': cfg.host, 'port': cfg.port, 'registered_host': cfg.host,
                  'registered_port': cfg.port, 'source_service': cfg.source_service,
                  'probe_kind': 'tcp', 'tcp': 'ok' if status == 'ok' else 'failed',
                  'elapsed_ms': float(elapsed), 'probe_origin': 'registered_spring_container'}
        if status != 'ok':
            result['error_type'] = status.partition(':')[2]
        return result
    return json.loads(docker('exec', service.docker_container, 'python', '-c', NETWORK, json.dumps(params)))
