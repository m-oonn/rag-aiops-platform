import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.knowledge_conditions import knowledge_conditions, check_knowledge_conditions, fixture_chunks


@pytest.fixture
def corpus(tmp_path):
    directory = tmp_path / 'runbooks'
    directory.mkdir()
    (directory / 'localapp-availability.md').write_text('localapp guide', encoding='utf-8')
    manifest = tmp_path / 'knowledge-manifest.json'
    manifest.write_text(json.dumps(knowledge_conditions(directory)), encoding='utf-8')
    return directory, manifest


@pytest.mark.parametrize('change', ['none', 'edit', 'add', 'remove', 'tamper'])
def test_knowledge_baseline_detects_corpus_and_manifest_drift(tmp_path, corpus, change):
    directory, manifest = corpus
    if change == 'edit': (directory / 'localapp-availability.md').write_text('changed')
    if change == 'add': (directory / 'new.md').write_text('new')
    if change == 'remove': (directory / 'localapp-availability.md').unlink()
    if change == 'tamper':
        data = json.loads(manifest.read_text())
        data['retrieval']['rag_min_score'] = .9
        manifest.write_text(json.dumps(data))
    if change == 'none':
        result = check_knowledge_conditions(manifest, directory, tmp_path, 'http://127.0.0.1:9200/mcp', 'before')
        assert result['passed'] and not result['remote_index_verified']
        assert json.loads(manifest.read_text())['chunks'] == json.loads(json.dumps(fixture_chunks(directory)))
    else:
        with pytest.raises((ValueError, FileNotFoundError)):
            check_knowledge_conditions(manifest, directory, tmp_path, None, 'before')
    record = json.loads((tmp_path / 'knowledge-conditions-before.json').read_text())
    assert record['passed'] is (change == 'none')


@pytest.mark.asyncio
async def test_mismatched_baseline_blocks_model_setup_before_budget(tmp_path, corpus):
    from scripts.evaluate_windows_probe import run_model
    directory, manifest = corpus
    (directory / 'localapp-availability.md').write_text('changed')
    args = SimpleNamespace(previous_cost=None, local_runbooks=directory, knowledge_manifest=manifest,
        knowledge_mcp_url='http://127.0.0.1:9200/mcp')
    with pytest.raises(ValueError, match='conditions changed'):
        await run_model(args, None, tmp_path, [])
    assert not (tmp_path / 'cost.json').exists()


@pytest.mark.asyncio
@pytest.mark.parametrize('audit', ['missing', 'wrong', 'valid'])
async def test_controller_requires_matching_completed_knowledge_audit(tmp_path, corpus, monkeypatch, audit):
    from scripts import verify_windows_local_faults as controller
    baseline = json.loads(corpus[1].read_text())
    def launch(args, name):
        assert args[args.index('--knowledge-manifest') + 1] == str(corpus[1])
        output = Path(args[args.index('--output-dir') + 1])
        output.mkdir()
        summary = {'has_final_report': True, 'report_kind': 'unlocated'}
        if audit != 'missing':
            summary['knowledge_conditions'] = {'passed': True, 'phase': 'after',
                'actual_sha256': baseline['sha256'] if audit == 'valid' else 'wrong',
                'endpoint': 'http://127.0.0.1:9200/mcp'}
        (output / 'summary.json').write_text(json.dumps(summary))
        (output / 'cost.json').write_text(json.dumps({'limit_cny': 5, 'reserved_cny': .1, 'requests': [
            {'number': 1, 'reserved_cny': .1, 'http_status': 200, 'usage': {'prompt_tokens': 1, 'completion_tokens': 1}}]}))
        return SimpleNamespace(wait=lambda: 0)
    # This test isolates the knowledge gate; full artifact validation has its own joined tests.
    from scripts import evaluation_record
    import hashlib
    def audit_evaluation(directory, **kwargs):
        symptom = next(tmp_path.glob('symptom-*.txt'))
        return {'passed': True, 'this_run_cost': {'requests': 1},
            'comparison_config': {'symptom_sha256': hashlib.sha256(symptom.read_bytes()).hexdigest()}}
    monkeypatch.setattr(evaluation_record, 'audit_evaluation', audit_evaluation)
    monkeypatch.setattr(controller, 'review_model_artifacts', lambda *a: {'passed': True, 'workflow_status': 'completed'})
    if audit == 'valid':
        result = await controller.evaluate_model_case(tmp_path, 'normal', launch, knowledge_url='http://127.0.0.1:9200/mcp')
        assert result['knowledge_conditions']['actual_sha256'] == baseline['sha256']
    else:
        with pytest.raises(RuntimeError, match='knowledge conditions audit failed'):
            await controller.evaluate_model_case(tmp_path, 'normal', launch, knowledge_url='http://127.0.0.1:9200/mcp')


