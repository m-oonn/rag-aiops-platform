"""Read-only, redacted inventory of settings, consumers and local listeners."""
import argparse
import ast
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def sensitive(name):
    return ('SECRET' in name.upper() or 'PASSWORD' in name.upper()
            or name.upper().endswith(('_KEY', '_TOKEN')))


def display(name, value):
    if sensitive(name):
        return {'configured': bool(value)}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = str(value)
    if name.endswith(('_USERNAME', '_USER', '_ACCESS_KEY')):
        return {'configured': bool(value)}
    if text.lstrip().startswith(('{', '[')):
        return '<structured value omitted>'
    if '://' in text:
        try:
            u = urlsplit(text)
            if u.scheme.startswith('sqlite'):
                return text.split('?', 1)[0].split('#', 1)[0]
            host = u.hostname or ''
            if ':' in host:
                host = '[' + host + ']'
            netloc = host + (':' + str(u.port) if u.port else '')
            return urlunsplit((u.scheme, netloc, u.path, '', ''))
        except ValueError:
            return '<invalid URL>'
    return re.sub(r'sk-[A-Za-z0-9_-]+', '<credential omitted>', text)


def environment_file(path, field_names):
    from dotenv import dotenv_values
    values = dotenv_values(path, interpolate=False) if path.is_file() else {}
    seen, duplicate = set(), set()
    for line in path.read_text(encoding='utf-8-sig').splitlines() if path.is_file() else []:
        match = re.match(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=', line)
        if match:
            key = match[1]
            if key in seen:
                duplicate.add(key)
            seen.add(key)
    return values, {'exists': path.is_file(), 'field_count': len(values),
        'unknown_field_names': sorted(set(values) - field_names), 'duplicate_field_names': sorted(duplicate),
        'omitted_field_names': sorted(field_names - set(values))}


def consumers(root):
    settings_refs, direct = {}, {}
    for folder in ('src', 'mcp_servers', 'scripts'):
        for path in sorted((root / folder).rglob('*.py')):
            tree = ast.parse(path.read_text(encoding='utf-8-sig'))
            for node in ast.walk(tree):
                location = path.relative_to(root).as_posix() + ':' + str(getattr(node, 'lineno', 0))
                if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                        and node.value.id == 'settings'):
                    settings_refs.setdefault(node.attr, []).append(location)
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == 'getattr' and len(node.args) > 1
                        and isinstance(node.args[0], ast.Name) and node.args[0].id == 'settings'
                        and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str)):
                    settings_refs.setdefault(node.args[1].value, []).append(location)
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr in {'get', 'getenv', 'setdefault'} and node.args
                        and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                    owner = ast.unparse(node.func.value)
                    if owner in {'os', 'os.environ'}:
                        direct.setdefault(node.args[0].value, []).append(location)
                if (isinstance(node, ast.Subscript) and ast.unparse(node.value) == 'os.environ'
                        and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str)):
                    direct.setdefault(node.slice.value, []).append(location)
    return settings_refs, direct


