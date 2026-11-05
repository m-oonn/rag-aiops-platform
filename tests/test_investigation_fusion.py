import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.orm import sessionmaker

from src.agent.aiops import run_store
from src.agent.aiops.evidence_reader import read_run_evidence, evidence_read_tool
from src.agent.aiops.target_catalog import resolve_target, normalized_url
from src.agent.aiops.observations import observation_clues
from src.agent.aiops.strategies import investigation as inv
from src.probe.protocol import evidence
from src.settings import settings


def catalog(**services):
    return json.dumps({'version': 1, 'target_id': settings.PROBE_TARGET_ID, 'services': services})


def test_exact_business_resolution_and_conflicts_do_not_grant_permissions():
    raw = catalog(orders={'aliases': ['订单'], 'probe_service': 'svc', 'dependencies': ['db'],
                          'entries': {'http://localhost:8080/health': 'entry'}, 'expected_ports': [8080]})
    inventory = {'configured_services': {'svc': {}}, 'configured_dependencies': ['entry']}
    found = resolve_target(raw, '订单打不开', inventory, settings.PROBE_TARGET_ID)
    assert found['status'] == 'resolved'
    assert found['allowed_dependencies'] == ['entry'] and found['allowed_services'] == ['svc']
    assert found['mismatches']
    assert resolve_target(raw, '检查 https://unknown.example/', inventory, settings.PROBE_TARGET_ID)['status'] == 'unmatched'
    assert resolve_target(raw, '检查 https://orders.example/', inventory, settings.PROBE_TARGET_ID)['status'] != 'resolved'
    assert resolve_target(raw, 'orders-other', inventory, settings.PROBE_TARGET_ID)['status'] != 'resolved'
    assert resolve_target(raw, '本机运行概况', inventory, settings.PROBE_TARGET_ID)['status'] == 'host_overview'
    ambiguous = catalog(one={'aliases': ['共同']}, two={'aliases': ['共同']})
    assert resolve_target(ambiguous, '共同', inventory, settings.PROBE_TARGET_ID)['status'] == 'ambiguous'
    assert normalized_url('http://localhost:443/') != normalized_url('https://localhost/')
    assert resolve_target('old reference', 'orders', {}, settings.PROBE_TARGET_ID)['status'] == 'legacy_reference'


def test_dependency_service_mapping_is_explicit_and_inventory_restricted():
    catalog = {'version': 1, 'target_id': settings.PROBE_TARGET_ID, 'services': {
        'entry': {'dependencies': ['db'], 'dependency_services': {'db': 'db-worker', 'rogue': 'other'}}}}
    inventory = {'configured_dependencies': ['db'], 'configured_services': {'db-worker': {}, 'other': {}}}
    found = resolve_target(json.dumps(catalog), 'entry', inventory, settings.PROBE_TARGET_ID)
    assert found['status'] == 'resolved'
    assert found['allowed_services'] == ['db-worker']
    assert found['dependency_services'] == {'db': 'db-worker'}
    inventory['configured_services'] = {}
    found = resolve_target(json.dumps(catalog), 'entry', inventory, settings.PROBE_TARGET_ID)
    assert found['allowed_services'] == [] and found['dependency_services'] == {}


def _wrong_endpoint_state(*, mapped=True, same_port=False, omit=(), truncate=()):
    upstream_port = 11750 if same_port else 11751
    snapshot = evidence(target_id=settings.PROBE_TARGET_ID, operation='configuration', payload={
        'service': 'localapp', 'path': 'C:/app/connection.json', 'source_sha256': 'abc123',
        'values': {'downstream_port': upstream_port}})
    upstream = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe', payload={
        'dependency': 'localapp_upstream', 'host': '127.0.0.1', 'port': upstream_port,
        'tcp': 'failed', 'http': {'error': 'connection refused'}})
    downstream = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe', payload={
        'dependency': 'downstream', 'host': '127.0.0.1', 'port': 11750, 'tcp': 'ok',
        'http': {'status': 200}})
    items = [('config', snapshot), ('upstream', upstream), ('downstream', downstream)]
    raw = [(name, json.dumps({**value, **({'truncated': True} if name in truncate else {})}))
           for name, value in items if name not in omit]
    state = {'raw_evidence': raw, 'target_resolution': {
        'status': 'resolved', 'target_id': settings.PROBE_TARGET_ID,
        'allowed_services': ['localapp', 'downstream'],
        'allowed_dependencies': ['localapp_upstream', 'downstream'],
        'dependency_services': {'downstream': 'downstream'} if mapped else {},
    }}
    return state


