"""Run an explicit evaluation command with the local, ignored model profile."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIELDS = {'LLM_API_BASE', 'LLM_API_KEY', 'AGENT_MODEL', 'AGENT_MODEL_SIMPLE',
          'AGENT_DISABLE_THINKING', 'EVIDENCE_LLM_MODEL', 'DEEPSEEK_API_KEY',
          'LLM_FALLBACK_API_BASE', 'LLM_FALLBACK_API_KEY', 'LLM_FALLBACK_MODEL',
          'LLM_FALLBACK_ENABLED'}
COMMANDS = {'scripts/evaluate_windows_probe.py', 'scripts/verify_windows_local_faults.py',
            'scripts/evaluate_autonomous_investigation.py', 'scripts/replay_model_request.py',
            'scripts/verify_competing_hypothesis_scenario.py'}


def profile_environment(path, inherited=None):
    from dotenv import dotenv_values
    if not Path(path).is_file():
        raise ValueError('Agent test profile is missing')
    values = dotenv_values(path, interpolate=False)
    if set(values) - FIELDS:
        raise ValueError('Agent test profile contains unsupported field names')
    if any(not values.get(key) for key in ('LLM_API_BASE', 'LLM_API_KEY', 'AGENT_MODEL')):
        raise ValueError('Agent test profile requires endpoint, credential and model')
    from urllib.parse import urlsplit
    endpoint = urlsplit(values['LLM_API_BASE'])
    if (endpoint.scheme != 'https' or not endpoint.hostname or endpoint.username
            or endpoint.password or endpoint.query or endpoint.fragment):
        raise ValueError('Agent test endpoint must be an HTTPS base URL without credentials or query')
    env = dict(os.environ if inherited is None else inherited)
    env.update({key: value for key, value in values.items() if value is not None})
    # All Agent roles use this profile unless the profile explicitly overrides one.
    env['AGENT_MODEL_SIMPLE'] = values.get('AGENT_MODEL_SIMPLE') or values['AGENT_MODEL']
    env['EVIDENCE_LLM_MODEL'] = values.get('EVIDENCE_LLM_MODEL') or values['AGENT_MODEL']
    env['AGENT_DISABLE_THINKING'] = values.get('AGENT_DISABLE_THINKING') or 'false'
    return env


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, default=ROOT / '.env.agent-test',
        help='Local private model profile; applies only to the child process')
    parser.add_argument('--check', action='store_true', help='Resolve model settings without sending requests')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if args.check == bool(command):
        parser.error('choose --check or one explicit evaluation command')
    if command and (command[0] not in COMMANDS):
        parser.error('only existing project evaluation scripts are accepted')
    try:
        env = profile_environment(args.profile)
    except ValueError as exc:
        parser.error(str(exc))
    if args.check:
        command = ['scripts/audit_configuration.py', '--profile-check']
    return subprocess.run([sys.executable, *command], cwd=ROOT, env=env).returncode


if __name__ == '__main__':
    raise SystemExit(main())
