"""Tool scope enforcement without MCP services or model requests."""
from unittest.mock import AsyncMock

import pytest
from langchain_core.tools import StructuredTool

from src.agent.aiops import tools as module


@pytest.mark.asyncio
async def test_single_library_default_is_real_scope_and_wrong_ids_never_reach_mcp():
    calls = []

    async def search(query: str, kb_id: int, top_k: int = 5):
        """Isolated retrieval endpoint."""
        calls.append((query, kb_id, top_k))
        return {'data_source': 'knowledge_base', 'kb_id': kb_id}

    original = StructuredTool.from_function(coroutine=search, name='search_knowledge_base')
    scoped = module.scope_knowledge_tools([original], [14])[0]
    schema = scoped.args_schema
    assert schema['properties']['kb_id']['enum'] == [14]
    assert schema['properties']['kb_id']['default'] == 14
    assert 'query' in schema['required'] and 'kb_id' not in schema['required']
    assert 'enum' not in original.args['kb_id']
    for bad in (0, 1, 15, True, '14', 14.0):
        with pytest.raises(PermissionError):
            await scoped.ainvoke({'query': 'upstream', 'kb_id': bad})
    assert calls == []
    assert (await scoped.ainvoke({'query': 'upstream', 'top_k': 2}))['kb_id'] == 14
    await scoped.ainvoke({'query': 'health', 'kb_id': 14})
    assert calls == [('upstream', 14, 2), ('health', 14, 5)]


@pytest.mark.asyncio
async def test_multiple_libraries_require_explicit_selection_and_preserve_other_tools():
    async def search(query: str, kb_id: int):
        """Isolated retrieval endpoint."""
        return kb_id

    original = StructuredTool.from_function(coroutine=search, name='search_knowledge_base')
    other = StructuredTool.from_function(coroutine=search, name='other_tool')
    scoped, kept = module.scope_knowledge_tools([original, other], [15, 14, 15])
    assert kept is other
    assert scoped.args_schema['properties']['kb_id']['enum'] == [15, 14]
    assert 'kb_id' in scoped.args_schema['required']
    with pytest.raises(PermissionError):
        await scoped.ainvoke({'query': 'health'})
    assert await scoped.ainvoke({'query': 'health', 'kb_id': 14}) == 14
    assert module.scope_knowledge_tools([original], None) == [original]


@pytest.mark.parametrize('scope', [[], [0], [True], ['14']])
def test_explicit_invalid_scope_is_never_treated_as_unrestricted(scope):
    with pytest.raises(ValueError):
        module.scope_knowledge_tools([], scope)


def test_schema_missing_never_disables_scope_enforcement():
    from types import SimpleNamespace
    with pytest.raises(ValueError, match='schema'):
        module.scope_knowledge_tools([SimpleNamespace(name='search_knowledge_base')], [14])


@pytest.mark.asyncio
async def test_schema_mutation_cannot_expand_runtime_scope():
    async def search(query: str, kb_id: int):
        """Isolated endpoint."""
        return kb_id
    tool = StructuredTool.from_function(coroutine=search, name='search_knowledge_base')
    scoped = module.scope_knowledge_tools([tool], [14])[0]
    scoped.args_schema['properties']['kb_id']['enum'].append(1)
    with pytest.raises(PermissionError):
        await scoped.ainvoke({'query': 'x', 'kb_id': 1})


@pytest.mark.asyncio
@pytest.mark.parametrize('setting', ['invalid', '0', ', ,'])
async def test_invalid_production_scope_disables_only_knowledge_search(monkeypatch, setting):
    from types import SimpleNamespace
    probe = SimpleNamespace(name='probe_inventory')
    search = SimpleNamespace(name='search_knowledge_base')
    monkeypatch.setattr(module, 'load_mcp_tools_safe', AsyncMock(return_value=([search, probe], None)))
    monkeypatch.setattr(module.settings, 'EXPERIENCE_KB_IDS', setting)
    loaded, error = await module.load_agent_tools()
    assert loaded == [probe]
    assert '范围配置无效' in error


@pytest.mark.asyncio
async def test_production_loader_uses_configured_scope(monkeypatch):
    async def search(query: str, kb_id: int):
        """Isolated retrieval endpoint."""
        return kb_id

    original = StructuredTool.from_function(coroutine=search, name='search_knowledge_base')
    monkeypatch.setattr(module, 'load_mcp_tools_safe', AsyncMock(return_value=([original], None)))
    monkeypatch.setattr(module.settings, 'EXPERIENCE_KB_IDS', '15')
    loaded, error = await module.load_agent_tools()
    assert error is None
    with pytest.raises(PermissionError):
        await loaded[0].ainvoke({'query': 'x', 'kb_id': 14})
    assert await loaded[0].ainvoke({'query': 'x'}) == 15


@pytest.mark.asyncio
async def test_scope_rejection_and_default_are_preserved_in_evaluation_trace(tmp_path):
    import json
    from scripts.evaluate_windows_probe import trace_evaluation_tools
    calls = []

    async def search(query: str, kb_id: int):
        """Isolated endpoint."""
        calls.append(kb_id)
        return {'data_source': 'knowledge_base', 'kb_id': kb_id, 'results': []}

    original = StructuredTool.from_function(coroutine=search, name='search_knowledge_base')
    scoped = module.scope_knowledge_tools([original], [14])
    trace = []
    traced = trace_evaluation_tools(scoped, 'target', tmp_path, trace)[0]
    with pytest.raises(PermissionError):
        await traced.ainvoke({'query': 'x', 'kb_id': 1})
    await traced.ainvoke({'query': 'x'})
    assert calls == [14]
    assert trace[0]['status'] == 'failed' and trace[0]['arguments']['kb_id'] == 1
    assert trace[1]['status'] == 'returned' and trace[1]['arguments']['kb_id'] == 14
    assert all(not row['validated_live_evidence'] for row in trace)
    assert json.loads((tmp_path / 'tool_trace.json').read_text(encoding='utf-8')) == trace
