"""Offline scoring gates do not infer semantic correctness from labels or quotes."""
import json

import pytest

from scripts import verify_windows_local_faults as controller


def artifacts(tmp_path):
    diagnosis = {'version': 1, 'kind': 'localized_fault', 'target_id': 'windows-local-01',
        'conclusion': 'arbitrary causal claim',
        'evidence': [{'evidence_id': 'ev-one', 'quote': 'failed'}],
        'recommendations': [{'origin': 'verified_observation_template', 'status': 'manual_review_required',
            'scope': {'dependency': 'db'}, 'action': 'check the service before restoring it',
            'evidence': [{'evidence_id': 'ev-one', 'quote': 'failed'}],
            'preconditions': ['confirm current failure'], 'risks': ['may interrupt requests'],
            'verification_steps': ['probe again']}] }
    (tmp_path / 'events.json').write_text(json.dumps([
        {'type': 'evidence', 'evidence_id': 'ev-one'},
        {'type': 'complete', 'response': 'report', 'diagnosis': diagnosis}]), encoding='utf-8')
    (tmp_path / 'tool_trace.json').write_text(json.dumps([
        {'tool': 'probe_dependency_probe', 'validated_live_evidence': True,
         'evidence_id': 'ev-one', 'result': {'payload': {'tcp': 'failed'}}}]), encoding='utf-8')
    return {'diagnosis': diagnosis, 'has_final_report': True}


@pytest.mark.parametrize('change', ['foreign_id', 'invented_quote', 'missing_evidence', 'missing_precondition'])
def test_manual_advice_is_mechanically_checked(tmp_path, change):
    summary = artifacts(tmp_path)
    advice = summary['diagnosis']['recommendations'][0]
    if change == 'foreign_id': advice['evidence'][0]['evidence_id'] = 'ev-other-run'
    if change == 'invented_quote': advice['evidence'][0]['quote'] = 'service crashed'
    if change == 'missing_evidence': advice['evidence'] = []
    if change == 'missing_precondition': advice['preconditions'] = []
    result = controller.review_model_artifacts(tmp_path, 'downstream_unreachable', summary)
    assert result['passed'] is False
    assert result['capability_passed'] is False


def test_pending_capability_is_explained_without_marking_diagnosis_failed(tmp_path):
    result = controller.review_model_artifacts(tmp_path, 'downstream_unreachable', artifacts(tmp_path))
    assert result['capability_passed'] is False
    assert '待人工语义审核' in result['capability_explanation']
    assert '不表示已证明诊断失败' in result['capability_explanation']
    assert result['workflow_status'] == 'completed'
    assert result['mechanical_status'] == result['result_level_status'] == 'passed'


@pytest.mark.parametrize('status', ['ready', 'degraded', 'failed', None])
def test_requested_report_quality_gate_is_separate_from_investigation(tmp_path, status):
    summary = artifacts(tmp_path)
    summary['report_model_enabled'] = True
    if status is not None:
        summary['report_generation'] = {'status': status}
    result = controller.review_model_artifacts(tmp_path, 'downstream_unreachable', summary)
    assert result['workflow_status'] == 'completed'
    assert result['report_generation_status'] == (status or 'unknown')
    assert result['passed'] is (status == 'ready')
    assert result['capability_passed'] is False


@pytest.mark.parametrize('change', ['missing_report_flag', 'missing_complete', 'empty_response', 'error_event', 'budget', 'execution_error'])
def test_missing_or_failed_workflow_is_not_completed(tmp_path, change):
    summary = artifacts(tmp_path)
    events = json.loads((tmp_path / 'events.json').read_text(encoding='utf-8'))
    if change == 'missing_report_flag': summary.pop('has_final_report')
    if change == 'missing_complete': events = events[:1]
    if change == 'empty_response': events[-1]['response'] = ''
    if change == 'error_event': events.append({'type': 'error'})
    if change == 'budget': summary['budget_stopped'] = True
    if change == 'execution_error': summary['execution_error'] = 'TimeoutError'
    (tmp_path / 'events.json').write_text(json.dumps(events), encoding='utf-8')
    result = controller.review_model_artifacts(tmp_path, 'downstream_unreachable', summary)
    assert result['workflow_status'] == 'incomplete'
    assert result['capability_passed'] is False


