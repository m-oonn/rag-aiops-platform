import json

import pytest

from src.agent.aiops.strategies import investigation as inv
from src.probe.protocol import evidence
from src.settings import settings


def stopped_chain(mutation=''):
    service = {'service': 'site', 'kind': 'docker', 'state': 'stopped',
        'published_tcp_ports': [{'host': '0.0.0.0', 'port': 8310, 'container_port': 8000}]}
    dep = {'dependency': 'entry', 'host': '127.0.0.1', 'port': 8310, 'tcp': 'failed'}
    if mutation == 'running': service['state'] = 'running'
    if mutation == 'port': dep['port'] = 8311
    if mutation == 'host': dep['host'] = 'other.example'
    if mutation == 'tcp': dep['tcp'] = 'ok'
    if mutation == 'mapping': dep['dependency'] = 'other'
    rows = [evidence(target_id=settings.PROBE_TARGET_ID, operation='services', payload=service),
            evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe', payload=dep,
                     truncated=mutation == 'truncated')]
    state = {'input': '商城打不开', 'raw_evidence': [('probe', json.dumps(raw)) for raw in rows],
        'target_resolution': {'status': 'resolved', 'allowed_services': ['site'],
            'allowed_dependencies': ['entry'], 'dependency_services': {'entry': 'site'}}}
    return state, inv.evidence_index(state)


@pytest.mark.parametrize('mutation', ['', 'running', 'port', 'host', 'tcp', 'mapping', 'truncated'])
def test_stop_cause_requires_actual_endpoint_and_registered_mapping(mutation):
    state, records = stopped_chain(mutation)
    chains = inv._registered_cause_chains(records, state)
    assert bool(chains) is (mutation == '')


@pytest.mark.parametrize('subject,expected', [('site', 'confirmed_cause'), ('', 'localized_fault'),
                                             ('other', 'localized_fault')])
def test_terminal_stop_requires_explicit_matching_subject_and_complete_citations(subject, expected):
    state, records = stopped_chain()
    condition = inv.ObservationCondition(operation='services', object_name='site', field='state', expected='stopped')
    citations = [inv.Citation(evidence_id=ident, quote=json.loads(record['payload'])['payload'].__str__())
                 for ident, record in records.items()]
    for citation in citations:
        citation.quote = json.dumps(json.loads(records[citation.evidence_id]['payload'])['payload'])
    proposed = inv.InvestigationDecision(hypothesis='当前站点服务已停止', hypothesis_condition=condition,
        root_cause='当前站点服务停止，对应入口无法连接；停止原因未知',
        root_cause_code='registered_service_stopped', cause_subject=subject,
        outcome='root_cause', conclusion_level='confirmed_cause', scope='本次入口访问',
        supporting_evidence=citations, alternatives=[inv.Alternative(
            explanation='services/site: state == "running"', status='excluded', claim_type='observed_condition',
            condition=inv.ObservationCondition(operation='services', object_name='site', field='state', expected='running'),
            evidence=[citations[0]])])
    result = inv.decide_from_evidence(state, proposed, records)
    assert result['diagnosis']['kind'] == expected
    if expected == 'confirmed_cause':
        assert result['diagnosis']['conclusion'] != proposed.root_cause
        assert '未检查的业务' in result['diagnosis']['scope']
        assert result['investigation_memory']['model_suggestion']['root_cause'] == proposed.root_cause


def test_internal_stop_requires_observed_consumer_failure():
    state, records = stopped_chain()
    body = json.loads(records['e1.1']['payload'])
    body['payload'].update(network_aliases=['db'], exposed_tcp_ports=[5432], published_tcp_ports=[])
    dep = json.loads(records['e2.1']['payload'])
    dep['payload'].update(host='db', port=5432, source_service='consumer')
    state['target_resolution']['allowed_services'].append('consumer')
    records['e1.1']['payload'] = json.dumps(body)
    records['e2.1']['payload'] = json.dumps(dep)
    assert inv._registered_cause_chains(records, state) == []
    consumer = evidence(target_id=settings.PROBE_TARGET_ID, operation='dependency_probe',
        payload={'dependency': 'page', 'http': {'status': 500}, 'tcp': 'ok'})
    state['target_resolution']['dependency_services']['page'] = 'consumer'
    records['page'] = {'payload': json.dumps(consumer)}
    assert inv._registered_cause_chains(records, state)[0]['subject'] == 'site'