def build_inventory(root=ROOT):
    from src.settings import Settings
    from scripts.with_agent_test_env import profile_environment
    root = Path(root).resolve()
    fields = set(Settings.model_fields)
    base, base_file = environment_file(root / '.env', fields)
    example, example_file = environment_file(root / '.env.example', fields)
    profile, profile_file = environment_file(root / '.env.agent-test', fields)
    current = Settings(_env_file=root / '.env')
    refs, direct = consumers(root)
    values = []
    for name in Settings.model_fields:
        origin = 'process_environment' if name in os.environ else '.env' if name in base else 'source_default'
        values.append({'name': name, 'effective': display(name, getattr(current, name)),
            'source_default': display(name, Settings.model_fields[name].default), 'origin': origin,
            'in_example': name in example, 'consumers': refs.get(name, [])})
    preview, profile_error = None, None
    if profile_file['exists']:
        try:
            env = profile_environment(root / '.env.agent-test')
            # Validation only. Do not alter this process's settings singleton.
            overrides = {key: value for key, value in env.items() if key in fields}
            resolved = Settings(_env_file=root / '.env', **overrides)
            preview = {key: display(key, getattr(resolved, key)) for key in profile}
            preview['RESOLVED_LLM_API_BASE'] = display('LLM_API_BASE', resolved.RESOLVED_LLM_API_BASE)
            preview['RESOLVED_LLM_API_KEY'] = display('LLM_API_KEY', resolved.RESOLVED_LLM_API_KEY)
        except (ValueError, TypeError):
            profile_error = 'profile validation failed (values withheld)'
    warnings = []
    if example_file['omitted_field_names']:
        warnings.append('example_missing_settings')
    if profile_error:
        warnings.append('test_profile_invalid')
    if profile and profile.get('AGENT_MODEL') != current.AGENT_MODEL:
        warnings.append('test_profile_requires_explicit_launcher')
    if profile and profile.get('AGENT_MODEL') not in {'deepseek-v4-flash', 'deepseek-flash'}:
        warnings.append('test_provider_pricing_and_evaluation_transport_not_verified')
    if not current.PROBE_ENABLED:
        warnings.append('regular_startup_probe_disabled')
    if not current.EXPERIENCE_KB_IDS:
        warnings.append('regular_startup_knowledge_scope_unrestricted')
    if current.ENABLE_RERANK:
        warnings.append('vector_rag_may_use_online_rerank_local_bm25_is_separate')
    if '(免费)' in current.MODEL_DISPLAY_NAMES:
        warnings.append('model_display_claims_free_without_current_quota_check')
    listeners, listen_error = [], None
    ports = {5273, 8200, 8103, 8104, 8105, 8106, 8107, 18765, 18766, 18767, 19530, 6379, 5672, 9000, 9200, 19090}
    try:
        import psutil
        listeners = [{'port': row.laddr.port, 'pid': row.pid, 'address': row.laddr.ip}
            for row in psutil.net_connections(kind='tcp') if row.status == 'LISTEN' and row.laddr.port in ports]
    except (OSError, RuntimeError):
        listen_error = 'local listener enumeration unavailable'
    ignored = subprocess.run(['git', 'check-ignore', '--quiet', '.env.agent-test'], cwd=root).returncode == 0
    tracked = bool(subprocess.run(['git', 'ls-files', '.env.agent-test'], cwd=root,
        capture_output=True, text=True).stdout.strip())
    return {'checked_at': datetime.now(timezone.utc).isoformat(), 'root': str(root),
        'settings_field_count': len(values), 'settings': values,
        'files': {'.env': base_file, '.env.example': example_file, '.env.agent-test': profile_file},
        'agent_test_profile': {'preview': preview, 'error': profile_error, 'git_ignored': ignored, 'tracked': tracked,
            'automatically_loaded': False, 'launcher': 'scripts/with_agent_test_env.py'},
        'direct_environment_consumers': direct,
        'computed_setting_names': sorted(name for name in set(refs) - fields if isinstance(getattr(Settings, name, None), property)),
        'unknown_setting_reference_names': sorted(name for name in set(refs) - fields if not isinstance(getattr(Settings, name, None), property)),
        'warnings': warnings, 'listeners': listeners, 'listener_error': listen_error,
        'runtime_settings_of_existing_processes': 'not inspected; listeners do not prove loaded configuration',
        'scope': 'static Python AST and current-process Settings; embedded scripts, external service configs and Docker interpolation need separate review',
        'model_calls': 0, 'service_restarted': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--profile-check', action='store_true')
    args = parser.parse_args()
    if args.profile_check:
        from src.settings import settings
        data = {'model': settings.AGENT_MODEL, 'simple_model': settings.AGENT_MODEL_SIMPLE,
            'evidence_model': settings.EVIDENCE_LLM_MODEL,
            'base_url': display('LLM_API_BASE', settings.RESOLVED_LLM_API_BASE),
            'credential_configured': bool(settings.RESOLVED_LLM_API_KEY),
            'supplier_specific_thinking_parameter': settings.AGENT_DISABLE_THINKING,
            'model_calls': 0, 'pricing_verified': False, 'connectivity_verified': False}
    else:
        data = build_inventory()
    text = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        with args.output.open('x', encoding='utf-8') as handle:
            handle.write(text)
        print(json.dumps({'output': str(args.output.resolve()), 'fields': data.get('settings_field_count'),
                          'warnings': data.get('warnings', []), 'model_calls': 0}, ensure_ascii=False))
    else:
        print(text)


if __name__ == '__main__':
    main()
