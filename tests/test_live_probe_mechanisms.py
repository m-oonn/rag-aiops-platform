import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.knowledge_conditions import knowledge_conditions
from scripts.verify_probe_mechanisms import verify_mechanism_groups
from src.probe.protocol import evidence
from src.settings import settings


@pytest.mark.asyncio
@pytest.mark.parametrize('tcp', ['ok', 'failed'])
async def test_live_harness_offline_contract_and_rejects_wrong_observation(tmp_path, tcp):
    # These tool inputs test the harness only; live acceptance is run separately.
    shutil.copytree(Path('docs/fixtures/windows-local-runbooks'), tmp_path / 'runbooks')
    (tmp_path / 'token').write_text('test-only-token')
    (tmp_path / 'config.toml').write_text(
        "target_id = 'windows-local-01'\ngateway_url = 'ws://127.0.0.1:12345/probe/ws'\n"
        + f"token_file = '{(tmp_path / 'token').as_posix()}'\n"
        + "[services.localapp]\nkind = 'process'\nprocess_names = ['python.exe']\n"
        + "[dependencies.localapp]\nhost = '127.0.0.1'\nport = 12346\n"
        + "[dependencies.downstream]\nhost = '127.0.0.1'\nport = 12347\n", encoding='utf-8')
    (tmp_path / 'knowledge-manifest.json').write_text(json.dumps(knowledge_conditions(tmp_path / 'runbooks'), ensure_ascii=False), encoding='utf-8')
    log = tmp_path / 'app.log'
    log.write_text('healthy')
    scenario = {'name': 'normal'}
    def tool(name, operation):
        async def invoke(args):
            payload = {'hostname': 'offline-harness', 'configured_dependencies': ['localapp', 'downstream'],
                'configured_services': {'localapp': {'kind': 'process', 'text_logs_available': True}}} if operation == 'inventory' else (
                {'dependency': args['dependency'], 'tcp': tcp,
                 'http': {'status': 503 if scenario['name'] == 'application_config_error'
                          and args['dependency'] == 'localapp' else 200}}
                if operation == 'dependency_probe'
                else {'service': 'localapp', 'lines': ['healthy']})
            return evidence(target_id=settings.PROBE_TARGET_ID, operation=operation, payload=payload)
        return SimpleNamespace(name=name, description=name, args={}, ainvoke=invoke)
    tools = {t.name: t for t in [tool('probe_inventory', 'inventory'),
        tool('probe_dependency_probe', 'dependency_probe'), tool('probe_text_log', 'text_logs')]}
    async def history(args):
        return {'status': {'status': 'online'}, 'baseline_history': [], 'baseline_summary': {}}
    tools['probe_list_evidence'] = SimpleNamespace(name='probe_list_evidence', description='history', args={}, ainvoke=history)
    async def lookup(args):
        return {'data_source': 'knowledge_base', 'results': [{'chunk_id': 'localapp-guide',
            'content': '手册不是现场事实 localapp downstream', 'source': 'localapp-availability.md', 'kb_id': 14}]}
    knowledge = SimpleNamespace(name='search_knowledge_base', description='knowledge', args={}, ainvoke=lookup)
    async def set_case(name):
        scenario['name'] = name
    if tcp == 'failed':
        with pytest.raises(AssertionError, match='expected healthy TCP observation'):
            await verify_mechanism_groups(tools, tmp_path, log, knowledge, 'http://127.0.0.1:12348/mcp', set_case)
        assert not (tmp_path / 'live-mechanism-groups.json').exists()
        assert (tmp_path / 'mechanisms-protection-G00/calls.json').exists()
    else:
        result = await verify_mechanism_groups(tools, tmp_path, log, knowledge,
            'http://127.0.0.1:12348/mcp', set_case)
        assert result['investigations'] == 12 and result['model_calls'] == 0
        rows = json.loads((tmp_path / 'live-mechanism-groups.json').read_text(encoding='utf-8'))
        assert all(row['behavior']['status'] == 'passed' for row in rows)
        def group(row):
            config = row['config']
            return f"G{int(config['hypothesis_protection'])}{int(config['contradiction_trigger'])}"

        protection_rows = {group(row): row for row in rows if row['case'] == 'protection'}
        contradiction_rows = {group(row): row for row in rows if row['case'] == 'contradiction'}
        no_refutation_rows = {group(row): row for row in rows if row['case'] == 'no_live_refutation'}
        assert set(protection_rows) == set(contradiction_rows) == set(no_refutation_rows) == {
            'G00', 'G10', 'G01', 'G11'}

        # The fixture must expose a protection opportunity, and only groups with
        # hypothesis protection may select and execute its follow-up check.
        assert all(row['behavior']['opportunities']['protection'] > 0
                   for row in protection_rows.values())
        assert all(row['behavior']['executed_changes']['protection'] == (group_id in {'G10', 'G11'})
                   for group_id, row in protection_rows.items())
        assert all(any(event['kind'] == 'protection_check_selected' for event in row['events'])
                   is (group_id in {'G10', 'G11'})
                   for group_id, row in protection_rows.items())
        assert all(any(item['tool'] == 'probe_dependency_probe'
                       and item['args'] == {'dependency': 'localapp'}
                       for item in row['calls']) == (group_id in {'G10', 'G11'})
                   for group_id, row in protection_rows.items())

        # The contradiction fixture must expose a reliable refutation, and only
        # groups with contradiction triggering may redirect to an alternative.
        assert all(row['behavior']['opportunities']['contradiction'] > 0
                   for row in contradiction_rows.values())
        assert all(row['behavior']['executed_changes']['contradiction'] == (group_id in {'G01', 'G11'})
                   for group_id, row in contradiction_rows.items())
        assert all(any(event['kind'] == 'contradiction_triggered' for event in row['events'])
                   is (group_id in {'G01', 'G11'})
                   for group_id, row in contradiction_rows.items())
        assert all(any(item['tool'] == 'probe_dependency_probe'
                       and item['args'] == {'dependency': 'localapp'}
                       for item in row['calls']) == (group_id in {'G01', 'G11'})
                   for group_id, row in contradiction_rows.items())

        # The no-refutation control must never claim a contradiction redirect.
        assert all(row['behavior']['executed_changes']['contradiction'] == 0
                   and not any(event['kind'] == 'contradiction_triggered' for event in row['events'])
                   for row in no_refutation_rows.values())
        assert all(not any(event['kind'] in {'protection_check_selected', 'contradiction_triggered'}
                           for event in row['events'])
                   for row in rows if group(row) == 'G00')
        assert len(list(tmp_path.glob('mechanisms-*/knowledge-conditions-after.json'))) == 12
        assert not list(tmp_path.rglob('cost.json'))
