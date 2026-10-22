from datetime import datetime, timedelta, timezone
import asyncio
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.agent.aiops import run_store
from src.database.models import ProbeSnapshot
from src.database.sql_session import Base, SessionLocal


@pytest.mark.asyncio
async def test_gateway_reads_baseline_comparisons_from_sqlite_after_memory_loss(monkeypatch):
    from mcp_servers import probe_gateway as module
    target = 'history-store-target'
    for age, cpu in [(5, 90), (1, 15)]:
        collected = (datetime.now(timezone.utc) - timedelta(minutes=age)).isoformat()
        run_store.save_probe_snapshot(target, 'baseline', {'target_id': target,
            'collected_at': collected, 'resources': {'payload': {'cpu_percent': cpu}}},
            'sha256:' + str(cpu))
    monkeypatch.setattr(module, 'gateway', module.ProbeGateway(target_id=target, token='test'))
    result = await module.probe_list_evidence.fn(limit=2)
    history = result['baseline_history']
    assert [row['cpu_percent'] for row in history] == [15, 90]
    assert [row['fresh'] for row in history] == [True, False]
    assert all(row['historical'] and not row['current'] for row in history)
    assert result['status']['status'] == 'offline'
    assert result['baseline_summary']['cpu_percent'] == 15


def test_probe_snapshot_is_readable_from_a_new_store_session_and_expired_rows_are_hidden():
    """The restart path uses a fresh SQLAlchemy session, not gateway memory."""
    target_id = "persistence-test-target"
    run_store.save_probe_snapshot(
        target_id,
        "baseline",
        {"target_id": target_id, "collected_at": datetime.now(timezone.utc).isoformat(),
         "resources": {"cpu_percent": 12}},
        "sha256:baseline",
    )

    db = SessionLocal()
    try:
        db.add(ProbeSnapshot(
            target_id=target_id,
            kind="baseline",
            collected_at=datetime.now(timezone.utc) - timedelta(hours=25),
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            payload={"old": True},
            raw_hash="sha256:old",
        ))
        db.commit()
    finally:
        db.close()

    rows = run_store.list_probe_snapshots(target_id)
    assert len(rows) == 1
    assert rows[0]["raw_hash"] == "sha256:baseline"
    assert rows[0]["fresh"] is True


def test_persisted_evidence_uses_collection_time_for_freshness(tmp_path, monkeypatch):
    monkeypatch.setattr(run_store.settings, "PROBE_EVIDENCE_DIR", str(tmp_path))
    collected_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    evidence_id = run_store.add_evidence(
        "freshness-test-thread",
        None,
        "persistence-test-target",
        "resource_snapshot",
        {
            "target_id": "persistence-test-target",
            "operation": "resources",
            "collected_at": collected_at,
            "payload": {"cpu_percent": 90},
            "raw_hash": "sha256:old-evidence",
        },
        ttl_seconds=180,
    )

    item = run_store.get_evidence("freshness-test-thread", evidence_id)
    assert item is not None
    assert item["fresh"] is False


def test_retained_baseline_is_not_current_evidence():
    target_id = "retained-stale-target"
    collected_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    run_store.save_probe_snapshot(target_id, "baseline",
                                  {"target_id": target_id, "collected_at": collected_at.isoformat()},
                                  "sha256:retained")
    rows = run_store.list_probe_snapshots(target_id)
    assert len(rows) == 1
    assert rows[0]["fresh"] is False


@pytest.fixture
def isolated_probe_store(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + str(tmp_path / 'retention.sqlite'))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(run_store, 'SessionLocal', factory)
    monkeypatch.setattr(run_store.settings, 'PROBE_EVIDENCE_DIR', str(tmp_path / 'evidence'))
    yield factory
    engine.dispose()


