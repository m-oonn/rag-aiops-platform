"""Replay every recorded round's final proposal through today's decision engine.

Read-only, zero model requests: each round directory holds the checkpoints of a
real paid diagnosis, so feeding the recorded `model_suggestion` back into
`decide_from_evidence` re-runs the *current* code against evidence that was
actually collected.  That makes the recorded rounds a regression corpus: a
round which produced `confirmed_cause` when it was recorded must still produce
`confirmed_cause` today.

Usage:
    python scripts/replay_recorded_rounds.py [--root runtime] [--min-round 36]

Writes `<root>/replay-all-rounds.json` and prints the summary.  The pytest
suite calls :func:`sweep` directly (`tests/test_recorded_round_replay.py`).
"""
import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer  # noqa: E402

from src.agent.aiops.strategies.investigation import (  # noqa: E402
    InvestigationProposal, decide_from_evidence, evidence_index,
)
from src.settings import settings  # noqa: E402

SER = JsonPlusSerializer()
# Rounds whose recorded failure was a logic defect, and which the current rules
# must therefore accept.  Any other failing round is a model-side failure that
# today's rules are expected to keep refusing.
FIXED_BY_CURRENT_RULES = ('039', '049')


def _readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)


def load_round(directory):
    """Load the pieces needed to replay one recorded round, or None."""
    directory = Path(directory).resolve()
    checkpoints, environment = directory / 'product/checkpoints.sqlite', directory / 'environment.json'
    if not checkpoints.exists() or not environment.exists():
        return None
    target = json.loads(environment.read_text(encoding='utf-8')).get('target_id')
    if not target:
        return None
    try:
        con = _readonly(checkpoints)
        rows = con.execute(
            "select checkpoint_id, type, checkpoint from checkpoints where checkpoint_ns = '' "
            'order by checkpoint_id').fetchall()
        con.close()
    except sqlite3.Error:
        return None
    if not rows:
        return None
    recorded_at = None
    runs = directory / 'product/runs.sqlite'
    if runs.exists():
        try:
            con = _readonly(runs)
            try:
                row = con.execute(
                    'select created_at, updated_at from aiops_runs '
                    'order by id desc limit 1').fetchone()
            except sqlite3.Error:
                row = None
            con.close()
        except sqlite3.Error:
            row = None
        if row and (row[1] or row[0]):
            recorded_at = datetime.fromisoformat(str(row[1] or row[0])).replace(tzinfo=timezone.utc)
    return {'target': target, 'rows': rows, 'recorded_at': recorded_at}


def replay(loaded, suggestion):
    checkpoint_id, typ, blob = loaded['rows'][-1]
    values = SER.loads_typed((typ, blob))['channel_values']
    state = {k: v for k, v in values.items() if k not in ('diagnosis', 'response')}
    recorded_kind = (values.get('diagnosis') or {}).get('kind')
    now = loaded['recorded_at'] or datetime.now(timezone.utc)
    with patch.object(settings, 'PROBE_TARGET_ID', loaded['target']):
        records = evidence_index(state, now=now)
        update = decide_from_evidence(
            state, InvestigationProposal.model_validate(suggestion), records)
    diagnosed = update.get('diagnosis') or {}
    memory = update.get('investigation_memory') or {}
    return {
        'checkpoint_id': checkpoint_id,
        'recorded_kind': recorded_kind or None,
        'replayed_kind': diagnosed.get('kind'),
        'replayed_code': diagnosed.get('root_cause_code'),
        'replayed_plan_len': len(update.get('plan') or []),
        'recorded_suggestion_level': (suggestion or {}).get('conclusion_level'),
        'recorded_suggestion_code': (suggestion or {}).get('root_cause_code'),
        'blocked_reason': (memory.get('blocked_reason') or '')[:120],
    }


def _rounds(root, min_round):
    for directory in sorted(Path(root).glob('aiops-goal-0*')):
        digits = directory.name.rsplit('-', 1)[-1]
        if digits.isdigit() and int(digits) >= min_round:
            yield digits, directory


def sweep(root='runtime', min_round=36):
    """Replay every recorded round in `root`; returns {'summary': …, 'rounds': …}."""
    rounds = []
    for digits, directory in _rounds(root, min_round):
        loaded = load_round(directory)
        if not loaded:
            continue
        try:
            values = SER.loads_typed((loaded['rows'][-1][1], loaded['rows'][-1][2]))['channel_values']
            suggestion = (values.get('investigation_memory') or {}).get('model_suggestion')
        except Exception as exc:  # pragma: no cover - corrupt checkpoint
            rounds.append({'round': digits, 'error': f'{type(exc).__name__}: {exc}'[:200]})
            continue
        if not suggestion:
            continue
        try:
            rounds.append({'round': digits, **replay(loaded, dict(suggestion))})
        except Exception as exc:  # keep the sweep going; report per round
            rounds.append({'round': digits, 'error': f'{type(exc).__name__}: {exc}'[:200]})
    usable = [r for r in rounds if 'replayed_kind' in r]
    passed = 'confirmed_cause'
    summary = {
        'rounds_examined': len(rounds),
        'rounds_replayed': len(usable),
        'recorded_confirmed': sum(1 for r in usable if r['recorded_kind'] == passed),
        'replayed_confirmed': sum(1 for r in usable if r['replayed_kind'] == passed),
        # A round that passed when recorded must not start failing: that is a
        # code regression, and it is the one thing this corpus can prove.
        'regressed': [r['round'] for r in usable
                      if r['recorded_kind'] == passed and r['replayed_kind'] != passed],
        # A round that failed for a logic defect must be accepted by today's rules.
        'fixed_by_current_code': [r['round'] for r in usable
                                  if r['recorded_kind'] != passed
                                  and r['replayed_kind'] == passed],
        'still_blocked': [r['round'] for r in usable
                          if r['recorded_kind'] != passed and r['replayed_kind'] != passed],
        'errors': [r['round'] for r in rounds if 'error' in r],
    }
    return {'summary': summary, 'rounds': rounds}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='runtime')
    parser.add_argument('--min-round', type=int, default=36)
    parser.add_argument('--output', default=None)
    args = parser.parse_args(argv)
    result = sweep(args.root, args.min_round)
    target = Path(args.output) if args.output else Path(args.root) / 'replay-all-rounds.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(result['summary'], ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
