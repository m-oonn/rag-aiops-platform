import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from scripts import verify_windows_local_faults as controller
from scripts.evaluate_autonomous_investigation import PaidRequestBudget, EvaluationBudgetExceeded


@pytest.fixture
def environment(tmp_path):
    (tmp_path / 'runbooks').mkdir()
    (tmp_path / 'runbooks/guide.md').write_text('neutral guide')
    (tmp_path / 'config.toml').write_text('fixed ports and log path')
    (tmp_path / 'knowledge-manifest.json').write_text('{}')
    prior = tmp_path / 'prior.json'
    prior.write_text(json.dumps({'limit_cny': 5, 'reserved_cny': 0.4, 'requests': [
        {'number': 1, 'reserved_cny': 0.4, 'http_status': 200,
         'usage': {'prompt_tokens': 1, 'completion_tokens': 1}}]}))
    return tmp_path, prior


@pytest.mark.asyncio
@pytest.mark.parametrize('suite', ['baseline-v1', 'mechanism-v1', 'e2-fault-pair-v1'])
@pytest.mark.parametrize('mutation', ['none', 'failed_child', 'exception', 'config_change',
    'source_change', 'reused_directory', 'reused_thread', 'missing_db', 'reset_failure', 'recovery_failure',
    'boundary_mismatch', 'symptom_mismatch'])
async def test_four_group_order_fixed_environment_isolation_and_failure(environment, monkeypatch, mutation, suite):
    out, prior = environment
    calls, resets = [], []
    expected_runs = len(controller.four_group_cases(suite)) * 4
    class Reverse:
        def shuffle(self, rows):
            rows.reverse()
    monkeypatch.setattr(controller.secrets, 'SystemRandom', Reverse)
    async def set_case(case):
        from scripts.evaluation_record import utc_now
        reset_times.append(utc_now())
        resets.append(case)
        if mutation == 'reset_failure' and len(resets) == 2:
            raise ValueError('reset verification failed')
        if mutation == 'recovery_failure' and len(calls) == expected_runs:
            raise RuntimeError('recovery failed')
    async def run(directory, case, launch, previous, *, knowledge_url, mechanism_group, budget_limit_cny, run_budget_cny, observation_not_before, symptom_profile):
        assert directory == out and knowledge_url == 'http://127.0.0.1:9200/mcp'
        assert budget_limit_cny == 5 and run_budget_cny == 0.1
        expected_profile = ('candidate-opportunity'
            if suite == 'e2-fault-pair-v1' and mutation == 'none' else 'neutral')
        assert symptom_profile == expected_profile
        symptom_sha256 = hashlib.sha256(controller.symptom_text(symptom_profile).encode('utf-8')).hexdigest()
        if mutation == 'symptom_mismatch':
            symptom_sha256 = 'wrong-symptom-hash'
        assert observation_not_before == json.loads((out / 'four-group-controller.json').read_text())['resets'][-1]['observation_not_before']
        assert observation_not_before <= reset_times[-2]
        assert previous == (prior if not calls else out / f'cost-{len(calls)}.json')
        calls.append((case, mechanism_group))
        index = len(calls)
        if mutation == 'exception' and index == 2:
            raise RuntimeError('unknown cost')
        child = out / ('child-1' if mutation == 'reused_directory' else f'child-{index}')
        child.mkdir(exist_ok=True)
        for name in ('runs.sqlite', 'checkpoints.sqlite'):
            (child / name).write_bytes(b'isolated test marker')
        if mutation == 'missing_db':
            (child / 'checkpoints.sqlite').unlink()
        (child / 'mechanism_trace.json').write_text(json.dumps({
            'thread_id': 'reused' if mutation == 'reused_thread' else f'thread-{index}'}))
        if mutation == 'config_change':
            (out / 'config.toml').write_text('changed')
        return {'status': 'failed' if mutation == 'failed_child' else 'passed', 'workflow_completed': True,
            'result_dir': str(child), 'cost_file': str(out / f'cost-{index}.json'),
            'record_integrity': {'passed': True, 'observation_not_before': 'wrong' if mutation == 'boundary_mismatch' else observation_not_before, 'source_signature': 'changed' if mutation == 'source_change' and index == 2 else 'fixed',
                'comparison_config': {'objects': ['fixed ports'], 'knowledge': 'same',
                    'run_budget_cny': run_budget_cny, 'shared_history_enabled': False,
                    'symptom_sha256': symptom_sha256}}}
    reset_times = []
    monkeypatch.setattr(controller, 'evaluate_model_case', run)
    before = prior.read_bytes()
    kwargs = dict(knowledge_url='http://127.0.0.1:9200/mcp', previous_cost=prior, budget_limit_cny=5, run_budget_cny=0.1,
        suite=suite)
    if suite == 'e2-fault-pair-v1' and mutation == 'none':
        kwargs['symptom_profile'] = 'candidate-opportunity'
    if mutation == 'none':
        result = await controller.evaluate_four_groups(out, Mock(), set_case, **kwargs)
        assert len(result) == expected_runs
        assert {case for case, group in calls} == set(controller.four_group_cases(suite))
        for case in {c for c, g in calls}:
            assert {g for c, g in calls if c == case} == {'G00', 'G10', 'G01', 'G11'}
        assert resets[:-1] == [part for case, group in calls for part in ('normal', case)]
    else:
        with pytest.raises((ValueError, RuntimeError)):
            await controller.evaluate_four_groups(out, Mock(), set_case, **kwargs)
        assert len(calls) <= (expected_runs if mutation == 'recovery_failure' else 2)
    saved = json.loads((out / 'four-group-controller.json').read_text())
    assert saved['suite'] == suite
    expected_profile = kwargs.get('symptom_profile', 'neutral')
    assert saved['symptom_profile'] == expected_profile
    assert saved['symptom_sha256'] == hashlib.sha256(controller.symptom_text(expected_profile).encode('utf-8')).hexdigest()
    assert saved['scenario_cases'] == list(controller.four_group_cases(suite))
    assert len(saved['order']) == expected_runs
    assert saved['status'] == ('completed' if mutation == 'none' else 'failed')
    assert saved['recovery'] == ('failed' if mutation == 'recovery_failure' else 'normal_restored')
    assert saved['ended_at'] and resets[-1] == 'normal'
    assert prior.read_bytes() == before


