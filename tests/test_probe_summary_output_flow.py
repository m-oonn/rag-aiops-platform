"""Constructed Probe shapes through the real API, executor, graph and reopened SQLite."""
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
from src.database.sql_session import Base
from src.probe.protocol import evidence
from src.settings import settings
from tests.test_matching503_output_flow import close_test_sse_watchers


@pytest.mark.asyncio
async def test_probe_coverage_states_survive_real_sse_and_reopened_refresh(
        tmp_path, monkeypatch, close_test_sse_watchers):
    graph = importlib.import_module('src.agent.aiops.graph')
    executor = importlib.import_module('src.agent.aiops.executor')
    inv = importlib.import_module('src.agent.aiops.strategies.investigation')
    from src.api.routers import aiops as api
    from src.api.dependencies import get_current_user

    for name, value in {
        'PROBE_ENABLED': True, 'TERMCP_ENABLED': False, 'ENABLE_HITL': False,
        'ENABLE_STEP_SNAPSHOTS': True, 'ENABLE_DYNAMIC_CLASSIFICATION': False,
        'INVESTIGATION_HYPOTHESIS_PROTECTION': True, 'INVESTIGATION_CONTRADICTION_TRIGGER': True,
        'AIOPS_CHECKPOINT_DB_PATH': str(tmp_path / 'checkpoints.sqlite'),
        'PROBE_EVIDENCE_DIR': str(tmp_path / 'evidence'),
    }.items():
        monkeypatch.setattr(settings, name, value)
    database = create_engine('sqlite:///' + (tmp_path / 'runs.sqlite').as_posix())
    Base.metadata.create_all(database)
    monkeypatch.setattr(run_store, 'SessionLocal', sessionmaker(bind=database))
    # Constructed coverage cases, never observations collected from a live target.
    definitions = [
        ('probe_service_status', 'services', {'service': 'localapp'},
         {'service': 'localapp', 'kind': 'process', 'state': 'not_applicable',
          'reason': 'process application; use process and entry observations'}, 'not_applicable'),
        ('probe_event_log', 'event_logs', {'service': 'localapp'},
         {'service': 'localapp', 'channels': [], 'events': [],
          'error': 'no event channels configured'}, 'not_applicable'),
        ('probe_port_snapshot', 'ports', {'local_port': 7063},
         {'local_port': 7063, 'ports': [], 'limit': 256, 'listening_only': False,
          'error': 'AccessDenied <img src=x onerror=alert(1)>'}, 'unavailable'),
        ('probe_resource_snapshot', 'resources', {},
         {'cpu_percent': 12.5, 'memory': {'percent': 55.2},
          'disks': [{'mountpoint': 'D:', 'error': 'unavailable'}]}, 'partial'),
        ('probe_process_snapshot', 'processes', {'service': 'localapp'},
         {'service': 'localapp', 'processes': [{'pid': 42, 'name': 'sample.exe'}]}, 'partial'),
        ('probe_dependency_probe', 'dependency_probe', {'dependency': 'downstream'},
         {'dependency': 'downstream', 'tcp': 'failed', 'http': {'error': 'URLError'}}, 'observed'),
    ]
    rows = [evidence(target_id=settings.PROBE_TARGET_ID, operation=op, payload=body)
            for _, op, _, body, _ in definitions]
    calls = []

    def make_tool(index):
        async def collect(service: str | None = None, local_port: int | None = None,
                          dependency: str | None = None):
            """Return a constructed, allowlisted coverage case."""
            arguments = {k: v for k, v in locals().items()
                         if k in {'service', 'local_port', 'dependency'} and v is not None}
            assert arguments == definitions[index][2]
            calls.append(definitions[index][0])
            return rows[index]
        return StructuredTool.from_function(coroutine=collect, name=definitions[index][0])

    tools = [make_tool(i) for i in range(len(definitions))]
    monkeypatch.setattr(executor, '_get_tools_for_state', AsyncMock(return_value=(tools, None)))
    monkeypatch.setattr(executor, 'create_agent_llm', lambda **kw: SimpleNamespace(bind_tools=lambda _: object()))
    messages = []
    for i, (name, _, arguments, _, _) in enumerate(definitions):
        messages.extend([AIMessage(content='', tool_calls=[{'id': f'coverage-{i}', 'name': name, 'args': arguments}]),
                         AIMessage(content='固定覆盖状态测试，不是自主判断')])
    execution = AsyncMock(side_effect=messages)
    monkeypatch.setattr(executor, 'ainvoke_with_retry', execution)

    async def planner(state):
        return {'plan': ['核对服务口径'], 'target_resolution': {'status': 'resolved',
            'target_id': settings.PROBE_TARGET_ID, 'allowed_dependencies': ['downstream'],
            'allowed_services': ['localapp'], 'services': {'localapp': {'expected_ports': [7063]}}}}

    monkeypatch.setattr(graph, 'planner', planner)
    monkeypatch.setattr(inv, 'create_agent_llm', lambda **kw: object())

    async def decide(*args, **kwargs):
        context = json.loads(args[3]['evidence'])
        count = len(context)
        if count < len(rows):
            return inv.InvestigationDecision(hypothesis='原因尚未核实',
                next_check=f'继续覆盖检查{count}', next_tools=[definitions[count][0]],
                next_arguments={definitions[count][0]: definitions[count][2]},
                discriminating_question='对象不适用、查询不可用还是现场异常',
                expected_observation='适用检查返回的有限事实')
        return inv.InvestigationDecision(hypothesis='原因尚未核实', scope='专用测试对象',
            next_check='继续覆盖检查5', next_tools=['probe_dependency_probe'],
            next_arguments={'probe_dependency_probe': {'dependency': 'downstream'}},
            repeat_reason='核实本轮连接失败是否持续', repeat_evidence_ids=list(context)[-1:],
            discriminating_question='TCP失败的更深原因是否已核实',
            expected_observation='能独立验证连接失败原因的现场证据',
            blocked_reason='构造检查结束，更深原因未验证')

    decisions = AsyncMock(side_effect=decide)
    monkeypatch.setattr(inv, 'ainvoke_structured', decisions)
    service = graph.AIOpsService()
    monkeypatch.setattr(api, 'aiops_service', service)
    app = FastAPI()
    app.include_router(api.router, prefix='/api/v1/aiops')
    owner = SimpleNamespace(id=17, role='auditor')
    app.dependency_overrides[get_current_user] = lambda: owner
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.post('/api/v1/aiops', json={'query': '核对专用对象，构造覆盖状态验收'})
            assert response.status_code == 200
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
            assert not [e for e in events if e['type'] == 'error'], events
            complete = next(e for e in events if e['type'] == 'complete')
            report = next(e for e in events if e['type'] == 'report')
            emitted = [e for e in events if e['type'] == 'evidence']
            assert len(emitted) == len(rows)
            summaries = complete['investigation']['evidence_summaries']
            assert [s['status'] for s in summaries] == [d[-1] for d in definitions]
            assert report['investigation'] == complete['investigation']
            seen = set()
            for event in events:
                if event['type'] == 'evidence':
                    seen.add(event['evidence_id'])
                assert {s['evidence_id'] for s in event.get('investigation', {}).get('evidence_summaries', [])} <= seen
            for summary, row, event in zip(summaries, rows, emitted):
                assert summary['evidence_id'] == event['evidence_id']
                assert summary['operation'] == row['operation']
                assert summary['collected_at'] == row['collected_at']
            assert 'skipped unknown' in summaries[4]['summary']
            assert 'TCP failed' in summaries[-1]['summary'] and not summaries[-1]['error']
            assert {f['code'] for f in complete['diagnosis']['observed_findings']} == {'dependency_tcp_failed'}
            assert complete['diagnosis']['kind'] == 'localized_fault'
            question = complete['diagnosis']['unresolved_questions'][0]
            # The scripted repeat check is rejected as an unexplained resample, so the
            # engine records that reviewed stop and drops the rejected check instead of
            # advertising it as a pending question.  The still-unverified dependency gap
            # remains the open question.
            assert question['id'].startswith('gap-dependency-')
            assert question['question'] == 'downstream 连接失败的更深原因是什么？'
            assert '无法核查退出或启动失败原因' in question['limitation']
            assert question['evidence_ids'] == [emitted[-1]['evidence_id']]
            assert '首选检查受阻' in complete['diagnosis']['stop_reason']
            assert '再次采样须说明复核目的' in complete['diagnosis']['stop_reason']
            assert next(e for e in events if e['type'] == 'usage')['llm_calls'] == 0
            tid = complete['thread_id']
    finally:
        await service.close()
    reopened = graph.AIOpsService()
    monkeypatch.setattr(api, 'aiops_service', reopened)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            refreshed = (await client.get(f'/api/v1/aiops/runs/{tid}')).json()
            assert refreshed['investigation'] == complete['investigation']
            assert refreshed['report'] == complete['response']
            raw_returns = [(await client.get(f'/api/v1/aiops/runs/{tid}/evidence/{e["evidence_id"]}')).json()['raw'] for e in emitted]
            assert raw_returns == rows
            owner.role = 'user'
            ledger = (await client.get(f'/api/v1/aiops/runs/{tid}/evidence')).json()
            assert ledger['can_read_raw'] is False
            assert (await client.get(f'/api/v1/aiops/runs/{tid}/evidence/{emitted[0]["evidence_id"]}')).json().get('raw') is None
            assert calls == [d[0] for d in definitions]
            assert execution.await_count == 2 and decisions.await_count == len(rows)
            persisted = await reopened._persistent_graph(reopened._create_run_strategy())
            config = {'configurable': {'thread_id': tid}}
            snapshot = await persisted.aget_state(config)
            memory = dict(snapshot.values['investigation_memory'])
            memory['evidence_summaries'] = [
                {key: value for key, value in item.items() if key != 'status'}
                for item in memory['evidence_summaries']]
            # An old checkpoint shape is constructed explicitly; do not mutate old artifacts.
            await persisted.aupdate_state(config, {'investigation_memory': memory})
            legacy_refreshed = (await client.get(f'/api/v1/aiops/runs/{tid}')).json()
            assert all('status' not in item for item in legacy_refreshed['investigation']['evidence_summaries'])
            assert legacy_refreshed['report'] == refreshed['report']
            assert calls == [d[0] for d in definitions] and decisions.await_count == len(rows)
            (tmp_path / 'output-audit.json').write_text(json.dumps({
                'mode': 'constructed_fixed_decision_coverage_flow', 'model_calls': 0,
                'new_observations': 0, 'autonomous_effectiveness_verified': False,
                'events': events, 'refreshed': refreshed, 'ledger': ledger,
                'raw_returns': raw_returns, 'legacy_refreshed': legacy_refreshed}, ensure_ascii=False, indent=2), encoding='utf-8')
    finally:
        await reopened.close()
        database.dispose()
