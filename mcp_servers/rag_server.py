"""RAG 知识库检索 MCP Server

把 RAG 检索能力封装为 MCP 工具，让 AIOps Agent 在诊断时能直接查知识库。
复用现有 HybridRetriever + DashScopeReranker，不重写检索逻辑。

两种部署模式:
1. 独立进程: python mcp_servers/rag_server.py  (默认 127.0.0.1:8105)
2. 同进程挂载: main.py 调用 create_rag_mcp_app() 挂载到主 FastAPI 应用
"""

import functools
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# 确保独立进程能 import src 模块
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from fastmcp import FastMCP

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("RAG_MCP_Server")

mcp = FastMCP("RAG")


def log_tool_call(func):
    """装饰器: 统一记录工具调用日志。"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        logger.info("=" * 60)
        logger.info("调用工具: %s", func.__name__)
        logger.info("参数: %s", json.dumps(kwargs, ensure_ascii=False) if kwargs else "无")
        try:
            result = func(*args, **kwargs)
            logger.info("返回: SUCCESS")
            return result
        except Exception as e:
            logger.error("返回: ERROR - %s", e)
            raise
    return wrapper


def _get_retriever():
    """获取 HybridRetriever 单例（懒加载）。"""
    from src.retrieval.hybrid_retriever import HybridRetriever
    if not hasattr(_get_retriever, "_instance"):
        _get_retriever._instance = HybridRetriever()
    return _get_retriever._instance


def _get_reranker():
    """获取 DashScopeReranker 单例（懒加载）。"""
    from src.retrieval.reranker import DashScopeReranker
    from src.settings import settings
    if not hasattr(_get_reranker, "_instance"):
        _get_reranker._instance = DashScopeReranker() if settings.ENABLE_RERANK else None
    return _get_reranker._instance


@mcp.tool()
@log_tool_call
def search_knowledge_base(
    query: str,
    kb_id: int,
    top_k: int = 5
) -> Dict[str, Any]:
    """从知识库中检索与查询相关的文档片段。

    用于运维诊断时查阅运维手册、故障排查指南、操作规范等文档。
    返回按相关度排序的文档片段，包含内容、来源文档、页码和相关度评分。

    Args:
        query: 自然语言检索查询，如 "CPU使用率过高如何排查"
        kb_id: 知识库 ID，指定从哪个知识库检索
        top_k: 返回的文档片段数量，默认 5

    Returns:
        包含 results 列表（每个元素有 content/source/page/score）和 total 计数。
    """
    retriever = _get_retriever()
    reranker = _get_reranker()

    # 混合检索（向量 + BM25 + RRF 融合）
    initial_k = top_k * 2 if reranker else top_k
    search_results = retriever.retrieve(query, top_k=initial_k, kb_ids=[kb_id])

    # Rerank
    if reranker and search_results:
        search_results = reranker.rerank(query, search_results)
    else:
        search_results = search_results[:top_k]

    # 格式化输出
    results = []
    for r in search_results:
        metadata = r.metadata or {}
        results.append({
            "content": r.text,
            "source": metadata.get("filename", metadata.get("source", "unknown")),
            "page": metadata.get("page", None),
            "score": round(r.score, 4) if r.score else None,
            "chunk_id": r.id,
        })

    return {
        "query": query,
        "kb_id": kb_id,
        "results": results,
        "total": len(results),
    }


@mcp.tool()
@log_tool_call
def list_knowledge_bases() -> Dict[str, Any]:
    """列出所有可用的知识库，包含 ID、名称和文档数量。

    当不确定该查哪个知识库时，先调用此工具查看可用列表。

    Returns:
        包含 knowledge_bases 列表和 total 计数。
    """
    from src.database.sql_session import SessionLocal
    from sqlalchemy import text as sql_text

    db = SessionLocal()
    try:
        rows = db.execute(sql_text(
            "SELECT kb.id, kb.name, kb.kb_uid, COUNT(kd.id) as doc_count "
            "FROM knowledge_bases kb "
            "LEFT JOIN knowledge_documents kd ON kb.id = kd.kb_id AND kd.status = 2 "
            "GROUP BY kb.id"
        )).fetchall()

        bases = []
        for row in rows:
            bases.append({
                "id": row[0],
                "name": row[1],
                "uid": row[2],
                "document_count": row[3],
            })

        return {"knowledge_bases": bases, "total": len(bases)}
    finally:
        db.close()


@mcp.tool()
@log_tool_call
def get_document_info(doc_id: int) -> Dict[str, Any]:
    """获取指定文档的详细信息和文本片段概要。

    当需要了解某篇文档的具体内容时使用。

    Args:
        doc_id: 文档 ID

    Returns:
        文档元信息和前 10 个 chunk 的内容摘要。
    """
    from src.database.sql_session import SessionLocal
    from sqlalchemy import text as sql_text

    db = SessionLocal()
    try:
        # 文档元信息
        doc = db.execute(sql_text(
            "SELECT id, doc_uid, filename, file_type, file_size, status, chunk_count "
            "FROM knowledge_documents WHERE id = :doc_id"
        ), {"doc_id": doc_id}).fetchone()

        if not doc:
            return {"error": f"文档 ID {doc_id} 不存在"}

        # 前 10 个 chunk
        chunks = db.execute(sql_text(
            "SELECT id, chunk_uid, content, page_num "
            "FROM document_chunks WHERE doc_id = :doc_id ORDER BY id LIMIT 10"
        ), {"doc_id": doc_id}).fetchall()

        chunk_summaries = []
        for c in chunks:
            content = c[2] or ""
            chunk_summaries.append({
                "chunk_id": c[1],
                "page": c[3],
                "preview": content[:200] + "..." if len(content) > 200 else content,
            })

        return {
            "doc_id": doc[0],
            "uid": doc[1],
            "filename": doc[2],
            "file_type": doc[3],
            "file_size": doc[4],
            "status": doc[5],
            "chunk_count": doc[6],
            "chunks": chunk_summaries,
        }
    finally:
        db.close()


def create_rag_mcp_app():
    """创建 RAG MCP 的 Starlette 子应用，供 main.py 挂载。"""
    return mcp.http_app(path="/mcp", transport="streamable-http", stateless_http=True)


if __name__ == "__main__":
    # 独立进程模式: python mcp_servers/rag_server.py
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8105, path="/mcp")
