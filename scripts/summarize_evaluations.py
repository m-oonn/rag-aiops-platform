"""Read-only engineering comparison of new autonomous evaluation artifacts."""
import argparse
from collections import Counter
import json
from datetime import datetime
from pathlib import Path

from scripts.evaluation_record import audit_evaluation, validate_timing


def audit_suite_budget(suite, rows):
    """Verify the ordered ledger chain and equal caps, independently of child success labels."""
    from scripts.evaluate_windows_probe import read_cost_ledger
    if suite.get('version', 1) >= 4:
        import hashlib
        from scripts.verify_windows_local_faults import symptom_text
        expected_symptom = hashlib.sha256(symptom_text(suite['symptom_profile']).encode('utf-8')).hexdigest()
        if suite.get('symptom_sha256') != expected_symptom:
            raise ValueError('suite symptom profile hash differs')
    previous_path = Path(suite['previous_cost']).resolve()
    previous = read_cost_ledger(previous_path)
    if suite['inherited_requests'] != len(previous['requests']):
        raise ValueError('suite inherited request count differs')
    import math
    reservation = suite['run_budget_cny']
    if reservation is not None and (type(reservation) not in (int, float)
            or not math.isfinite(reservation) or reservation <= 0
            or suite['budget_limit_cny'] - previous['reserved_cny'] < len(suite['order']) * reservation):
        raise ValueError('unequal suite reservation allowance')
    cap, per_run = suite['max_model_requests'], suite['run_max_model_requests']
    unpriced = suite['allow_unpriced_model']
    if not unpriced and reservation is None and per_run is None:
        raise ValueError('priced suite missing reservation cap')
    for value in (cap, per_run):
        if value is not None and (type(value) is not int or value <= 0):
            raise ValueError('invalid suite request cap')
    if unpriced and (cap is None or per_run is None):
        raise ValueError('unpriced suite missing request caps')
    if per_run is not None and (cap is None or cap - len(previous['requests']) < len(suite['order']) * per_run):
        raise ValueError('unequal suite request allowance')
    by_directory = {row['directory']: row for row in rows}
    for item, result in zip(suite['order'], suite['results']):
        directory = Path(result['result_dir']).resolve()
        row = by_directory[str(directory)]
        if (row['case'], row['group']) != (item['case'], item['group']):
            raise ValueError('suite execution order differs')
        record = json.loads((directory / 'evaluation-record.json').read_text(encoding='utf-8'))
        config = record['config']
        if suite.get('version', 1) >= 4 and config.get('symptom_sha256') != suite['symptom_sha256']:
            raise ValueError('suite child symptom differs')
        if Path(config['previous_cost']).resolve() != previous_path:
            raise ValueError('suite ledger chain skipped or reused a child')
        current = read_cost_ledger(directory / 'cost.json')
        if current['requests'][:len(previous['requests'])] != previous['requests']:
            raise ValueError('suite ledger prefix changed')
        if (current['limit_cny'] != suite['budget_limit_cny']
                or config.get('run_budget_cny') != suite['run_budget_cny']):
            raise ValueError('suite reservation limits differ')
        if unpriced or cap is not None or per_run is not None:
            for key in ('allow_unpriced_model', 'max_model_requests', 'run_max_model_requests', 'max_output_tokens'):
                if config.get(key) != suite[key]:
                    raise ValueError('suite child budget configuration differs: ' + key)
            if cap is not None and len(current['requests']) > cap:
                raise ValueError('suite cumulative request cap exceeded')
            if per_run is not None and len(current['requests']) - len(previous['requests']) > per_run:
                raise ValueError('suite per-run request cap exceeded')
        previous_path, previous = directory / 'cost.json', current