def test_matching_label_and_quote_leave_semantic_and_advice_review_pending(tmp_path):
    summary = artifacts(tmp_path)
    result = controller.review_model_artifacts(tmp_path, 'downstream_unreachable', summary)
    assert result['passed'] is True
    assert result['workflow_status'] == 'completed'
    assert result['level_matches_scenario'] is True
    assert result['manual_verdict'] == 'pending'
    assert result['semantic_status'] == 'pending_manual_review'
    assert result['recommendation_status'] == 'pending_manual_review'
    assert result['capability_passed'] is False


def test_quote_in_another_trace_row_does_not_validate_current_id(tmp_path):
    summary = artifacts(tmp_path)
    trace = [{'tool': 'probe_dependency_probe', 'validated_live_evidence': True,
              'evidence_id': 'ev-other', 'result': {'tcp': 'failed'}}]
    (tmp_path / 'tool_trace.json').write_text(json.dumps(trace), encoding='utf-8')
    result = controller.review_model_artifacts(tmp_path, 'downstream_unreachable', summary)
    assert result['gates']['quotes_observed'] is False
    assert result['gates']['recommendation_quotes'] is False


def prepare_packet(tmp_path):
    from scripts.diagnostic_review import prepare
    source = tmp_path / 'source'
    source.mkdir()
    summary = artifacts(source)
    (source / 'summary.json').write_text(json.dumps(summary), encoding='utf-8')
    (source / 'report.txt').write_text('report', encoding='utf-8')
    output = tmp_path / 'review'
    prepare(source, output, 'downstream_unreachable')
    return source, output


def test_review_packet_stays_pending_and_does_not_overwrite(tmp_path):
    from scripts.diagnostic_review import prepare, check
    source, output = prepare_packet(tmp_path)
    result = check(output)
    assert result['review_status'] == 'pending'
    assert len(result['pending_dimensions']) == 3
    assert result['automatically_verified_correctness'] is False
    with pytest.raises(FileExistsError):
        prepare(source, output, 'downstream_unreachable')


@pytest.mark.parametrize('change', ['source', 'packet', 'verdict', 'no_reason', 'foreign_evidence', 'positive_without_evidence', 'skip_existing_advice'])
def test_manual_review_rejects_changed_sources_or_incomplete_record(tmp_path, change):
    from scripts.diagnostic_review import check
    source, output = prepare_packet(tmp_path)
    if change == 'source':
        (source / 'report.txt').write_text('changed', encoding='utf-8')
    elif change == 'packet':
        (output / 'review-packet.json').write_text('{}', encoding='utf-8')
    else:
        path = output / 'manual-review.json'
        record = json.loads(path.read_text(encoding='utf-8'))
        record.update(reviewer='test reviewer', reviewed_at='2026-10-24')
        item = record['dimensions']['diagnosis']
        item.update(verdict='invented' if change == 'verdict' else 'incomplete',
                    reason='' if change == 'no_reason' else 'fixture review only',
                    evidence_ids=['ev-other'] if change == 'foreign_evidence' else [])
        if change == 'positive_without_evidence':
            item['verdict'] = 'correct_localization'
        if change == 'skip_existing_advice':
            record['dimensions']['recommendation'].update(
                verdict='not_applicable', reason='synthetic skip', evidence_ids=[])
        path.write_text(json.dumps(record), encoding='utf-8')
    with pytest.raises(ValueError):
        check(output)


def test_recording_all_dimensions_is_not_automatic_semantic_verification(tmp_path):
    from scripts.diagnostic_review import check
    _, output = prepare_packet(tmp_path)
    path = output / 'manual-review.json'
    record = json.loads(path.read_text(encoding='utf-8'))
    record.update(reviewer='synthetic test reviewer', reviewed_at='2026-10-24')
    for key, verdict in [('diagnosis', 'incomplete'), ('citation_support', 'insufficient'),
                         ('recommendation', 'insufficient')]:
        record['dimensions'][key].update(verdict=verdict, reason='synthetic record validation only', evidence_ids=[])
    path.write_text(json.dumps(record), encoding='utf-8')
    result = check(output)
    assert result['review_status'] == 'recorded'
    assert result['automatically_verified_correctness'] is False