def test_wrong_downstream_endpoint_finding_cites_snapshot_and_both_probes():
    state = _wrong_endpoint_state()
    findings = inv._localized_findings(inv.evidence_index(state), state)
    mismatch = next(item for item in findings if item['code'] == 'configured_downstream_endpoint_mismatch')
    assert 'downstream_port=11751' in mismatch['summary']
    assert '11750' in mismatch['summary'] and 'HTTP 200' in mismatch['summary']
    assert mismatch['causal'] is False
    assert len(mismatch['related_evidence']) == 2
    assert {item['evidence_id'] for item in mismatch['related_evidence']} == {'e2.1', 'e3.1'}
    assert mismatch['quote']


def test_endpoint_root_cause_requires_configured_failure_and_matching_business_request_logs():
    state = _wrong_endpoint_state()
    state['target_resolution']['allowed_services'].append('edge')
    request_id = 'request-123'
    localapp_event = {'event': 'request_completed', 'request_id': request_id,
        'path': '/api/availability', 'status': 503, 'detail': 'upstream connection failed',
        'upstream': {'port': 11751}, 'configuration': {'source_sha256': 'abc123'}}
    edge_event = {'event': 'request_completed', 'request_id': request_id,
        'path': '/api/availability', 'status': 503}
    state['raw_evidence'].extend([
        ('localapp log', json.dumps(evidence(target_id=settings.PROBE_TARGET_ID,
            operation='text_logs', payload={'service': 'localapp', 'lines': [json.dumps(localapp_event)]}))),
        ('edge log', json.dumps(evidence(target_id=settings.PROBE_TARGET_ID,
            operation='text_logs', payload={'service': 'edge', 'lines': [json.dumps({'status': None}),
                json.dumps(edge_event)]}))),
    ])
    records = inv.evidence_index(state)

    required = inv._confirmed_endpoint_cause_evidence(records, state)

    assert required == {'e1.1', 'e2.1', 'e3.1', 'e4.1', 'e5.1'}
    decision = inv.InvestigationDecision(
        hypothesis='localapp 使用了未登记的下游端口',
        root_cause='localapp 启动时加载的 downstream_port 与登记服务不一致，导致该业务请求连接失败',
        root_cause_code='configured_downstream_endpoint_mismatch', outcome='root_cause',
        conclusion_level='confirmed_cause', scope='edge /api/availability 本次失败请求',
        supporting_evidence=[inv.Citation(evidence_id=ident, quote=records[ident]['payload'][:300])
            for ident in sorted(required)],
        alternatives=[inv.Alternative(explanation='downstream 曾在 5889 提供服务后迁移；何时迁移仍未知',
            status='unresolved', critical=False,
            noncritical_reason='该历史可能解释配置为何过期，但不否定本次请求中 localapp 指向无监听端口导致失败。')])
    accepted = inv.decide_from_evidence(state, decision, records)
    assert accepted['diagnosis']['kind'] == 'confirmed_cause'
    assert 'localapp 启动时加载的 downstream_port' in accepted['response']
    assert accepted['diagnosis']['alternatives'][0]['status'] == 'unresolved'
    state['raw_evidence'].pop()
    incomplete_records = inv.evidence_index(state)
    assert not inv._confirmed_endpoint_cause_evidence(incomplete_records, state)
    rejected = inv.decide_from_evidence(state, decision, incomplete_records)
    assert rejected['diagnosis']['kind'] == 'localized_fault'