def summarize(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    directories = sorted({p.parent for name in ('summary.json', 'evaluation-record.json', 'cost.json')
        for p in source.rglob(name) if p.parent != output
        and ((p.parent / 'cost.json').exists() or (p.parent / 'evaluation-record.json').exists())})
    # Include controller attempts even when the child failed before writing summary.
    labels = {}
    invalid_attempts = []
    for path in source.rglob('model-attempt-*.json'):
        try:
            attempt = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(attempt, dict) or not isinstance(attempt.get('result_dir'), str):
                raise ValueError('invalid controller attempt')
        except (OSError, ValueError):
            invalid_attempts.append(str(path))
            continue
        directory = Path(attempt['result_dir']).resolve()
        if not directory.is_relative_to(source):
            raise ValueError('controller attempt outside source')
        directories.append(directory)
        if directory in labels:
            invalid_attempts.append(str(path))
        labels[directory] = attempt
    rows = []
    for directory in sorted(set(directories)):
        attempt = labels.get(directory, {})
        audit = audit_evaluation(directory)
        try:
            summary = json.loads((directory / 'summary.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            summary = {}
        behavior = (summary.get('mechanism_audit') or {}).get('behavior') or {}
        row = {'directory': str(directory), 'case': attempt.get('case', summary.get('scenario')),
            'group': attempt.get('mechanism_group', summary.get('mechanism_group')),
            'controller_case_verified': bool(attempt.get('case')),
            'audit': audit, 'diagnosis_review': 'pending', 'diagnostic_correctness_verified': False,
            'mechanism_behavior': {key: behavior.get(key) for key in (
                'status', 'opportunities', 'executed_changes', 'executed_checks', 'blocked_events', 'no_opportunity')},
            'vs_G00': None}
        if attempt and (attempt.get('status') != 'returned' or attempt.get('exit_code') != 0):
            audit['issues'].append('controller child not returned successfully')
            audit['passed'] = False
        if attempt:
            try:
                validate_timing(attempt)
                if attempt.get('mechanism_group') != summary.get('mechanism_group'):
                    raise ValueError('controller group differs')
            except (ValueError, TypeError, KeyError):
                audit['issues'].append('controller attempt timing or group invalid')
                audit['passed'] = False
        rows.append(row)
    issues = ['invalid or duplicate controller attempt: ' + p for p in invalid_attempts]
    for path in source.rglob('four-group-controller.json'):
        try:
            suite = json.loads(path.read_text(encoding='utf-8'))
            order, results = suite['order'], suite['results']
            expected = Counter((item['case'], item['group']) for item in order)
            resets = Counter((item['case'], item['group']) for item in suite['resets'])
            from scripts.verify_windows_local_faults import four_group_cases
            cases = four_group_cases(suite.get('suite', 'baseline-v1'))
            if suite.get('version', 1) >= 2 and suite.get('scenario_cases') != list(cases):
                raise ValueError('suite scenario cases differ from versioned protocol')
            run_count = len(cases) * 4
            expected_pairs = {(case, group) for case in cases
                for group in ('G00', 'G10', 'G01', 'G11')}
            for reset in suite['resets']:
                boundary = reset.get('observation_not_before')
                parsed = datetime.fromisoformat(str(boundary).replace('Z', '+00:00'))
                if parsed.tzinfo is None:
                    raise ValueError('reset observation boundary is not timezone-aware')
            if (suite.get('status') != 'completed' or suite.get('recovery') != 'normal_restored'
                    or not suite.get('ended_at') or len(results) != run_count or len(order) != run_count
                    or set(expected) != expected_pairs or any(n != 1 for n in expected.values())
                    or resets != expected
                    or any(result.get('status') != 'passed' for result in results)):
                raise ValueError('suite incomplete or not recovered')
            result_dirs = {str(Path(r['result_dir']).resolve()) for r in results}
            actual_dirs = {r['directory'] for r in rows if Path(r['directory']).is_relative_to(path.parent)}
            if len(result_dirs) != run_count or result_dirs != actual_dirs:
                raise ValueError('suite results differ from artifacts')
            boundaries = {(r['case'], r['group']): r['observation_not_before'] for r in suite['resets']}
            for row in rows:
                if row['directory'] in result_dirs and row['audit'].get('observation_not_before') != boundaries.get((row['case'], row['group'])):
                    raise ValueError('child observation boundary differs from controller reset')
            if suite.get('version', 1) >= 3:
                audit_suite_budget(suite, [row for row in rows if row['directory'] in result_dirs])
            import hashlib
            for name, expected_hash in suite['conditions_sha256'].items():
                condition = (path.parent / name).resolve()
                if (not condition.is_relative_to(path.parent.resolve())
                        or hashlib.sha256(condition.read_bytes()).hexdigest() != expected_hash):
                    raise ValueError('suite fixed conditions changed')
        except (OSError, ValueError, KeyError, TypeError):
            issues.append('four-group controller not accepted: ' + str(path))
    if not rows:
        issues.append('no evaluation artifacts')
    counts = Counter((r['case'], r['group']) for r in rows)
    for case in {r['case'] for r in rows}:
        subset = [r for r in rows if r['case'] == case]
        if any(counts[(case, g)] != 1 for g in ('G00', 'G10', 'G01', 'G11')) or len(subset) != 4:
            issues.append('expected one run per group: ' + str(case))
            continue
        baseline = next(r for r in subset if r['group'] == 'G00')
        if not all(r['audit']['passed'] for r in subset):
            issues.append('incomplete record set: ' + str(case))
            continue
        if not all(r['controller_case_verified'] for r in subset):
            issues.append('controller scenario mapping required: ' + str(case))
            continue
        if any(r['audit']['source_signature'] != baseline['audit']['source_signature']
                or r['audit']['comparison_config'] != baseline['audit']['comparison_config'] for r in subset):
            issues.append('source/configuration conditions differ: ' + str(case))
            continue
        for row in subset:
            current, base = row['audit'], baseline['audit']
            row['vs_G00'] = {
                'this_run_request_delta': current['this_run_cost']['requests'] - base['this_run_cost']['requests'],
                'this_run_reserved_cny_delta': current['this_run_cost']['reserved_cny'] - base['this_run_cost']['reserved_cny'],
                'run_model_duration_delta_ms': current['duration_ms'] - base['duration_ms'],
                'causal_overhead_estimated': False}
    result = {'runs': rows, 'issues': issues, 'passed': bool(rows) and not issues and all(r['audit']['passed'] for r in rows),
        'human_reviewed': 0, 'diagnostic_accuracy': None, 'model_calls_this_summary': 0,
        'scope': 'engineering comparison; not independent trials or diagnostic effect'}
    if issues:
        for row in rows:
            row['vs_G00'] = None
    output.mkdir(parents=True, exist_ok=False)
    (output / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.source, args.output)
    print(json.dumps({'passed': result['passed'], 'runs': len(result['runs']), 'human_reviewed': 0}))
    raise SystemExit(0 if result['passed'] else 1)
