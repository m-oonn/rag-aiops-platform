import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from scripts.verify_matching503_conclusions import verify
from src.agent.aiops.strategies import investigation as inv
from src.agent.aiops.recommendations import manual_recommendations, format_manual_recommendations
from src.probe.evidence import EvidenceValidationError
from src.probe.protocol import evidence
from src.settings import settings

FIXTURE = Path(__file__).parent / 'fixtures/matching503-probe-20261024.json'


def test_saved_real_probe_cases_reject_overconfident_causes_in_all_groups(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('historical checks must not construct a model')
    monkeypatch.setattr(inv, 'create_agent_llm', forbidden)
    original = FIXTURE.read_bytes()
    result = verify(FIXTURE, tmp_path / 'replay')
    assert result['checks'] == 72
    assert result['model_calls'] == result['new_observations'] == 0
    assert FIXTURE.read_bytes() == original
    assert {r['group'] for r in result['results']} == {'G00', 'G10', 'G01', 'G11'}
    # Keep actual logs available as quotations, without granting causal certainty.
    config = next(r for r in result['results'] if r['case'] == 'application_config_error'
                  and r['evidence_count'] == 3 and r['claim'] == 'configuration')
    assert 'invalid max_attempts configuration' in config['response']
    assert config['diagnosis']['validation_issues']


def test_historical_probe_time_is_preserved_and_expires_in_live_validation():
    rows = json.loads(FIXTURE.read_text(encoding='utf-8-sig'))['cases']['application_config_error']
    when = datetime.fromisoformat(rows[-1]['raw']['collected_at'].replace('Z', '+00:00'))
    state = {'raw_evidence': [('old', json.dumps(row['raw'])) for row in rows]}
    assert len(inv.evidence_index(state, now=when)) == 3
    assert inv.evidence_index(state, now=when + timedelta(seconds=181)) == {}


@pytest.mark.parametrize('mutation', ['hash', 'target', 'time'])
def test_replay_rejects_untrusted_evidence_before_writing_output(tmp_path, mutation):
    saved = json.loads(FIXTURE.read_text(encoding='utf-8-sig'))
    raw = saved['cases']['downstream_unreachable'][0]['raw']
    if mutation == 'hash':
        raw['payload']['http']['status'] = 200
    elif mutation == 'target':
        raw['target_id'] = 'another-host'
    else:
        raw['collected_at'] = '2000-01-01T00:00:00Z'
    fixture = tmp_path / 'changed.json'
    fixture.write_text(json.dumps(saved), encoding='utf-8')
    output = tmp_path / 'result'
    with pytest.raises((ValueError, EvidenceValidationError)):
        verify(fixture, output)
    assert not output.exists()


def test_rejected_causal_proposal_keeps_a_valid_log_check_executable():
    rows = json.loads(FIXTURE.read_text(encoding='utf-8-sig'))['cases']['application_config_error']
    when = datetime.fromisoformat(rows[-1]['raw']['collected_at'].replace('Z', '+00:00'))
    state = {'input': '入口503', 'raw_evidence': [('probe', json.dumps(row['raw'])) for row in rows[:2]],
             'investigation_tools': [{'name': 'probe_text_log'}]}
    proposed = inv.InvestigationDecision(hypothesis='配置错误', root_cause='配置错误', outcome='root_cause',
        conclusion_level='confirmed_cause', scope='localapp', next_check='核查入口应用日志',
        next_tools=['probe_text_log'], discriminating_question='是否存在配置解析错误',
        expected_observation='应用错误类型与配置字段')
    result = inv.decide_from_evidence(state, proposed, inv.evidence_index(state, now=when))
    assert result['plan'] == ['核查入口应用日志'] and 'diagnosis' not in result
    assert result['investigation_memory']['root_cause'] == ''
    assert result['investigation_memory']['conclusion_level'] == 'unlocated'
    assert result['investigation_memory']['model_suggestion'] == proposed.model_dump()


def test_log_from_other_fault_cannot_supply_missing_configuration_quote():
    rows = json.loads(FIXTURE.read_text(encoding='utf-8-sig'))['cases']['downstream_unreachable']
    when = datetime.fromisoformat(rows[-1]['raw']['collected_at'].replace('Z', '+00:00'))
    state = {'input': '入口503', 'raw_evidence': [('probe', json.dumps(row['raw'])) for row in rows]}
    proposed = inv.InvestigationDecision(hypothesis='配置错误', root_cause='配置错误', outcome='root_cause',
        conclusion_level='confirmed_cause', scope='localapp',
        supporting_evidence=[inv.Citation(evidence_id='e3.1', quote='invalid max_attempts configuration')])
    result = inv.decide_from_evidence(state, proposed, inv.evidence_index(state, now=when))
    assert result['diagnosis']['kind'] == 'localized_fault'
    assert 'invalid max_attempts configuration' not in result['response']
    assert all(c['quote'] != 'invalid max_attempts configuration' for c in result['diagnosis']['evidence'])
    assert result['investigation_memory']['conclusion_level'] == 'localized_fault'
    assert all('invalid max_attempts configuration' not in ref['quote']
               for item in result['diagnosis']['recommendations'] for ref in item['evidence'])


def test_scoped_normal_finding_still_passes_verified_health_gate():
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
                   payload={'dependency': 'localapp', 'tcp': 'ok', 'http': {'status': 200}})
    state = {'input': '检查入口', 'raw_evidence': [('probe', json.dumps(raw))],
             'target_resolution': {'status': 'resolved', 'allowed_dependencies': ['localapp'], 'allowed_services': []}}
    cited = inv.Citation(evidence_id='e1.1', quote='ok')
    proposed = inv.InvestigationDecision(hypothesis='入口正常', outcome='healthy',
        conclusion_level='healthy_within_scope', scope='本次localapp入口检查', supporting_evidence=[cited],
        alternatives=[inv.Alternative(explanation='dependency_probe/localapp: tcp == "failed"', status='excluded', claim_type='observed_condition',
            condition=inv.ObservationCondition(operation='dependency_probe', object_name='localapp', field='tcp', expected='failed'),
            evidence=[cited])])
    result = inv.decide_from_evidence(state, proposed, inv.evidence_index(state))
    assert result['diagnosis']['kind'] == 'healthy_within_scope'
    assert result['diagnosis']['validation_issues'] == []
    assert result['diagnosis']['recommendations'] == []