def test_wrong_downstream_endpoint_reaches_cited_diagnosis_and_actionable_report():
    from src.agent.aiops.reporting import build_bundle, render_report, rule_layout

    state = _wrong_endpoint_state()
    records = inv.evidence_index(state)
    diagnosis = inv.diagnosis_result(state, inv.InvestigationDecision(hypothesis='原因尚未知'),
        'localized_fault', records, reason='有限检查已完成；更深原因未知。')
    mismatch = next(item for item in diagnosis['observed_findings']
                    if item['code'] == 'configured_downstream_endpoint_mismatch')
    advice = next(item for item in diagnosis['recommendations']
                  if item['finding_code'] == 'configured_downstream_endpoint_mismatch')
    bundle = build_bundle(diagnosis, records=records, resolution=state['target_resolution'])
    report = render_report(bundle, rule_layout(bundle))

    assert [ref['evidence_id'] for ref in advice['evidence']] == ['e1.1', 'e2.1', 'e3.1']
    assert 'downstream_port=11751' in report
    assert '登记的 downstream（端口 11750）' in report
    assert '端点错配解释' in report
    assert '更深原因尚未确认' in report
    assert all(ref['quote'] for ref in [
        {'quote': mismatch['quote']}, *mismatch['related_evidence'], *advice['evidence']])


@pytest.mark.parametrize('state', [
    _wrong_endpoint_state(mapped=False),
    _wrong_endpoint_state(same_port=True),
    _wrong_endpoint_state(omit=('downstream',)),
    _wrong_endpoint_state(truncate=('config',)),
    {'raw_evidence': _wrong_endpoint_state()['raw_evidence'],
     'target_resolution': {'status': 'unmatched'}},
])
def test_wrong_downstream_endpoint_finding_requires_complete_explicit_scope(state):
    findings = inv._localized_findings(inv.evidence_index(state), state)
    assert 'configured_downstream_endpoint_mismatch' not in {item['code'] for item in findings}


def test_negative_process_query_requires_configured_names_and_complete_access():
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='processes', payload={
        'service': 'svc', 'processes': [], 'skipped_count': 0})
    current = {'raw_evidence': [('processes', json.dumps(raw))]}
    assert observation_clues(inv.evidence_index(current)) == []
    inventory = evidence(target_id=settings.PROBE_TARGET_ID, operation='inventory', payload={
        'configured_services': {'svc': {'process_names': ['app.exe']}}})
    current['raw_evidence'].insert(0, ('inventory', json.dumps(inventory)))
    clue = observation_clues(inv.evidence_index(current))[0]
    assert clue['code'] == 'configured_process_not_observed'
    assert clue['summary'] == '本次可枚举范围内未发现配置进程'
    raw['truncated'] = True
    current['raw_evidence'][-1] = ('processes', json.dumps(raw))
    assert [c['code'] for c in observation_clues(inv.evidence_index(current))] == ['truncated_observation']


@pytest.fixture
def ledger(engine, tmp_path, monkeypatch):
    monkeypatch.setattr(run_store, 'SessionLocal', sessionmaker(bind=engine))
    monkeypatch.setattr(settings, 'PROBE_EVIDENCE_DIR', str(tmp_path / 'evidence'))
    tid = 'fusion-' + uuid4().hex
    run_store.create_run(tid, 712, 'read evidence')
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='services', payload={'service': 'svc', 'state': 'running'},
        collected_at=(datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat().replace('+00:00', 'Z'))
    eid = run_store.add_evidence(tid, 712, settings.PROBE_TARGET_ID, 'services', raw)
    return tid, eid, raw


def test_evidence_reader_owner_thread_paging_integrity_and_old_time(ledger):
    tid, eid, raw = ledger
    first = read_run_evidence(tid, 712, eid, limit=40)
    assert first['fresh'] is False and first['new_observation'] is False
    assert run_store._parse_utc(first['collected_at']) == run_store._parse_utc(raw['collected_at'])
    assert first['next_offset'] == 40 and first['truncated']
    filtered = read_run_evidence(tid, 712, eid, query='running')
    assert 'running' in filtered['excerpt']
    with pytest.raises(PermissionError): read_run_evidence(tid, 999, eid)
    other = 'other-' + uuid4().hex
    run_store.create_run(other, 712, 'other')
    with pytest.raises(PermissionError): read_run_evidence(other, 712, eid)
    with pytest.raises(ValueError): read_run_evidence(tid, 712, eid, limit=16385)
    from pathlib import Path
    path = Path(run_store.get_evidence(tid, eid, 712)['raw_ref'])
    saved = json.loads(path.read_text(encoding='utf-8'))
    saved['payload']['state'] = 'stopped'
    path.write_text(json.dumps(saved), encoding='utf-8')
    with pytest.raises(ValueError, match='integrity'): read_run_evidence(tid, 712, eid)
    assert len(run_store.list_evidence(tid, 712)) == 1
    assert set(evidence_read_tool(tid, 712).args) == {'evidence_id', 'query', 'offset', 'limit'}


