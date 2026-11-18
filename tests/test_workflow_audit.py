"""Read failures, corrupt rows and step/call association must stay observable."""
import pytest
from sqlalchemy.orm import sessionmaker
from src.agent.aiops import run_store
from src.database.models import AiopsStepSnapshot


def test_step_read_failure_is_not_an_empty_replay(monkeypatch):
    def unavailable():
        raise RuntimeError("database unavailable")
    monkeypatch.setattr(run_store, "SessionLocal", unavailable)
    with pytest.raises(run_store.StepSnapshotReadError):
        run_store.list_step_snapshots("run")


def test_corrupt_step_is_explicit_and_other_steps_survive(engine, monkeypatch):
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(run_store, "SessionLocal", factory)
    run_store.add_step_snapshot("run", 0, "planner", {"plan": ["check"]})
    with factory() as db:
        db.add(AiopsStepSnapshot(thread_id="run", step_index=1, node="executor", payload="not-json"))
        db.commit()
    rows = run_store.list_step_snapshots("run")
    assert rows[0]["payload"] == {"plan": ["check"]}
    assert rows[1]["status"] == "corrupt"


def test_snapshot_keeps_evidence_and_decision_links():
    from src.agent.aiops.graph import _snapshot_payload
    row = _snapshot_payload("executor", {"past_steps": [("check", "long result")],
        "evidence_events": [{"evidence_id": "ev-one"}]})
    assert row["evidence_ids"] == ["ev-one"]
    decision = _snapshot_payload("replanner", {"investigation_memory": {"hypothesis": "timeout",
        "next_check": "compare request latency", "next_tools": ["probe_dependency"],
        "stop_reason": "evidence incomplete"}})
    assert decision["decision"]["next_check"] == "compare request latency"