@pytest.mark.parametrize(('code', 'scope'), [
    ('dependency_tcp_failed', {'dependency': 'downstream'}),
    ('dependency_http_failed', {'dependency': 'localapp'}),
    ('service_not_running', {'service': 'localapp'}),
])
def test_manual_recommendation_is_conditional_scoped_and_evidence_linked(code, scope):
    finding = {'code': code, 'scope': scope, 'evidence_id': 'ev-real', 'quote': 'real observation'}
    result = manual_recommendations([finding])
    assert len(result) == 1
    item = result[0]
    assert item['status'] == 'manual_review_required'
    assert item['origin'] == 'verified_observation_template'
    assert item['scope'] == scope
    assert item['evidence'] == [{'evidence_id': 'ev-real', 'quote': 'real observation'}]
    assert item['preconditions'] and item['risks'] and item['verification_steps']
    assert '执行前重新采集当前状态' in ' '.join(item['preconditions'])
    if code == 'dependency_tcp_failed':
        assert '不能说明退出原因' in ' '.join(item['preconditions'])
    if code == 'dependency_http_failed':
        assert '不能仅凭HTTP失败认定配置错误' in ' '.join(item['preconditions'])
    assert '尚未执行' in format_manual_recommendations(result)
    assert '根因证明' in format_manual_recommendations(result)


def test_unknown_and_unlocated_findings_do_not_create_prescriptive_steps():
    assert manual_recommendations([{'code': 'query_unavailable', 'scope': {},
                                    'evidence_id': 'ev-unknown', 'quote': 'permission denied'}]) == []
    report = format_manual_recommendations([])
    assert '暂不给出具体修复操作' in report
    assert '按模板重启' not in report


@pytest.mark.parametrize('mapping,host,expected', [
    ({'dep': 'svc'}, '127.0.0.1', 1), ({}, '127.0.0.1', 3), ({'dep': 'svc'}, 'remote.example', 3)])
