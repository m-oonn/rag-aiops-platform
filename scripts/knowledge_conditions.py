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


def knowledge_conditions(directory):
    directory = Path(directory)
    sources = [{'path': path.relative_to(directory).as_posix(),
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in sorted(directory.rglob('*.md'))]
    if not sources:
        raise ValueError('knowledge corpus is empty')
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
        actual = knowledge_conditions(directory)
        record.update(expected_sha256=expected.get('sha256'), actual_sha256=actual['sha256'])
        # Compare all fields so changing a manifest without recomputing its hash also fails.
        if expected != actual:
            raise ValueError('knowledge conditions changed')
        record['passed'] = True
    except Exception as exc:
        record['error'] = type(exc).__name__
        raise
    finally:
        (Path(output) / ('knowledge-conditions-' + phase + '.json')).write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    return record
