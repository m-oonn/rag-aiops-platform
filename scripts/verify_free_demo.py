"""Reproducible free engineering demo; fixed decisions, never autonomous effects."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.evaluation_record import source_snapshot, utc_now


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(output):
    result = source_snapshot(ROOT, output)
    paths = [ROOT / name for name in ('scripts/verify_free_demo.py',
        'scripts/verify_probe_observation_boundary.py', 'scripts/verify_probe_mechanisms.py',
        'scripts/verify_matching503_conclusions.py', 'pytest.ini',
        'frontend/package.json', 'frontend/package-lock.json')]
    paths.extend(p for folder in ('tests', 'frontend/src', 'docs/fixtures/windows-local-runbooks')
        for p in (ROOT / folder).rglob('*') if p.suffix in {'.py', '.json', '.js', '.vue', '.md'})
    for path in sorted(set(paths)):
        if path.is_file():
            name = path.relative_to(ROOT).as_posix()
            target = output / 'source-snapshot' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            data = path.read_bytes()
            target.write_bytes(data)
            result['sources'][name] = hashlib.sha256(data).hexdigest()
    result['scope'] += '; includes demo harness, tests, frontend sources and local runbooks; not a full machine image'
    save(output / 'source.json', result)
    return result


async def run_controller(output, fail_reset=False):
    from scripts import verify_probe_observation_boundary as boundary
    from scripts.verify_windows_local_faults import verify
    original = boundary.verify_boundary_rounds
    async def controlled(tools, target, directory, log, reset, scenarios=None):
        calls = 0
        async def third_reset(case):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise RuntimeError('controlled third reset failure')
            return await reset(case)
        return await original(tools, target, directory, log, third_reset, scenarios)
    if fail_reset:
        boundary.verify_boundary_rounds = controlled
    try:
        report = await verify(output, evaluation_preflight=True, run_model=False)
    finally:
        boundary.verify_boundary_rounds = original
    assert report['model_calls'] == 0
    assert report['owned_processes_stopped'] and report['ports_released'] and not report['cleanup_errors']
    detail = json.loads((output / 'observation-boundary/report.json').read_text(encoding='utf-8'))
    if fail_reset:
        assert report['ok'] is False and detail['error_type'] == 'RuntimeError'
        assert [r['status'] for r in detail['rounds']] == ['passed', 'passed', 'failed']
        assert not any(r['case'].startswith('controller_preflight_') for r in report['cases'])
    else:
        assert report['ok'] and detail['status'] == 'passed'
        assert len(detail['rounds']) == 13 and len(detail['observations']) == 52


def bundle_path(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('manifest path escapes bundle')
    return path


def verify_bundle(output):
    record = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))
    if record['status'] != 'completed' or not record['source_unchanged']:
        raise ValueError('demo incomplete or sources changed during execution')
    required = {'before/source.json', 'after/source.json', 'controller/summary.json',
        'controller/observation-boundary/report.json', 'failure/summary.json',
        'failure/observation-boundary/report.json', 'historical-api.xml'}
    if not required <= record['artifacts_sha256'].keys():
        raise ValueError('required demo artifacts missing')
    for name, expected in record['artifacts_sha256'].items():
        if digest(bundle_path(output, name)) != expected:
            raise ValueError('artifact hash mismatch: ' + name)
    sources = []
    for phase in ('before', 'after'):
        value = json.loads((output / phase / 'source.json').read_text(encoding='utf-8'))
        if not value['sources']:
            raise ValueError('source manifest empty')
        for name, expected in value['sources'].items():
            if digest(bundle_path(output / phase / 'source-snapshot', name)) != expected:
                raise ValueError('source snapshot hash mismatch: ' + name)
        sources.append(value['sources'])
    if sources[0] != sources[1]:
        raise ValueError('source sets differ')
    return {'passed': True, 'source_files': len(sources[0]), 'artifacts': len(record['artifacts_sha256']),
        'model_calls': 0, 'autonomous_effectiveness_verified': False}


def run(output):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    record = {'version': 1, 'started_at': utc_now(), 'status': 'started', 'steps': [],
        'mode': 'live_tools_fixed_decisions_and_separate_historical_api_replay',
        'model_calls': 0, 'autonomous_effectiveness_verified': False}
    save(output / 'manifest.json', record)
    def step(name, args):
        with (output / (name + '.log')).open('wb') as log:
            code = subprocess.run([sys.executable, *args], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT).returncode
        record['steps'].append({'name': name, 'exit_code': code})
        save(output / 'manifest.json', record)
        if code:
            raise RuntimeError('demo step failed: ' + name)
    try:
        before = snapshot(output / 'before')
        child = 'import asyncio,sys; from pathlib import Path; from scripts.verify_free_demo import run_controller; asyncio.run(run_controller(Path(sys.argv[1]), sys.argv[2] == "failure"))'
        step('live-controller', ['-c', child, str(output / 'controller'), 'normal'])
        step('controlled-failure', ['-c', child, str(output / 'failure'), 'failure'])
        step('historical-api', ['-m', 'pytest', '-q', 'tests/test_matching503_output_flow.py',
            '--basetemp', str(output / 'api-tests'), '--junitxml', str(output / 'historical-api.xml'), '--tb=short'])
        after = snapshot(output / 'after')
        record['source_unchanged'] = before['sources'] == after['sources']
        if not record['source_unchanged']:
            raise ValueError('sources changed during demo')
        record['artifacts_sha256'] = {p.relative_to(output).as_posix(): digest(p) for p in sorted(output.rglob('*'))
            if p.is_file() and 'source-snapshot' not in p.parts and p.suffix in {'.json', '.jsonl', '.xml', '.toml', '.txt', '.log'}
            and p != output / 'manifest.json' and p.name != 'token'}
        record['status'] = 'completed'
    except BaseException as exc:
        record.update(status='failed', error_type=type(exc).__name__)
        raise
    finally:
        record['ended_at'] = utc_now()
        save(output / 'manifest.json', record)
    return verify_bundle(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--output', type=Path, help='New local directory; starts disposable business and real faults, no paid calls')
    mode.add_argument('--verify', type=Path, help='Read-only hash verification of an existing bundle; no services or models')
    args = parser.parse_args()
    print(json.dumps(run(args.output) if args.output else verify_bundle(args.verify.resolve()), ensure_ascii=False))
