from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from src.agent.aiops.continuous_monitor import classify_up_samples, record_observation
from src.database.models import OpsWatchIncident, OpsWatchServiceState


def _payload(value, sample_time, source="prometheus"):
    return {
        "data_source": source,
        "samples": [{"instance": "mall-api-1", "sample_time_unix": sample_time, "value": value}],
    }


def _record(db, value, now, source="prometheus", sample_time=None):
    return record_observation(
        db, "mall-api", _payload(value, sample_time or now.timestamp(), source), now, 60
    )


def test_classify_rejects_mock_missing_and_stale_samples():
    now = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)

    assert classify_up_samples(_payload(1, now.timestamp(), "mock"), now, 60)[0] == "unknown"
    assert classify_up_samples({"data_source": "prometheus", "samples": []}, now, 60)[0] == "unknown"
    assert classify_up_samples(_payload(1, now.timestamp() - 61), now, 60)[0] == "unknown"


def test_repeated_prometheus_sample_does_not_count_as_new_failure(db):
    now = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
    sample_time = now.timestamp()

    observations = [
        _record(db, 0, now + timedelta(seconds=offset), sample_time=sample_time)
        for offset in (0, 10, 20)
    ]

    state = db.query(OpsWatchServiceState).filter_by(service_name="mall-api").one()
    assert [item["transition"] for item in observations] == [None, None, None]
    assert state.breach_count == 1
    assert db.query(OpsWatchIncident).count() == 0


def test_three_fresh_failures_open_and_two_fresh_recover(db):
    now = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
    first = _record(db, 0, now)
    second = _record(db, 0, now + timedelta(seconds=10))
    third = _record(db, 0, now + timedelta(seconds=20))

    assert [first["status"], second["status"], third["transition"]] == ["suspect", "suspect", "opened"]
    incident_id = third["incident_id"]
    incident = db.query(OpsWatchIncident).filter_by(incident_uid=incident_id).one()
    assert len(incident.evidence["trigger_samples"]) == 3

    recovery_one = _record(db, 1, now + timedelta(seconds=30))
    recovery_two = _record(db, 1, now + timedelta(seconds=40))
    state = db.query(OpsWatchServiceState).filter_by(service_name="mall-api").one()
    incident = db.query(OpsWatchIncident).filter_by(incident_uid=incident_id).one()
    assert recovery_one["status"] == "alerting"
    assert recovery_two["transition"] == "resolved"
    assert state.status == "healthy" and state.active_incident_id is None
    assert incident.status == "resolved"


def test_repeated_healthy_sample_does_not_resolve_incident(db):
    now = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
    for offset in (0, 10, 20):
        _record(db, 0, now + timedelta(seconds=offset))
    incident_id = db.query(OpsWatchIncident).one().incident_uid

    _record(db, 1, now + timedelta(seconds=30))
    repeated = _record(
        db, 1, now + timedelta(seconds=40), sample_time=(now + timedelta(seconds=30)).timestamp()
    )
    state = db.query(OpsWatchServiceState).filter_by(service_name="mall-api").one()
    assert repeated["transition"] is None
    assert state.recovery_count == 1
    assert db.query(OpsWatchIncident).filter_by(incident_uid=incident_id).one().status == "open"

    resolved = _record(db, 1, now + timedelta(seconds=50))
    assert resolved["transition"] == "resolved"


def test_unknown_sample_breaks_streak_and_cannot_resolve_incident(db):
    now = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
    _record(db, 0, now)
    _record(db, 0, now + timedelta(seconds=10))
    stale = _record(db, 1, now + timedelta(seconds=20), sample_time=now.timestamp() - 100)
    after_gap = _record(db, 0, now + timedelta(seconds=30))
    assert stale["observation"] == "unknown"
    assert after_gap["transition"] is None
    assert db.query(OpsWatchIncident).count() == 0

    _record(db, 0, now + timedelta(seconds=40))
    opened = _record(db, 0, now + timedelta(seconds=50))
    incident_id = opened["incident_id"]
    unavailable = _record(db, 1, now + timedelta(seconds=60), source="unavailable")
    state = db.query(OpsWatchServiceState).filter_by(service_name="mall-api").one()
    assert unavailable["observation"] == "unknown"
    assert state.status == "alerting" and state.recovery_count == 0


def test_query_up_preserves_real_sample_timestamp(monkeypatch):
    from mcp_servers import prometheus_client as module

    sample_time = 1794916785.0
    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"status": "success", "data": {"result": [{
                "metric": {"__name__": "up", "instance": "mall-api-1", "job": "mall-api"},
                "value": [sample_time, "0"],
            }]}}

    monkeypatch.setattr(module.settings, "MONITOR_BACKEND", "prometheus")
    monkeypatch.setattr(module.settings, "PROMETHEUS_URL", "http://prometheus.test")
    monkeypatch.setattr(module.PrometheusClient, "_probe", lambda self: True)

    def fake_get(*args, **kwargs):
        calls.append(kwargs["params"].copy())
        return Response()

    monkeypatch.setattr(module.requests, "get", fake_get)

    result = module.PrometheusClient().query_up("mall-api")
    assert result["data_source"] == "prometheus"
    assert len(calls) == 1
    assert result["samples"] == [{
        "instance": "mall-api-1", "series_key": result["samples"][0]["series_key"],
        "sample_time_unix": sample_time, "value": 0.0,
    }]


def test_monitor_triggered_graph_run_is_persisted(monkeypatch):
    import asyncio
    from src.agent.aiops import graph as module

    class FakeGraph:
        async def aget_state(self, config):
            return SimpleNamespace(values={"response": "diagnosis report"}, next=[])

    service = module.AIOpsService()
    created = []
    completed = []
    monkeypatch.setattr(service, "_create_run_strategy", lambda terminal_enabled: object())

    async def persistent_graph(strategy):
        return FakeGraph()

    async def fake_stream(graph, config, initial):
        if False:
            yield {}

    monkeypatch.setattr(service, "_persistent_graph", persistent_graph)
    monkeypatch.setattr(service, "_stream_events", fake_stream)
    monkeypatch.setattr(service, "_failed_investigation", lambda *args, **kwargs: None)
    monkeypatch.setattr(module.run_store, "create_run", lambda *args: created.append(args))
    monkeypatch.setattr(module.run_store, "mark_completed", lambda *args: completed.append(args))
    monkeypatch.setattr(module, "clear_terminal_context", lambda *args: None)

    async def collect():
        return [event async for event in service.execute("monitor alert", persist_run=True)]

    events = asyncio.run(collect())
    assert created and completed
    assert events[-1]["type"] == "complete"
    assert events[-1]["response"] == "diagnosis report"
