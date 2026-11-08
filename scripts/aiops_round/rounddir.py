"""Resolve which round directory a round helper should operate on.

Every helper under ``scripts/aiops_round`` used to carry the round name and the
round's wrong port as literals, because each round got its own copy inside
``runtime/aiops-goal-0<NN>`` and that whole tree is machine-local
(``.gitignore: /runtime/``).  The copies were not reproducible for anyone
without this checkout, so the helpers now take the round directory from the
command line and derive everything else from files the round already has.

Resolution order for the round directory:

1. ``--round-dir <path>`` argument
2. ``$AIOPS_ROUND_DIR`` environment variable
3. the most recent ``runtime/aiops-goal-0*`` directory that has a
   ``product-model/cost.json`` (i.e. the round that actually ran)

The wrong port is never hardcoded either: the fixture rewrites
``business/localapp.connection.json`` back to the healthy port when the
environment stops, so the archived file cannot be trusted.  ``wrong_port()``
reads it from the round's own ``gate-b-acceptance.json``, which recorded the
configured value as evidence at acceptance time.
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _from_argv(argv):
    for index, item in enumerate(argv):
        if item == '--round-dir' and index + 1 < len(argv):
            return Path(argv[index + 1])
        if item.startswith('--round-dir='):
            return Path(item.split('=', 1)[1])
    return None


def _latest_round():
    candidates = sorted(
        (p for p in (ROOT / 'runtime').glob('aiops-goal-0*')
         if (p / 'product-model' / 'cost.json').exists()),
        key=lambda p: p.name)
    return candidates[-1] if candidates else None


def round_dir(argv=None):
    """Return the round directory to operate on, or exit with a clear message."""
    argv = list(sys.argv[1:] if argv is None else argv)
    chosen = _from_argv(argv) or (Path(os.environ['AIOPS_ROUND_DIR'])
                                 if os.environ.get('AIOPS_ROUND_DIR') else None) \
        or _latest_round()
    if chosen is None:
        raise SystemExit('no round directory found; pass --round-dir runtime/aiops-goal-0XX '
                         'or set AIOPS_ROUND_DIR')
    path = chosen if chosen.is_absolute() else ROOT / chosen
    if not path.is_dir():
        raise SystemExit(f'round directory does not exist: {path}')
    return path


def round_name(argv=None):
    return round_dir(argv).name


def wrong_port(argv=None):
    """The misconfigured downstream port this round's scenario injected."""
    directory = round_dir(argv)
    acceptance = directory / 'gate-b-acceptance.json'
    if acceptance.exists():
        body = json.loads(acceptance.read_text(encoding='utf-8'))
        requirement = (body.get('requirements') or {}).get(
            'app_loaded_downstream_port_and_config_hash') or {}
        for evidence_id in requirement.get('evidence') or []:
            item = directory / 'product' / 'evidence' / f'{evidence_id}.json'
            if not item.exists():
                continue
            payload = json.loads(item.read_text(encoding='utf-8')).get('payload') or {}
            values = payload.get('values') or {}
            if values.get('downstream_port') is not None:
                return str(values['downstream_port'])
    # Before the round has run there is no acceptance record yet; fall back to
    # the file the fixture writes while the scenario is live.
    connection = directory / 'business' / 'localapp.connection.json'
    if connection.exists():
        return str(json.loads(connection.read_text(encoding='utf-8'))['downstream_port'])
    raise SystemExit(f'cannot determine the configured downstream port for {directory}')


def inherited_baseline(argv=None):
    """Number of ledger rows this round inherited from the previous round."""
    manifest = round_dir(argv) / 'product-model' / 'run-budget.json'
    if manifest.exists():
        return int(json.loads(manifest.read_text(encoding='utf-8'))['inherited_requests'])
    raise SystemExit(f'no run-budget.json in {round_dir(argv)}; start the paid backend first')


def inherited_reserved(argv=None):
    """Reserved CNY carried in from the previous rounds at this round's start."""
    manifest = round_dir(argv) / 'product-model' / 'run-budget.json'
    if manifest.exists():
        return float(json.loads(manifest.read_text(encoding='utf-8'))['inherited_reserved_cny'])
    raise SystemExit(f'no run-budget.json in {round_dir(argv)}; start the paid backend first')