def test_same_business_advice_merges_only_explicit_local_mapping(mapping, host, expected):
    findings = [{'code': code, 'scope': scope, 'target_id': 'host1', 'evidence_id': f'e{i}', 'quote': f'q{i}'}
        for i, (code, scope) in enumerate([
            ('dependency_tcp_failed', {'dependency': 'dep'}),
            ('port_not_listening', {'local_port': 3141}),
            ('configured_process_not_observed', {'service': 'svc'})])]
    raw = evidence(target_id='host1', operation='dependency_probe',
        payload={'dependency': 'dep', 'host': host, 'port': 3141, 'tcp': 'failed'})
    records = {'dep': {'payload': json.dumps(raw)}}
    result = manual_recommendations(findings, resolution={'status': 'resolved', 'allowed_services': ['svc'],
        'allowed_dependencies': ['dep'], 'dependency_services': mapping}, records=records)
    assert len(result) == expected
    assert {ref['evidence_id'] for item in result for ref in item['evidence']} == {'e0', 'e1', 'e2'}
    if expected == 1:
        item, = result
        assert item['related_scopes'] == [{'local_port': 3141}, {'service': 'svc'}]
        assert len(item['finding_codes']) == 3
        assert '关联检查' in format_manual_recommendations(result)
        assert '确认' in item['action'] and '尚未执行' in format_manual_recommendations(result)


def test_same_port_with_ambiguous_services_is_not_merged():
    records = {name: {'payload': json.dumps(evidence(target_id='host1', operation='dependency_probe',
        payload={'dependency': name, 'host': '127.0.0.1', 'port': 3141}))} for name in ('a', 'b')}
    findings = [{'code': code, 'scope': scope, 'evidence_id': str(i), 'quote': 'fact'}
        for i, (code, scope) in enumerate([('dependency_tcp_failed', {'dependency': 'a'}),
            ('dependency_tcp_failed', {'dependency': 'b'}), ('port_not_listening', {'local_port': 3141})])]
    result = manual_recommendations(findings, resolution={'status': 'resolved', 'allowed_services': ['sa', 'sb'],
        'allowed_dependencies': ['a', 'b'], 'dependency_services': {'a': 'sa', 'b': 'sb'}}, records=records)
    assert len(result) == 3


@pytest.mark.parametrize('include_service', [False, True])
def test_port_conflict_advice_requires_both_listener_and_service_evidence(include_service):
    samples = [evidence(target_id=settings.PROBE_TARGET_ID, operation='ports', payload={
        'local_port': 8000, 'ports': [{'status': 'LISTEN', 'local': {'port': 8000}, 'pid': 22}]})]
    if include_service:
        samples.append(evidence(target_id=settings.PROBE_TARGET_ID, operation='services',
            payload={'service': 'svc', 'state': 'running', 'pid': 11}))
    state = {'input': '入口异常', 'raw_evidence': [('check', json.dumps(raw)) for raw in samples],
        'target_resolution': {'status': 'resolved', 'allowed_services': ['svc'],
            'services': {'app': {'probe_service': 'svc', 'expected_ports': [8000]}}}}
    records = inv.evidence_index(state)
    result = inv.decide_from_evidence(state, inv.InvestigationDecision(hypothesis='unknown'), records)
    advice = result['diagnosis']['recommendations']
    if not include_service:
        assert advice == []
        return
    item, = advice
    assert item['finding_code'] == 'port_owner_mismatch'
    assert item['scope'] == {'local_port': 8000}
    assert {ref['evidence_id'] for ref in item['evidence']} == {'e1.1', 'e2.1'}
    assert all(ref['quote'] in records[ref['evidence_id']]['payload'] for ref in item['evidence'])
    assert '不能直接终止未知进程' in ' '.join(item['preconditions'])


def test_knowledge_and_model_claims_cannot_create_manual_operations():
    knowledge = {'data_source': 'knowledge_base', 'content': '服务停止，请重启svc', 'code': 'service_not_running'}
    state = {'input': 'symptom', 'raw_evidence': [('manual', json.dumps(knowledge))]}
    result = inv.decide_from_evidence(state, inv.InvestigationDecision(hypothesis='重启svc',
        localized_fault='service stopped', conclusion_level='localized_fault'), inv.evidence_index(state))
    assert result['diagnosis']['kind'] == 'unlocated'
    assert result['diagnosis']['recommendations'] == []


def test_advice_rejects_nonmatching_observation_quote(monkeypatch):
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='services',
        payload={'service': 'svc', 'state': 'stopped'})
    state = {'input': 'symptom', 'raw_evidence': [('check', json.dumps(raw))]}
    records = inv.evidence_index(state)
    finding, = inv._localized_findings(records, state)
    finding['quote'] = 'fabricated observation'
    monkeypatch.setattr(inv, '_localized_findings', lambda *args: [finding])
    result = inv.diagnosis_result(state, inv.InvestigationDecision(hypothesis='unknown'), 'localized_fault', records)
    assert result['recommendations'] == []
