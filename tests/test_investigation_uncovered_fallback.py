"""A rejected fallback must not hide the next legal, unobserved query."""
import json

import pytest

from src.agent.aiops.strategies import investigation as inv
from src.settings import settings
from tests.test_concrete_investigation_checks import decision, state


def dependency_state():
    current = state()
    current['target_resolution'] = {
        'status': 'resolved', 'target_id': settings.PROBE_TARGET_ID,
        'allowed_dependencies': ['broken', 'entry'], 'allowed_services': [],
    }
    return current


def failed_attempt(current, tool, arguments, status='failed'):
    current['raw_evidence'].append(('previous check', json.dumps({
        'data_source': 'tool_execution', 'tool': tool, 'arguments': arguments,
        'status': status, 'reason': 'ToolException:ToolException',
    })))


@pytest.mark.parametrize('status', ['failed', 'unavailable', 'cancelled'])
def test_fallback_skips_failed_dependency_and_checks_next_allowed_one(status):
    current = dependency_state()
    failed_attempt(current, 'probe_dependency_probe', {'dependency': 'broken'}, status)
    selected = inv._uncovered_scope_followup(current, inv.evidence_index(current))
    assert selected['check']['next_arguments'] == {
        'probe_dependency_probe': {'dependency': 'entry'}}


def test_fallback_skips_dependency_missing_from_current_inventory():
    current = dependency_state()
    current['raw_evidence'] = state(('inventory', {
        'configured_dependencies': ['entry']}))['raw_evidence']
    selected = inv._uncovered_scope_followup(current, inv.evidence_index(current))
    assert selected['check']['next_arguments'] == {
        'probe_dependency_probe': {'dependency': 'entry'}}


def test_fallback_skips_completed_step_without_renaming_it():
    current = dependency_state()
    current['past_steps'] = [('探测登记依赖 broken 的 DNS、TCP 与 HTTP 状态', 'done')]
    selected = inv._uncovered_scope_followup(current, inv.evidence_index(current))
    assert selected['check']['next_arguments'] == {
        'probe_dependency_probe': {'dependency': 'entry'}}


def test_no_fallback_when_all_allowed_dependencies_previously_failed():
    current = dependency_state()
    for dependency in ['broken', 'entry']:
        failed_attempt(current, 'probe_dependency_probe', {'dependency': dependency})
    assert inv._uncovered_scope_followup(current, inv.evidence_index(current)) is None


def test_guarded_decision_continues_after_rejected_first_fallback():
    current = dependency_state()
    failed_attempt(current, 'probe_dependency_probe', {'dependency': 'broken'})
    answer = decision(next_tools=['missing_probe'], next_arguments={})
    result = inv.decide_from_evidence(
        current, answer, inv.evidence_index(current),
        require_concrete_checks=True, allow_uncovered_scope_fallback=True)
    assert result['plan'] == ['探测登记依赖 entry 的 DNS、TCP 与 HTTP 状态']
    memory = result['investigation_memory']
    assert memory['next_arguments'] == {'probe_dependency_probe': {'dependency': 'entry'}}
    assert memory['model_suggestion']['next_tools'] == ['missing_probe']
    assert memory['hypothesis_tracking']['blocked_check_recovery']['kind'] == 'uncovered_scope_check'
    assert not result.get('response')


def test_fallback_skips_failed_process_and_checks_next_registered_process():
    current = state(('inventory', {'configured_services': {
        service: {'kind': 'process', 'process_names': [service + '.exe']}
        for service in ['broken', 'entry']}}))
    current['investigation_tools'] = [{'name': 'probe_process_snapshot'}]
    current['target_resolution'] = {
        'status': 'resolved', 'target_id': settings.PROBE_TARGET_ID,
        'allowed_dependencies': [], 'allowed_services': ['broken', 'entry'],
    }
    failed_attempt(current, 'probe_process_snapshot', {'service': 'broken', 'sort_by': 'memory'})
    selected = inv._uncovered_scope_followup(current, inv.evidence_index(current))
    assert selected['check']['next_arguments'] == {
        'probe_process_snapshot': {'service': 'entry', 'sort_by': 'memory'}}
