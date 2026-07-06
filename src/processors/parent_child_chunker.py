"""父子块切分策略。

父块 ≈ 1000 tokens（检索返回的上下文单元）
子块 ≈ 200 tokens（向量索引的最小粒度）

子块命中时，在 retrieval 层自动替换为对应的父块，
兼顾向量检索的精度（细粒度匹配）和 LLM 输入的上下文完整性。
"""

import uuid
from typing import Callable, List, Optional, Tuple

from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.models.chunk import Chunk, ChunkMetadata


class ParentChildChunker:
    """创建父子块两级结构。

    子块用于 embedding 索引，父块用于 retrieval 返回。
    每个子块 metadata 中记录 parent_id / parent_text，HybridRetriever
    在返回时用 parent_text 覆盖 chunk.text。
    """

    def __init__(
        self,
        parent_chunk_size: int = 1000,
        parent_overlap: int = 100,
        child_chunk_size: int = 200,
        child_overlap: int = 50,
        separators: Optional[List[str]] = None,
    ):
        if separators is None:
            separators = ["\n\n", "\n", "。", "！", "？", ".", " ", ""]
        self.parent_splitter = RecursiveCharacterTextSplitter(
            chunk_size=parent_chunk_size,
            chunk_overlap=parent_overlap,
            separators=separators,
        )
        self.child_splitter = RecursiveCharacterTextSplitter(
            chunk_size=child_chunk_size,
            chunk_overlap=child_overlap,
            separators=separators,
        )

    def split_document(
        self,
        document: "Document",
    ) -> List[Chunk]:
        """将 Document 拆成子块（每个子块携带父块内容）。"""
        if not document.content:
            return []

        parent_texts = self.parent_splitter.split_text(document.content)
        chunks: List[Chunk] = []
        child_index = 0

        for pi, parent_text in enumerate(parent_texts):
            parent_id = f"parent_{document.id}_{pi}"
            child_texts = self.child_splitter.split_text(parent_text)

            for child_text in child_texts:
                chunk_id = f"child_{document.id}_{child_index}"
                chunks.append(Chunk(
                    id=chunk_id,
                    text=child_text,
                    metadata=ChunkMetadata(
                        doc_id=str(document.id),
                        page=pi,
                        section=None,
                        chunk_index=child_index,
                        source=document.metadata.source if document.metadata else None,
                    ),
                    doc_id=str(document.id),
                ))
                child_index += 1

        return chunks

    def split_text_with_pages(
        self,
        pages: List[Tuple[int, str]],
        doc_id: str,
        source: str,
    ) -> List[Chunk]:
        """按页做父子切分，保留页码。"""
        chunks: List[Chunk] = []
        child_index = 0

        for page_num, page_text in pages:
            parent_texts = self.parent_splitter.split_text(page_text)
            for pi, parent_text in enumerate(parent_texts):
                child_texts = self.child_splitter.split_text(parent_text)
                for child_text in child_texts:
                    chunk_id = f"child_{doc_id}_{child_index}"
                    chunks.append(Chunk(
                        id=chunk_id,
                        text=child_text,
                        metadata=ChunkMetadata(
                            doc_id=doc_id,
                            page=page_num,
                            section=f"parent_{pi}",
                            chunk_index=child_index,
                            source=source,
                        ),
                        doc_id=doc_id,
                    ))
                    child_index += 1

        return chunks
