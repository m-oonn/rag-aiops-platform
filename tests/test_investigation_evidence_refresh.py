"""Expired evidence is a refresh basis, never a current factual citation."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from src.agent.aiops.strategies import investigation as inv
from src.agent.aiops.probe_checks import check_progress, progress_error
from src.probe.protocol import evidence
from src.settings import settings
from tests.test_concrete_investigation_checks import decision, state


def expired_state(*, tampered=False):
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
                   payload={'dependency': 'entry', 'tcp': 'ok'})
    raw['collected_at'] = (datetime.now(timezone.utc) - timedelta(seconds=181)).isoformat()
    if tampered:
        raw['payload']['tcp'] = 'failed'
    current = state()
    current['raw_evidence'] = [('inspect entry', json.dumps(raw))]
    current['past_steps'] = [('inspect entry', 'completed')]
    return current

def test_expired_query_is_distinguished_from_never_collected():
    current = expired_state()
    records = inv.evidence_index(current)
    assert records == {}
    row = check_progress(decision().model_dump(), current, records)[0]
    assert row['status'] == 'expired'
    assert row['evidence_ids'] == []
    assert row['expired_evidence_ids'] == ['e1.1']

@pytest.mark.parametrize('reason,ids,allowed', [
    ('', ['e1.1'], False), ('refresh expired sample', ['invented'], False),
    ('refresh expired sample', ['e1.1'], True)])
def test_same_named_refresh_requires_explicit_expired_basis(reason, ids, allowed):
    current = expired_state()
    answer = decision(repeat_reason=reason, repeat_evidence_ids=ids)
    result = inv.decide_from_evidence(current, answer, inv.evidence_index(current))
    assert bool(result['plan']) is allowed
    assert result.get('diagnosis', {}).get('kind') != 'confirmed_cause'

def test_tampered_expired_evidence_cannot_authorize_refresh():
    current = expired_state(tampered=True)
    row = check_progress(decision().model_dump(), current, {})[0]
    assert row['status'] == 'unexecuted'
    assert not row.get('expired_evidence_ids')


def test_wrong_target_expired_evidence_cannot_authorize_refresh():
    current = expired_state()
    raw = json.loads(current['raw_evidence'][0][1])
    raw['target_id'] = 'different-target'
    current['raw_evidence'][0] = ('inspect entry', json.dumps(raw))
    assert not inv.expired_probe_index(current)
    answer = decision(repeat_reason='refresh expired sample', repeat_evidence_ids=['e1.1'])
    assert not inv.decide_from_evidence(current, answer, {})['plan']

def test_expired_history_in_agenda_contains_no_reusable_fact_or_quote():
    current = expired_state()
    agenda = inv._decision_check_agenda({}, current, {})
    rows = agenda['expired_observations']
    assert rows[0]['evidence_id'] == 'e1.1'
    assert rows[0]['not_citable'] is True
    assert 'tcp' not in json.dumps(rows)
    assert 'payload' not in rows[0] and 'quote' not in rows[0]

def test_same_named_fresh_repeat_is_allowed_when_existing_guards_pass():
    current = state(('dependency_probe', {'dependency': 'entry', 'tcp': 'failed'}))
    current['past_steps'] = [('inspect entry', 'completed')]
    answer = decision(repeat_reason='verify recovery', repeat_evidence_ids=['e1.1'])
    result = inv.decide_from_evidence(current, answer, inv.evidence_index(current))
    assert result['plan'] == ['inspect entry']

def test_expired_query_with_failed_latest_attempt_is_not_automatically_retried():
    current = expired_state()
    current['raw_evidence'].append(('inspect entry', json.dumps({
        'data_source': 'tool_execution', 'tool': 'probe_dependency_probe',
        'arguments': {'dependency': 'entry'}, 'status': 'failed', 'reason': 'unavailable'})))
    answer = decision(repeat_reason='refresh expired sample', repeat_evidence_ids=['e1.1'])
    assert '不原样自动重试' in progress_error(answer.model_dump(), current, {})

def test_expiry_does_not_reset_unchanged_query_guard():
    current = expired_state()
    current['raw_evidence'] *= 2
    answer = decision(repeat_reason='refresh expired sample', repeat_evidence_ids=['e2.1'])
    assert 'raw_hash 未变化' in progress_error(answer.model_dump(), current, {})

def test_expired_sample_is_not_a_terminal_citation():
    current = expired_state()
    answer = decision(outcome='healthy', conclusion_level='healthy_within_scope', scope='entry',
                      next_check='', next_tools=[], next_arguments={},
                      supporting_evidence=[inv.Citation(evidence_id='e1.1', quote='ok')])
    result = inv.decide_from_evidence(current, answer, {})
    assert result['diagnosis']['kind'] != 'healthy_within_scope'

def test_executor_accepts_explicit_refresh_but_not_changed_arguments():
    from src.agent.aiops.executor import _probe_request_limit
    current = expired_state()
    current['autonomous_investigation'] = True
    current['investigation_memory'] = decision(repeat_reason='refresh expired sample',
        repeat_evidence_ids=['e1.1']).model_dump()
    assert not _probe_request_limit({'name': 'probe_dependency_probe', 'args': {'dependency': 'entry'}}, current)
    assert _probe_request_limit({'name': 'probe_dependency_probe', 'args': {'dependency': 'other'}}, current)

def test_configuration_progress_preserves_missing_runtime_provenance():
    current = state(('configuration', {'service': 'web',
        'source': 'mounted_spring_config_snapshot', 'values': {'port': 3307},
        'runtime_effective_values_confirmed': False, 'mount_matches_registered_file': True}))
    current['investigation_tools'] = [{'name': 'probe_config_snapshot'}]
    check = {'next_arguments': {'probe_config_snapshot': {'service': 'web'}}}
    row = check_progress(check, current, inv.evidence_index(current))[0]
    assert row['observation']['runtime_effective_values_confirmed'] is False
    assert '实际加载' in row['remaining_unknown']


@pytest.mark.parametrize('changed', [False, True])
def test_expired_log_refresh_still_requires_a_new_change(changed):
    current = state()
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='text_logs', payload={
        'service': 'entry', 'path': r'D:\logs\app.log', 'line_limit': 100,
        'lines': ['application started']})
    raw['collected_at'] = (datetime.now(timezone.utc) - timedelta(seconds=181)).isoformat()
    current['raw_evidence'] = [('inspect entry', json.dumps(raw))]
    current['past_steps'] = [('inspect entry', 'completed')]
    ids = ['e1.1']
    if changed:
        current['raw_evidence'].append(('new connection failure', json.dumps(evidence(
            target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
            payload={'dependency': 'entry', 'tcp': 'failed'}))))
        ids.append('e2.1')
    answer = decision(next_tools=['probe_text_log'], next_arguments={
        'probe_text_log': {'service': 'entry', 'path': r'D:\logs\app.log'}},
        repeat_reason='inspect logs after the new failure', repeat_evidence_ids=ids)
    records = inv.evidence_index(current)
    error = progress_error(answer.model_dump(), current, records)
    assert bool(error) is (not changed)
    if not changed:
        assert '相同日志检查已完成' in error
    result = inv.decide_from_evidence(current, answer, records)
    assert bool(result['plan']) is changed


def test_expired_query_does_not_authorize_automatic_fallback_resampling():
    current = expired_state()
    current['target_resolution'] = {'status': 'resolved', 'allowed_dependencies': ['entry']}
    answer = decision(repeat_reason='refresh expired sample', repeat_evidence_ids=['e1.1'])
    check = {key: value for key, value in answer.model_dump().items()
             if key in inv.CandidateCheck.model_fields}
    candidate = {'explanation': 'unknown', 'check': check}
    assert not inv._candidate_check_rejection(candidate, current, {}, automatic=False)
    assert '不自动重新采样' in inv._candidate_check_rejection(candidate, current, {}, automatic=True)
    assert inv._uncovered_scope_followup(current, {}) is None
