"""Offline regressions for the four failures from the competing-fault run."""
from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

from scripts import competing_hypothesis_fixture as fixture_module
from scripts.knowledge_conditions import knowledge_conditions, check_knowledge_conditions
from scripts.mechanism_behavior import behavior_snapshot, audit_behavior
from src.agent.aiops.strategies import investigation as inv
from src.probe.evidence import validate_observation_window, EvidenceValidationError
from src.probe.protocol import evidence
from src.settings import settings
from tests.test_concrete_investigation_checks import state, decision, decide


def test_reset_boundary_precedes_startup_and_rejects_previous_logs(tmp_path, monkeypatch):
    fixture = object.__new__(fixture_module.CompetingFaultFixture)
    fixture.output, fixture.processes = tmp_path, {}
    fixture.startup_configuration = False
    old_time = datetime.now(timezone.utc).isoformat()
    for name in ('edge', 'localapp', 'downstream'):
        (tmp_path / (name + '.log')).write_text(json.dumps({'at': old_time}))
    def start(name):
        assert not (tmp_path / (name + '.log')).read_text()
        (tmp_path / (name + '.log')).write_text(json.dumps({'at': datetime.now(timezone.utc).isoformat()}))
    monkeypatch.setattr(fixture, '_start', start)
    boundary = fixture.reset('normal')
    assert isinstance(boundary, str)
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='text_logs', payload={
        'service': 'localapp', 'lines': [(tmp_path / 'localapp.log').read_text()]})
    validate_observation_window(raw, boundary)
    raw['payload']['lines'] = [json.dumps({'at': old_time})]
    with pytest.raises(EvidenceValidationError):
        validate_observation_window(raw, boundary)


@pytest.mark.parametrize('change', ['none', 'edit', 'add', 'add_jsonl', 'remove', 'tamper'])
def test_local_knowledge_baseline_without_mcp_fixture(tmp_path, change):
    corpus = tmp_path / 'books'
    corpus.mkdir()
    (corpus / 'topology.md').write_text('edge connects to localapp', encoding='utf-8')
    baseline = knowledge_conditions(corpus, mode='local_runbooks')
    assert baseline['mode'] == 'local_runbooks' and 'chunks' not in baseline
    manifest = tmp_path / 'manifest.json'
    if change == 'tamper':
        baseline['implementations']['src/agent/aiops/local_retrieval.py'] = 'tampered'
    manifest.write_text(json.dumps(baseline), encoding='utf-8')
    if change == 'edit': (corpus / 'topology.md').write_text('different')
    if change == 'add': (corpus / 'extra.md').write_text('extra')
    if change == 'add_jsonl': (corpus / 'extra.jsonl').write_text('{"root_cause_category":"test"}')
    if change == 'remove': (corpus / 'topology.md').unlink()
    if change == 'none':
        assert check_knowledge_conditions(manifest, corpus, tmp_path, None, 'before')['passed']
    else:
        with pytest.raises(ValueError):
            check_knowledge_conditions(manifest, corpus, tmp_path, None, 'before')


@pytest.mark.asyncio
@pytest.mark.parametrize('missing', [False, True])
async def test_local_knowledge_gate_precedes_model_setup(tmp_path, missing):
    from scripts.evaluate_windows_probe import parse_args, run_model
    corpus = tmp_path / 'runbooks'
    corpus.mkdir()
    (corpus / 'topology.md').write_text('localapp guide', encoding='utf-8')
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps(knowledge_conditions(corpus, mode='local_runbooks')), encoding='utf-8')
    args = parse_args(['--local-runbooks', str(corpus), '--knowledge-manifest', str(manifest)])
    if missing:
        args.knowledge_manifest = None
    else:
        (corpus / 'topology.md').write_text('changed before setup', encoding='utf-8')
    with pytest.raises(ValueError, match='manifest|conditions changed'):
        await run_model(args, None, tmp_path, [])
    assert not (tmp_path / 'cost.json').exists()