@pytest.mark.asyncio
@pytest.mark.parametrize('cap', [None, 0, -1, True, float('nan'), 1])
async def test_equal_budget_preflight_rejects_before_any_reset_or_model(environment, cap):
    out, prior = environment
    reset, launch = AsyncMock(), Mock()
    with pytest.raises((ValueError, RuntimeError)):
        await controller.evaluate_four_groups(out, launch, reset, 'http://127.0.0.1:9200/mcp', prior, 5, cap)
    reset.assert_not_awaited()
    launch.assert_not_called()


def test_per_run_cap_does_not_reset_inherited_budget(tmp_path):
    budget = PaidRequestBudget(tmp_path, limit_cny=5, run_limit_cny=0.05)
    budget.reserved = budget.inherited_reserved = 0.4
    budget.ledger = [{'number': 1, 'reserved_cny': 0.4}]
    while True:
        try:
            budget.reserve({'model': 'deepseek-flash', 'max_tokens': 2048})
        except EvaluationBudgetExceeded:
            break
    assert budget.ledger[0] == {'number': 1, 'reserved_cny': 0.4}
    assert 0 < budget.reserved - 0.4 <= 0.05


@pytest.mark.parametrize('cumulative, expected', [(54, 'max_requests'), (76, 'per_run_request_limit')])
def test_request_caps_stop_before_send_and_preserve_inherited_ledger(tmp_path, cumulative, expected):
    budget = PaidRequestBudget(tmp_path, allow_unpriced_models=True, max_requests=cumulative, run_max_requests=2)
    old = [{'number': i, 'reserved_cny': 0, 'pricing_verified': False, 'http_status': 200,
        'usage': {'prompt_tokens': 1, 'completion_tokens': 1}} for i in range(1, 53)]
    budget.ledger, budget.inherited_requests = list(old), 52
    for _ in range(2):
        row = budget.reserve({'model': 'deepseek-v4-flash'}, require_known_usage=True)
        row.update(http_status=200, usage={'prompt_tokens': 1, 'completion_tokens': 1})
    with pytest.raises(EvaluationBudgetExceeded) as error:
        budget.reserve({'model': 'deepseek-v4-flash'}, require_known_usage=True)
    assert error.value.reason_code == expected
    assert len(budget.ledger) == 54 and budget.ledger[:52] == old
    saved = json.loads((tmp_path / 'cost.json').read_text())
    assert saved['blocked_requests'][-1]['sent'] is False
    assert saved['request_limits']['inherited_requests'] == 52
    assert budget.cost_summary()['estimated_cny_peak'] is None


@pytest.mark.asyncio
@pytest.mark.parametrize('total, per_run', [(24, 2), (25, None), (None, 2), (25, 0)])
async def test_unpriced_batch_budget_rejects_before_reset(environment, total, per_run):
    out, prior = environment
    reset, launch = AsyncMock(), Mock()
    with pytest.raises((ValueError, RuntimeError)):
        await controller.evaluate_four_groups(out, launch, reset, 'http://127.0.0.1:9200/mcp', prior, 5, None,
            allow_unpriced_model=True, max_model_requests=total, run_max_model_requests=per_run)
    reset.assert_not_awaited()
    launch.assert_not_called()


