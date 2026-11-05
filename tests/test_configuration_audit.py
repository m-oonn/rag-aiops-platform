import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts.audit_configuration import consumers, display, environment_file
from scripts import with_agent_test_env as launcher
from src.settings import Settings


@pytest.mark.parametrize(('name', 'value'), [
    ('LLM_API_KEY', 'private-value'), ('SECRET_KEY', 'private-value'),
    ('PROBE_TOKEN', 'private-value'), ('MINIO_ACCESS_KEY', 'private-value'),
    ('PROMETHEUS_URL', 'https://user:private-value@example.com/api?token=private-value'),
    ('DIAGNOSTIC_TARGET_CATALOG', '{"token":"private-value","url":"https://host"}'),
])
def test_inventory_redacts_credentials_and_structured_values(name, value):
    assert 'private-value' not in json.dumps(display(name, value))


def test_inventory_preserves_nonsecret_token_limits():
    assert display('ACCESS_TOKEN_EXPIRE_MINUTES', 480) == 480
    assert display('DATABASE_URL', 'sqlite:///./test.db') == 'sqlite:///./test.db'


def test_profile_overrides_only_child_environment_and_all_agent_roles(tmp_path, monkeypatch):
    path = tmp_path / 'private.env'
    path.write_text('LLM_API_BASE=https://example.com/v1\nLLM_API_KEY=private-value\n'
                    'AGENT_MODEL=deepseek-v4.1-flash-1017\n', encoding='utf-8')
    monkeypatch.setenv('AGENT_MODEL', 'parent-model')
    env = launcher.profile_environment(path, {'AGENT_MODEL': 'parent-model',
        'AGENT_MODEL_SIMPLE': 'old-model', 'EVIDENCE_LLM_MODEL': 'old-judge',
        'AGENT_DISABLE_THINKING': 'true', 'DATABASE_URL': 'unchanged'})
    assert env['AGENT_MODEL'] == env['AGENT_MODEL_SIMPLE'] == env['EVIDENCE_LLM_MODEL'] == 'deepseek-v4.1-flash-1017'
    assert env['AGENT_DISABLE_THINKING'] == 'false'
    assert env['DATABASE_URL'] == 'unchanged'
    assert os.environ['AGENT_MODEL'] == 'parent-model'


@pytest.mark.parametrize('extra', ['DATABASE_URL=other', 'LLM_API_BASE=http://example.com/v1',
    'LLM_API_BASE=https://user:private-value@example.com/v1', 'LLM_API_KEY='])
def test_profile_rejects_unsupported_overrides_without_values(tmp_path, extra):
    path = tmp_path / 'private.env'
    path.write_text('LLM_API_BASE=https://example.com/v1\nLLM_API_KEY=private-value\n'
                    'AGENT_MODEL=deepseek-v4.1-flash-1017\n' + extra + '\n', encoding='utf-8')
    with pytest.raises(ValueError) as error:
        launcher.profile_environment(path, {})
    assert 'private-value' not in str(error.value)


def test_launcher_check_is_explicit_subprocess_and_does_not_call_model(monkeypatch):
    fake = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr(launcher, 'profile_environment', lambda path: {'AGENT_MODEL': 'test'})
    monkeypatch.setattr(launcher.subprocess, 'run', fake)
    assert launcher.main(['--check']) == 0
    assert fake.call_args.args[0][1:] == ['scripts/audit_configuration.py', '--profile-check']
    assert fake.call_args.kwargs['env'] == {'AGENT_MODEL': 'test'}
    with pytest.raises(SystemExit):
        launcher.main(['scripts/arbitrary.py'])
    assert fake.call_count == 1


