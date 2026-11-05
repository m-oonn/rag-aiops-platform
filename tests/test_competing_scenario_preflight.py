import json
import sys
from unittest.mock import AsyncMock, Mock

import pytest

from scripts.competing_hypothesis_fixture import CompetingFaultFixture
from scripts.verify_competing_hypothesis_scenario import (
    assert_answer_isolated, capture_decision_input, paid_endpoint_evaluation_command,
    verify, verify_controller_file_denied,
)


@pytest.mark.asyncio
async def test_transport_failure_cannot_count_as_controller_file_denial():
    tool = Mock(ainvoke=AsyncMock(side_effect=ConnectionError('probe offline')))
    with pytest.raises(ConnectionError):
        await verify_controller_file_denied(tool, 'controller-only.json', 'private-canary')
    tool.ainvoke.side_effect = ValueError('ProbeConfigError')
    assert await verify_controller_file_denied(tool, 'controller-only.json', 'private-canary') == 'ProbeConfigError'
    tool.ainvoke.side_effect = None
    tool.ainvoke.return_value = {'payload': 'private-canary', 'error': 'ProbeConfigError'}
    with pytest.raises(AssertionError):
        await verify_controller_file_denied(tool, 'controller-only.json', 'private-canary')


@pytest.mark.parametrize('marker', ['private-canary', 'hidden_fault', 'localapp_unavailable',
    'downstream_unreachable', 'downstream_bind_failed', 'localapp_wrong_endpoint',
    'localapp loaded an obsolete downstream endpoint at startup', 'controller_fixture_check_not_agent_evidence'])
def test_controller_answers_are_rejected_in_nested_model_inputs(marker):
    with pytest.raises(AssertionError, match='controller-only'):
        assert_answer_isolated({'evidence': [{'excerpt': marker}]}, 'private-canary')
    assert_answer_isolated({'evidence': [{'excerpt': 'downstream TCP failed; edge HTTP 503'}]}, 'private-canary')


@pytest.mark.asyncio
async def test_actual_decision_input_capture_stops_before_model_creation_and_preserves_contract(monkeypatch):
    from src.agent.aiops.strategies import investigation as inv
    forbidden = Mock(side_effect=AssertionError('model creation forbidden'))
    monkeypatch.setattr(inv, 'create_agent_llm', forbidden)
    state = {'input': 'edge unavailable', 'raw_evidence': [], 'past_steps': [], 'plan': [],
        'investigation_tools': [{'name': 'probe_dependency_probe'}],
        'target_resolution': {'status': 'resolved', 'service': 'edge'}}
    captured = await capture_decision_input(state)
    forbidden.assert_not_called()
    assert captured['inputs']['input'] == state['input']
    assert json.loads(captured['inputs']['evidence']) == {}
    assert json.loads(captured['inputs']['target_resolution']) == state['target_resolution']
    assert 'alternatives' in captured['schema']['required']
    assert len(captured['messages']) >= 2
    assert_answer_isolated(captured, 'private-canary')


def test_fixture_start_failure_still_stops_owned_processes(monkeypatch, tmp_path):
    from scripts import competing_hypothesis_fixture as module
    original = module.wait_listener
    calls = []

    def fail_second_listener(port, process):
        calls.append(port)
        if len(calls) == 2:
            raise RuntimeError('application startup failed')
        return original(port, process)

    monkeypatch.setattr(module, 'wait_listener', fail_second_listener)
    fixture = CompetingFaultFixture('localapp_unavailable', tmp_path)
    with pytest.raises(RuntimeError, match='startup failed'):
        with fixture:
            pass
    assert fixture.owned and all(process.poll() is not None for process in fixture.owned)
    assert fixture.cleanup_result == {'remaining_listener_ports': [], 'cleanup_errors': []}


def test_paid_endpoint_command_binds_new_output_and_keeps_existing_guards(tmp_path):
    command = paid_endpoint_evaluation_command(
        config=tmp_path / 'config.toml', symptom=tmp_path / 'symptom.txt',
        runbooks=tmp_path / 'runbooks', manifest=tmp_path / 'manifest.json',
        output=tmp_path / 'model', previous_cost=tmp_path / 'cost.json',
        timeout_authorization=tmp_path / 'authorization.json',
        boundary='2026-11-05T00:00:00+00:00', cumulative_limit=33.058792)
    assert command[0] == sys.executable
    assert command[1].endswith('evaluate_windows_probe.py')
    assert command[command.index('--output-dir') + 1] == str(tmp_path / 'model')
    assert command[command.index('--run-budget-cny') + 1] == '5'
    assert command[command.index('--budget-limit-cny') + 1] == '33.058792'
    assert command[command.index('--observation-not-before') + 1] == '2026-11-05T00:00:00+00:00'
    assert command[command.index('--resume-timeout-authorization') + 1] == str(tmp_path / 'authorization.json')
    assert '--isolate-history' in command and '--max-output-tokens' in command


@pytest.mark.asyncio
@pytest.mark.parametrize('fault_pair,previous_cost', [('causes', 'ledger.json'), ('endpoint', None)])
async def test_paid_run_rejects_non_endpoint_or_missing_ledger_before_creating_output(
        tmp_path, fault_pair, previous_cost):
    output = tmp_path / 'not-created'
    with pytest.raises(ValueError, match='paid evaluation'):
        await verify(output, stop_mode='request', fault_pair=fault_pair,
            run_model=True, previous_cost=previous_cost)
    assert not output.exists()
