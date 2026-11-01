"""Free historical rule checks using saved Probe evidence, without model/tool calls."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def verify(fixture, output):
    from src.agent.aiops.strategies import investigation as inv
    from src.probe.evidence import validate_evidence

    fixture, output = Path(fixture).resolve(strict=True), Path(output).resolve()
    if output.exists() or output == fixture or fixture in output.parents:
        raise ValueError('output must be a new directory')
    original = fixture.read_bytes()
    saved = json.loads(original.decode('utf-8-sig'))
    results = []
    for case, rows in saved['cases'].items():
        when = max(datetime.fromisoformat(row['raw']['collected_at'].replace('Z', '+00:00')) for row in rows)
        target_id = rows[0]['raw']['target_id']
        if target_id != inv.settings.PROBE_TARGET_ID:
            raise ValueError('historical target differs from configured target')
        for row in rows:
            validate_evidence(row['raw'], target_id=target_id, now=when)
        for count in (1, 2, 3):
            for claim in ('downstream', 'configuration', 'unrelated'):
                for protection, trigger in ((False, False), (True, False), (False, True), (True, True)):
                    selected = rows[:count]
                    state = {
                        'input': '本地应用入口返回503，请排查', 'plan': [],
                        'target_resolution': {'status': 'resolved', 'target_id': target_id,
                            'allowed_dependencies': ['localapp', 'downstream'], 'allowed_services': ['localapp']},
                        'investigation_config': {'hypothesis_protection': protection, 'contradiction_trigger': trigger,
                            'protection_steps': 2},
                        'raw_evidence': [('historical tool return', json.dumps(row['raw'], ensure_ascii=False)) for row in selected],
                        'evidence_events': [{'evidence_id': row['evidence_id'], 'kind': row['raw']['operation'],
                            **{key: row['raw'][key] for key in ('target_id', 'collected_at', 'raw_hash')}} for row in selected],
                    }
                    citations = [inv.Citation(evidence_id=rows[0]['evidence_id'], quote='temporarily unavailable')]
                    if count == 3:
                        # Even a real log citation cannot validate arbitrary causal text.
                        citations.append(inv.Citation(evidence_id=rows[2]['evidence_id'],
                            quote='upstream connection failed' if case == 'downstream_unreachable'
                            else 'invalid max_attempts configuration'))
                    condition = inv.ObservationCondition(operation='dependency_probe', object_name='downstream', field='tcp', expected='failed')
                    cause = {'downstream': '下游进程崩溃导致入口503',
                             'configuration': 'max_attempts配置解析失败导致入口503',
                             'unrelated': '数据库磁盘损坏导致入口503'}[claim]
                    proposed = inv.InvestigationDecision(hypothesis=cause, root_cause=cause,
                        hypothesis_condition=condition if claim == 'downstream' else None,
                        outcome='root_cause', conclusion_level='confirmed_cause', scope='localapp入口与下游',
                        supporting_evidence=citations,
                        alternatives=[inv.Alternative(explanation='dependency_probe/localapp: tcp == "failed"', status='excluded',
                            claim_type='observed_condition',
                            condition=inv.ObservationCondition(operation='dependency_probe', object_name='localapp', field='tcp', expected='failed'),
                            evidence=[inv.Citation(evidence_id=rows[0]['evidence_id'], quote='ok')])])
                    before = proposed.model_dump()
                    records = inv.evidence_index(state, now=when)
                    if len(records) != count:
                        raise ValueError('historical records failed validation')
                    update = inv.decide_from_evidence(state, proposed, records)
                    diagnosis = update['diagnosis']
                    findings = {(item['code'], item['scope'].get('dependency')) for item in diagnosis['observed_findings']}
                    expected = {('dependency_http_failed', 'localapp')}
                    if count >= 2 and case == 'downstream_unreachable':
                        expected.add(('dependency_tcp_failed', 'downstream'))
                    if diagnosis['kind'] != 'localized_fault' or findings != expected:
                        raise AssertionError(f'{case}/{count}/{claim}: unsupported conclusion or incorrect fault layer: {diagnosis}')
                    if cause in diagnosis['conclusion'] or cause in update['response']:
                        raise AssertionError('unverified causal text leaked into the final report')
                    if update['investigation_memory']['model_suggestion'] != before or proposed.model_dump() != before:
                        raise AssertionError('original proposal was not preserved')
                    results.append({'case': case, 'evidence_count': count, 'claim': claim,
                        'group': f'G{int(protection)}{int(trigger)}',
                        'historical_validation_time': when.isoformat(),
                        'evidence_ids': list(records), 'diagnosis': diagnosis, 'response': update['response'],
                        'proposal': before})
    if fixture.read_bytes() != original:
        raise ValueError('source fixture changed during replay')
    report = {'mode': 'historical_rule_boundary_check', 'model_calls': 0, 'new_observations': 0,
        'autonomous_model_success_proven': False, 'checked_at': datetime.now(timezone.utc).isoformat(),
        'fixture_sha256': hashlib.sha256(original).hexdigest(), 'source': saved['source'],
        'source_files_sha256': saved['source_files_sha256'], 'source_fixture_unchanged': True,
        'original_runtime_revalidated': False, 'checks': len(results), 'results': results}
    output.mkdir(parents=True, exist_ok=False)
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, default=ROOT / 'tests/fixtures/matching503-probe-20261024.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime' / ('matching503-boundaries-' + uuid4().hex))
    args = parser.parse_args()
    result = verify(args.fixture, args.output)
    print(json.dumps({key: result[key] for key in ('mode', 'checks', 'model_calls', 'source_fixture_unchanged')}, ensure_ascii=False))
    print('OUTPUT=' + str(args.output))
