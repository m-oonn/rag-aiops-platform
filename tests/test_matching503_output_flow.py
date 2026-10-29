"""Historical Probe returns through real executor, graph, SSE and owned refresh API."""
from datetime import datetime as RealDateTime
import asyncio
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
import httpx
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.agent.aiops import run_store
from src.database.sql_session import Base
from src.settings import settings

FIXTURE = Path(__file__).parent / 'fixtures/matching503-probe-20261024.json'


@pytest_asyncio.fixture
async def close_test_sse_watchers():
    existing = asyncio.all_tasks()
    yield
    # ASGITransport has no server shutdown; close only watchers this test created.
    watchers = [task for task in asyncio.all_tasks() - existing
                if getattr(task.get_coro(), '__name__', '') == '_shutdown_watcher']
    for task in watchers:
        task.cancel()
    await asyncio.gather(*watchers, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['downstream_unreachable', 'application_config_error'])
@pytest.mark.parametrize('evidence_count', [1, 2, 3])
@pytest.mark.parametrize('protection,trigger', [(False, False), (True, False), (False, True), (True, True)])
async def test_real_sse_and_reopened_refresh_preserve_historical_fault_boundary(
        tmp_path, monkeypatch, close_test_sse_watchers, case, evidence_count, protection, trigger):
    graph_module = importlib.import_module('src.agent.aiops.graph')
    ex = importlib.import_module('src.agent.aiops.executor')
    inv = importlib.import_module('src.agent.aiops.strategies.investigation')
    evidence_module = importlib.import_module('src.probe.evidence')
    from src.api.routers import aiops as api
    from src.api.dependencies import get_current_user
    original = FIXTURE.read_bytes()
    rows = json.loads(original.decode('utf-8-sig'))['cases'][case]
    when = RealDateTime.fromisoformat(rows[-1]['raw']['collected_at'].replace('Z', '+00:00'))

    class HistoricalValidationClock(RealDateTime):
        @classmethod
        def now(cls, tz=None):
            return when.astimezone(tz) if tz else when.replace(tzinfo=None)

    # Freeze validation only; original collected_at and hashes are never rewritten.
    monkeypatch.setattr(evidence_module, 'datetime', HistoricalValidationClock)
    for name, value in {'PROBE_ENABLED': True, 'TERMCP_ENABLED': False, 'ENABLE_HITL': False,
            'ENABLE_STEP_SNAPSHOTS': True, 'ENABLE_DYNAMIC_CLASSIFICATION': False,
            'INVESTIGATION_HYPOTHESIS_PROTECTION': protection, 'INVESTIGATION_CONTRADICTION_TRIGGER': trigger,
            'AIOPS_CHECKPOINT_DB_PATH': str(tmp_path / 'checkpoints.sqlite'),
            'PROBE_EVIDENCE_DIR': str(tmp_path / 'evidence')}.items():
        monkeypatch.setattr(settings, name, value)
    database = create_engine('sqlite:///' + (tmp_path / 'runs.sqlite').as_posix())
    Base.metadata.create_all(database)
    monkeypatch.setattr(run_store, 'SessionLocal', sessionmaker(bind=database))
    calls = []

    async def dependency(dependency: str):
        """Read one saved allowlisted dependency response."""
        calls.append(('probe_dependency_probe', dependency))
        return next(row['raw'] for row in rows if row['raw']['payload'].get('dependency') == dependency)

    async def logs(service: str):
        """Read the saved application log response."""
        assert service == 'localapp'
        calls.append(('probe_text_log', service))
        return rows[2]['raw']

    tools = [StructuredTool.from_function(coroutine=dependency, name='probe_dependency_probe'),
             StructuredTool.from_function(coroutine=logs, name='probe_text_log')]
    loader = AsyncMock(return_value=(tools, None))
    monkeypatch.setattr(ex, '_get_tools_for_state', loader)
    monkeypatch.setattr(ex, 'create_agent_llm', lambda **kw: SimpleNamespace(bind_tools=lambda _: object()))
    step_calls = [('probe_dependency_probe', {'dependency': 'localapp'}),
                  ('probe_dependency_probe', {'dependency': 'downstream'}),
                  ('probe_text_log', {'service': 'localapp'})]
    messages = []
    for i, (name, arguments) in enumerate(step_calls[:evidence_count]):
        messages.extend([AIMessage(content='', tool_calls=[{'id': f'call-{i}', 'name': name, 'args': arguments}]),
                         AIMessage(content='固定摘要：待现场裁决核验')])
    execution_decisions = AsyncMock(side_effect=messages)
    monkeypatch.setattr(ex, 'ainvoke_with_retry', execution_decisions)

    async def planner(state):
        assert state['autonomous_investigation'] and not state['terminal_enabled']
        return {'plan': ['检查本地应用入口'], 'target_resolution': {'status': 'resolved',
            'target_id': settings.PROBE_TARGET_ID, 'allowed_dependencies': ['localapp', 'downstream'],
            'allowed_services': ['localapp']}}

    monkeypatch.setattr(graph_module, 'planner', planner)
    monkeypatch.setattr(inv, 'create_agent_llm', lambda **kw: object())
    cause = '下游进程崩溃导致入口503'  # Deliberately excessive proposal, never an injected observation.

    async def decision(*args, **kwargs):
        context = json.loads(args[3]['evidence'])
        count = len(context)
        if count < evidence_count:
            next_name, _ = step_calls[count]
            return inv.InvestigationDecision(hypothesis='入口503原因尚未查清',
                next_check='检查下游独立探测' if count == 1 else '检查入口日志', next_tools=[next_name],
                discriminating_question='下游连通异常还是应用自身异常', expected_observation='下游状态或应用错误原文')
        citations = [inv.Citation(evidence_id=next(iter(context)), quote='temporarily unavailable')]
        if count == 3:
            citations.append(inv.Citation(evidence_id=list(context)[-1],
                quote='upstream connection failed' if case == 'downstream_unreachable' else 'invalid max_attempts configuration'))
        return inv.InvestigationDecision(hypothesis=cause, root_cause=cause,
            outcome='root_cause', conclusion_level='confirmed_cause', scope='localapp入口与下游',
            supporting_evidence=citations, alternatives=[inv.Alternative(explanation='入口TCP失败',
                status='excluded', claim_type='observed_condition',
                condition=inv.ObservationCondition(operation='dependency_probe', object_name='localapp', field='tcp', expected='failed'),
                evidence=[inv.Citation(evidence_id=next(iter(context)), quote='ok')])])

    fixed_decisions = AsyncMock(side_effect=decision)
    monkeypatch.setattr(inv, 'ainvoke_structured', fixed_decisions)
    service = graph_module.AIOpsService()
    monkeypatch.setattr(api, 'aiops_service', service)
    app = FastAPI()
    app.include_router(api.router, prefix='/api/v1/aiops')
    owner = SimpleNamespace(id=17, role='auditor')
    app.dependency_overrides[get_current_user] = lambda: owner
    events = []
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.post('/api/v1/aiops', json={'query': '本地应用入口返回503，请排查', 'session_id': 'history-check'})
            assert response.status_code == 200
            assert response.headers['content-type'].startswith('text/event-stream')
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
            assert not any(event['type'] == 'error' for event in events), events
            complete = next(event for event in events if event['type'] == 'complete')
            report = next(event for event in events if event['type'] == 'report')
            tid = complete['thread_id']
            diagnosis = complete['diagnosis']
            assert diagnosis['kind'] == 'localized_fault' and diagnosis['validation_issues']
            expected = {('dependency_http_failed', 'localapp')}
            if evidence_count >= 2 and case == 'downstream_unreachable':
                expected.add(('dependency_tcp_failed', 'downstream'))
            assert {(f['code'], f['scope'].get('dependency')) for f in diagnosis['observed_findings']} == expected
            http_finding = next(f for f in diagnosis['observed_findings']
                                if f['code'] == 'dependency_http_failed')
            assert http_finding['summary'] == 'HTTP 探测返回失败状态'
            assert 'HTTP 探测返回失败状态' in complete['response']
            assert 'HTTP 健康检查失败' not in complete['response']
            assert report['diagnosis'] == diagnosis and report['report'] == complete['response']
            assert report['investigation'] == complete['investigation']
            assert cause not in diagnosis['conclusion'] and cause not in complete['response']
            assert '更深原因尚未确认' in complete['response']
            assert 'model_suggestion' not in complete['investigation']
            emitted = [event for event in events if event['type'] == 'evidence']
            assert len(emitted) == evidence_count
            seen_ids = set()
            for event in events:
                if event['type'] == 'evidence':
                    seen_ids.add(event['evidence_id'])
                investigation = event.get('investigation')
                if investigation and investigation.get('evidence_summaries'):
                    assert {item['evidence_id'] for item in investigation['evidence_summaries']} <= seen_ids
            summaries = complete['investigation']['evidence_summaries']
            assert [item['evidence_id'] for item in summaries] == [item['evidence_id'] for item in emitted]
            for item, historical in zip(summaries, rows):
                raw = historical['raw']
                assert item['operation'] == raw['operation']
                assert item['collected_at'] == raw['collected_at']
                assert set(item) == {'evidence_id', 'operation', 'subject', 'collected_at',
                                     'summary', 'status', 'truncated', 'error'}
            assert 'HTTP 503' in summaries[0]['summary']
            if evidence_count >= 2 and case == 'application_config_error':
                assert summaries[1]['subject'] == 'downstream'
                assert 'TCP ok, HTTP 200' in summaries[1]['summary']
                middle = next(event['investigation'] for event in events
                    if len(event.get('investigation', {}).get('evidence_summaries', [])) == 2)
                if evidence_count == 3:
                    assert middle['next_check'] == '检查入口日志'
                    assert middle['discriminating_question'] == '下游连通异常还是应用自身异常'
            advice = diagnosis['recommendations']
            assert advice and all(item['status'] == 'manual_review_required' for item in advice)
            assert all(item['evidence'] and item['preconditions'] and item['risks']
                       and item['verification_steps'] for item in advice)
            assert all(ref['evidence_id'] in {event['evidence_id'] for event in emitted}
                       for item in advice for ref in item['evidence'])
            advice_text = complete['response'].split('人工处理建议', 1)[1]
            assert '尚未执行' in advice_text and '不作为根因证明' in advice_text
            if case == 'downstream_unreachable' and evidence_count >= 2:
                assert any(item['finding_code'] == 'dependency_tcp_failed' for item in advice)
                assert '不能说明退出原因' in advice_text
            else:
                assert all(item['finding_code'] != 'dependency_tcp_failed' for item in advice)
            assert all('配置解析失败' not in item['action'] for item in advice)
            if evidence_count == 1:
                assert all(item['finding_code'] == 'dependency_http_failed' for item in advice)
            assert [e['collected_at'] for e in emitted] == [r['raw']['collected_at'] for r in rows[:evidence_count]]
            assert calls == [(name, next(iter(args.values()))) for name, args in step_calls[:evidence_count]]
            assert execution_decisions.await_count == evidence_count * 2
            assert fixed_decisions.await_count == evidence_count
            assert next(event for event in events if event['type'] == 'usage')['llm_calls'] == 0
            assert run_store.get_run(tid).status == 'completed'
            assert run_store.get_run(tid).report == complete['response']
            snapshot = await (await service._persistent_graph(service._create_run_strategy())).aget_state({'configurable': {'thread_id': tid}})
            assert snapshot.next == () and len(snapshot.values['past_steps']) == evidence_count
            assert snapshot.values['investigation_memory']['root_cause'] == ''
            assert snapshot.values['investigation_memory']['model_suggestion']['root_cause'] == cause
    finally:
        await service.close()
    reopened = graph_module.AIOpsService()
    monkeypatch.setattr(api, 'aiops_service', reopened)
    calls_before = list(calls)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            refreshed = await client.get(f'/api/v1/aiops/runs/{tid}')
            assert refreshed.status_code == 200
            refreshed = refreshed.json()
            assert refreshed['diagnosis'] == diagnosis
            assert refreshed['investigation'] == complete['investigation']
            assert refreshed['report'] == complete['response'] and refreshed['status'] == 'completed'
            ledger = (await client.get(f'/api/v1/aiops/runs/{tid}/evidence')).json()
            assert ledger['total'] == evidence_count
            assert all(not item['fresh'] for item in ledger['evidence'])
            ids = {e['evidence_id'] for e in ledger['evidence']}
            assert ids == {e['evidence_id'] for e in emitted}
            assert {c['evidence_id'] for c in diagnosis['evidence']} <= ids
            raw_returns = []
            for event, historical in zip(emitted, rows):
                item = await client.get(f'/api/v1/aiops/runs/{tid}/evidence/{event["evidence_id"]}')
                assert item.status_code == 200
                raw = item.json()['raw']
                assert raw == historical['raw']
                raw_returns.append(raw)
            steps = (await client.get(f'/api/v1/aiops/runs/{tid}/steps')).json()
            assert steps['total'] == 1 + 2 * evidence_count
            owner.role = 'user'
            regular_ledger = (await client.get(f'/api/v1/aiops/runs/{tid}/evidence')).json()
            assert regular_ledger['can_read_raw'] is False
            regular_item = (await client.get(f'/api/v1/aiops/runs/{tid}/evidence/{emitted[0]["evidence_id"]}')).json()
            assert 'raw' not in regular_item and 'raw_ref' not in regular_item
            assert (await client.get(f'/api/v1/aiops/runs/{tid}')).json()['diagnosis'] == diagnosis
            app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=18, role='auditor')
            assert (await client.get(f'/api/v1/aiops/runs/{tid}')).status_code == 404
            assert (await client.get(f'/api/v1/aiops/runs/{tid}/evidence')).status_code == 404
            assert calls == calls_before and fixed_decisions.await_count == evidence_count
            assert FIXTURE.read_bytes() == original
            (tmp_path / 'output-audit.json').write_text(json.dumps({'mode': 'historical_fixed_decision_api_check',
                'case': case, 'group': f'G{int(protection)}{int(trigger)}', 'evidence_count': evidence_count,
                'model_calls': 0, 'new_observations': 0, 'autonomous_model_verified': False,
                'historical_validation_time': when.isoformat(), 'events': events,
                'refreshed': refreshed, 'ledger': ledger, 'regular_ledger': regular_ledger,
                'raw_returns': raw_returns}, ensure_ascii=False, indent=2), encoding='utf-8')
    finally:
        await reopened.close()
        database.dispose()
