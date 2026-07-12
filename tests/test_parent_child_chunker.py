"""parent_child_chunker.py 的功能测试。

目标：验证父子块切分策略正确创建两级结构，
子块用于 embedding 索引，父块用于 retrieval 返回。
"""

import pytest
from src.processors.parent_child_chunker import ParentChildChunker
from src.models.document import Document, DocumentMetadata
from src.models.chunk import Chunk


class TestParentChildChunkerEmpty:
    """空输入处理。"""

    def test_empty_document_returns_empty_list(self):
        """内容为空的文档应返回空列表。"""
        doc = Document(filename="test.pdf", content="")
        chunker = ParentChildChunker(parent_chunk_size=100, child_chunk_size=50)
        chunks = chunker.split_document(doc)
        assert chunks == []

    def test_none_content_returns_empty_list(self):
        """content 为 None 的文档应返回空列表。"""
        doc = Document(filename="test.pdf", content=None)
        chunker = ParentChildChunker(parent_chunk_size=100, child_chunk_size=50)
        chunks = chunker.split_document(doc)
        assert chunks == []


class TestParentChildChunkerBasicSplit:
    """基本分块功能。"""

    def test_short_text_produces_chunks(self):
        """短文本应至少产生一个子块。"""
        doc = Document(filename="test.pdf", content="Hello world.")
        chunker = ParentChildChunker(parent_chunk_size=100, child_chunk_size=50)
        chunks = chunker.split_document(doc)
        assert len(chunks) >= 1

    def test_long_text_produces_multiple_chunks(self):
        """长文本应产生多个子块。"""
        long_text = "这是一段很长的文本，用于测试分块功能。" * 50
        doc = Document(filename="test.pdf", content=long_text)
        chunker = ParentChildChunker(parent_chunk_size=100, child_chunk_size=50)
        chunks = chunker.split_document(doc)
        assert len(chunks) > 1

    def test_child_chunks_are_smaller_than_parent_size(self):
        """子块文本不应超过 child_chunk_size。"""
        long_text = "A" * 500
        doc = Document(filename="test.pdf", content=long_text)
        chunker = ParentChildChunker(parent_chunk_size=200, child_chunk_size=50, child_overlap=0)
        chunks = chunker.split_document(doc)
        for chunk in chunks:
            assert len(chunk.text) <= 50 + 10  # 允许少量误差

    def test_chunk_ids_are_unique(self):
        """每个子块的 ID 应唯一。"""
        long_text = "这是一段很长的文本。" * 50
        doc = Document(filename="test.pdf", content=long_text, id="doc-xyz")
        chunker = ParentChildChunker(parent_chunk_size=100, child_chunk_size=50)
        chunks = chunker.split_document(doc)
        ids = [c.id for c in chunks]
        assert len(ids) == len(set(ids))

    def test_chunk_metadata_contains_doc_id(self):
        """子块的 metadata 应包含正确的 doc_id。"""
        doc = Document(filename="test.pdf", content="Hello world.", id="doc-abc")
        chunker = ParentChildChunker(parent_chunk_size=100, child_chunk_size=50)
        chunks = chunker.split_document(doc)
        assert chunks[0].metadata.doc_id == "doc-abc"
        assert chunks[0].doc_id == "doc-abc"


class TestParentChildChunkerSplitWithPages:
    """split_text_with_pages 方法测试。"""

    def test_preserves_page_numbers(self):
        """按页切分时应保留正确的页码。"""
        pages = [
            (1, "Page one content here."),
            (2, "Page two content here."),
        ]
        chunker = ParentChildChunker(parent_chunk_size=1000, child_chunk_size=500)
        chunks = chunker.split_text_with_pages(pages, "doc-1", "upload")
        assert len(chunks) >= 2
        page_numbers = {c.metadata.page for c in chunks}
        assert 1 in page_numbers
        assert 2 in page_numbers

    def test_chunk_index_is_global(self):
        """chunk_index 应为全局递增。"""
        pages = [
            (1, "A" * 200),
            (2, "B" * 200),
        ]
        chunker = ParentChildChunker(parent_chunk_size=100, child_chunk_size=50, child_overlap=0)
        chunks = chunker.split_text_with_pages(pages, "doc-1", "upload")
        indices = [c.metadata.chunk_index for c in chunks]
        assert indices == list(range(len(chunks)))

    def test_empty_pages_produce_empty_list(self):
        """空页面列表应返回空列表。"""
        chunker = ParentChildChunker(parent_chunk_size=100, child_chunk_size=50)
        chunks = chunker.split_text_with_pages([], "doc-1", "upload")
        assert chunks == []

    def test_section_field_records_parent_index(self):
        """section 字段应记录父块索引。"""
        pages = [(1, "A" * 200)]
        chunker = ParentChildChunker(parent_chunk_size=100, child_chunk_size=50, child_overlap=0)
        chunks = chunker.split_text_with_pages(pages, "doc-1", "upload")
        for chunk in chunks:
            assert chunk.metadata.section is not None
            assert chunk.metadata.section.startswith("parent_")