@pytest.mark.parametrize('kind,query,expected', [('django_database', 'failed', True),
    ('django_cache', 'failed', True), ('tcp', 'failed', False),
    ('django_database', 'ok', False), ('django_database', None, False)])
def test_internal_stop_with_loaded_consumer_operation(kind, query, expected):
    state, records = stopped_chain()
    body = json.loads(records['e1.1']['payload'])
    body['payload'].update(network_aliases=['db'], exposed_tcp_ports=[5432], published_tcp_ports=[])
    dep = json.loads(records['e2.1']['payload'])
    dep['payload'].update(host='db', port=5432, source_service='consumer', probe_kind=kind, query=query)
    state['target_resolution']['allowed_services'].append('consumer')
    records['e1.1']['payload'] = json.dumps(body)
    records['e2.1']['payload'] = json.dumps(dep)
    assert bool(inv._registered_cause_chains(records, state)) is expected


def test_primary_review_exposes_extra_truncated_reference_without_accepting_it():
    state, records = stopped_chain()
    raw = evidence(target_id=settings.PROBE_TARGET_ID, operation='text_logs',
                   payload={'service': 'site', 'lines': ['partial log']}, truncated=True)
    records['tail'] = {'payload': json.dumps(raw)}
    refs = [inv.Citation(evidence_id='e1.1', quote='"state": "stopped"'),
            inv.Citation(evidence_id='tail', quote='partial log'),
            inv.Citation(evidence_id='missing', quote='unknown')]
    review = inv._primary_evidence_review(refs, records)
    assert review[0]['eligible_as_primary'] is True
    assert review[1]['eligible_as_primary'] is False
    assert '截断' in review[1]['reason']
    assert review[2]['eligible_as_primary'] is False


@pytest.mark.parametrize('mutation', ['', 'startup', 'other_target', 'allowed', 'status', 'truncated'])
def test_host_rejection_requires_loaded_config_and_same_target_response(mutation):
    from src.agent.aiops.registered_causes import configuration_chains
    config = {'service': 'site', 'source': 'running_container_django_settings',
              'values': {'allowed_hosts': ['localhost']}}
    response = {'dependency': 'entry', 'http': {'url': 'http://127.0.0.1:8310/',
                'status': 400, 'exception_type': 'DisallowedHost'}}
    if mutation == 'startup': config['source'] = 'container_start_environment'
    if mutation == 'allowed': config['values']['allowed_hosts'] = ['127.0.0.1']
    if mutation == 'status': response['http']['status'] = 500
    records = {'config': {'payload': json.dumps(evidence(target_id='target', operation='configuration', payload=config))},
        'response': {'payload': json.dumps(evidence(target_id='other' if mutation == 'other_target' else 'target',
            operation='dependency_probe', payload=response, truncated=mutation == 'truncated'))}}
    resolution = {'status': 'resolved', 'allowed_services': ['site'], 'dependency_services': {'entry':'site'}}
    chains = configuration_chains(records, resolution)
    assert bool(chains) is (mutation == '')
    if chains: assert chains[0]['code'] == 'registered_host_rejected'


@pytest.mark.parametrize('mode', ['endpoint', 'authentication'])
@pytest.mark.parametrize('mutation', ['', 'startup', 'other_target', 'truncated', 'loaded_mismatch',
    'consumer_healthy', 'registered_failed', 'registered_wrong_endpoint', 'wrong_source'])