@pytest.mark.parametrize(('field', 'value'), [('platform', 'linux'), ('data_source', 'knowledge_base')])
def test_evidence_reader_rejects_changed_provenance(ledger, field, value):
    from pathlib import Path
    tid, eid, raw = ledger
    path = Path(run_store.get_evidence(tid, eid, 712)['raw_ref'])
    saved = json.loads(path.read_text(encoding='utf-8'))
    saved[field] = value
    path.write_text(json.dumps(saved), encoding='utf-8')
    with pytest.raises(ValueError, match='integrity'):
        read_run_evidence(tid, 712, eid)


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['critical_unavailable', 'status_only', 'global_healthy', 'entry_503', 'healthy_missing_dependency'])
async def test_strict_conclusions_reject_unsupported_cases(monkeypatch, case):
    payload = {'service': 'svc', 'state': 'running'}
    operation = 'services'
    level, outcome, cause, scope = 'confirmed_cause', 'root_cause', 'database crashed', 'svc'
    alternative = inv.Alternative(explanation='another explanation', status='excluded',
        evidence=[inv.Citation(evidence_id='e1.1', quote='running')])
    if case == 'critical_unavailable':
        operation, payload = 'text_logs', {'lines': ['fatal error']}
        alternative = inv.Alternative(explanation='network', status='unavailable', limitation='no permission')
    if case in {'global_healthy', 'healthy_missing_dependency'}:
        level, outcome, cause = 'healthy_within_scope', 'healthy', ''
        scope = '整机长期健康' if case == 'global_healthy' else 'orders'
    if case == 'entry_503':
        operation, payload = 'dependency_probe', {'dependency': 'entry', 'tcp': 'ok', 'http': {'status': 503}}
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation=operation, payload=payload)
    current = {'input': 'symptom', 'raw_evidence': [('check', json.dumps(raw))], 'plan': []}
    if case == 'healthy_missing_dependency':
        current['target_resolution'] = {'status': 'resolved', 'allowed_services': ['svc'], 'allowed_dependencies': ['db']}
    quote = next(iter(payload))
    answer = inv.InvestigationDecision(hypothesis='candidate', conclusion_level=level, outcome=outcome,
        root_cause=cause, scope=scope, supporting_evidence=[inv.Citation(evidence_id='e1.1', quote=quote)], alternatives=[alternative])
    monkeypatch.setattr(inv, 'ainvoke_structured', AsyncMock(return_value=answer))
    result = await inv.InvestigationStrategy().decide(current)
    assert result['diagnosis']['kind'] == ('localized_fault' if case == 'entry_503' else 'unlocated')


def test_concrete_repeat_guard_keeps_an_unchecked_service_executable():
    from src.agent.aiops.executor import _probe_request_limit
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='services', payload={'service': 'one', 'state': 'running'})
    state = {'autonomous_investigation': True, 'raw_evidence': [('one', json.dumps(raw)), ('again', json.dumps(raw))]}
    assert _probe_request_limit({'name': 'probe_service_status', 'args': {'service': 'one'}}, state)
    assert _probe_request_limit({'name': 'probe_service_status', 'args': {'service': 'two'}}, state) == ''


@pytest.mark.parametrize('change', ['same', 'path_spelling', 'more_lines', 'other_path', 'other_service'])
def test_log_repeat_guard_uses_normalized_path_and_the_actual_line_limit(change):
    from src.agent.aiops.executor import _probe_request_limit
    payload = {'service': 'entry', 'path': 'D:\\demo\\app.log', 'line_limit': 100, 'lines': []}
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='text_logs', payload=payload)
    state = {'autonomous_investigation': True,
        'raw_evidence': [('read', json.dumps(raw)), ('confirm', json.dumps(raw))]}
    args = {'service': 'entry', 'path': 'D:\\demo\\app.log', 'lines': 100}
    if change == 'path_spelling': args['path'] = 'd:/demo/./APP.log'
    if change == 'more_lines': args['lines'] = 200
    if change == 'other_path': args['path'] = 'D:/demo/other.log'
    if change == 'other_service': args['service'] = 'downstream'
    assert bool(_probe_request_limit({'name': 'probe_text_log', 'args': args}, state)) is (change in {'same', 'path_spelling'})