def test_cleanup_expired_probe_snapshots_deletes_only_expired_rows_and_keeps_evidence(isolated_probe_store):
    target_id = "retention-cleanup-target"
    now = datetime.now(timezone.utc)
    db = isolated_probe_store()
    try:
        db.add_all([
            ProbeSnapshot(target_id=target_id, kind="baseline",
                          collected_at=now - timedelta(hours=25),
                          expires_at=now - timedelta(hours=1), payload={"old": True},
                          raw_hash="sha256:old"),
            ProbeSnapshot(target_id=target_id, kind="baseline",
                          collected_at=now - timedelta(minutes=1),
                          expires_at=now + timedelta(hours=23), payload={"new": True},
                          raw_hash="sha256:new"),
        ])
        db.commit()
    finally:
        db.close()

    evidence_id = run_store.add_evidence('retention-thread', None, target_id, 'resources',
        {'collected_at': (now - timedelta(days=2)).isoformat(), 'payload': {'cpu_percent': 20}})
    original = run_store.get_evidence('retention-thread', evidence_id, include_raw=True)
    raw_path = Path(original['raw_ref'])
    raw_bytes = raw_path.read_bytes()
    deleted = run_store.cleanup_expired_probe_snapshots()
    assert deleted == 1
    rows = run_store.list_probe_snapshots(target_id)
    assert [row["raw_hash"] for row in rows] == ["sha256:new"]
    with isolated_probe_store() as db:
        assert db.query(ProbeSnapshot).count() == 1
    assert run_store.get_evidence('retention-thread', evidence_id, include_raw=True) == original
    assert raw_path.read_bytes() == raw_bytes
    assert run_store.cleanup_expired_probe_snapshots() == 0


@pytest.mark.asyncio
async def test_offline_gateway_cleans_on_start_and_timer_and_stops_task(isolated_probe_store, monkeypatch):
    from mcp_servers import probe_gateway as module
    monkeypatch.setattr(module, '_mcp_app', module.mcp.http_app(path='/mcp'))
    monkeypatch.setattr(module, 'gateway', module.ProbeGateway(target_id='offline-cleanup', token='test'))
    monkeypatch.setattr(module, 'BASELINE_CLEANUP_INTERVAL_SECONDS', 0.02)

    def seed_expired():
        now = datetime.now(timezone.utc)
        with isolated_probe_store() as db:
            db.add(ProbeSnapshot(target_id='offline-cleanup', kind='baseline',
                collected_at=now - timedelta(hours=25), expires_at=now - timedelta(hours=1),
                raw_hash='sha256:expired', payload={}))
            db.commit()

    def count():
        with isolated_probe_store() as db:
            return db.query(ProbeSnapshot).count()

    seed_expired()
    async with module.lifespan(module.app):
        assert module.gateway.status()['status'] == 'offline'
        assert count() == 0
        tasks = [task for task in asyncio.all_tasks() if task.get_name() == 'probe-baseline-retention']
        assert len(tasks) == 1
        seed_expired()
        assert count() == 1
        async with asyncio.timeout(2):
            while count():
                await asyncio.sleep(0.01)
    assert tasks[0].cancelled()


@pytest.mark.asyncio
async def test_gateway_cleanup_retries_after_storage_failure(isolated_probe_store, monkeypatch, caplog):
    from mcp_servers import probe_gateway as module
    monkeypatch.setattr(module, '_mcp_app', module.mcp.http_app(path='/mcp'))
    monkeypatch.setattr(module, 'BASELINE_CLEANUP_INTERVAL_SECONDS', 0.02)
    real_cleanup = run_store.cleanup_expired_probe_snapshots
    attempts = []
    now = datetime.now(timezone.utc)
    with isolated_probe_store() as db:
        db.add(ProbeSnapshot(target_id='retry-cleanup', kind='baseline',
            collected_at=now - timedelta(hours=25), expires_at=now - timedelta(hours=1),
            raw_hash='sha256:retry', payload={}))
        db.commit()

    def flaky_cleanup():
        attempts.append(True)
        if len(attempts) == 1:
            raise RuntimeError('test storage temporarily unavailable')
        return real_cleanup()

    monkeypatch.setattr(run_store, 'cleanup_expired_probe_snapshots', flaky_cleanup)
    async with module.lifespan(module.app):
        with isolated_probe_store() as db:
            assert db.query(ProbeSnapshot).count() == 1
        async with asyncio.timeout(2):
            while len(attempts) < 2:
                await asyncio.sleep(0.01)
        with isolated_probe_store() as db:
            assert db.query(ProbeSnapshot).count() == 0
    assert 'Expired Probe baseline cleanup failed' in caplog.text


def test_target_heartbeat_expires_and_can_be_refreshed():
    target_id = 'heartbeat-target'
    run_store.upsert_probe_target(target_id, last_seen=datetime.now(timezone.utc) - timedelta(minutes=5))
    assert run_store.get_probe_target(target_id)['status'] == 'stale'
    run_store.upsert_probe_target(target_id)
    current = run_store.get_probe_target(target_id)
    assert current['status'] == 'online'
    assert current['stale'] is False
