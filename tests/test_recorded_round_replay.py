"""Replay every recorded paid round through the current decision rules.

`runtime/aiops-goal-0NN/product/checkpoints.sqlite` keeps the last proposal each
round actually produced, together with the evidence that round really collected.
Feeding those proposals back into `decide_from_evidence` therefore re-runs the
current code against real evidence at zero cost — a regression corpus bought
with the 15 paid rounds already spent.

Two invariants matter, and only these two:

* a round that produced `confirmed_cause` when it ran must still produce it
  (anything else is a code regression), and
* a round whose failure was a *logic defect* (039, 049) must now be accepted.

Rounds that failed because the model itself made an unsupported claim stay
refused — that is the rules doing their job, so the test only requires that the
refusal carries a stated reason.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.replay_recorded_rounds import FIXED_BY_CURRENT_RULES, sweep  # noqa: E402

CORPUS = ROOT / 'runtime'

pytestmark = pytest.mark.skipif(
    not (CORPUS / 'aiops-goal-049' / 'product/checkpoints.sqlite').exists(),
    reason='recorded round corpus is not present on this checkout (runtime/ is machine-local)')


@pytest.fixture(scope='module')
def replayed():
    return sweep(str(CORPUS), 36)


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