@pytest.mark.asyncio
async def test_newer_normal_observation_blocks_old_fault_conclusion(monkeypatch):
    stopped = evidence(target_id=settings.PROBE_TARGET_ID, operation='services', payload={'service': 'svc', 'state': 'stopped'})
    running = evidence(target_id=settings.PROBE_TARGET_ID, operation='services', payload={'service': 'svc', 'state': 'running'})
    current = {'input': 'symptom', 'raw_evidence': [('old', json.dumps(stopped)), ('new', json.dumps(running))]}
    answer = inv.InvestigationDecision(hypothesis='stopped', conclusion_level='localized_fault',
        scope='svc', localized_fault='someone deliberately stopped service',
        supporting_evidence=[inv.Citation(evidence_id='e1.1', quote='stopped')])
    monkeypatch.setattr(inv, 'ainvoke_structured', AsyncMock(return_value=answer))
    result = await inv.InvestigationStrategy().decide(current)
    assert result['diagnosis']['kind'] == 'unlocated'
    assert result['diagnosis']['contradictions']
    assert result['diagnosis']['recommendations'] == []


def test_superseded_observations_use_collection_time_not_insertion_order():
    now = datetime.now(timezone.utc)
    newer = evidence(target_id=settings.PROBE_TARGET_ID, operation='services',
        payload={'service': 'svc', 'state': 'running'}, collected_at=now.isoformat())
    older = evidence(target_id=settings.PROBE_TARGET_ID, operation='services',
        payload={'service': 'svc', 'state': 'stopped'}, collected_at=(now - timedelta(seconds=15)).isoformat())
    records = inv.evidence_index({'raw_evidence': [('newer', json.dumps(newer)), ('older delayed', json.dumps(older))]})
    assert inv.superseded_citations([inv.Citation(evidence_id='e1.1', quote='running')], records) == []
    assert inv.superseded_citations([inv.Citation(evidence_id='e2.1', quote='stopped')], records)


@pytest.mark.parametrize('changed', [False, True])
def test_dependency_timing_jitter_is_not_a_conflict_or_new_diagnostic_information(changed):
    from src.agent.aiops.executor import _probe_request_limit
    samples = [evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
        payload={'dependency': 'db', 'tcp': 'ok' if changed and i else 'failed',
                 'http': {'status': 503}, 'elapsed_ms': 10 + i}) for i in range(2)]
    state = {'autonomous_investigation': True,
             'raw_evidence': [('probe', json.dumps(item)) for item in samples]}
    records = inv.evidence_index(state)
    conflicts = inv.superseded_citations([inv.Citation(evidence_id='e1.1', quote='failed')], records)
    repeated = _probe_request_limit({'name': 'probe_dependency_probe', 'args': {'dependency': 'db'}}, state)
    assert bool(conflicts) is changed
    assert bool(repeated) is not changed
    assert samples[0]['raw_hash'] != samples[1]['raw_hash']


@pytest.mark.parametrize('tool,operation,payload,changed', [
    ('probe_event_log', 'event_logs', {'service': 'entry', 'events': []}, {'since_minutes': 120}),
    ('probe_event_log', 'event_logs', {'service': 'entry', 'events': []}, {'limit': 100}),
    ('probe_port_snapshot', 'ports', {'local_port': 8000, 'ports': []}, {'local_port': 8001}),
    ('probe_port_snapshot', 'ports', {'local_port': 8000, 'ports': []}, {'listening_only': True}),
    ('probe_process_snapshot', 'processes', {'service': 'entry', 'processes': []}, {'sort_by': 'cpu'}),
])
def test_repeat_guard_keeps_changed_query_filters_executable(tool, operation, payload, changed):
    args = {key: payload[key] for key in ('service', 'local_port') if key in payload}
    state = {'raw_evidence': [('sample', json.dumps(evidence(target_id=settings.PROBE_TARGET_ID,
        operation=operation, payload=payload))) for _ in range(2)]}
    assert inv.repeated_probe_arguments(tool, args, state)
    assert not inv.repeated_probe_arguments(tool, {**args, **changed}, state)


