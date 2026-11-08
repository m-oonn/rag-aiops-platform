# `scripts/aiops_round` — the per-round evidence harness

These are the helpers used to produce and verify each real diagnostic round
(`runtime/aiops-goal-0NN`).  They used to live only inside the round directory,
and `runtime/` is gitignored, so anyone without this machine could not reproduce
a round at all.  They now live here, with every round-specific literal removed.

## Finding the round

All scripts resolve the round the same way (`rounddir.py`):

1. `--round-dir runtime/aiops-goal-0NN`
2. `$AIOPS_ROUND_DIR`
3. otherwise the newest `runtime/aiops-goal-0*` that has `product-model/cost.json`

The most convenient form is therefore:

```powershell
$env:AIOPS_ROUND_DIR = 'runtime/aiops-goal-051'
python scripts/aiops_round/observe.py
```

Nothing is hardcoded per round any more:

| value | where it comes from |
| --- | --- |
| round directory | `rounddir.round_dir()` |
| the misconfigured downstream port | `rounddir.wrong_port()` — from `gate-b-acceptance.json`'s configuration evidence, because the fixture rewrites `business/localapp.connection.json` back to the healthy port when the environment stops |
| inherited ledger rows | `rounddir.inherited_baseline()` — `product-model/run-budget.json` |
| inherited reservation | `rounddir.inherited_reserved()` — same manifest |
| ledger chain length | derived from the round directories present, up to the current round |

## Order of a round

`ledger_snapshot.py before` → click once → `observe.py` → `accept_reader.py live` →
`render_browser.py --thread <id>` + `browser-refresh.js` → `hash_artifacts.py before-restart` →
restart backend → `accept_reader.py after-restart` → `logical_digest.py after-restart` →
`hash_artifacts.py after-restart` → stop backend → `logical_digest_final.py` /
`wal_attribution.py` / `heartbeat_drift.py` → stop environment → `build_deliverables.py` /
`build_event_trail.py` / `ckpt_decode.py` → `report_outline.py` (must run before
`gate_b_acceptance.py`, which reads `report.txt`) → `gate_b_acceptance.py` /
`gate_b_checks.py` / `verify_chain.py` / `hash_evidence.py` → `check_all_envs.py`.

## Warning: these write into the round directory

`ledger_snapshot.py`, `report_outline.py`, `build_deliverables.py`,
`build_event_trail.py`, `ckpt_decode.py`, `gate_b_acceptance.py`, `gate_b_checks.py`,
`verify_chain.py`, `hash_evidence.py`, `hash_artifacts.py`, `logical_digest*.py`,
`wal_attribution.py`, `heartbeat_drift.py` and `check_all_envs.py` all write their
output into the round directory.  Two of them — `hash_artifacts.py` and
`gate_b_checks.py` — snapshot the *current* state of the databases, so re-running
them on a finished round replaces the original restart comparison with a fresh one.
Run the sequence against a round that is still in progress, not against archive
evidence you have already published.

## Browser snippets

`browser-start.template.js` / `browser-refresh.template.js` are committed.
`render_browser.py` fills in the round directory, the round's login and (for the
refresh snippet) the run's thread id, and writes `browser-start.js` /
`browser-refresh.js` next to itself.  Those two outputs are gitignored because they
contain the round's live credentials.

## Reproduction check

Re-running this harness over the archived round `050` reproduced the following
byte-identically: `result-summary.json`, `decision-audit.json`, `latest-state.json`,
`report-headings.json`, `chain-equivalence.json`, `gate-b-acceptance.json`,
`event-trail-reconstructed.json`.  The two that differ — `artifacts-before-restart.json`
and `gate-b-checks.json` — are the pair described in the warning above: they record
*when* the snapshot was taken, so a post-hoc re-run cannot match the original.