@pytest.mark.parametrize('options', [
    ['--model-stage', 'four-groups'],
    ['--run-model', '--model-stage', 'four-groups'],
    ['--run-model', '--model-stage', 'four-groups', '--run-budget-cny', '0.1', '--mechanism-group', 'G11'],
    ['--run-model', '--model-stage', 'four-groups', '--run-budget-cny', 'nan'],
    ['--scenario-preflight', '--run-model'],
    ['--scenario-preflight', '--evaluation-preflight'],
    ['--four-group-suite', 'mechanism-v1'],
    ['--run-model', '--model-stage', 'four-groups', '--allow-unpriced-model', '--max-model-requests', '196'],
    ['--run-model', '--model-stage', 'four-groups', '--allow-unpriced-model', '--max-model-requests', '196', '--run-max-model-requests', '0'],
])
def test_four_group_cli_rejects_incomplete_parameters_before_environment(monkeypatch, options):
    import sys
    monkeypatch.setattr(sys, 'argv', ['controller', *options])
    verify = AsyncMock(side_effect=AssertionError('must not create environment'))
    monkeypatch.setattr(controller, 'verify', verify)
    with pytest.raises(SystemExit) as error:
        controller.main()
    assert error.value.code == 2
    verify.assert_not_awaited()


def test_four_group_cli_preserves_review_ledger_and_cap_before_dispatch(tmp_path, monkeypatch):
    import sys
    review = tmp_path / 'review.json'
    review.write_text(json.dumps({'smoke_passed': True}))
    prior = tmp_path / 'prior.json'
    monkeypatch.setattr(sys, 'argv', ['controller', '--run-model', '--model-stage', 'four-groups',
        '--run-budget-cny', '0.1', '--previous-cost', str(prior), '--smoke-review', str(review)])
    verify = AsyncMock(return_value={'ok': True})
    monkeypatch.setattr(controller, 'verify', verify)
    assert controller.main() == 0
    assert verify.await_args.kwargs['model_stage'] == 'four-groups'
    assert verify.await_args.kwargs['run_budget_cny'] == 0.1
    assert verify.await_args.kwargs['previous_cost'] == prior


def test_unpriced_four_group_cli_preserves_equal_caps_and_requires_review(tmp_path, monkeypatch):
    import sys
    review = tmp_path / 'review.json'
    review.write_text(json.dumps({'smoke_passed': True}))
    options = ['controller', '--run-model', '--model-stage', 'four-groups', '--four-group-suite', 'mechanism-v1',
        '--allow-unpriced-model', '--max-model-requests', '196', '--run-max-model-requests', '12',
        '--previous-cost', str(tmp_path / 'prior.json')]
    monkeypatch.setattr(sys, 'argv', options)
    verify = AsyncMock(return_value={'ok': True})
    monkeypatch.setattr(controller, 'verify', verify)
    with pytest.raises(SystemExit):
        controller.main()
    verify.assert_not_awaited()
    monkeypatch.setattr(sys, 'argv', [*options, '--smoke-review', str(review)])
    assert controller.main() == 0
    assert verify.await_args.kwargs['run_max_model_requests'] == 12
    assert verify.await_args.kwargs['max_model_requests'] == 196
    assert verify.await_args.kwargs['allow_unpriced_model'] is True
    assert verify.await_args.kwargs['run_budget_cny'] is None


def test_free_scenario_cli_does_not_request_model_or_budget(monkeypatch):
    import sys
    monkeypatch.setattr(sys, 'argv', ['controller', '--scenario-preflight', '--four-group-suite', 'mechanism-v1'])
    verify = AsyncMock(return_value={'ok': True, 'model_calls': 0})
    monkeypatch.setattr(controller, 'verify', verify)
    assert controller.main() == 0
    assert verify.await_args.kwargs['scenario_preflight'] is True
    assert verify.await_args.kwargs['four_group_suite'] == 'mechanism-v1'
    assert verify.await_args.kwargs['run_model'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['none', 'reset', 'recovery'])
async def test_free_scenario_preflight_preserves_schedule_failure_and_recovery(environment, monkeypatch, failure):
    from scripts import verify_probe_observation_boundary as boundary
    out, prior = environment
    calls = []

    async def reset(case):
        calls.append(case)
        if failure == 'reset' and len(calls) == 2:
            raise RuntimeError('reset failed')
        if failure == 'recovery' and len(calls) == 25:
            raise RuntimeError('recovery failed')
        return {'case': case, 'passed': True}

    async def run(tools, target, output, log, reset, scenarios):
        assert len(scenarios) == 12
        assert set(scenarios) == set(controller.four_group_cases('mechanism-v1'))
        for case in scenarios:
            await reset(case)
        return {'rounds': 12, 'evidence_count': 48}

    monkeypatch.setattr(boundary, 'verify_boundary_rounds', run)
    before = prior.read_bytes()
    if failure == 'none':
        result = await controller.preflight_four_group_scenarios(out, {}, 'fixture', out / 'app.log', reset, 'mechanism-v1')
        assert result['model_calls'] == 0 and result['rounds'] == 12
        assert not result['mechanism_effectiveness_verified']
    else:
        with pytest.raises(RuntimeError):
            await controller.preflight_four_group_scenarios(out, {}, 'fixture', out / 'app.log', reset, 'mechanism-v1')
    record = json.loads((out / 'four-group-scenario-preflight.json').read_text())
    assert record['status'] == ('passed' if failure == 'none' else 'failed')
    assert record['recovery'] == ('failed' if failure == 'recovery' else 'normal_restored')
    assert calls[-1] == 'normal' and record['ended_at']
    assert record['group_labels_only'] is True
    assert prior.read_bytes() == before