def test_launcher_selects_dedicated_profile_without_changing_default(tmp_path, monkeypatch):
    path = tmp_path / 'deepseek.env'
    path.write_text('LLM_API_BASE=https://api.deepseek.com\nLLM_API_KEY=private-test-key\n'
                    'AGENT_MODEL=deepseek-v4-flash\nAGENT_DISABLE_THINKING=true\n', encoding='utf-8')
    fake = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr(launcher.subprocess, 'run', fake)
    monkeypatch.setenv('LLM_API_BASE', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
    assert launcher.main(['--profile', str(path), '--check']) == 0
    env = fake.call_args.kwargs['env']
    assert env['AGENT_MODEL'] == env['AGENT_MODEL_SIMPLE'] == env['EVIDENCE_LLM_MODEL'] == 'deepseek-v4-flash'
    assert env['LLM_API_BASE'] == 'https://api.deepseek.com'
    assert env['AGENT_DISABLE_THINKING'] == 'true'
    assert os.environ['LLM_API_BASE'] == 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    assert fake.call_args.args[0][1:] == ['scripts/audit_configuration.py', '--profile-check']


def test_full_example_has_no_missing_unknown_or_duplicate_fields():
    root = Path(__file__).resolve().parents[1]
    values, audit = environment_file(root / '.env.example', set(Settings.model_fields))
    assert not audit['omitted_field_names'] and not audit['unknown_field_names']
    assert not audit['duplicate_field_names']
    cfg = Settings(_env_file=root / '.env.example')
    assert cfg.INVESTIGATION_PROTECTION_STEPS == 2
    assert values['LLM_API_KEY'] == 'sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'


def test_static_scan_includes_dynamic_settings_and_direct_environment(tmp_path):
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src' / 'sample.py').write_text(
        'value = settings.AGENT_MODEL\nother = getattr(settings, "PROBE_ENABLED", False)\n'
        'base = os.getenv("DIRECT_URL")\ncount = os.environ.get("DIRECT_COUNT")\n', encoding='utf-8')
    fields, direct = consumers(tmp_path)
    assert set(fields) == {'AGENT_MODEL', 'PROBE_ENABLED'}
    assert set(direct) == {'DIRECT_URL', 'DIRECT_COUNT'}


def test_aliyun_defaults_are_consistent_without_private_env(monkeypatch):
    for key in ('LLM_API_BASE', 'LLM_MODEL', 'AGENT_MODEL', 'AGENT_MODEL_SIMPLE',
                'EVIDENCE_LLM_MODEL', 'AVAILABLE_MODELS', 'MODEL_DISPLAY_NAMES', 'AGENT_DISABLE_THINKING'):
        monkeypatch.delenv(key, raising=False)
    cfg = Settings(_env_file=None)
    assert cfg.LLM_API_BASE == 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    assert cfg.LLM_MODEL == cfg.AGENT_MODEL == cfg.AGENT_MODEL_SIMPLE == cfg.EVIDENCE_LLM_MODEL == 'deepseek-v4.1-flash-1017'
    assert cfg.AVAILABLE_MODELS == 'deepseek-v4.1-flash-1017'
    assert cfg.AGENT_DISABLE_THINKING


def test_rag_and_agent_factories_share_aliyun_provider_without_network(monkeypatch):
    from src.settings import settings
    from src.llm import llm_client as rag
    from src.agent import aiops_llm as agent
    for name, value in {'LLM_MODEL': 'deepseek-v4.1-flash-1017', 'AGENT_MODEL': 'deepseek-v4.1-flash-1017',
                        'LLM_API_BASE': 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'LLM_API_KEY': 'synthetic-test-key',
                        'AGENT_DISABLE_THINKING': False, 'AVAILABLE_MODELS': 'deepseek-v4.1-flash-1017',
                        'LLM_FALLBACK_ENABLED': False}.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.delenv('AGENT_MODEL', raising=False)
    factory = Mock()
    monkeypatch.setattr(rag, 'ChatOpenAI', factory)
    monkeypatch.setattr(agent, 'ChatOpenAI', factory)
    client = rag.LLMClient()
    assert client._get_llm('qwen3.8-max') is client.llm
    assert client._get_llm('deepseek-v4-flash', temperature=0) is factory.return_value
    agent.create_agent_llm()
    assert factory.call_count == 3
    for call in factory.call_args_list:
        assert call.kwargs['model'] == 'deepseek-v4.1-flash-1017'
        assert call.kwargs['base_url'] == 'https://dashscope.aliyuncs.com/compatible-mode/v1'
        assert call.kwargs['api_key'] == 'synthetic-test-key'
        assert call.kwargs['extra_body'] is None


