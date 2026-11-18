"""Real Probe signal adapters, synthetic samples only in these unit tests."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import json

import pytest
from src.agent.aiops import continuous_monitor as monitor
from src.database.models import OpsWatchIncident
from src.probe.protocol import evidence

NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)


def test_http_latency_uses_business_response_and_configured_threshold():
    from src.agent.aiops.watch_signals import classify_probe_check
    raw = evidence(target_id='local', operation='dependency_probe', collected_at=NOW.isoformat(),
        payload={'dependency': 'mall-business', 'tcp': 'ok', 'http': {'status': 200}, 'elapsed_ms': 1200})
    config = {'kind': 'http', 'dependency': 'mall-business', 'max_elapsed_ms': 500}
    payload = classify_probe_check(raw, config)
    assert payload['signal_kind'] == 'business_http'
    assert monitor.classify_up_samples(payload, NOW, 120)[0] == 'unhealthy'
    assert payload['evidence']['payload']['elapsed_ms'] == 1200
    raw['payload']['http'] = {'error': 'TimeoutError'}
    assert monitor.classify_up_samples(classify_probe_check(raw, config), NOW, 120)[0] == 'unhealthy'


def test_old_desktop_stack_remains_stale_and_empty_capture_is_not_recovery():
    from src.agent.aiops.watch_signals import classify_probe_check
    body = {'recorded_at': (NOW - timedelta(hours=1)).isoformat(), 'simulation': False,
            'errors': ['TypeError at teamMembersOf'], 'source': 'DSH DevTools'}
    raw = evidence(target_id='local', operation='text_logs', payload={'service': 'dsh',
        'lines': [json.dumps(body)]}, collected_at=NOW.isoformat())
    config = {'kind': 'desktop', 'path': 'fixed.json', 'max_event_loop_lag_ms': 200}
    assert monitor.classify_up_samples(classify_probe_check(raw, config), NOW, 120)[0] == 'unknown'
    body.update(recorded_at=NOW.isoformat(), errors=[])
    raw['payload']['lines'] = [json.dumps(body)]
    assert monitor.classify_up_samples(classify_probe_check(raw, config), NOW, 120)[0] == 'unknown'
    body.update(window_complete=True, event_loop_lag_ms=10, host_version='0.2.2', plugin_versions={'sidebar': '0.28.2'})
    raw['payload']['lines'] = [json.dumps(body)]
    assert monitor.classify_up_samples(classify_probe_check(raw, config), NOW, 120)[0] == 'healthy'
    body['simulation'] = True
    raw['payload']['lines'] = [json.dumps(body)]
    assert monitor.classify_up_samples(classify_probe_check(raw, config), NOW, 120)[0] == 'unknown'


def test_business_signal_incident_keeps_original_evidence_and_duplicates_do_not_recover(db, monkeypatch):
    from src.agent.aiops.watch_signals import classify_probe_check
    monkeypatch.setattr(monitor.settings, 'OPS_WATCH_AUTO_DIAGNOSE', False)
    config = {'kind': 'http', 'dependency': 'mall-business', 'max_elapsed_ms': 500}
    for seconds in range(3):
        now = NOW + timedelta(seconds=seconds)
        raw = evidence(target_id='local', operation='dependency_probe', collected_at=now.isoformat(),
            payload={'dependency': 'mall-business', 'http': {'status': 503}, 'elapsed_ms': 20})
        result = monitor.record_observation(db, 'mall', classify_probe_check(raw, config), now)
    assert result['transition'] == 'opened'
    row = db.query(OpsWatchIncident).one()
    assert row.evidence['trigger_samples'][0]['signal_kind'] == 'business_http'
    assert row.evidence['trigger_samples'][0]['evidence']['payload']['http']['status'] == 503
    prompt = monitor._diagnosis_prompt(row.incident_uid, 'mall', NOW.isoformat(), row.evidence)
    assert 'up 值为 0' not in prompt
    projected = monitor._diagnosis_trigger_samples(row.evidence)
    assert projected[0]['measurement']['http_status'] == 503
    assert projected[0]['measurement']['elapsed_ms'] == 20
    assert projected[0]['rule']['max_elapsed_ms'] == 500
    raw['payload']['http']['status'] = 200
    raw['collected_at'] = (NOW + timedelta(seconds=4)).isoformat()
    payload = classify_probe_check(raw, config)
    monitor.record_observation(db, 'mall', payload, NOW + timedelta(seconds=4))
    second = monitor.record_observation(db, 'mall', payload, NOW + timedelta(seconds=5))
    assert second['transition'] is None
    assert db.query(OpsWatchIncident).one().status == 'open'
