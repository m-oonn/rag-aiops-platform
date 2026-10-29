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
@pytest.mark.parametrize('mutation', ['none', 'failed_child', 'exception', 'config_change',
    'source_change', 'reused_directory', 'reused_thread', 'missing_db', 'reset_failure', 'recovery_failure', 'boundary_mismatch'])
async def test_four_group_order_fixed_environment_isolation_and_failure(environment, monkeypatch, mutation):
    out, prior = environment
    calls, resets = [], []
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
        if mutation == 'recovery_failure' and len(calls) == 12:
            raise RuntimeError('recovery failed')
    async def run(directory, case, launch, previous, *, knowledge_url, mechanism_group, budget_limit_cny, run_budget_cny, observation_not_before):
        assert directory == out and knowledge_url == 'http://127.0.0.1:9200/mcp'
        assert budget_limit_cny == 5 and run_budget_cny == 0.1
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
                    'run_budget_cny': run_budget_cny, 'shared_history_enabled': False}}}
    reset_times = []
    monkeypatch.setattr(controller, 'evaluate_model_case', run)
    before = prior.read_bytes()
    kwargs = dict(knowledge_url='http://127.0.0.1:9200/mcp', previous_cost=prior, budget_limit_cny=5, run_budget_cny=0.1)
    if mutation == 'none':
        result = await controller.evaluate_four_groups(out, Mock(), set_case, **kwargs)
        assert len(result) == 12
        assert {case for case, group in calls} == {'normal', 'downstream_unreachable', 'application_error'}
        for case in {c for c, g in calls}:
            assert {g for c, g in calls if c == case} == {'G00', 'G10', 'G01', 'G11'}
        assert resets[:-1] == [part for case, group in calls for part in ('normal', case)]
    else:
        with pytest.raises((ValueError, RuntimeError)):
            await controller.evaluate_four_groups(out, Mock(), set_case, **kwargs)
        assert len(calls) <= (12 if mutation == 'recovery_failure' else 2)
    saved = json.loads((out / 'four-group-controller.json').read_text())
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


@pytest.mark.parametrize('options', [
    ['--model-stage', 'four-groups'],
    ['--run-model', '--model-stage', 'four-groups'],
    ['--run-model', '--model-stage', 'four-groups', '--run-budget-cny', '0.1', '--mechanism-group', 'G11'],
    ['--run-model', '--model-stage', 'four-groups', '--run-budget-cny', 'nan'],
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
