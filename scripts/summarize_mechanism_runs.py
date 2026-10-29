"""Summarize fixed-decision historical runs; never grade diagnostic correctness."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

GROUPS = {'G00': (False, False), 'G10': (True, False), 'G01': (False, True), 'G11': (True, True)}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(source, audits, output):
    source, audits, output = Path(source), Path(audits), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    hashes = {}
    def read(path):
        hashes[str(path.resolve())] = digest(path)
        return json.loads(path.read_text(encoding='utf-8'))
    manifest_path = source / 'live-mechanism-groups.json'
    manifest = read(manifest_path) if manifest_path.exists() else []
    listed = {'mechanisms-' + item['case'] + '-' + item['group'] for item in manifest}
    for directory in sorted(source.glob('mechanisms-*')):
        if directory.is_dir() and directory.name not in listed:
            case, group = directory.name.removeprefix('mechanisms-').rsplit('-', 1)
            manifest.append({'case': case, 'group': group, 'unlisted': True})
    rows = []
    for item in manifest:
        case, group = item['case'], item['group']
        sample = 'mechanisms-' + case + '-' + group
        directory = source / sample
        row = {'sample': sample, 'case': case, 'group': group, 'mode': 'fixed_decision_live_probe_history',
            'issues': [], 'workflow_status': 'incomplete', 'reported_kind': None,
            'diagnosis_review': 'pending', 'citation_review': 'pending', 'recommendation_review': 'pending',
            'behavior_status': 'not_assessed', 'tool_attempts': None, 'successful_tools': None,
            'failed_tools': None, 'tool_counts': {}, 'dependency_objects': {}, 'executor_steps': None,
            'timed_tool_calls': 0, 'recorded_tool_elapsed_ms': None, 'total_duration_ms': None,
            'model_cost_cny': None, 'cost_status': 'no_model_ledger_in_this_fixed_decision_run',
            'protection_changes': None, 'contradiction_changes': None, 'blocked_events': None}
        rows.append(row)
        if item.get('unlisted'):
            row['issues'].append('run directory missing from successful manifest')
        try:
            events = read(directory / 'events.json')
            complete = next((e for e in reversed(events) if e.get('type') == 'complete'), {})
            diagnosis = complete.get('diagnosis') or {}
            row['workflow_status'] = 'completed' if (str(complete.get('response') or '').strip()
                and not any(e.get('type') == 'error' for e in events)) else 'incomplete'
            row['reported_kind'] = diagnosis.get('kind')
            audit = read(audits / (sample + '.json'))
            if set(audit['source_sha256']) != {'mechanism_trace.json', 'checkpoints.sqlite'}:
                row['issues'].append('behavior audit missing required source hashes')
            for name, expected in audit['source_sha256'].items():
                path = directory / name
                hashes[str(path.resolve())] = digest(path)
                if hashes[str(path.resolve())] != expected:
                    row['issues'].append('historical source hash changed: ' + name)
            calls = read(directory / 'calls.json')
            original = read(directory / 'mechanism_trace.json')
            before = read(directory / 'knowledge-conditions-before.json')
            after = read(directory / 'knowledge-conditions-after.json')
            config = diagnosis.get('mechanism_config') or {}
            if group not in GROUPS or (config.get('hypothesis_protection'), config.get('contradiction_trigger')) != GROUPS.get(group):
                row['issues'].append('group/config mismatch')
            row['manifest_config_present'] = 'config' in item
            if (('config' in item and config != item['config']) or config != original['audit']['expected_config']
                    or config != original['audit']['actual_config']):
                row['issues'].append('saved configurations disagree')
            if complete.get('thread_id') != item.get('thread_id') or complete.get('thread_id') != original['thread_id']:
                row['issues'].append('thread mismatch')
            if (not before.get('passed') or not after.get('passed') or not before.get('actual_sha256')
                    or before.get('actual_sha256') != after.get('actual_sha256')
                    or before.get('expected_sha256') != before.get('actual_sha256')
                    or after.get('expected_sha256') != after.get('actual_sha256')):
                row['issues'].append('knowledge conditions not consistent')
            row['knowledge_sha256'] = before.get('actual_sha256')
            row['remote_index_verified'] = before.get('remote_index_verified') is True and after.get('remote_index_verified') is True
            steps = [e.get('current_step') for e in events if e.get('type') == 'step_complete']
            if steps != original['executed_steps']:
                row['issues'].append('completed steps disagree with trace')
            row['executor_steps'] = len(steps)
            records = audit['execution_records']
            row['tool_attempts'] = len(records)
            row['successful_tools'] = sum(e.get('status') == 'success' for e in records)
            row['failed_tools'] = len(records) - row['successful_tools']
            row['tool_counts'] = dict(Counter(e.get('tool', '<missing>') for e in records))
            row['dependency_objects'] = dict(Counter(e.get('arguments', {}).get('dependency', '<missing>')
                for e in records if e.get('tool') == 'probe_dependency_probe'))
            if [e.get('tool') for e in records if e.get('status') == 'success'] != [c['tool'] for c in calls]:
                row['issues'].append('tool execution records disagree with successful calls')
            durations = []
            for record in records:
                value = record.get('elapsed_ms')
                if value is None:
                    continue
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    row['issues'].append('invalid tool elapsed_ms')
                else:
                    durations.append(value)
            row['timed_tool_calls'] = len(durations)
            row['recorded_tool_elapsed_ms'] = round(sum(durations), 3) if durations else None
            behavior = audit['behavior']
            row['behavior_status'] = behavior['status']
            if (audit.get('sample') != sample or not audit.get('source_unchanged')
                    or not audit.get('decision_boundaries_matched') or behavior['status'] != 'passed'):
                row['issues'].append('behavior audit not accepted')
            row.update(protection_changes=behavior.get('executed_changes', {}).get('protection'),
                contradiction_changes=behavior.get('executed_changes', {}).get('contradiction'),
                blocked_events=behavior.get('blocked_events'), opportunities=behavior.get('opportunities'),
                candidate_correctness=behavior.get('candidate_correctness'))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            row['issues'].append('artifact unavailable or invalid: ' + type(exc).__name__)
    counts = Counter((r['case'], r['group']) for r in rows)
    issues = []
    if not rows:
        issues.append('empty manifest')
    if not manifest_path.exists():
        issues.append('successful manifest missing')
    for case in {r['case'] for r in rows}:
        for group in GROUPS:
            if counts[(case, group)] != 1:
                issues.append('expected one run: ' + case + '/' + group)
    if len({r.get('knowledge_sha256') for r in rows}) != 1:
        issues.append('cross-run knowledge conditions differ')
    for row in rows:
        baseline = next((r for r in rows if r['case'] == row['case'] and r['group'] == 'G00'), None)
        comparable = (baseline and not issues and not row['issues'] and not baseline['issues']
                      and row['workflow_status'] == baseline['workflow_status'] == 'completed'
                      and counts[(row['case'], 'G00')] == counts[(row['case'], row['group'])] == 1)
        row['vs_G00'] = {'tool_attempt_delta': row['tool_attempts'] - baseline['tool_attempts'] if comparable else None,
            'executor_step_delta': row['executor_steps'] - baseline['executor_steps'] if comparable else None,
            'recorded_tool_elapsed_delta_ms': round(row['recorded_tool_elapsed_ms'] - baseline['recorded_tool_elapsed_ms'], 3)
                if comparable and row['recorded_tool_elapsed_ms'] is not None and baseline['recorded_tool_elapsed_ms'] is not None else None,
            'causal_overhead_estimated': False}
    unchanged = all(Path(path).exists() and digest(Path(path)) == value for path, value in hashes.items())
    result = {'runs': rows, 'run_count': len(rows), 'issues': issues, 'source_sha256': hashes,
        'source_unchanged': unchanged, 'workflow_counts': dict(Counter(r['workflow_status'] for r in rows)),
        'reported_kind_counts': dict(Counter(r['reported_kind'] or 'missing' for r in rows)),
        'human_reviewed': 0, 'model_calls_this_summary': 0, 'new_observations': 0,
        'diagnostic_accuracy': None, 'mechanism_effectiveness_verified': False,
        'passed': bool(rows) and unchanged and not issues and not any(r['issues'] for r in rows)}
    (output / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 历史四组逐场汇总', '', '固定决策历史；人工全部待审。耗时仅为已记录工具耗时之和，不是完整诊断时间或因果开销。', '',
        '| 场景 | 组 | 流程 | 报告类型 | 工具次数 | 计时覆盖 | 工具耗时ms | 对G00工具差 | 保护改查 | 矛盾改查 | 阻塞 |',
        '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for r in rows:
        lines.append('| ' + ' | '.join(str(v) for v in [r['case'], r['group'], r['workflow_status'], r['reported_kind'],
            r['tool_attempts'], str(r['timed_tool_calls']) + '/' + str(r['tool_attempts']), r['recorded_tool_elapsed_ms'],
            r['vs_G00']['tool_attempt_delta'], r['protection_changes'], r['contradiction_changes'], r['blocked_events']]) + ' |')
    lines += ['', '源文件未改变：' + str(unchanged) + '；汇总一致性通过：' + str(result['passed']),
        '失败与缺件详见 summary.json；待审不计正确，缺失费用不填零。']
    (output / 'summary.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--audits', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.source, args.audits, args.output)
    print(json.dumps({k: result[k] for k in ('run_count', 'passed', 'source_unchanged', 'human_reviewed')}))
    raise SystemExit(0 if result['passed'] else 1)