@pytest.mark.parametrize('invalid', ['single', 'expired', 'wrong_target', 'error'])
def test_repeat_guard_requires_two_valid_returns(invalid):
    payload = {'dependency': 'db', 'tcp': 'failed'}
    if invalid == 'error': payload['error'] = 'unavailable'
    state = {'raw_evidence': [('sample', json.dumps(evidence(
        target_id='other' if invalid == 'wrong_target' else settings.PROBE_TARGET_ID,
        collected_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat() if invalid == 'expired' else None,
        operation='dependency_probe', payload=payload))) for _ in range(1 if invalid == 'single' else 2)]}
    assert not inv.repeated_probe_arguments('probe_dependency_probe', {'dependency': 'db'}, state)


@pytest.mark.asyncio
@pytest.mark.parametrize('same_batch', [False, True])
async def test_executor_blocks_third_unchanged_query_in_same_step_but_keeps_other_object(monkeypatch, same_batch):
    import importlib
    from types import SimpleNamespace
    from langchain_core.messages import AIMessage
    from langchain_core.tools import StructuredTool
    ex = importlib.import_module('src.agent.aiops.executor')
    called = []

    async def probe(dependency: str):
        """Construct an offline dependency observation."""
        called.append(dependency)
        return evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
                        payload={'dependency': dependency, 'tcp': 'failed'})

    tool = StructuredTool.from_function(coroutine=probe, name='probe_dependency_probe')
    monkeypatch.setattr(ex, '_get_tools_for_state', AsyncMock(return_value=([tool], None)))
    monkeypatch.setattr(ex, 'create_agent_llm', lambda **kw: SimpleNamespace(bind_tools=lambda _: object()))
    calls = [{'id': str(i), 'name': tool.name, 'args': {'dependency': dependency}}
             for i, dependency in enumerate(['db', 'db', 'db', 'other'])]
    responses = ([AIMessage(content='', tool_calls=calls)] if same_batch else [
        AIMessage(content='', tool_calls=calls[:1]), AIMessage(content='', tool_calls=calls[1:])])
    monkeypatch.setattr(ex, 'ainvoke_with_retry', AsyncMock(side_effect=[*responses, AIMessage(content='done')]))
    result, raw = await ex._run_step('inspect dependencies', {'autonomous_investigation': True})
    assert result == 'done'
    assert called == ['db', 'db', 'other']
    records = inv.execution_checks({'raw_evidence': [('step', raw)]})
    assert [record['status'] for record in records] == ['success', 'success', 'unavailable', 'success']
    assert records[2]['reason'] == 'repeated_identical_observation_for_same_arguments'


@pytest.mark.asyncio
@pytest.mark.parametrize('omit_supporting_evidence', [False, True])
async def test_localized_conclusion_uses_observed_fault_not_model_causal_claim(monkeypatch,
                                                                               omit_supporting_evidence):
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='services', payload={'service': 'svc', 'state': 'stopped'})
    current = {'input': 'symptom', 'raw_evidence': [('check', json.dumps(raw))]}
    answer = inv.InvestigationDecision(hypothesis='candidate', conclusion_level='localized_fault',
        scope='svc', localized_fault='administrator stopped it',
        supporting_evidence=[] if omit_supporting_evidence else
            [inv.Citation(evidence_id='e1.1', quote='stopped')])
    monkeypatch.setattr(inv, 'ainvoke_structured', AsyncMock(return_value=answer))
    result = await inv.InvestigationStrategy().decide(current)
    assert result['diagnosis']['kind'] == 'localized_fault'
    assert 'administrator' not in result['diagnosis']['conclusion']
    assert 'svc' in result['diagnosis']['conclusion']
    assert result['diagnosis']['evidence']
    assert result['diagnosis']['evidence'][0]['evidence_id'] == 'e1.1'


@pytest.mark.asyncio
async def test_unlocated_model_keeps_observed_dependency_fault_layer(monkeypatch):
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
        payload={'dependency': 'downstream', 'tcp': 'failed', 'tcp_error': 'ConnectionRefusedError'})
    current = {'input': 'application unavailable', 'raw_evidence': [('check', json.dumps(raw))]}
    answer = inv.InvestigationDecision(hypothesis='downstream failure', conclusion_level='unlocated',
        scope='configured downstream', supporting_evidence=[inv.Citation(evidence_id='e1.1', quote='failed')])
    monkeypatch.setattr(inv, 'ainvoke_structured', AsyncMock(return_value=answer))
    result = await inv.InvestigationStrategy().decide(current)
    assert result['diagnosis']['kind'] == 'localized_fault'
    assert 'TCP' in result['diagnosis']['conclusion']
    assert 'confirmed_cause' not in result['diagnosis']['kind']


