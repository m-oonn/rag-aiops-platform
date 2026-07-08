
import html
import os
import pandas as pd
from docx import Document as DocxDocument
from fastapi.responses import StreamingResponse, FileResponse
import io
import markdown

# 安全最佳实践: 用于净化 Markdown HTML 输出的白名单标签/属性
# bleach 在部分环境不可用，这里用 markdown 的 output_format + 手动净化
try:
    import bleach
    _HAS_BLEACH = True
except ImportError:
    _HAS_BLEACH = False


def _sanitize_html(html_str: str) -> str:
    """净化 HTML 字符串，移除危险的标签和属性。

    安全最佳实践: 用户上传的文件内容不可信任，插入 HTML 前必须净化。
    阻止 <script>、<iframe>、on* 事件处理器等 XSS 载荷。
    """
    if _HAS_BLEACH:
        # 使用 bleach 白名单净化
        return bleach.clean(
            html_str,
            tags=bleach.sanitizer.ALLOWED_TAGS | {
                "h1", "h2", "h3", "h4", "h5", "h6",
                "p", "br", "hr", "table", "thead", "tbody", "tr", "th", "td",
                "pre", "code", "blockquote", "ul", "ol", "li",
                "strong", "em", "del", "a", "img", "span", "div",
            },
            attributes={
                **bleach.sanitizer.ALLOWED_ATTRIBUTES,
                "a": ["href", "title"],
                "img": ["src", "alt", "title"],
            },
            protocols=bleach.sanitizer.ALLOWED_PROTOCOLS,
            strip=True,
        )
    else:
        # bleach 不可用时，用正则移除 <script> 和 on* 事件
        import re
        html_str = re.sub(r"<script[^>]*>.*?</script>", "", html_str, flags=re.DOTALL | re.IGNORECASE)
        html_str = re.sub(r"<iframe[^>]*>.*?</iframe>", "", html_str, flags=re.DOTALL | re.IGNORECASE)
        html_str = re.sub(r"<object[^>]*>.*?</object>", "", html_str, flags=re.DOTALL | re.IGNORECASE)
        html_str = re.sub(r"<embed[^>]*/?>", "", html_str, flags=re.IGNORECASE)
        html_str = re.sub(r'\son\w+\s*=\s*"[^"]*"', "", html_str, flags=re.IGNORECASE)
        html_str = re.sub(r"\son\w+\s*=\s*'[^']*'", "", html_str, flags=re.IGNORECASE)
        html_str = re.sub(r"\son\w+\s*=\s*[^\s>]+", "", html_str, flags=re.IGNORECASE)
        return html_str


def get_preview_response(file_path: str, file_type: str):
    if not os.path.exists(file_path):
        return None

    file_type = file_type.lower()

    if file_type == 'pdf':
        return FileResponse(file_path, media_type="application/pdf", content_disposition_type="inline")

    elif file_type == 'md':
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        # 安全最佳实践: 先用 markdown 转换，再用白名单净化输出
        # 不启用 markdown 内联 HTML(防止 <script> 原样保留)
        html_content = markdown.markdown(content, extensions=['extra', 'codehilite'])
        # 净化: 移除 <script>/<iframe>/on* 事件等危险内容
        html_content = _sanitize_html(html_content)
        full_html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif; padding: 20px; line-height: 1.6; max-width: 800px; margin: 0 auto; }}
                pre {{ background: #f6f8fa; padding: 16px; overflow: auto; border-radius: 6px; }}
                code {{ font-family: ui-monospace,SFMono-Regular,SF Mono,Menlo,Consolas,Liberation Mono,monospace; }}
                table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
                th, td {{ border: 1px solid #dfe2e5; padding: 6px 13px; }}
                th {{ background-color: #f6f8fa; }}
                blockquote {{ border-left: 4px solid #dfe2e5; color: #6a737d; padding-left: 16px; margin: 0; }}
            </style>
        </head>
        <body>
            {html_content}
        </body>
        </html>
        """
        return StreamingResponse(io.StringIO(full_html), media_type="text/html")

    elif file_type == 'txt':
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        # 安全最佳实践: 转义 HTML 特殊字符防止 XSS
        safe_content = html.escape(content)
        html_page = f"""
        <html>
        <head><style>body {{ font-family: monospace; white-space: pre-wrap; padding: 20px; }}</style></head>
        <body>{safe_content}</body>
        </html>
        """
        return StreamingResponse(io.StringIO(html_page), media_type="text/html")

    elif file_type in ['docx', 'doc']:
        try:
            from docx.table import Table
            from docx.text.paragraph import Paragraph

            doc = DocxDocument(file_path)
            html_parts = []
            html_parts.append("<html><head><style>body { font-family: sans-serif; padding: 20px; max-width: 800px; margin: 0 auto; } table { border-collapse: collapse; width: 100%; margin: 10px 0; } td, th { border: 1px solid #ddd; padding: 8px; } p { margin-bottom: 1em; }</style></head><body>")

            for element in doc.element.body.iterchildren():
                if element.tag.endswith('p'):
                    para = Paragraph(element, doc)
                    if para.text.strip():
                        # 安全最佳实践: 转义 docx 段落文本防止 XSS
                        safe_text = html.escape(para.text)
                        if para.style and hasattr(para.style, 'name') and para.style.name.startswith('Heading'):
                            try:
                                level = para.style.name.split(' ')[-1]
                                if level.isdigit():
                                    html_parts.append(f"<h{level}>{safe_text}</h{level}>")
                                    continue
                            except:
                                pass
                        html_parts.append(f"<p>{safe_text}</p>")

                elif element.tag.endswith('tbl'):
                    table = Table(element, doc)
                    html_parts.append("<table>")
                    for row in table.rows:
                        html_parts.append("<tr>")
                        for cell in row.cells:
                            # 安全最佳实践: 转义单元格文本防止 XSS
                            safe_cell = html.escape(cell.text)
                            html_parts.append(f"<td>{safe_cell}</td>")
                        html_parts.append("</tr>")
                    html_parts.append("</table>")

            html_parts.append("</body></html>")
            return StreamingResponse(io.StringIO("".join(html_parts)), media_type="text/html")
        except Exception as e:
            return StreamingResponse(io.StringIO(f"Error previewing DOCX: {str(e)}"), media_type="text/plain")

    elif file_type in ['xlsx', 'xls']:
        try:
            df = pd.read_excel(file_path)
            # 安全最佳实践: to_html 默认转义单元格内容，安全
            html_table = df.to_html(classes='table table-striped', index=False, na_rep='', escape=True)
            full_html = f"""
            <html>
            <head>
                <style>
                    body {{ font-family: sans-serif; padding: 20px; }}
                    table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
                    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                    th {{ background-color: #f2f2f2; font-weight: bold; position: sticky; top: 0; }}
                    tr:nth-child(even) {{ background-color: #f9f9f9; }}
                    tr:hover {{ background-color: #f5f5f5; }}
                </style>
            </head>
            <body>
                {html_table}
            </body>
            </html>
            """
            return StreamingResponse(io.StringIO(full_html), media_type="text/html")
        except Exception as e:
            return StreamingResponse(io.StringIO(f"Error previewing Excel: {str(e)}"), media_type="text/plain")

    else:
        # 安全最佳实践: 未知文件类型强制下载，不内联渲染(防止浏览器以 text/html 执行)
        return FileResponse(
            file_path,
            media_type="application/octet-stream",
            content_disposition_type="attachment",
        )
