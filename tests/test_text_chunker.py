"""text_chunker.py 的功能测试。

目标：验证文档分块逻辑正确处理各种输入，
包括空内容、页面标记提取、分块大小等。
"""

import pytest
from src.processors.text_chunker import TextChunker
from src.models.document import Document, DocumentMetadata
from src.models.chunk import Chunk


class TestTextChunkerEmptyInput:
    """空输入处理。"""

    def test_empty_document_returns_empty_list(self):
        """内容为空的文档应返回空列表。"""
        doc = Document(filename="test.pdf", content="")
        chunker = TextChunker(chunk_size=100, chunk_overlap=10)
        chunks = chunker.split_document(doc)
        assert chunks == []

    def test_none_content_returns_empty_list(self):
        """content 为 None 的文档应返回空列表。"""
        doc = Document(filename="test.pdf", content=None)
        chunker = TextChunker(chunk_size=100, chunk_overlap=10)
        chunks = chunker.split_document(doc)
        assert chunks == []


class TestTextChunkerBasicSplit:
    """基本分块功能。"""

    def test_short_text_produces_one_chunk(self):
        """短于 chunk_size 的文本应产生一个块。"""
        doc = Document(filename="test.pdf", content="Hello world.")
        chunker = TextChunker(chunk_size=100, chunk_overlap=10)
        chunks = chunker.split_document(doc)
        assert len(chunks) == 1
        assert chunks[0].text == "Hello world."

    def test_long_text_produces_multiple_chunks(self):
        """长文本应被分成多个块。"""
        long_text = "这是一段很长的文本。" * 100
        doc = Document(filename="test.pdf", content=long_text)
        chunker = TextChunker(chunk_size=100, chunk_overlap=10)
        chunks = chunker.split_document(doc)
        assert len(chunks) > 1

    def test_chunk_ids_are_unique(self):
        """每个块的 ID 应唯一。"""
        long_text = "这是一段很长的文本。" * 100
        doc = Document(filename="test.pdf", content=long_text, id="doc-123")
        chunker = TextChunker(chunk_size=100, chunk_overlap=10)
        chunks = chunker.split_document(doc)
        ids = [c.id for c in chunks]
        assert len(ids) == len(set(ids))

    def test_chunk_metadata_contains_doc_id(self):
        """块的 metadata 应包含正确的 doc_id。"""
        doc = Document(filename="test.pdf", content="Hello world.", id="doc-abc")
        chunker = TextChunker(chunk_size=100, chunk_overlap=10)
        chunks = chunker.split_document(doc)
        assert chunks[0].metadata.doc_id == "doc-abc"
        assert chunks[0].doc_id == "doc-abc"

    def test_chunk_metadata_contains_source(self):
        """块的 metadata 应包含 source 字段。"""
        doc = Document(
            filename="test.pdf",
            content="Hello world.",
            metadata=DocumentMetadata(source="upload"),
        )
        chunker = TextChunker(chunk_size=100, chunk_overlap=10)
        chunks = chunker.split_document(doc)
        assert chunks[0].metadata.source == "upload"


class TestTextChunkerPageExtraction:
    """页面标记提取。"""

    def test_page_marker_is_extracted(self):
        """文本中的 [Page X] 标记应被提取到 metadata.page。"""
        content = "[Page 3] This is page three content."
        doc = Document(filename="test.pdf", content=content)
        chunker = TextChunker(chunk_size=1000, chunk_overlap=0)
        chunks = chunker.split_document(doc)
        assert len(chunks) >= 1
        assert chunks[0].metadata.page == 3

    def test_slide_marker_is_extracted(self):
        """文本中的 [Slide X] 标记应被提取到 metadata.page。"""
        content = "[Slide 5] Slide five content."
        doc = Document(filename="test.pptx", content=content)
        chunker = TextChunker(chunk_size=1000, chunk_overlap=0)
        chunks = chunker.split_document(doc)
        assert chunks[0].metadata.page == 5


class TestTextChunkerSplitWithPages:
    """split_text_with_pages 方法测试。"""

    def test_preserves_page_numbers(self):
        """按页切分时应保留正确的页码。"""
        pages = [
            (1, "Page one content here."),
            (2, "Page two content here."),
            (3, "Page three content here."),
        ]
        chunker = TextChunker(chunk_size=1000, chunk_overlap=0)
        chunks = chunker.split_text_with_pages(pages, "doc-1", "upload")
        assert len(chunks) == 3
        assert chunks[0].metadata.page == 1
        assert chunks[1].metadata.page == 2
        assert chunks[2].metadata.page == 3

    def test_chunk_index_is_global(self):
        """chunk_index 应为全局递增，不是页内重置。"""
        pages = [
            (1, "A" * 150),
            (2, "B" * 150),
        ]
        chunker = TextChunker(chunk_size=100, chunk_overlap=0)
        chunks = chunker.split_text_with_pages(pages, "doc-1", "upload")
        # 每页 150 字符，chunk_size=100，每页应产生 2 个块
        indices = [c.metadata.chunk_index for c in chunks]
        assert indices == list(range(len(chunks)))

    def test_empty_pages_produce_empty_list(self):
        """空页面列表应返回空列表。"""
        chunker = TextChunker(chunk_size=100, chunk_overlap=10)
        chunks = chunker.split_text_with_pages([], "doc-1", "upload")
        assert chunks == []