def test_agent_factory_uses_official_deepseek_only_for_transient_fallback(monkeypatch):
    from src.settings import settings
    from src import agent as agent_package  # noqa: F401
    from src.agent import aiops_llm as agent

    values = {
        'LLM_API_BASE': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        'LLM_API_KEY': 'aliyun-test-key',
        'AGENT_MODEL': 'deepseek-v4.1-flash-1017',
        'AGENT_DISABLE_THINKING': True,
        'LLM_FALLBACK_ENABLED': True,
        'LLM_FALLBACK_API_BASE': 'https://api.deepseek.com',
        'LLM_FALLBACK_API_KEY': 'deepseek-test-key',
        'LLM_FALLBACK_MODEL': 'deepseek-v4-flash',
    }
    for name, value in values.items():
        monkeypatch.setattr(settings, name, value)
    primary, fallback, wrapped = Mock(), Mock(), Mock()
    primary.with_fallbacks.return_value = wrapped
    factory = Mock(side_effect=[primary, fallback])
    monkeypatch.setattr(agent, 'ChatOpenAI', factory)

    assert agent.create_agent_llm() is wrapped
    assert factory.call_count == 2
    assert factory.call_args_list[0].kwargs['base_url'] == values['LLM_API_BASE']
    assert factory.call_args_list[1].kwargs['base_url'] == values['LLM_FALLBACK_API_BASE']
    primary.with_fallbacks.assert_called_once()


def test_rag_factory_uses_official_deepseek_only_for_transient_fallback(monkeypatch):
    from src.settings import settings
    from src.llm import llm_client as rag

    for name, value in {
        'LLM_MODEL': 'deepseek-v4.1-flash-1017',
        'LLM_API_BASE': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        'LLM_API_KEY': 'aliyun-test-key',
        'LLM_FALLBACK_ENABLED': True,
        'LLM_FALLBACK_API_BASE': 'https://api.deepseek.com',
        'LLM_FALLBACK_API_KEY': 'deepseek-test-key',
        'LLM_FALLBACK_MODEL': 'deepseek-v4-flash',
        'AVAILABLE_MODELS': 'deepseek-v4.1-flash-1017',
    }.items():
        monkeypatch.setattr(settings, name, value)
    primary, fallback, wrapped = Mock(), Mock(), Mock()
    primary.with_fallbacks.return_value = wrapped
    monkeypatch.setattr(rag, 'ChatOpenAI', Mock(side_effect=[primary, fallback]))

    client = rag.LLMClient()
    assert client.llm is wrapped
    primary.with_fallbacks.assert_called_once()
    assert rag.APIConnectionError in primary.with_fallbacks.call_args.kwargs['exceptions_to_handle']


def test_assistant_orm_default_follows_current_model(monkeypatch):
    from src.settings import settings
    from src.database.models import Assistant
    monkeypatch.setattr(settings, 'LLM_MODEL', 'deepseek-v4.1-flash-1017')
    assert Assistant.__table__.c.llm_model.default.arg(None) == 'deepseek-v4.1-flash-1017'


def test_saved_agent_old_provider_model_uses_current_default(monkeypatch):
    from src.settings import settings
    from src.database.models import Agent
    from src.services import agent_tool_service as tools
    monkeypatch.setattr(settings, 'AVAILABLE_MODELS', 'deepseek-v4.1-flash-1017')
    monkeypatch.setattr(settings, 'AGENT_MODEL', 'deepseek-v4.1-flash-1017')
    factory = Mock()
    monkeypatch.setattr(tools, 'create_agent_llm', factory)
    saved = Agent(llm_config={'model': 'deepseek-v4-flash', 'temperature': 0.2})
    assert tools._get_agent_llm(saved) is factory.return_value
    factory.assert_called_once_with(model='deepseek-v4.1-flash-1017', temperature=0.2)
    assert saved.llm_config['model'] == 'deepseek-v4-flash'


def test_model_listing_and_chat_whitelist_use_aliyun(client, monkeypatch):
    from src.settings import settings
    from src.api.routers.chat import ChatRequest
    monkeypatch.setattr(settings, 'LLM_MODEL', 'deepseek-v4.1-flash-1017')
    monkeypatch.setattr(settings, 'AVAILABLE_MODELS', 'deepseek-v4.1-flash-1017')
    monkeypatch.setattr(settings, 'MODEL_DISPLAY_NAMES', 'DeepSeek-V4.1-Flash-1017')
    response = client.get('/api/v1/health/models')
    assert response.status_code == 200
    assert response.json() == {'models': [{'id': 'deepseek-v4.1-flash-1017', 'name': 'DeepSeek-V4.1-Flash-1017'}],
                               'default_model': 'deepseek-v4.1-flash-1017'}
    assert ChatRequest(query='hello', llm_model='deepseek-v4.1-flash-1017').llm_model == 'deepseek-v4.1-flash-1017'
    with pytest.raises(ValueError):
        ChatRequest(query='hello', llm_model='deepseek-v4-flash')