@pytest.mark.asyncio
async def test_supported_observation_cannot_be_reported_as_excluded(monkeypatch):
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
        payload={'dependency': 'downstream', 'tcp': 'failed', 'tcp_error': 'ConnectionRefusedError'})
    current = {'input': 'application unavailable', 'raw_evidence': [('check', json.dumps(raw))]}
    answer = inv.InvestigationDecision(hypothesis='downstream failure', conclusion_level='unlocated',
        scope='configured downstream', supporting_evidence=[inv.Citation(evidence_id='e1.1', quote='failed')],
        alternatives=[inv.Alternative(explanation='downstream TCP 不可达', status='excluded',
            evidence=[inv.Citation(evidence_id='e1.1', quote='failed')])])
    monkeypatch.setattr(inv, 'ainvoke_structured', AsyncMock(return_value=answer))
    result = await inv.InvestigationStrategy().decide(current)
    alternative = result['investigation_memory']['alternatives'][0]
    assert alternative['status'] == 'unresolved'
    assert alternative['original_status'] == 'excluded'
    assert result['investigation_memory']['validation_issues']


@pytest.mark.parametrize('truncated', [False, True])
def test_time_wait_is_not_listen_and_actual_truncation_controls_negative_findings(truncated):
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='ports', payload={
        'local_port': 8000, 'limit': 256, 'ports': [
            {'status': 'TIME_WAIT', 'local': {'port': 8000}, 'pid': 0}]}, truncated=truncated)
    clues = observation_clues(inv.evidence_index({'raw_evidence': [('ports', json.dumps(raw))]}))
    assert ('port_not_listening' in {c['code'] for c in clues}) is not truncated


@pytest.mark.parametrize('invalid', ['expired', 'wrong_target', 'outside_scope', 'incomplete', 'hash'])
def test_fault_fallback_rejects_untrusted_or_out_of_scope_observations(invalid):
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
        payload={'dependency': 'db', 'tcp': 'failed'})
    current = {'input': 'symptom', 'raw_evidence': []}
    if invalid == 'expired':
        raw['collected_at'] = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    if invalid == 'wrong_target': raw['target_id'] = 'other'
    if invalid == 'hash': raw['payload']['tcp'] = 'ok'
    if invalid == 'incomplete': raw['truncated'] = True
    if invalid == 'outside_scope':
        current['target_resolution'] = {'status': 'resolved', 'allowed_dependencies': ['entry']}
    current['raw_evidence'] = [('probe', json.dumps(raw))]
    result = inv.decide_from_evidence(current, inv.InvestigationDecision(hypothesis='unknown'), inv.evidence_index(current))
    assert result['diagnosis']['kind'] == 'unlocated'
    assert result['diagnosis']['observed_findings'] == []
    assert result['diagnosis']['recommendations'] == []


def test_observed_fault_does_not_stop_a_valid_new_check_and_question_id_survives():
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
        payload={'dependency': 'db', 'tcp': 'failed'})
    current = {'input': 'symptom', 'raw_evidence': [('probe', json.dumps(raw))],
        'investigation_tools': [{'name': 'probe_text_log'}]}
    proposal = inv.InvestigationDecision(hypothesis='db unreachable', next_check='inspect application log',
        next_tools=['probe_text_log'], discriminating_question='does the log show dependency failure',
        expected_observation='connection error or another application error')
    original = proposal.model_dump()
    first = inv.decide_from_evidence(current, proposal, inv.evidence_index(current))
    assert first['plan'] == ['inspect application log'] and 'diagnosis' not in first
    assert proposal.model_dump() == original
    assert first['investigation_memory']['model_suggestion'] == original
    current['investigation_memory'] = first['investigation_memory']
    second = inv.decide_from_evidence(current, proposal, inv.evidence_index(current))
    assert second['investigation_memory']['next_question_id'] == first['investigation_memory']['next_question_id']


