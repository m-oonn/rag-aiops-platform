"""Replay every recorded paid round through the current decision rules.

Each paid diagnosis kept its checkpoints, so the proposals those rounds really
produced can be fed back into `decide_from_evidence` and re-judged by today's
code — at zero cost.  The 15 rounds already paid for thereby become a
regression corpus.

Two invariants matter, and only these two:

* a round that produced `confirmed_cause` when it ran must still produce it
  (anything else is a code regression), and
* a round whose failure was a *logic defect* (039, 049) must now be accepted.

Rounds that failed because the model itself made an unsupported claim stay
refused — that is the rules doing their job, so the test only requires that the
refusal carries a stated reason.

`runtime/` is machine-local, so the corpus is also distilled into
`tests/data/recorded-rounds.json.gz` (built by `scripts/distil_recorded_rounds.py`)
which keeps only the channel values the decision reads.  The live directories win
when present; the committed corpus lets the same gate run on a fresh checkout.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.replay_recorded_rounds import (  # noqa: E402
    FIXED_BY_CURRENT_RULES, corpus_path, replay_any,
)

CORPUS = ROOT / 'runtime'

pytestmark = pytest.mark.skipif(
    not corpus_path().exists() and not (CORPUS / 'aiops-goal-036').exists(),
    reason='no recorded round corpus on this checkout')


@pytest.fixture(scope='module')
def replayed():
    return replay_any(str(CORPUS), 36)


def test_no_previously_passing_round_regresses(replayed):
    summary = replayed['summary']
    assert summary['errors'] == []
    assert summary['regressed'] == [], (
        f'rounds that once produced confirmed_cause now fail: {summary["regressed"]}')


def test_rounds_failed_by_a_logic_defect_are_accepted_by_todays_rules(replayed):
    summary = replayed['summary']
    missed = [name for name in FIXED_BY_CURRENT_RULES
              if name not in summary['fixed_by_current_code']]
    assert missed == [], f'logic-defect rounds still refused: {missed}'


def test_surviving_refusals_carry_a_stated_reason(replayed):
    blocked = {str(row['round']): row for row in replayed['rounds']
               if row.get('replayed_kind') not in (None, 'confirmed_cause')}
    assert blocked, 'expected at least one recorded round to stay refused'
    unexplained = [name for name, row in blocked.items() if not row['blocked_reason'].strip()]
    assert unexplained == [], f'refused without a reason: {unexplained}'


def test_every_replayed_round_reaches_a_terminal_diagnosis(replayed):
    for row in replayed['rounds']:
        assert 'error' not in row, f'round {row["round"]} raised {row.get("error")}'
        assert row['replayed_kind'] in {'confirmed_cause', 'localized_fault', 'unlocated'}, row
