"""Knowledge recipe and audit for the controller-owned local fixture only."""
import hashlib
import json
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fixture_chunks(directory):
    return [
        ('localapp-guide', 'localapp availability ' + (Path(directory) / 'localapp-availability.md').read_text(encoding='utf-8'),
            {'kb_id': 14, 'filename': 'localapp-availability.md', 'page': 1}),
        ('cpu-guide', 'processor utilization sampling interval', {'kb_id': 14}),
        ('disk-guide', 'disk capacity filesystem storage', {'kb_id': 14}),
        ('auth-guide', 'identity certificate authentication login', {'kb_id': 14}),
    ]


def knowledge_conditions(directory, *, mode='mcp_fixture'):
    directory = Path(directory)
    files = sorted(path for path in directory.rglob('*') if path.is_file()
                   and path.suffix.lower() in ({'.md', '.jsonl'} if mode == 'local_runbooks' else {'.md'}))
    sources = [{'path': path.relative_to(directory).as_posix(),
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in files]
    if not any(path.suffix.lower() == '.md' for path in files):
        raise ValueError('knowledge corpus is empty')
    if mode == 'local_runbooks':
        from src.agent.aiops import local_retrieval
        # This path uses the actual isolated keyword retriever, not the MCP fixture index.
        implementations = ['scripts/knowledge_conditions.py', 'scripts/evaluate_windows_probe.py',
            'src/agent/aiops/local_retrieval.py']
        value = {'version': 2, 'mode': mode, 'scope': 'isolated local runbooks; not MCP or production corpus',
            'sources': sources, 'retrieval': {'planning': 'isolated_local_runbooks',
                'implementation': 'retrieve_local', 'top_k': local_retrieval._EXPERIENCE_TOP_K, 'external_corpora': False},
            'implementations': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                for name in implementations}}
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        return {**value, 'sha256': hashlib.sha256(encoded.encode('utf-8')).hexdigest()}
    if mode != 'mcp_fixture':
        raise ValueError('unsupported knowledge baseline mode')
    implementations = ['scripts/knowledge_conditions.py', 'scripts/verify_windows_probe_graph.py',
        'src/agent/aiops/local_retrieval.py', 'src/retrieval/bm25_retriever.py', 'mcp_servers/rag_server.py']
    value = {'version': 1, 'scope': 'controller-owned Markdown/BM25 fixture; not production PDF corpus',
        'sources': sources, 'chunks': [list(chunk) for chunk in fixture_chunks(directory)],
        'retrieval': {'kb_id': 14, 'rag_min_score': 0.1, 'rerank': False, 'planning': 'isolated_local_runbooks'},
        'packages': {name: version(name) for name in ('rank-bm25', 'fastmcp')},
        'implementations': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in implementations}}
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return {**value, 'sha256': hashlib.sha256(encoded.encode('utf-8')).hexdigest()}


def check_knowledge_conditions(expected_path, directory, output, endpoint, phase):
    record = {'phase': phase, 'endpoint': endpoint, 'passed': False, 'remote_index_verified': False}
    try:
        expected = json.loads(Path(expected_path).read_text(encoding='utf-8'))
        mode = expected.get('mode', 'mcp_fixture')
        if (mode == 'local_runbooks') != (not endpoint):
            raise ValueError('knowledge baseline mode does not match retrieval endpoint')
        actual = knowledge_conditions(directory, mode=mode)
        if mode == 'local_runbooks':
            record['mode'] = mode
        record.update(expected_sha256=expected.get('sha256'), actual_sha256=actual['sha256'])
        # Compare all fields so changing a manifest without recomputing its hash also fails.
        if expected != actual:
            raise ValueError('knowledge conditions changed')
        if mode == 'local_runbooks':
            saved = Path(output) / 'knowledge-baseline.json'
            if phase == 'before':
                saved.write_text(json.dumps(actual, ensure_ascii=False, indent=2), encoding='utf-8')
            elif json.loads(saved.read_text(encoding='utf-8')) != actual:
                raise ValueError('saved knowledge baseline changed')
            record['baseline_file'] = saved.name
        record['passed'] = True
    except Exception as exc:
        record['error'] = type(exc).__name__
        raise
    finally:
        (Path(output) / ('knowledge-conditions-' + phase + '.json')).write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    return record
