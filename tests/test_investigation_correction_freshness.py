"""Correction requests must use current evidence without extending its lifetime."""
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from src.agent.aiops.strategies import investigation as inv
from src.probe.protocol import evidence
from src.settings import settings
from tests.test_investigation_strategy import decision, state


@pytest.mark.asyncio
@pytest.mark.parametrize('correction', ['health', 'check'])
@pytest.mark.parametrize('expires', [False, True])
async def test_correction_refreshes_evidence_context_and_primary_schema(monkeypatch, correction, expires):
    start = datetime.now(timezone.utc)
    clock = [start]
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='services',
                   payload={'service': 'orders', 'state': 'running'})
    raw['collected_at'] = start.isoformat()
    current = state(raw)
    current['investigation_tools'] = [{'name': 'diagnostic_query'}]
    before = deepcopy(current)
    original_validate = inv.validate_evidence

    def validate_at_clock(item, **kwargs):
        return original_validate(item, now=clock[0], **kwargs)

    monkeypatch.setattr(inv, 'validate_evidence', validate_at_clock)
    monkeypatch.setattr(inv, 'create_agent_llm', lambda **kwargs: object())
    citation = inv.Citation(evidence_id='e1.1', quote='running')
    invalid = (decision(outcome='healthy', conclusion_level='healthy_within_scope',
                        scope='orders', supporting_evidence=[citation]) if correction == 'health' else
               decision(next_check='inspect logs', next_tools=['diagnostic_query']))
    calls = []

    async def model(llm, schema, prompt, inputs):
        calls.append(inputs)
        records = json.loads(inputs['evidence'])
        base = {'hypothesis': 'unknown', 'alternatives': [],
                'supporting_evidence': [citation.model_dump()]}
        if len(calls) == 1:
            assert 'e1.1' in records
            schema.model_validate(base)
            clock[0] = start + timedelta(seconds=181 if expires else 30)
            return invalid
        assert len(calls) == 2
        assert correction + '_feedback' in inputs
        assert ('e1.1' in records) is (not expires)
        if expires:
            with pytest.raises(ValidationError):
                schema.model_validate(base)
            assert json.loads(inputs['progress']) == []
            assert not json.loads(inputs['memory'])['evidence_summaries']
        else:
            schema.model_validate(base)
        return decision(blocked_reason='no further permitted check')

    monkeypatch.setattr(inv, 'ainvoke_structured', model)
    result = await inv.InvestigationStrategy().decide(current)
    assert len(calls) == 2
    assert current == before
    assert result['diagnosis']['kind'] == 'unlocated'
    assert result['investigation_memory'][correction + '_correction']['attempts'] == 1
