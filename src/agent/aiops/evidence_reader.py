"""An explicit, run-scoped read of already collected redacted evidence."""
import json
import re
import os
from pathlib import Path

from langchain_core.tools import tool
from src.agent.aiops import run_store
from src.probe.protocol import raw_hash, redact
from src.settings import settings


def validate_read_arguments(evidence_id, query=None, offset=0, limit=4000):
    if not isinstance(evidence_id, str) or not re.fullmatch(r'ev-[A-Za-z0-9]{16,80}', evidence_id):
        raise ValueError('invalid evidence identity')
    if type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= 16384:
        raise ValueError('invalid evidence page')
    if query is not None and (not isinstance(query, str) or len(query) > 256):
        raise ValueError('invalid literal query')


def read_query_key(arguments):
    validate_read_arguments(**arguments)
    return (arguments['evidence_id'], arguments.get('query') or None,
            arguments.get('offset', 0), arguments.get('limit', 4000))


def stored_excerpt(raw, query=None, offset=0, limit=4000):
    text = json.dumps(redact(raw), ensure_ascii=False, indent=2)
    if query:
        text = '\n'.join(line for line in text.splitlines() if query in line)
    excerpt = text[offset:offset + limit].encode('utf-8')[:16384].decode('utf-8', errors='ignore')
    return {'excerpt': excerpt, 'offset': offset,
            'next_offset': offset + len(excerpt) if offset + len(excerpt) < len(text) else None,
            'truncated': bool(offset or len(excerpt) < len(text))}


def read_run_evidence(thread_id, user_id, evidence_id, query=None, offset=0, limit=4000):
    validate_read_arguments(evidence_id, query, offset, limit)
    if user_id is None:
        raise ValueError('invalid evidence identity')
    run = run_store.get_run(thread_id)
    if not run or run.user_id != user_id:
        raise PermissionError('evidence unavailable for this run')
    row = run_store.get_evidence(thread_id, evidence_id, user_id)
    if not row or not row.get('raw_ref'):
        raise PermissionError('evidence unavailable for this run')
    root = Path(settings.PROBE_EVIDENCE_DIR).resolve(strict=True)
    path = Path(row['raw_ref'])
    if (path.is_symlink() or any(getattr(p.lstat(), 'st_file_attributes', 0) & 0x400
            for p in (path, *path.parents)) or path.resolve(strict=True).parent != root
            or path.name != evidence_id + '.json' or path.stat().st_size > 1024 * 1024):
        raise PermissionError('unsafe evidence reference')
    with path.open('rb') as handle:
        if os.name == 'nt':
            import msvcrt
            import win32file
            actual = win32file.GetFinalPathNameByHandle(msvcrt.get_osfhandle(handle.fileno()), 0)
            actual = actual[4:] if actual.startswith('\\\\?\\') else actual
            actual = Path(actual).resolve(strict=True)
        else:
            actual = Path(f'/proc/self/fd/{handle.fileno()}').resolve(strict=True)
        if actual != path.resolve(strict=True) or actual.parent != root:
            raise PermissionError('opened evidence escaped storage')
        content = handle.read(1024 * 1024 + 1)
        if len(content) > 1024 * 1024:
            raise ValueError('evidence exceeds stored size limit')
    raw = json.loads(content)
    if (not isinstance(raw, dict) or raw.get('target_id') != row['target_id']
            or row.get('source') != 'windows_probe'
            or raw.get('data_source') != 'probe_target' or raw.get('platform') != 'windows'
            or raw.get('operation') != row['kind']
            or run_store._parse_utc(raw.get('collected_at')) != run_store._parse_utc(row['collected_at'])
            or raw_hash(raw.get('payload')) != row['raw_hash'] or raw.get('raw_hash') != row['raw_hash']):
        raise ValueError('evidence integrity check failed')
    return {'data_source': 'evidence_excerpt', 'evidence_id': evidence_id,
            'target_id': row['target_id'], 'operation': row['kind'],
            'collected_at': row['collected_at'], 'raw_hash': row['raw_hash'],
            'fresh': row['fresh'], **stored_excerpt(raw, query, offset, limit), 'new_observation': False}


def evidence_read_tool(thread_id, user_id):
    @tool
    def read_run_evidence(evidence_id: str, query: str | None = None, offset: int = 0, limit: int = 4000) -> dict:
        """Read a bounded redacted excerpt from this run's existing evidence ID; literal query only, no filesystem paths."""
        return globals()['read_run_evidence'](thread_id, user_id, evidence_id, query, offset, limit)
    return read_run_evidence
