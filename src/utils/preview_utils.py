
import os
import pandas as pd
from docx import Document as DocxDocument
from fastapi.responses import StreamingResponse, FileResponse
import io
import markdown

def get_preview_response(file_path: str, file_type: str):
    if not os.path.exists(file_path):
        return None
        
    file_type = file_type.lower()
    
    if file_type == 'pdf':
        return FileResponse(file_path, media_type="application/pdf", content_disposition_type="inline")
    
    elif file_type == 'md':
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        html_content = markdown.markdown(content, extensions=['extra', 'codehilite'])
        # Add basic styling
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
        # Wrap in pre to preserve whitespace
        html = f"""
        <html>
        <head><style>body {{ font-family: monospace; white-space: pre-wrap; padding: 20px; }}</style></head>
        <body>{content}</body>
        </html>
        """
        return StreamingResponse(io.StringIO(html), media_type="text/html")
        
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
                        style = ""
                        # Handle headings roughly
                        if para.style and hasattr(para.style, 'name') and para.style.name.startswith('Heading'):
                            try:
                                level = para.style.name.split(' ')[-1]
                                if level.isdigit():
                                    html_parts.append(f"<h{level}>{para.text}</h{level}>")
                                    continue
                            except:
                                pass
                        html_parts.append(f"<p>{para.text}</p>")
                
                elif element.tag.endswith('tbl'):
                    table = Table(element, doc)
                    html_parts.append("<table>")
                    for row in table.rows:
                        html_parts.append("<tr>")
                        for cell in row.cells:
                            html_parts.append(f"<td>{cell.text}</td>")
                        html_parts.append("</tr>")
                    html_parts.append("</table>")
            
            html_parts.append("</body></html>")
            return StreamingResponse(io.StringIO("".join(html_parts)), media_type="text/html")
        except Exception as e:
            return StreamingResponse(io.StringIO(f"Error previewing DOCX: {str(e)}"), media_type="text/plain")
            
    elif file_type in ['xlsx', 'xls']:
        try:
            df = pd.read_excel(file_path)
            html = df.to_html(classes='table table-striped', index=False, na_rep='')
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
                {html}
            </body>
            </html>
            """
            return StreamingResponse(io.StringIO(full_html), media_type="text/html")
        except Exception as e:
            return StreamingResponse(io.StringIO(f"Error previewing Excel: {str(e)}"), media_type="text/plain")
            
    else:
        return FileResponse(file_path)
