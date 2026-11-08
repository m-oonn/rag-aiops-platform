"""Read-only: verify that every finished test environment is cleanly stopped.

A round's environment is only acceptable when it reports
``recovery=three_business_endpoints_200``, ports released, owned processes
stopped, no ``cleanup_errors``, and zero model calls from the environment
itself.  Rounds created before this check existed are listed explicitly;
everything else is discovered.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = ('three_business_endpoints_200',)


def environments():
    found = sorted(p for p in (ROOT / 'runtime').glob('aiops-goal-*')
                   if (p / 'environment.json').exists())
    return found


def main():
    problems = []
    for directory in environments():
        body = json.loads((directory / 'environment.json').read_text(encoding='utf-8'))
        status = body.get('status')
        if status in {'ready', 'stopping'}:
            # still open: report but do not treat as a failure of a finished round
            print(f'{directory.name:34} OPEN  {status}')
            continue
        ok = (body.get('recovery') in EXPECTED
              and body.get('ports_released') is True
              and body.get('owned_processes_stopped') is True
              and not (body.get('cleanup_errors') or [])
              and body.get('environment_model_calls') in (0, None))
        line = (f"{directory.name:34} {status:8} {str(body.get('recovery')):32} "
                f"ports={body.get('ports_released')} proc={body.get('owned_processes_stopped')} "
                f"cleanup={len(body.get('cleanup_errors') or [])} "
                f"model_calls={body.get('environment_model_calls')}")
        print(line)
        if status != 'stopped' or not ok:
            problems.append(directory.name)
    if problems:
        print('NOT CLEAN:', problems)
        raise SystemExit(1)
    print('all finished environments are cleanly stopped')


if __name__ == '__main__':
    main()
