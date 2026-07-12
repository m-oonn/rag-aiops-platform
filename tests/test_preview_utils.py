"""preview_utils.py 的安全测试。

目标：验证文件预览功能正确防御 XSS 攻击，
确保用户上传的恶意内容不会在浏览器中执行。
"""

import asyncio
import os
import tempfile
import pytest
from fastapi.responses import StreamingResponse, FileResponse

from src.utils.preview_utils import get_preview_response, _sanitize_html


def _read_streaming_body(response: StreamingResponse) -> str:
    """从 StreamingResponse 中读取全部内容（处理异步 body_iterator）。"""
    async def _read():
        body = b""
        async for chunk in response.body_iterator:
            if isinstance(chunk, str):
                body += chunk.encode("utf-8")
            else:
                body += chunk
        return body.decode("utf-8")
    return asyncio.run(_read())


class TestTxtPreviewSecurity:
    """txt 文件预览必须转义 HTML 特殊字符。"""

    def test_txt_with_script_tag_is_escaped(self):
        """txt 文件中的 <script> 标签应被 HTML 转义，不会在浏览器执行。"""
        content = "<script>alert('xss')</script>"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(content)
            f.flush()
            tmp_path = f.name

        try:
            response = get_preview_response(tmp_path, "txt")
            assert isinstance(response, StreamingResponse)
            html_content = _read_streaming_body(response)
            # 转义后 < 应变成 &lt;，不能原样保留 <script>
            assert "<script>" not in html_content
            assert "&lt;script&gt;" in html_content
        finally:
            os.unlink(tmp_path)

    def test_txt_with_img_onerror_is_escaped(self):
        """txt 文件中的 <img onerror=...> 载荷应被转义。"""
        content = '<img src=x onerror=alert(1)>'
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(content)
            f.flush()
            tmp_path = f.name

        try:
            response = get_preview_response(tmp_path, "txt")
            html_content = _read_streaming_body(response)
            assert "onerror" not in html_content or "&lt;" in html_content
        finally:
            os.unlink(tmp_path)


class TestMdPreviewSecurity:
    """md 文件预览必须净化危险 HTML。"""

    def test_md_with_script_tag_is_sanitized(self):
        """md 文件中的 <script> 标签应被移除或转义。"""
        content = "# Title\n\n<script>alert('xss')</script>\n\nNormal text."
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(content)
            f.flush()
            tmp_path = f.name

        try:
            response = get_preview_response(tmp_path, "md")
            assert isinstance(response, StreamingResponse)
            html_content = _read_streaming_body(response)
            # <script> 标签不应原样保留在输出中
            assert "<script>" not in html_content
        finally:
            os.unlink(tmp_path)

    def test_md_with_iframe_is_sanitized(self):
        """md 文件中的 <iframe> 标签应被移除或转义。"""
        content = '# Page\n\n<iframe src="evil.com"></iframe>\n\nText.'
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(content)
            f.flush()
            tmp_path = f.name

        try:
            response = get_preview_response(tmp_path, "md")
            html_content = _read_streaming_body(response)
            assert "<iframe" not in html_content
        finally:
            os.unlink(tmp_path)

    def test_md_with_onclick_event_is_sanitized(self):
        """md 文件中的 on* 事件处理器应被移除。"""
        content = '# Page\n\n<a href="#" onclick="alert(1)">click</a>\n\nText.'
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(content)
            f.flush()
            tmp_path = f.name

        try:
            response = get_preview_response(tmp_path, "md")
            html_content = _read_streaming_body(response)
            assert "onclick" not in html_content
        finally:
            os.unlink(tmp_path)

    def test_md_normal_content_is_preserved(self):
        """正常的 Markdown 内容应被正确渲染。"""
        content = "# Title\n\nThis is **bold** and *italic*."
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(content)
            f.flush()
            tmp_path = f.name

        try:
            response = get_preview_response(tmp_path, "md")
            html_content = _read_streaming_body(response)
            assert "<h1>" in html_content
            assert "<strong>bold</strong>" in html_content
        finally:
            os.unlink(tmp_path)


class TestUnknownFileTypeSecurity:
    """未知文件类型应强制下载，不在浏览器内联渲染。"""

    def test_unknown_type_forces_download(self):
        """未知扩展名的文件应以 attachment 方式返回，防止浏览器内联执行。"""
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
            f.write(b"MZ\x90\x00")
            tmp_path = f.name

        try:
            response = get_preview_response(tmp_path, "exe")
            assert isinstance(response, FileResponse)
            assert response.headers.get("content-disposition", "").startswith("attachment")
        finally:
            os.unlink(tmp_path)

    def test_html_type_forces_download(self):
        """HTML 文件不应被内联渲染，应强制下载防止 XSS。"""
        content = "<script>alert('xss')</script>"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8") as f:
            f.write(content)
            f.flush()
            tmp_path = f.name

        try:
            response = get_preview_response(tmp_path, "html")
            assert isinstance(response, FileResponse)
            assert response.headers.get("content-disposition", "").startswith("attachment")
        finally:
            os.unlink(tmp_path)


class TestPreviewEdgeCases:
    """预览功能的边界情况。"""

    def test_nonexistent_file_returns_none(self):
        """不存在的文件路径应返回 None。"""
        response = get_preview_response("/nonexistent/path/file.txt", "txt")
        assert response is None

    def test_empty_txt_file_returns_valid_response(self):
        """空 txt 文件应返回有效的响应，不崩溃。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("")
            f.flush()
            tmp_path = f.name

        try:
            response = get_preview_response(tmp_path, "txt")
            assert isinstance(response, StreamingResponse)
        finally:
            os.unlink(tmp_path)
