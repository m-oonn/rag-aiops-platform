"""Audit existing trusted local checkpoints without services, tools or model calls."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
from unittest.mock import patch

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from scripts.mechanism_behavior import audit_behavior, behavior_snapshot
from src.agent.aiops.strategies.investigation import execution_checks
from src.settings import settings


def verify_history(source, output):
    output.mkdir(parents=True, exist_ok=False)
    summaries = []
    directories = ([source] if (source / 'mechanism_trace.json').is_file()
                   and (source / 'checkpoints.sqlite').is_file()
                   else sorted(source.glob('mechanisms-*')))
    for directory in directories:
        paths = [directory / 'mechanism_trace.json', directory / 'checkpoints.sqlite']
        fingerprint = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
        before = {p.name: fingerprint(p) for p in paths}
        original = json.loads(paths[0].read_text(encoding='utf-8'))
        legacy = audit_behavior(original['decisions'], original['executed_steps'])
        target_id = settings.PROBE_TARGET_ID
        evaluation_record = directory / 'evaluation-record.json'
        if evaluation_record.is_file():
            target_id = json.loads(evaluation_record.read_text(encoding='utf-8'))['config']['target_id']
        connection = sqlite3.connect(paths[1].resolve().as_uri() + '?mode=ro', uri=True)
        try:
            serialized = connection.execute(
                'SELECT type, checkpoint FROM checkpoints WHERE thread_id=? AND checkpoint_ns=? ORDER BY checkpoint_id',
                (original['thread_id'], '')).fetchall()
        finally:
            connection.close()
        serde = JsonPlusSerializer()
        checkpoints = [serde.loads_typed((kind, data)) for kind, data in serialized]
        snapshots, state = [], {}
        with patch.object(settings, 'PROBE_TARGET_ID', target_id):
            for checkpoint in checkpoints:
                state = checkpoint['channel_values']
                if not state.get('investigation_memory'):
                    continue
                # Match the saved decision boundary, excluding intervening executor states.
                if len(snapshots) < len(original['decisions']):
                    old = original['decisions'][len(snapshots)]
                    saved_context = old.get('behavior_context') or {}
                    candidate = behavior_snapshot({**state, '_probe_check_contract_version':
                        saved_context.get('probe_check_contract_version', 2)}, checkpoint['ts'])
                    if all(candidate[key] == old[key] for key in ('step', 'plan', 'tracking', 'next_tools')):
                        snapshots.append(candidate)
            executions = execution_checks(state)
            executed = [name for name, _ in state.get('past_steps', [])]
            behavior = audit_behavior(snapshots, executed, executions)
        complete = len(snapshots) == len(original['decisions']) and executed == original['executed_steps']
        unchanged = before == {p.name: fingerprint(p) for p in paths}
        result = {'sample': directory.name, 'source_sha256': before, 'source_unchanged': unchanged,
            'decision_boundaries_matched': complete, 'legacy_status': legacy['status'], 'behavior': behavior,
            'decisions': snapshots, 'execution_records': executions}
        (output / (directory.name + '.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        summaries.append({k: v for k, v in result.items() if k not in {'decisions', 'execution_records'}})
    summary = {'samples': len(summaries), 'results': summaries, 'model_calls': 0, 'new_observations': 0,
        'mechanism_effectiveness_verified': False,
        'passed': bool(summaries) and all(r['source_unchanged'] and r['decision_boundaries_matched']
            and r['behavior']['status'] == 'passed' for r in summaries)}
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = verify_history(args.source, args.output)
    print(json.dumps({k: v for k, v in result.items() if k != 'results'}))
    raise SystemExit(0 if result['passed'] else 1)
