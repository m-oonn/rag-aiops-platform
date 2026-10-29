"""从已完成的 SQL 文档构建指定知识库的本地关键词索引。"""

from src.database.models import DocumentChunk, KnowledgeDocument
from src.retrieval.bm25_retriever import BM25Retriever


def retrieve_knowledge_bm25(db, kb_id: int, query: str, top_k: int = 5):
    # 每次读取当前库，避免进程内缓存遗漏新上传、重试或删除的文档。
    rows = db.query(DocumentChunk, KnowledgeDocument).join(
        KnowledgeDocument, DocumentChunk.doc_id == KnowledgeDocument.id
    ).filter(KnowledgeDocument.kb_id == kb_id, KnowledgeDocument.status == 2).all()
    retriever = BM25Retriever()
    retriever.index_chunks([
        (chunk.chunk_uid, chunk.content, {
            "kb_id": kb_id, "doc_id": doc.id, "filename": doc.filename,
            "page": chunk.page_num, "source_url": doc.source_url,
        }) for chunk, doc in rows if chunk.content
    ])
    return retriever.retrieve(query.strip(), top_k=top_k, kb_ids=[kb_id])
