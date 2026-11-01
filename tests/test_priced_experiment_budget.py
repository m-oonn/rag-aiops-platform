import json

import httpx
import pytest

from scripts.evaluate_autonomous_investigation import PaidRequestBudget, EvaluationBudgetExceeded
from scripts.model_request_diagnostics import record_model_response


@pytest.mark.asyncio
async def test_real_transport_callback_settles_only_new_priced_usage(tmp_path):
    old = {'number': 1, 'model': 'deepseek-v4-flash', 'reserved_cny': 0,
           'pricing_verified': False, 'http_status': 200,
           'usage': {'prompt_tokens': 100, 'completion_tokens': 10}}
    budget = PaidRequestBudget(tmp_path, limit_cny=0.06, max_output_tokens=4096)
    budget.ledger = [dict(old)]
    budget.inherited_requests = 1
    body = {'model': 'deepseek-v4-flash', 'max_tokens': 4096}
    row = budget.reserve(dict(body), require_known_usage=True)
    initial_reserve = row['reserved_cny']
    assert 0 < initial_reserve < 0.06
    response = httpx.Response(200, json={'model': 'deepseek-flash',
        'usage': {'prompt_tokens': 100, 'completion_tokens': 10}})
    await record_model_response(httpx.MockTransport(lambda _: response),
        httpx.Request('POST', 'https://api.deepseek.com/chat/completions'), row, budget.save)
    assert row['reserved_cny'] == pytest.approx(0.00028)
    assert row['reservation_upper_cny'] == initial_reserve
    assert budget.ledger[0] == old
    assert budget.cost_summary()['estimated_cny_peak'] is None
    assert budget.cost_summary(1)['estimated_cny_peak'] == pytest.approx(0.00028)
    # Settled usage frees only the unused reservation, allowing another bounded send.
    budget.reserve(dict(body), require_known_usage=True)
    with pytest.raises(EvaluationBudgetExceeded, match='prior model request'):
        budget.reserve(dict(body), require_known_usage=True)
    saved = json.loads((tmp_path / 'cost.json').read_text())
    assert saved['reserved_cny'] < 0.06
    assert saved['requests'][0] == old


def test_shared_currency_cap_checks_next_request_before_sending(tmp_path):
    budget = PaidRequestBudget(tmp_path, limit_cny=0.001, max_output_tokens=4096)
    with pytest.raises(EvaluationBudgetExceeded) as error:
        budget.reserve({'model': 'deepseek-v4-flash'})
    assert error.value.reason_code == 'cumulative_cost_limit'
    assert budget.ledger == []
    assert budget.blocked_requests[-1]['sent'] is False


def test_supplier_usage_above_bound_stops_and_keeps_reported_cost(tmp_path):
    budget = PaidRequestBudget(tmp_path)
    row = budget.reserve({'model': 'deepseek-flash'})
    row.update(http_status=200, usage={'prompt_tokens': row['input_token_upper'] + 1,
                                      'completion_tokens': 0})
    budget.save()
    assert row['budget_bound_exceeded'] is True
    assert row['reserved_cny'] > 0
    with pytest.raises(EvaluationBudgetExceeded) as error:
        budget.reserve({'model': 'deepseek-flash'}, require_known_usage=True)
    assert error.value.reason_code == 'usage_exceeded_reservation_bound'
