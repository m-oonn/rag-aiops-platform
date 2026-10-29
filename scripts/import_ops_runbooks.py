"""向指定的本地关键词知识库追加项目运维 PDF，不调用模型、不覆盖原文。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run(kb_id):
    from src.database.sql_session import SessionLocal
    from src.database.models import KnowledgeBase, KnowledgeDocument, DocumentChunk
    from src.settings import settings
    import src.worker.tasks as worker
    from src.retrieval.knowledge_bm25 import retrieve_knowledge_bm25
    def forbidden(*args, **kwargs):
        raise RuntimeError('Online embeddings and vector writes disabled for this import')
    worker.get_embedding_service = forbidden
    worker.MilvusClient = forbidden
    db = SessionLocal()
    results = []
    try:
        kb = db.get(KnowledgeBase, kb_id)
        assert kb and (kb.chunking_config or {}).get('retrieval_mode') == 'bm25', 'local keyword KB required'
        settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        for source in sorted((ROOT / 'docs/fixtures/ops-runbooks').glob('*.pdf')):
            previous = db.query(KnowledgeDocument).filter_by(kb_id=kb_id, filename=source.name).first()
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            if previous:
                assert Path(previous.file_path).is_file() and hashlib.sha256(Path(previous.file_path).read_bytes()).hexdigest() == digest, 'existing different document; will not overwrite'
                assert previous.status == 2, 'existing incomplete import; inspect before retrying'
                doc = previous
            else:
                uid = str(uuid4())
                target = settings.UPLOAD_DIR / (uid + '_' + source.name)
                shutil.copyfile(source, target)
                references = re.findall(r'https://[^\s]+', source.with_suffix('.md').read_text(encoding='utf-8'))
                doc = KnowledgeDocument(doc_uid=uid, kb_id=kb_id, filename=source.name,
                    file_path=str(target.resolve()), file_type='pdf', file_size=target.stat().st_size,
                    status=0, source_url=references[0], chunking_config=dict(kb.chunking_config))
                db.add(doc)
                db.commit()
                answer = worker.process_document(doc.id)
                db.refresh(doc)
                assert doc.status == 2, answer
            chunks = db.query(DocumentChunk).filter_by(doc_id=doc.id).all()
            assert chunks and {c.page_num for c in chunks} == {1, 2}
            assert all(c.vector_id == '' for c in chunks)
            results.append({'doc_id': doc.id, 'filename': doc.filename, 'chunks': len(chunks),
                'pages': 2, 'source_url': doc.source_url, 'sha256': digest})
        queries = ['连接拒绝', 'TcpTestSucceeded', '监听端口', 'traceback', '应用内部异常',
                   '超时', '响应变慢', 'CPU 快照', 'quantum entanglement']
        checks = []
        for query in queries:
            hits = retrieve_knowledge_bm25(db, kb_id, query)
            checks.append({'query': query, 'hits': [{'chunk_id': h.id, 'filename': h.metadata['filename'],
                'page': h.metadata['page'], 'score': h.score} for h in hits]})
            assert bool(hits) == (query != 'quantum entanglement'), query
            assert all(h.metadata['kb_id'] == kb_id for h in hits)
        report = {'kb_id': kb_id, 'name': kb.name, 'retrieval_mode': 'bm25', 'model_calls': 0,
                  'documents': results, 'checks': checks, 'effectiveness_experiment': False}
        output = ROOT / 'runtime' / ('ops-knowledge-import-' + uuid4().hex)
        output.mkdir()
        (output / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'output': str(output), **report}, ensure_ascii=False))
    finally:
        db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kb-id', type=int, required=True)
    run(parser.parse_args().kb_id)
