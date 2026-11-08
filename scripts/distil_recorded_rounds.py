"""Build a distilled, committable replay corpus from the machine-local rounds.

The gate must run where `runtime/` does not exist (CI), so the replay material
has to live in the repository.  Only the channel values the decision logic
actually reads are kept, and the whole corpus is stored as one gzip blob so the
repository carries kilobytes rather than megabytes.
"""
import gzip
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

S = JsonPlusSerializer()
CORPUS = ROOT / 'tests' / 'data' / 'recorded-rounds.json.gz'
# Everything decide_from_evidence reads from the checkpoint; dropping any of
# the first four changes the replayed outcome (see runtime/shrink_state.py).
KEEP = ('raw_evidence', 'investigation_memory', 'evidence_events',
        'target_resolution', 'investigation_tools')


def round_dirs(root):
    for directory in sorted(Path(root).glob('aiops-goal-0*')):
        digits = directory.name.rsplit('-', 1)[-1]
        if digits.isdigit() and int(digits) >= 36:
            if (directory / 'product/checkpoints.sqlite').exists():
                yield digits, directory


def _readonly(path):
    """Read-only sqlite whose sort spill stays in memory (see replay script)."""
    con = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    con.execute('PRAGMA temp_store=MEMORY')
    return con


def scrub(value):
    """Return the state as JSON-round-trippable plain data.

    Deliberately does *not* rewrite the absolute paths inside evidence payloads:
    the decision logic compares those strings against each other (check-argument
    identity, observation scope keys), so rewriting them consistently is still
    enough to change the replayed outcome.  They only ever name this repository's
    own `runtime/` files, so keeping them is both harmless and necessary.
    """
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def distil(name, directory):
    con = _readonly(directory / 'product/checkpoints.sqlite')
    rows = con.execute(
        "select type, checkpoint from checkpoints where checkpoint_ns = '' "
        'order by checkpoint_id').fetchall()
    con.close()
    values = S.loads_typed(rows[-1])['channel_values']
    recorded_at = None
    runs = directory / 'product/runs.sqlite'
    if runs.exists():
        con = _readonly(runs)
        row = con.execute('select updated_at from aiops_runs order by id desc limit 1').fetchone()
        con.close()
        if row and row[0]:
            recorded_at = str(row[0])
    environment = json.loads((directory / 'environment.json').read_text(encoding='utf-8'))
    state = {k: values.get(k) for k in KEEP if values.get(k) is not None}
    suggestion = (values.get('investigation_memory') or {}).get('model_suggestion')
    return {
        'round': name,
        'target_id': environment.get('target_id'),
        'recorded_at': recorded_at,
        'recorded_kind': (values.get('diagnosis') or {}).get('kind'),
        'state': scrub(state),
        'suggestion': scrub(suggestion),
    }


def main():
    rounds = [distil(name, directory) for name, directory in round_dirs(ROOT / 'runtime')]
    raw = json.dumps(rounds, ensure_ascii=False, sort_keys=True, default=str).encode('utf-8')
    CORPUS.parent.mkdir(parents=True, exist_ok=True)
    CORPUS.write_bytes(gzip.compress(raw, 9))
    print(json.dumps({
        'rounds': [r['round'] for r in rounds],
        'raw_bytes': len(raw),
        'gzip_bytes': CORPUS.stat().st_size,
        'corpus': str(CORPUS.relative_to(ROOT)),
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