@pytest.mark.asyncio
@pytest.mark.parametrize('drift', [False, True])
async def test_free_entry_checks_manifest_before_and_after(tmp_path, corpus, monkeypatch, drift):
    from unittest.mock import AsyncMock
    from scripts import evaluate_windows_probe as evaluation, windows_probe
    from src.probe.windows import config
    directory, manifest = corpus
    output = tmp_path / 'free'
    args = evaluation.parse_args(['--local-runbooks', str(directory), '--knowledge-manifest', str(manifest),
        '--knowledge-mcp-url', 'http://127.0.0.1:9200/mcp', '--output-dir', str(output)])
    monkeypatch.setattr(evaluation, 'parse_args', lambda: args)
    monkeypatch.setattr(windows_probe, '_set_acl', lambda path: None)
    monkeypatch.setattr(config, 'load_config', lambda path: SimpleNamespace(tls_ca_file=None))
    for name in ['DATABASE_URL', 'AIOPS_CHECKPOINT_DB_PATH', 'ENABLE_EXPERIENCE_CONTEXT']:
        monkeypatch.setenv(name, 'test-placeholder')
    async def preflight(*args, **kwargs):
        if drift:
            (directory / 'localapp-availability.md').write_text('changed during preflight', encoding='utf-8')
    monkeypatch.setattr(evaluation, 'preflight', preflight)
    paid = AsyncMock(side_effect=AssertionError('paid path forbidden'))
    monkeypatch.setattr(evaluation, 'run_model', paid)
    if drift:
        with pytest.raises(ValueError, match='conditions changed'):
            await evaluation.main()
    else:
        await evaluation.main()
    for phase in ['before', 'after']:
        record = json.loads((output / ('knowledge-conditions-' + phase + '.json')).read_text())
        assert record['passed'] is (not drift or phase == 'before')
    paid.assert_not_awaited()
    assert not (output / 'cost.json').exists()


@pytest.mark.asyncio
async def test_fixture_manifest_recipe_is_used_by_real_mcp(tmp_path, corpus, monkeypatch):
    from fastmcp import Client
    from scripts.verify_windows_probe_graph import create_local_knowledge_server
    from src.agent.aiops.evidence_sources import knowledge_context
    from src.settings import settings
    import mcp_servers.rag_server as rag
    for name in ['_get_retriever', '_get_reranker']:
        monkeypatch.setattr(rag, name, getattr(rag, name))
    monkeypatch.setattr(settings, 'RAG_MIN_SCORE', settings.RAG_MIN_SCORE)
    server = create_local_knowledge_server(corpus[0])
    async with Client(server) as client:
        response = await client.call_tool('search_knowledge_base', {'query': 'localapp availability', 'kb_id': 14})
    fragments = knowledge_context([('lookup', [item.model_dump() for item in response.content])])
    assert fragments[0]['chunk_id'] == 'localapp-guide' and fragments[0]['kb_id'] == 14
    baseline = json.loads(corpus[1].read_text())
    assert baseline['chunks'][0][1] == fragments[0]['content']