def repeated_stop_trace():
    current = state()
    current['investigation_tools'] = [{'name': 'probe_text_log'}]
    check = decision(hypothesis='退出原因未知', next_check='inspect saved log', next_tools=['probe_text_log'],
        next_arguments={'probe_text_log': {'service': 'entry', 'path': 'D:/entry.log', 'lines': 20}})
    current.update(decide(current, check))
    snapshots = [behavior_snapshot(current, datetime.now(timezone.utc).isoformat())]
    for name in ('sample one', 'sample two'):
        current['raw_evidence'].append((name, json.dumps(evidence(target_id=settings.PROBE_TARGET_ID,
            operation='text_logs', payload={'service': 'entry', 'path': 'D:/entry.log', 'lines': [], 'line_limit': 20}))))
        current['past_steps'].append((name, 'empty log'))
        current['raw_evidence'].append((name, json.dumps({'data_source': 'tool_execution',
            'tool': 'probe_text_log', 'arguments': {'service': 'entry', 'path': 'D:/entry.log', 'lines': 20},
            'status': 'success'})))
    current.update(decide(current, decision(hypothesis='退出原因未知', next_check='', next_tools=[], next_arguments=None)))
    snapshots.append(behavior_snapshot(current, datetime.now(timezone.utc).isoformat()))
    return current, snapshots


@pytest.mark.parametrize('mutation', [None, 'payload', 'object', 'missing', 'execution', 'legacy'])
def test_stop_audit_replays_validated_repeat_history(mutation):
    current, snapshots = repeated_stop_trace()
    history = snapshots[-1]['behavior_context']['observation_history']
    assert len(history) == 2
    review = snapshots[-1]['tracking']['blocked_check_review']
    # The stop is a reviewed saved-candidate stop: every saved check that was not
    # resampled is recorded with its rejection reason, so the stop is auditable.
    assert review['kind'] == 'no_eligible_saved_candidate'
    assert review['rejected_candidates'] and all(item['reason'] for item in review['rejected_candidates'])
    if mutation in {'payload', 'object'}:
        record = next(iter(history.values()))
        raw = json.loads(record['payload'])
        raw['payload']['service' if mutation == 'object' else 'lines'] = 'tampered'
        record['payload'] = json.dumps(raw)
    if mutation == 'missing': history.pop(next(iter(history)))
    if mutation == 'legacy':
        for row in snapshots:
            row['behavior_context'].pop('observation_history')
            row['behavior_context'].pop('observation_history_sha256')
    executions = deepcopy(inv.execution_checks(current))
    if mutation == 'execution': executions[-1]['arguments']['service'] = 'other'
    result = audit_behavior(snapshots, [s for s, _ in current['past_steps']], executions)
    assert result['status'] == ('not_assessed' if mutation == 'legacy' else 'failed' if mutation else 'passed'), result


def test_history_reconstruction_uses_recorded_time_after_ttl_expires():
    from datetime import timedelta
    from scripts.mechanism_behavior import _history_hash
    current, snapshots = repeated_stop_trace()
    def earlier(value):
        return (datetime.fromisoformat(value.replace('Z', '+00:00')) - timedelta(days=1)).isoformat()
    for row in snapshots:
        context = row['behavior_context']
        context['validated_at'] = earlier(context['validated_at'])
        for records in (context['records'], context['observation_history']):
            for record in records.values():
                raw = json.loads(record['payload'])
                raw['collected_at'] = earlier(raw['collected_at'])
                record['payload'] = json.dumps(raw, ensure_ascii=False)
                record['provenance']['collected_at'] = raw['collected_at']
        context['observation_history_sha256'] = _history_hash(context['observation_history'])
    assert audit_behavior(snapshots, [s for s, _ in current['past_steps']],
                          inv.execution_checks(current))['status'] == 'passed'


@pytest.mark.parametrize('drift', [False, True])
def test_local_materials_verified_before_and_after_actual_retrieval(tmp_path, drift):
    from scripts.evaluate_windows_probe import local_runbook_retrieval
    corpus = tmp_path / 'runbooks'
    corpus.mkdir()
    (corpus / 'topology.md').write_text('localapp availability and downstream connectivity', encoding='utf-8')
    manifest = tmp_path / 'manifest.json'
    baseline = knowledge_conditions(corpus, mode='local_runbooks')
    manifest.write_text(json.dumps(baseline), encoding='utf-8')
    check_knowledge_conditions(manifest, corpus, tmp_path, None, 'before')
    with local_runbook_retrieval(corpus, tmp_path) as retrieve:
        retrieve('localapp availability')
    trace = json.loads((tmp_path / 'knowledge_trace.json').read_text(encoding='utf-8'))
    assert trace['sources'] == baseline['sources'] and trace['queries']
    if drift:
        (corpus / 'topology.md').write_text('changed during run', encoding='utf-8')
        with pytest.raises(ValueError, match='conditions changed'):
            check_knowledge_conditions(manifest, corpus, tmp_path, None, 'after')
    else:
        assert check_knowledge_conditions(manifest, corpus, tmp_path, None, 'after')['passed']


