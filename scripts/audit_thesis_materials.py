"""Read-only provenance of replay reports and fixed-decision live records."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from scripts.diagnostic_review import check as check_review
from src.probe.protocol import raw_hash


def observation_key(raw):
    if raw.get('raw_hash') != raw_hash(raw.get('payload')):
        raise ValueError('invalid payload hash')
    # A new ledger ID does not create a new observation.
    return hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def audit_materials(reviews, mechanism_summary, fixture, output):
    reviews, mechanism_summary, fixture, output = map(Path, (reviews, mechanism_summary, fixture, output))
    output.mkdir(parents=True, exist_ok=False)
    hashes, issues = {}, []
    def read(path):
        hashes[str(path.resolve())] = hashlib.sha256(path.read_bytes()).hexdigest()
        return json.loads(path.read_text(encoding='utf-8-sig'))
    def bound(path, expected):
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        hashes[str(path.resolve())] = actual
        if actual != expected:
            raise ValueError('bound source hash changed: ' + path.name)
    saved = read(fixture)
    root = Path(saved['source'])
    for name, expected in saved['source_files_sha256'].items():
        bound(root / name, expected)
    originals = read(root / 'evidence.json')
    origin = {(r['case'], r['evidence_id']): observation_key(r['raw']) for r in originals}
    fixture_keys = set()
    for case, rows in saved['cases'].items():
        for row in rows:
            key = observation_key(row['raw'])
            fixture_keys.add(key)
            if origin.get(('controller-' + case, row['evidence_id'])) != key:
                issues.append('fixture differs from original: ' + case + '/' + row['evidence_id'])
    reports, replay_keys, ledger_ids = [], set(), set()
    for directory in sorted(reviews.glob('sample-*')):
        row = {'review': str(directory), 'issues': [], 'status': 'invalid', 'observations': []}
        reports.append(row)
        try:
            audit = read(directory / 'source-audit.json')
            packet = read(directory / 'review-packet.json')
            read(directory / 'manual-review.json')
            review = check_review(directory)
            row.update(status=review['review_status'], mechanical_status=review['mechanical_review']['mechanical_status'])
            for path, expected in audit['source_hashes'].items():
                bound(Path(path), expected)
            sources = [Path(p) for p in audit['source_hashes'] if Path(p).name == 'output-audit.json']
            if len(sources) != 1:
                raise ValueError('expected one replay source')
            source = read(sources[0])
            case, group, count = source['case'], source['group'], source['evidence_count']
            row.update(source=str(sources[0]), case=case, group=group, evidence_count=count, mode=source['mode'])
            if (source['mode'] != 'historical_fixed_decision_api_check' or source.get('model_calls') != 0
                    or source.get('new_observations') != 0 or source.get('autonomous_model_verified') is not False):
                row['issues'].append('unexpected replay mode or claims')
            if (type(count) is not int or count not in (1, 2, 3)
                    or source['raw_returns'] != [item['raw'] for item in saved['cases'][case]][:count]):
                row['issues'].append('replay differs from original evidence prefix')
            if packet['report'] != source['refreshed']['report'] or audit['case'] != case:
                row['issues'].append('review report/case differs from replay')
            diagnosis = {k: v for k, v in source['refreshed']['diagnosis'].items()
                         if k not in {'mechanism_config', 'mechanisms'}}
            if packet['diagnosis'] != diagnosis:
                row['issues'].append('review diagnosis differs from replay')
            for raw in source['raw_returns']:
                key = observation_key(raw)
                replay_keys.add(key)
                row['observations'].append(key)
            for raw in packet['evidence'].values():
                if observation_key(raw) not in row['observations']:
                    row['issues'].append('review evidence not from this replay')
            ids = [item['evidence_id'] for item in source['ledger']['evidence']]
            if len(ids) != count or len(ids) != len(set(ids)):
                row['issues'].append('replay ledger count/ids inconsistent')
            row['ledger_ids'] = ids
            ledger_ids.update(ids)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            row['issues'].append('lineage unavailable: ' + type(exc).__name__)
    combinations = Counter((r.get('case'), r.get('group'), r.get('evidence_count')) for r in reports)
    for case in saved['cases']:
        for group in ('G00', 'G10', 'G01', 'G11'):
            for count in (1, 2, 3):
                if combinations[(case, group, count)] != 1:
                    issues.append('missing/duplicate replay: ' + str((case, group, count)))
    summary = read(mechanism_summary)
    for path, expected in summary['source_sha256'].items():
        bound(Path(path), expected)
    if not summary.get('passed') or not summary.get('source_unchanged'):
        issues.append('mechanism summary not accepted')
    mechanisms, mechanism_keys = [], set()
    for run in summary['runs']:
        row = {k: run[k] for k in ('sample', 'case', 'group', 'mode')}
        row.update(issues=[], observations=[])
        mechanisms.append(row)
        try:
            if run['mode'] != 'fixed_decision_live_probe_history':
                row['issues'].append('unexpected mechanism mode')
            if run.get('issues') or run.get('behavior_status') != 'passed':
                row['issues'].append('mechanism row audit not accepted')
            paths = [Path(p) for p in summary['source_sha256']
                     if Path(p).parent.name == run['sample'] and Path(p).name == 'events.json']
            if len(paths) != 1:
                raise ValueError('expected one event source')
            events = read(paths[0])
            for event in events:
                if event.get('type') == 'evidence':
                    raw = read(paths[0].parent / 'evidence' / (event['evidence_id'] + '.json'))
                    if raw.get('target_id') != event.get('target_id') or raw.get('operation') != event.get('kind'):
                        row['issues'].append('event target/operation differs from evidence')
                    key = observation_key(raw)
                    mechanism_keys.add(key)
                    row['observations'].append(key)
            if not row['observations']:
                row['issues'].append('no live evidence artifacts')
        except (OSError, ValueError, KeyError, TypeError) as exc:
            row['issues'].append('lineage unavailable: ' + type(exc).__name__)
    unchanged = all(Path(p).is_file() and hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p, h in hashes.items())
    result = {'report_rows': reports, 'mechanism_rows': mechanisms, 'issues': issues,
        'counts': {'review_packets': len(reports), 'replay_ledger_ids': len(ledger_ids),
            'replay_original_observations': len(replay_keys), 'fixture_original_observations': len(fixture_keys),
            'mechanism_runs': len(mechanisms), 'mechanism_original_observations': len(mechanism_keys),
            'shared_observations_between_batches': len(replay_keys & mechanism_keys)},
        'review_status_counts': dict(Counter(r['status'] for r in reports)),
        'source_sha256': hashes, 'source_unchanged': unchanged,
        'independent_fault_trials': None, 'diagnostic_accuracy': None,
        'new_model_calls': 0, 'new_observations': 0, 'autonomous_effect_verified': False,
        'passed': unchanged and bool(reports) and bool(mechanisms) and not issues
            and not any(r['issues'] for r in reports + mechanisms)}
    (output / 'lineage.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 论文材料来源核对', '', '## 数量口径', '']
    lines += ['- ' + k + ': ' + str(v) for k, v in result['counts'].items()]
    lines += ['', '## 报告审核包到历史证据', '', '| 审核包 | 场景 | 组 | 证据档 | 审核状态 | 缺口数 |',
              '| --- | --- | --- | --- | --- | --- |']
    lines += ['| ' + ' | '.join(str(v) for v in [Path(r['review']).name, r.get('case'), r.get('group'),
              r.get('evidence_count'), r['status'], len(r['issues'])]) + ' |' for r in reports]
    lines += ['', '报告重放用于输出/裁决/刷新与审核记录；固定决策现场用于机制执行接线。',
        '两批均不能独立证明自主模型效果；原始观测数量也不等于独立故障试验数量。',
        '缺真实自主验收、人工语义审核与正式四组效果比较，不生成准确率。',
        '来源核对通过：' + str(result['passed'])]
    (output / 'lineage.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reviews', type=Path, required=True)
    parser.add_argument('--mechanism-summary', type=Path, required=True)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit_materials(args.reviews, args.mechanism_summary, args.fixture, args.output)
    print(json.dumps({'passed': result['passed'], **result['counts']}))
    raise SystemExit(0 if result['passed'] else 1)
