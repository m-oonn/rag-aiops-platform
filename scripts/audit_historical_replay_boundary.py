"""Record why a historical replay is intentionally not treated as a final report."""
import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(directory: Path, output: Path) -> dict:
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
    from src.agent.aiops.strategies.investigation import (
        InvestigationDecision,
        decide_from_evidence,
        evidence_index,
    )
    from src.probe.evidence import validate_evidence
    from src.settings import settings

    directory = directory.resolve(strict=True)
    output = output.resolve()
    if output.exists() or directory in output.parents:
        raise ValueError("audit output must be a new directory outside the original run")

    watched: dict[Path, str] = {}

    def read(path: Path) -> bytes:
        data = path.read_bytes()
        watched[path] = hashlib.sha256(data).hexdigest()
        return data

    original = json.loads(read(directory / "summary.json"))
    for name in ("checkpoints.sqlite", "runs.sqlite"):
        read(directory / name)
    with sqlite3.connect((directory / "checkpoints.sqlite").as_uri() + "?mode=ro", uri=True) as db:
        rows = db.execute(
            "SELECT thread_id, type, checkpoint FROM checkpoints "
            "WHERE checkpoint_ns = ? ORDER BY checkpoint_id DESC", ("",)
        ).fetchall()
    if not rows or len({row[0] for row in rows}) != 1:
        raise ValueError("expected exactly one historical investigation")

    thread_id, encoding, blob = rows[0]
    checkpoint = JsonPlusSerializer().loads_typed((encoding, blob))
    state = checkpoint["channel_values"]
    if not state.get("response") or not state.get("diagnosis"):
        raise ValueError("incomplete investigation has no final decision to audit")
    when = datetime.fromisoformat(checkpoint["ts"].replace("Z", "+00:00"))
    proposal = (state.get("investigation_memory") or {}).get("model_suggestion") or state["investigation_memory"]
    proposed = InvestigationDecision.model_validate(proposal)
    target_id = state["diagnosis"]["target_id"]
    if target_id != settings.PROBE_TARGET_ID:
        raise ValueError("historical target differs from configured target")

    with sqlite3.connect((directory / "runs.sqlite").as_uri() + "?mode=ro", uri=True) as db:
        ledger = db.execute(
            "SELECT evidence_id, raw_ref, raw_hash FROM aiops_evidence WHERE thread_id = ?",
            (thread_id,),
        ).fetchall()
    saved = {}
    for evidence_id, raw_ref, digest in ledger:
        path = Path(raw_ref).resolve(strict=True)
        if path.parent != (directory / "evidence").resolve() or path.name != evidence_id + ".json":
            raise ValueError("evidence path does not belong to this run")
        value = json.loads(read(path))
        validate_evidence(value, target_id=target_id,
                          now=datetime.fromisoformat(value["collected_at"].replace("Z", "+00:00")))
        if value["raw_hash"] != digest:
            raise ValueError("ledger hash mismatch")
        saved[evidence_id] = value

    for event in state.get("evidence_events") or []:
        value = saved.get(event.get("evidence_id"))
        if value is None or any(event.get(key) != value[key]
                                for key in ("target_id", "collected_at", "raw_hash")):
            raise ValueError("checkpoint evidence identity does not match this ledger")

    records = evidence_index(state, now=when)
    update = decide_from_evidence(state, proposed, records)
    replay_error = None
    if "diagnosis" not in update:
        replay_error = "historical proposal still requires an executable check; not a final replay"

    result = {
        "mode": "historical_replay_boundary_audit",
        "model_calls": 0,
        "new_observations": 0,
        "autonomous_model_success_proven": False,
        "thread_id": thread_id,
        "historical_validation_time": checkpoint["ts"],
        "original_report_kind": original.get("diagnosis", {}).get("kind"),
        "proposed_hypothesis": proposed.hypothesis,
        "proposed_next_check": proposed.next_check,
        "proposed_next_tools": proposed.next_tools,
        "validated_current_records_at_that_time": len(records),
        "replay_error": replay_error,
        "replay_refused_as_final": replay_error is not None,
        "original_artifacts_unchanged": all(sha256(path) == digest for path, digest in watched.items()),
        "input_file_sha256": {str(path.relative_to(directory)): digest for path, digest in watched.items()},
    }
    if not result["original_artifacts_unchanged"]:
        raise ValueError("source artifacts changed during audit")
    output.mkdir(parents=False, exist_ok=False)
    (output / "replay-boundary-audit.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.directory, args.output)
    print(json.dumps({key: result[key] for key in (
        "mode", "replay_error", "replay_refused_as_final", "model_calls",
        "new_observations", "original_artifacts_unchanged",
    )}, ensure_ascii=False))
