import importlib
from datetime import datetime, timezone

from sqlalchemy import create_engine, inspect, text

from src.database.models import OpsWatchIncident, OpsWatchServiceState


def test_watch_routes_are_admin_only(client, auth_headers):
    paths = [
        "/api/v1/monitor/watch/services",
        "/api/v1/monitor/watch/incidents",
        "/api/v1/monitor/watch/incidents/missing",
    ]

    for path in paths:
        assert client.get(path).status_code == 401
        assert client.get(path, headers=auth_headers).status_code == 403


def test_admin_can_read_watch_state_and_incident_evidence(client, db, test_user):
    test_user.role = "admin"
    db.commit()

    incident_id = "test-watch-incident"
    db.add(OpsWatchServiceState(
        service_name="mall-api",
        status="alerting",
        latest_observation="unhealthy",
        breach_count=3,
        latest_value=0.0,
        data_source="prometheus",
        active_incident_id=incident_id,
    ))
    db.add(OpsWatchIncident(
        incident_uid=incident_id,
        service_name="mall-api",
        status="open",
        opened_at=datetime(2026, 11, 17, tzinfo=timezone.utc),
        evidence={"trigger_samples": [{"status": "unhealthy", "data_source": "prometheus"}]},
        diagnosis_status="disabled",
    ))
    db.commit()

    login = client.post(
        "/api/v1/auth/login/access-token",
        data={"username": test_user.username, "password": "testpass"},
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    services = client.get("/api/v1/monitor/watch/services", headers=headers)
    assert services.status_code == 200
    service = services.json()["services"][0]
    assert service["service_name"] == "mall-api"
    assert service["active_incident_id"] == incident_id

    detail = client.get(f"/api/v1/monitor/watch/incidents/{incident_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["evidence"]["trigger_samples"][0]["data_source"] == "prometheus"


def test_startup_migration_adds_signature_column_to_legacy_watch_table(tmp_path, monkeypatch):
    main_module = importlib.import_module("src.main")
    legacy_engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    try:
        with legacy_engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE ops_watch_service_states "
                "(id INTEGER PRIMARY KEY, service_name VARCHAR(128))"
            ))

        monkeypatch.setattr(main_module, "engine", legacy_engine)
        main_module._migrate_schema()

        columns = {column["name"] for column in inspect(legacy_engine).get_columns(
            "ops_watch_service_states"
        )}
        assert "latest_sample_signature" in columns
    finally:
        legacy_engine.dispose()
