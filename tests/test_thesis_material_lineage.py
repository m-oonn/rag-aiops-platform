import hashlib
import json
import shutil

import pytest

from scripts.audit_thesis_materials import audit_materials, observation_key
from src.probe.protocol import raw_hash


@pytest.fixture
def materials(tmp_path):
    def save(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    def raw(value):
        payload = {'tcp': value}
        return {'target_id': 'target', 'operation': 'dependency_probe', 'collected_at': 'original-time',
                'payload': payload, 'raw_hash': raw_hash(payload)}
    original = [raw('first'), raw('second'), raw('third')]
    origin = tmp_path / 'origin'
    save(origin / 'evidence.json', [{'case': 'controller-case', 'evidence_id': 'old-' + str(i), 'raw': r}
                                  for i, r in enumerate(original)])
    fixture = tmp_path / 'fixture.json'
    save(fixture, {'source': str(origin), 'source_files_sha256': {'evidence.json': digest(origin / 'evidence.json')},
        'cases': {'case': [{'evidence_id': 'old-' + str(i), 'raw': r} for i, r in enumerate(original)]}})
    reviews = tmp_path / 'reviews'
    for group in ('G00', 'G10', 'G01', 'G11'):
        for count in (1, 2, 3):
            directory = reviews / ('sample-' + group + '-' + str(count))
            ids = [group + '-' + str(count) + '-' + str(i) for i in range(count)]
            source = tmp_path / 'replays' / directory.name / 'output-audit.json'
            save(source, {'case': 'case', 'group': group, 'evidence_count': count,
                'mode': 'historical_fixed_decision_api_check', 'model_calls': 0, 'new_observations': 0,
                'autonomous_model_verified': False, 'raw_returns': original[:count],
                'refreshed': {'report': 'unknown', 'diagnosis': {}}, 'ledger': {'evidence': [{'evidence_id': i} for i in ids]}})
            save(directory / 'review-packet.json', {'report': 'unknown', 'diagnosis': {},
                 'evidence': dict(zip(ids, original[:count]))})
            packet_hash = digest(directory / 'review-packet.json')
            save(directory / 'source-audit.json', {'case': 'case', 'mode': 'historical_fixed_decision_api_check',
                'source_hashes': {str(source): digest(source)}, 'packet_sha256': packet_hash,
                'mechanical_review': {'mechanical_status': 'failed'}})
            save(directory / 'manual-review.json', {'packet_sha256': packet_hash,
                'dimensions': {k: {'verdict': 'pending'} for k in ('diagnosis', 'citation_support', 'recommendation')}})
    mechanism = tmp_path / 'mechanisms-test-G11'
    save(mechanism / 'events.json', [{'type': 'evidence', 'evidence_id': 'live',
        'target_id': 'target', 'kind': 'dependency_probe'}])
    save(mechanism / 'evidence/live.json', raw('live'))
    summary = tmp_path / 'mechanism-summary.json'
    save(summary, {'passed': True, 'source_unchanged': True,
        'source_sha256': {str(mechanism / 'events.json'): digest(mechanism / 'events.json')},
        'runs': [{'sample': mechanism.name, 'case': 'test', 'group': 'G11', 'issues': [],
                  'behavior_status': 'passed', 'mode': 'fixed_decision_live_probe_history'}]})
    return reviews, summary, fixture, tmp_path / 'result'


def test_lineage_deduplicates_replayed_observations_and_keeps_reviews_pending(materials):
    result = audit_materials(*materials)
    assert result['passed'] and result['source_unchanged']
    assert result['counts'] == {'review_packets': 12, 'replay_ledger_ids': 24,
        'replay_original_observations': 3, 'fixture_original_observations': 3,
        'mechanism_runs': 1, 'mechanism_original_observations': 1, 'shared_observations_between_batches': 0}
    assert result['review_status_counts'] == {'pending': 12}
    assert result['diagnostic_accuracy'] is result['independent_fault_trials'] is None
    assert result['new_model_calls'] == result['new_observations'] == 0
    with pytest.raises(FileExistsError):
        audit_materials(*materials)


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'wrong_origin', 'invalid_hash', 'foreign_review', 'missing_live'])
def test_lineage_rejects_missing_or_foreign_materials(materials, mutation):
    reviews, summary, fixture, output = materials
    directory = next(reviews.glob('sample-*'))
    if mutation == 'missing':
        shutil.rmtree(directory)
    if mutation == 'duplicate':
        shutil.copytree(directory, reviews / 'sample-duplicate')
    if mutation in ('wrong_origin', 'invalid_hash'):
        saved = json.loads(fixture.read_text())
        saved['cases']['case'][0]['raw']['payload']['tcp'] = 'wrong'
        if mutation == 'wrong_origin':
            saved['cases']['case'][0]['raw']['raw_hash'] = raw_hash({'tcp': 'wrong'})
        fixture.write_text(json.dumps(saved))
    if mutation == 'foreign_review':
        packet = directory / 'review-packet.json'
        packet.write_text('{}')
    if mutation == 'missing_live':
        (summary.parent / 'mechanisms-test-G11/evidence/live.json').unlink()
    if mutation == 'invalid_hash':
        with pytest.raises(ValueError, match='payload hash'):
            audit_materials(*materials)
    else:
        assert not audit_materials(*materials)['passed']


def test_observation_identity_includes_collection_time():
    raw = {'payload': {'tcp': 'ok'}, 'raw_hash': raw_hash({'tcp': 'ok'}), 'collected_at': 'first'}
    assert observation_key(raw) != observation_key({**raw, 'collected_at': 'second'})


def test_rebound_packet_with_changed_diagnosis_is_not_accepted(materials):
    reviews, summary, fixture, output = materials
    directory = next(reviews.glob('sample-*'))
    path = directory / 'review-packet.json'
    packet = json.loads(path.read_text())
    packet['diagnosis'] = {'conclusion': 'invented cause'}
    path.write_text(json.dumps(packet))
    new_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ('source-audit.json', 'manual-review.json'):
        path = directory / name
        data = json.loads(path.read_text())
        data['packet_sha256'] = new_hash
        path.write_text(json.dumps(data))
    result = audit_materials(*materials)
    assert not result['passed']
    assert any('review diagnosis differs from replay' in r['issues'] for r in result['report_rows'])