def test_candidate_feedback_states_observation_and_causal_limit():
    current = state(('text_logs', {'service': 'entry', 'path': 'D:/entry.log', 'lines': [], 'line_limit': 20}))
    result = decide(current, decision(hypothesis='进程不存在或没有输出日志', next_check='inspect log',
        next_tools=['probe_text_log'], next_arguments={'probe_text_log': {'service': 'entry', 'path': 'D:/entry.log', 'lines': 20}}))
    prompt = inv._decision_memory_context(result['investigation_memory'])
    progress = next(iter(prompt['candidate_check_progress'].values()))[0]
    assert progress['observation']['line_count'] == 0
    assert progress['evidence_ids'] and '不能证明进程不存在' in progress['remaining_unknown']
    assert result['plan'] == []


@pytest.mark.asyncio
async def test_next_existing_request_receives_new_result_before_deciding(monkeypatch):
    from unittest.mock import AsyncMock
    current = state()
    current['investigation_tools'] = [{'name': 'probe_port_snapshot'}]
    answer = decision(hypothesis='ports/2293: listening == false', hypothesis_condition=inv.ObservationCondition(
        operation='ports', object_name='2293', field='listening', expected=False),
        next_check='inspect port', next_tools=['probe_port_snapshot'],
        next_arguments={'probe_port_snapshot': {'local_port': 2293, 'listening_only': True}})
    current.update(decide(current, answer))
    original_memory = deepcopy(current['investigation_memory'])
    current['raw_evidence'].append(('inspect port', json.dumps(evidence(target_id=settings.PROBE_TARGET_ID,
        operation='ports', payload={'local_port': 2293, 'listening_only': True,
            'ports': [{'status': 'LISTEN', 'local': {'port': 2293}, 'pid': 123}]}))))
    current['past_steps'].append(('inspect port', 'listener found'))
    async def model(llm, schema, prompt, inputs):
        memory = json.loads(inputs['memory'])
        candidate, = memory['hypothesis_tracking']['candidates']
        assert candidate['relation'] == 'contradict' and candidate['evidence_ids']
        option = next(row for row in memory['decision_agenda']['checks']
                      if any(ref['candidate_id'] == candidate['id'] for ref in row['references']))
        progress, = option['progress']
        assert progress['observation']['listening_count'] == 1 and progress['status'] == 'observed'
        return decision(hypothesis='原因仍未知', next_check='', next_tools=[], next_arguments=None)
    invoke = AsyncMock(side_effect=model)
    monkeypatch.setattr(inv, 'create_agent_llm', lambda **kwargs: object())
    monkeypatch.setattr(inv, 'ainvoke_structured', invoke)
    result = await inv.InvestigationStrategy().decide(current)
    assert invoke.await_count == 1 and not result['plan']
    assert current['investigation_memory'] == original_memory


def test_localized_report_keeps_candidate_validation_in_details():
    current = state(('dependency_probe', {'dependency': 'entry', 'tcp': 'ok', 'http': {'status': 503}}))
    current['input'] = 'LONG USER INSTRUCTIONS ' * 30
    result = decide(current, decision(next_check='', next_tools=[], next_arguments=None,
        hypothesis='内部错误原因未知', hypothesis_condition=inv.ObservationCondition(
            operation='dependency_probe', object_name='entry', field='http.status', expected=503),
        alternatives=[inv.Alternative(explanation='未经核验的复杂原因', status='unresolved')]))
    assert result['diagnosis']['kind'] == 'localized_fault'
    assert result['diagnosis']['validation_issues']
    assert '判断校验：' not in result['response'] and '未决解释：' not in result['response']
    assert 'LONG USER INSTRUCTIONS' not in result['response']
    assert '故障对象与影响' in result['response'] and '剩余未知' in result['response']
    assert result['response'].count('停止原因：') == 1
