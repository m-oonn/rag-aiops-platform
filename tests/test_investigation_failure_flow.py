"""Offline failure contract through real executor/API/SSE and reopened SQLite."""
import importlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
import httpx
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.agent.aiops import run_store
from src.agent.aiops.structured import StructuredOutputError
from src.database.sql_session import Base
from src.probe.protocol import evidence
from src.settings import settings
from tests.test_matching503_output_flow import close_test_sse_watchers


@pytest.mark.asyncio
@pytest.mark.parametrize('resume', [False, True])
@pytest.mark.parametrize('failure_type', [httpx.ReadTimeout, StructuredOutputError, 'truncated', 'budget', 'per_run_budget'])
async def test_failed_investigation_preserves_report_and_owned_refresh(
        tmp_path, monkeypatch, close_test_sse_watchers, resume, failure_type):
    graph_module = importlib.import_module('src.agent.aiops.graph')
    ex = importlib.import_module('src.agent.aiops.executor')
    inv = importlib.import_module('src.agent.aiops.strategies.investigation')
    from src.api.routers import aiops as api
    from src.api.dependencies import get_current_user
    for name, value in {'PROBE_ENABLED': True, 'TERMCP_ENABLED': False, 'ENABLE_HITL': resume,
            'ENABLE_DYNAMIC_CLASSIFICATION': False,
            'AIOPS_CHECKPOINT_DB_PATH': str(tmp_path / 'checkpoints.sqlite'),
            'PROBE_EVIDENCE_DIR': str(tmp_path / 'evidence')}.items():
        monkeypatch.setattr(settings, name, value)
    database = create_engine('sqlite:///' + (tmp_path / 'runs.sqlite').as_posix())
    Base.metadata.create_all(database)
    monkeypatch.setattr(run_store, 'SessionLocal', sessionmaker(bind=database))
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='resources',
                   payload={'cpu_percent': 12.5, 'memory': {'percent': 55.2}, 'disks': []})

    async def resources():
        """Return constructed offline evidence."""
        return raw

    tool = StructuredTool.from_function(coroutine=resources, name='probe_resource_snapshot')
    monkeypatch.setattr(ex, '_get_tools_for_state', AsyncMock(return_value=([tool], None)))
    monkeypatch.setattr(ex, 'create_agent_llm', lambda **kw: SimpleNamespace(bind_tools=lambda _: object()))
    messages = []
    for i in range(2 if resume else 1):
        messages.extend([AIMessage(content='', tool_calls=[{'id': f'c{i}', 'name': tool.name, 'args': {}}]),
                         AIMessage(content='constructed resource snapshot')])
    monkeypatch.setattr(ex, 'ainvoke_with_retry', AsyncMock(side_effect=messages))

    async def planner(state):
        return {'plan': ['check resources']}

    monkeypatch.setattr(graph_module, 'planner', planner)
    monkeypatch.setattr(inv, 'create_agent_llm', lambda **kw: object())
    if failure_type in {'budget', 'per_run_budget'}:
        from openai import APIStatusError
        failure = APIStatusError('private-provider-detail must not appear',
            response=httpx.Response(402, request=httpx.Request('POST', 'https://test.invalid')),
            body={'error': {'type': 'evaluation_budget_exceeded',
                'code': 'per_run_request_limit' if failure_type == 'per_run_budget' else 'max_requests'}})
    elif failure_type == 'truncated':
        failure = StructuredOutputError('Model output was truncated at the token limit', code='output_truncated')
    else:
        failure = failure_type('private-provider-detail must not appear')
    decisions = [inv.InvestigationDecision(hypothesis='', blocked_reason='no further check'), failure] if resume else [failure]
    invoke = AsyncMock(side_effect=decisions)
    monkeypatch.setattr(inv, 'ainvoke_structured', invoke)
    service = graph_module.AIOpsService()
    monkeypatch.setattr(api, 'aiops_service', service)
    app = FastAPI()
    app.include_router(api.router, prefix='/api/v1/aiops')
    owner = SimpleNamespace(id=17, role='user')
    app.dependency_overrides[get_current_user] = lambda: owner
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.post('/api/v1/aiops', json={'query': 'check local application'})
            assert response.status_code == 200
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
            if resume:
                pending = next(e for e in events if e['type'] == 'pending_review')
                # The real graph resume path follows rejection into a new investigation.
                events = [e async for e in service.resume(pending['thread_id'],
                    {'action': 'reject', 'instruction': 'check once more'})]
            terminal = next(e for e in events if e['type'] == 'error')
            tid = terminal['thread_id']
            assert terminal['stage'] == 'investigation_failed'
            assert terminal['diagnosis']['kind'] == 'unlocated'
            if failure_type in {'budget', 'per_run_budget'}:
                assert terminal['investigation_failure']['code'] == 'evaluation_budget_exceeded'
                assert terminal['investigation_failure']['reason_code'] == (
                    'per_run_request_limit' if failure_type == 'per_run_budget' else 'max_requests')
                assert '预算' in terminal['response']
            if failure_type == 'truncated':
                assert terminal['investigation_failure']['code'] == 'model_output_truncated'
                assert '被截断' in terminal['response'] and '保留证据' in terminal['response']
            assert '12.5' in terminal['response'] and raw['raw_hash'] in terminal['response']
            assert 'private-provider-detail' not in json.dumps(events)
            assert not any(e['type'] in {'complete', 'draft', 'pending_review'} for e in events)
            assert next(e['report'] for e in events if e['type'] == 'report') == terminal['response']
            assert run_store.get_run(tid).status == 'failed'
            assert tid not in service._thread_runs
            await service.close()
            reopened = graph_module.AIOpsService()
            monkeypatch.setattr(api, 'aiops_service', reopened)
            try:
                refresh = await client.get('/api/v1/aiops/runs/' + tid)
                assert refresh.status_code == 200
                saved = refresh.json()
                assert saved['status'] == 'failed' and saved['report'] == terminal['response']
                assert saved['investigation_failure'] == terminal['investigation_failure']
                assert saved['diagnosis'] == terminal['diagnosis']
                assert saved['investigation'] == terminal['investigation']
                ledger = (await client.get('/api/v1/aiops/runs/' + tid + '/evidence')).json()['evidence']
                assert len(ledger) == (2 if resume else 1)
                item = await client.get('/api/v1/aiops/runs/' + tid + '/evidence/' + ledger[0]['evidence_id'])
                assert item.status_code == 200
                assert 'raw' not in item.json() and 'raw_ref' not in item.json()
                owner.id = 99
                assert (await client.get('/api/v1/aiops/runs/' + tid)).status_code == 404
                assert (await client.get('/api/v1/aiops/runs/' + tid + '/evidence')).status_code == 404
            finally:
                await reopened.close()
            assert invoke.await_count == (2 if resume else 1)
    finally:
        await service.close()
        database.dispose()