@pytest.mark.parametrize(('status', 'expected', 'claim_type', 'verified'), [
    ('excluded', 'failed', 'observed_condition', False),
    ('excluded', 'ok', 'observed_condition', True),
    ('supported', 'failed', 'observed_condition', True),
    ('supported', 'failed', 'causal_explanation', False),
    ('excluded', 'ok', 'causal_explanation', False),
])
def test_explicit_predicates_validate_direction_without_rewriting_model(status, expected, claim_type, verified):
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
        payload={'dependency': 'db', 'tcp': 'failed'})
    current = {'input': 'symptom', 'raw_evidence': [('probe', json.dumps(raw))]}
    proposal = inv.InvestigationDecision(hypothesis='candidate', alternatives=[inv.Alternative(
        explanation=f'dependency_probe/db: tcp == {json.dumps(expected)}', status=status, claim_type=claim_type,
        condition=inv.ObservationCondition(operation='dependency_probe', object_name='db', field='tcp', expected=expected),
        evidence=[inv.Citation(evidence_id='e1.1', quote='failed')])])
    result = inv.decide_from_evidence(current, proposal, inv.evidence_index(current))
    alternative = result['diagnosis']['alternatives'][0]
    assert alternative['original_status'] == status
    assert alternative['status'] == (status if verified else 'unresolved')
    assert result['investigation_memory']['model_suggestion'] == proposal.model_dump()
    assert result['diagnosis']['kind'] == 'localized_fault'
    assert result['diagnosis']['evidence']
    assert result['diagnosis']['observed_findings'][0]['causal'] is False


def test_latest_normal_observation_removes_old_fault_from_findings():
    now = datetime.now(timezone.utc)
    old = evidence(target_id=settings.PROBE_TARGET_ID, operation='services', payload={'service': 'svc', 'state': 'stopped'},
        collected_at=(now - timedelta(seconds=10)).isoformat())
    new = evidence(target_id=settings.PROBE_TARGET_ID, operation='services', payload={'service': 'svc', 'state': 'running'},
        collected_at=now.isoformat())
    current = {'input': 'symptom', 'raw_evidence': [('new', json.dumps(new)), ('delayed old', json.dumps(old))]}
    result = inv.decide_from_evidence(current, inv.InvestigationDecision(hypothesis='unknown'), inv.evidence_index(current))
    assert result['diagnosis']['kind'] == 'unlocated'
    assert result['diagnosis']['observed_findings'] == []
    assert result['diagnosis']['recommendations'] == []


@pytest.mark.parametrize('expected', ['impossible-state', 1, True])
def test_invalid_condition_value_cannot_prove_exclusion(expected):
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
        payload={'dependency': 'db', 'tcp': 'ok'})
    state = {'input': 'symptom', 'raw_evidence': [('check', json.dumps(raw))]}
    proposal = inv.InvestigationDecision(hypothesis='candidate', alternatives=[inv.Alternative(
        explanation='TCP condition', status='excluded', claim_type='observed_condition',
        condition=inv.ObservationCondition(operation='dependency_probe', object_name='db', field='tcp', expected=expected),
        evidence=[inv.Citation(evidence_id='e1.1', quote='ok')])])
    result = inv.decide_from_evidence(state, proposal, inv.evidence_index(state))
    assert result['diagnosis']['alternatives'][0]['status'] == 'unresolved'
    assert result['diagnosis']['validation_issues']


def test_different_objects_cannot_be_combined_as_one_verified_condition():
    samples = [evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
        payload={'dependency': name, 'tcp': 'failed'}) for name in ('one', 'two')]
    state = {'input': 'symptom', 'raw_evidence': [('check', json.dumps(item)) for item in samples]}
    proposal = inv.InvestigationDecision(hypothesis='candidate', alternatives=[inv.Alternative(
        explanation='unspecified dependency', status='supported', claim_type='observed_condition',
        condition=inv.ObservationCondition(operation='dependency_probe', field='tcp', expected='failed'),
        evidence=[inv.Citation(evidence_id=f'e{i+1}.1', quote='failed') for i in range(2)])])
    result = inv.decide_from_evidence(state, proposal, inv.evidence_index(state))
    assert result['diagnosis']['alternatives'][0]['status'] == 'unresolved'
