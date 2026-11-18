"""Monitor continuity without external collectors or model calls."""
import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker

from src.agent.aiops import continuous_monitor as monitor
from src.database.models import AiopsRun, OpsWatchIncident, OpsWatchServiceState


def payload(now, value=0, key="one"):
    return {"data_source": "prometheus", "samples": [
        {"series_key": key, "sample_time_unix": now.timestamp(), "value": value}]}


def test_out_of_order_sample_cannot_open_an_incident(db):
    now = datetime.now(timezone.utc)
    for offset in (0, 10, 0):
        result = monitor.record_observation(db, "service", payload(now + timedelta(seconds=offset)), now + timedelta(seconds=20))
    assert result["new_sample"] is False
    assert db.query(OpsWatchIncident).count() == 0
    assert db.query(OpsWatchServiceState).one().breach_count == 2


def test_conflicting_duplicate_series_is_unknown():
    now = datetime.now(timezone.utc)
    sample = payload(now)
    sample["samples"] += payload(now, 1)["samples"]
    assert monitor.classify_up_samples(sample, now, 120)[0] == "unknown"


def test_identical_duplicate_series_is_counted_once():
    now = datetime.now(timezone.utc)
    sample = payload(now)
    sample["samples"] *= 2
    assert len(monitor.classify_up_samples(sample, now, 120)[1]) == 1


def test_resolved_incident_is_skipped_before_queued_diagnosis(db, monkeypatch):
    import src.agent.aiops as package
    db.add(OpsWatchIncident(incident_uid="resolved", service_name="svc", opened_at=datetime.now(timezone.utc), status="resolved", diagnosis_status="pending"))
    db.commit()
    calls = []
    async def execute(**kwargs):
        calls.append(kwargs)
        yield {"type": "complete"}
    monkeypatch.setattr(monitor, "SessionLocal", sessionmaker(bind=db.get_bind()))
    monkeypatch.setattr(package, "aiops_service", SimpleNamespace(execute=execute))
    asyncio.run(monitor._diagnose_incident("resolved", "svc", asyncio.Semaphore(1)))
    assert calls == []
    db.expire_all()
    assert db.query(OpsWatchIncident).one().diagnosis_status == "skipped"


def test_cancelled_diagnosis_records_interruption(db, monkeypatch):
    import src.agent.aiops as package
    db.add(OpsWatchIncident(incident_uid="cancel", service_name="svc", opened_at=datetime.now(timezone.utc), status="open", diagnosis_status="pending"))
    db.add(AiopsRun(thread_id="watch-cancel", user_id=None, query="watch", status="running"))
    db.commit()
    async def execute(**kwargs):
        yield {"type": "status", "thread_id": "watch-cancel"}
        raise asyncio.CancelledError
    monkeypatch.setattr(monitor, "SessionLocal", sessionmaker(bind=db.get_bind()))
    monkeypatch.setattr(package, "aiops_service", SimpleNamespace(execute=execute))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(monitor._diagnose_incident("cancel", "svc", asyncio.Semaphore(1)))
    db.expire_all()
    assert db.query(OpsWatchIncident).one().diagnosis_status == "interrupted"
    assert db.query(AiopsRun).one().status == "failed"


def test_restart_updates_only_linked_monitor_runs(db, monkeypatch):
    db.add_all([AiopsRun(thread_id=tid, user_id=None, query="watch", status="running") for tid in ("linked", "unrelated")])
    db.add(OpsWatchIncident(incident_uid="restart", service_name="svc", opened_at=datetime.now(timezone.utc), status="open", diagnosis_status="running", diagnosis_thread_id="linked"))
    db.commit()
    monkeypatch.setattr(monitor, "SessionLocal", sessionmaker(bind=db.get_bind()))
    monitor._reset_after_restart()
    db.expire_all()
    assert db.query(AiopsRun).filter_by(thread_id="linked").one().status == "failed"
    assert db.query(AiopsRun).filter_by(thread_id="unrelated").one().status == "running"


def test_one_poll_failure_does_not_discard_other_services(db, monkeypatch):
    from mcp_servers import prometheus_client
    class Client:
        def query_up(self, name):
            if name == "broken":
                raise OSError("offline")
            return payload(datetime.now(timezone.utc), 1)
    @contextmanager
    def lock():
        yield True
    async def stop(delay):
        raise asyncio.CancelledError
    monkeypatch.setattr(monitor, "_single_process_lock", lock)
    monkeypatch.setattr(monitor, "SessionLocal", sessionmaker(bind=db.get_bind()))
    for key, value in {"OPS_WATCH_ENABLED": True, "OPS_WATCH_SERVICES": "broken,working", "OPS_WATCH_PROBE_CHECKS": "", "OPS_WATCH_AUTO_DIAGNOSE": False}.items():
        monkeypatch.setattr(monitor.settings, key, value)
    monkeypatch.setattr(prometheus_client, "use_prometheus_backend", lambda: True)
    monkeypatch.setattr(prometheus_client, "PrometheusClient", Client)
    monkeypatch.setattr(monitor, "asyncio", SimpleNamespace(gather=asyncio.gather, to_thread=asyncio.to_thread, sleep=stop, Semaphore=asyncio.Semaphore, create_task=asyncio.create_task, CancelledError=asyncio.CancelledError))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(monitor.run_continuous_watch())
    assert db.query(OpsWatchServiceState).filter_by(service_name="working").one().latest_observation == "healthy"
    assert db.query(OpsWatchServiceState).filter_by(service_name="broken").one().latest_observation == "unknown"


def test_stale_watch_state_is_not_displayed_as_healthy(db, monkeypatch):
    from src.api.routers import monitor as api
    old = datetime.now(timezone.utc) - timedelta(days=1)
    db.add(OpsWatchServiceState(service_name="stale", status="healthy", latest_observation="healthy", last_observed_at=old, latest_sample_at=old))
    db.commit()
    monkeypatch.setattr(api, "settings_watch_enabled", lambda: True)
    row = api.get_watch_services(current_admin=None, db=db)["services"][0]
    assert row["status"] == "unknown" and row["stale"] is True
    assert row["last_observed_at"].endswith("+00:00")
