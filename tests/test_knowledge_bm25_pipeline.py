"""真实本地解析、持久化、查询与 MCP 的免费边界回归。"""

from unittest.mock import Mock

import fitz
import pytest
from sqlalchemy.orm import sessionmaker

from src.database.models import KnowledgeBase, KnowledgeDocument, DocumentChunk


@pytest.fixture
def local_pipeline(monkeypatch, engine, tmp_path):
    import src.worker.tasks as worker
    import src.api.routers.knowledge_base as api
    import src.database.sql_session as sql
    import mcp_servers.rag_server as rag
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(worker, 'SessionLocal', factory)
    monkeypatch.setattr(sql, 'SessionLocal', factory)
    monkeypatch.setattr(api.settings, 'UPLOAD_DIR', tmp_path)
    forbidden = Mock(side_effect=AssertionError('online service must not be called'))
    monkeypatch.setattr(worker, 'get_embedding_service', forbidden)
    monkeypatch.setattr(worker, 'MilvusClient', forbidden)
    monkeypatch.setattr(api, '_try_celery_delay', forbidden)
    monkeypatch.setattr(api.storage_service, 'upload_file', Mock())
    monkeypatch.setattr(rag, '_get_retriever', forbidden)
    monkeypatch.setattr(rag, '_get_reranker', forbidden)
    return forbidden


def test_pdf_upload_search_retry_reprocess_and_mcp(client, auth_headers, db, local_pipeline):
    kb = client.post('/api/v1/knowledge-bases/', headers=auth_headers,
        json={'name': 'Local runbooks', 'chunking_config': {
            'retrieval_mode': 'bm25', 'chunk_size': 250, 'chunk_overlap': 20}}).json()
    pdf = fitz.open()
    pdf.new_page().insert_text((40, 50), 'HTTP 503 downstream connection refused')
    pdf.new_page().insert_text((40, 50), 'Application traceback inspect exception logs')
    response = client.post(f"/api/v1/knowledge-bases/{kb['id']}/upload", headers=auth_headers,
        files={'file': ('runbook.pdf', pdf.tobytes(), 'application/pdf')},
        data={'source_url': 'https://docs.python.org/3/library/socket.html'})
    pdf.close()
    assert response.status_code == 200, response.text
    doc_id = response.json()['doc_id']
    db.expire_all()
    doc = db.get(KnowledgeDocument, doc_id)
    assert doc.status == 2 and doc.chunk_count == 2 and doc.celery_task_id is None
    chunks = db.query(DocumentChunk).filter_by(doc_id=doc_id).all()
    assert {c.page_num for c in chunks} == {1, 2}
    assert all(c.vector_id == '' for c in chunks)
    from mcp_servers.rag_server import search_knowledge_base
    for query, page in [('connection refused', 1), ('traceback', 2)]:
        res = client.post(f"/api/v1/knowledge-bases/{kb['id']}/search", headers=auth_headers,
                          json={'query': query}).json()
        assert res['results'][0]['page'] == page
        assert res['results'][0]['source_url'].startswith('https://docs.python.org/')
        tool = search_knowledge_base.fn(query, kb['id'])
        assert tool['results'][0]['chunk_id'] == res['results'][0]['chunk_id']
    assert client.post(f"/api/v1/knowledge-bases/{kb['id']}/search", headers=auth_headers,
                       json={'query': 'quantum entanglement'}).json()['results'] == []
    for suffix, body in [('retry', None), ('reprocess', {'chunk_size': 200, 'chunk_overlap': 10})]:
        assert client.post(f'/api/v1/knowledge-bases/documents/{doc_id}/{suffix}',
                           headers=auth_headers, json=body).status_code == 200
    db.expire_all()
    assert db.get(KnowledgeDocument, doc_id).chunking_config['retrieval_mode'] == 'bm25'
    assert db.query(DocumentChunk).filter_by(doc_id=doc_id).count() == 2
    local_pipeline.assert_not_called()
    # 空原文重新处理后不能继续检索到上一次的旧片段。
    import src.worker.tasks as worker
    doc = db.get(KnowledgeDocument, doc_id)
    empty = fitz.open()
    empty.new_page()
    empty.save(doc.file_path)
    empty.close()
    assert worker.process_document(doc_id) == 'Completed (No content)'
    db.expire_all()
    assert db.get(KnowledgeDocument, doc_id).chunk_count == 0
    assert db.query(DocumentChunk).filter_by(doc_id=doc_id).count() == 0


def test_search_isolates_kb_and_denies_other_owner(client, auth_headers, db, other_user, local_pipeline):
    from src.retrieval.knowledge_bm25 import retrieve_knowledge_bm25
    for kid, owner in [(101, 1), (102, other_user.id)]:
        db.add(KnowledgeBase(id=kid, kb_uid=str(kid), name='Runbooks', owner_id=owner,
                            chunking_config={'retrieval_mode': 'bm25'}))
        db.flush()
        db.add(KnowledgeDocument(id=kid, doc_uid=str(kid), kb_id=kid, filename='guide.md',
                                file_path='unused', file_type='md', status=2))
        db.flush()
        db.add(DocumentChunk(chunk_uid=str(kid), doc_id=kid, content='downstream refused',
                             page_num=1, vector_id=''))
    db.commit()
    assert {r.id for r in retrieve_knowledge_bm25(db, 101, 'downstream')} == {'101'}
    # 重新读取 SQL，不缓存旧内容或被删除片段。
    db.query(DocumentChunk).filter_by(doc_id=101).delete()
    db.commit()
    assert retrieve_knowledge_bm25(db, 101, 'downstream') == []
    assert client.post('/api/v1/knowledge-bases/102/search', headers=auth_headers,
                       json={'query': 'downstream'}).status_code == 403
    assert client.post('/api/v1/knowledge-bases/101/search', headers=auth_headers,
                       json={'query': 'x', 'top_k': 0}).status_code == 422


def test_invalid_mode_rejected(client, auth_headers):
    assert client.post('/api/v1/knowledge-bases/', headers=auth_headers,
        json={'name': 'Invalid', 'chunking_config': {'retrieval_mode': 'typo'}}).status_code == 422