def test_configuration_failure_requires_loaded_settings_and_independent_comparison(mode, mutation):
    from src.agent.aiops.registered_causes import configuration_chains
    auth = mode == 'authentication'
    port = 5432 if auth else 5433
    config = {'service': 'site', 'source': 'running_container_django_settings',
              'values': {'database': {'host': 'db', 'port': port}}}
    failed = {'dependency': 'actual', 'source_service': 'site', 'probe_kind': 'django_database',
        'host': 'db', 'port': port, 'registered_host': 'db', 'registered_port': 5432,
        'tcp': 'ok' if auth else 'failed', 'query': 'failed',
        'error_category': 'authentication_rejected' if auth else 'connection_or_query_failed'}
    comparison = {'dependency': 'reference', 'source_service': 'worker' if auth else 'site',
        'probe_kind': 'django_database' if auth else 'tcp', 'host': 'db', 'port': 5432,
        'tcp': 'ok', 'query': 'ok' if auth else None}
    page = {'dependency': 'entry', 'http': {'status': 500}}
    if mutation == 'startup': config['source'] = 'container_start_environment'
    if mutation == 'loaded_mismatch': config['values']['database']['port'] = 5440
    if mutation == 'consumer_healthy': page['http']['status'] = 200
    if mutation == 'registered_failed': comparison.update(tcp='failed', query='failed')
    if mutation == 'registered_wrong_endpoint': comparison['port'] = 5440
    if mutation == 'wrong_source': comparison['source_service'] = 'site' if auth else 'worker'
    records = {}
    for ident, operation, body in [('config', 'configuration', config), ('actual', 'dependency_probe', failed),
            ('reference', 'dependency_probe', comparison), ('page', 'dependency_probe', page)]:
        records[ident] = {'payload': json.dumps(evidence(
            target_id='other' if mutation == 'other_target' and ident == 'reference' else 'target',
            operation=operation, payload=body, truncated=mutation == 'truncated' and ident == 'actual'))}
    resolution = {'status': 'resolved', 'allowed_services': ['site', 'worker', 'db'],
                  'dependency_services': {'entry': 'site', 'actual': 'db', 'reference': 'db'}}
    chains = configuration_chains(records, resolution)
    assert bool(chains) is (mutation == '')
    if chains:
        assert set(chains[0]['evidence_ids']) == {'config', 'actual', 'reference', 'page'}
        assert chains[0]['code'] == ('registered_authentication_rejected' if auth
                                   else 'registered_dependency_endpoint_mismatch')


def test_public_registered_cause_cannot_publish_extra_model_claims():
    from src.agent.aiops.registered_causes import public_cause
    result = public_cause('registered_dependency_endpoint_mismatch', 'consumer')
    assert 'consumer' in result['conclusion']
    assert '/cart/' not in result['conclusion']
    assert '未检查的业务' in result['scope']
    assert public_cause('unsupported', 'consumer') is None


@pytest.mark.parametrize('mutation', ['', 'startup', 'other_target', 'truncated', 'found', 'missing_source',
    'same_mount', 'other_url', 'status', 'not_loaded', 'malformed_found'])
def test_static_mount_cause_requires_loaded_lookup_mount_and_exact_failed_resource(mutation):
    from src.agent.aiops.registered_causes import configuration_chains
    config = {'service': 'site', 'source': 'running_container_django_settings',
        'values': {'static_url': '/static/', 'static_directories': ['/lab/static'],
                   'static_files': {'shop.css': {'found': False}}},
        'static_mounts': [{'destination': '/lab/static', 'registered_source': 'expected',
            'actual_source': 'empty', 'registered_resources_present': {'shop.css': True}}]}
    page = {'dependency': 'style', 'http': {'url': 'http://127.0.0.1:8310/static/shop.css', 'status': 404}}
    if mutation == 'startup': config['source'] = 'container_start_environment'
    if mutation == 'found': config['values']['static_files']['shop.css']['found'] = True
    if mutation == 'malformed_found': config['values']['static_files']['shop.css'] = False
    if mutation == 'missing_source': config['static_mounts'][0]['registered_resources_present']['shop.css'] = False
    if mutation == 'same_mount': config['static_mounts'][0]['actual_source'] = 'expected'
    if mutation == 'other_url': page['http']['url'] = 'http://127.0.0.1:8310/not-the-resource'
    if mutation == 'status': page['http']['status'] = 200
    if mutation == 'not_loaded': config['values']['static_directories'] = ['/other']
    records = {'config': {'payload': json.dumps(evidence(target_id='target', operation='configuration', payload=config))},
        'page': {'payload': json.dumps(evidence(target_id='other' if mutation == 'other_target' else 'target',
            operation='dependency_probe', payload=page, truncated=mutation == 'truncated'))}}
    chains = configuration_chains(records, {'status': 'resolved', 'allowed_services': ['site'],
        'dependency_services': {'style': 'site'}})
    assert bool(chains) is (mutation == '')
    if chains: assert chains[0]['evidence_ids'] == ['config', 'page']
