"""从项目运维手册生成两页文本 PDF；需要 reportlab（桌面 bundled Python 已提供）。"""
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak

ROOT = Path(__file__).resolve().parents[1]


def build():
    pdfmetrics.registerFont(TTFont('Runbook', 'C:/Windows/Fonts/simsun.ttc', subfontIndex=0))
    body = ParagraphStyle('body', fontName='Runbook', fontSize=11, leading=18, spaceAfter=7,
                          wordWrap='CJK')
    heading = ParagraphStyle('heading', parent=body, fontSize=15, leading=23, spaceBefore=12)
    for source in sorted((ROOT / 'docs/fixtures/ops-runbooks').glob('*.md')):
        story = []
        section = 0
        for line in source.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            if line.startswith('## '):
                section += 1
                if section == 2:
                    story.append(PageBreak())
            style = heading if line.startswith('#') else body
            story.append(Paragraph(escape(line.lstrip('# ').strip()), style))
        target = source.with_suffix('.pdf')
        def footer(canvas, doc):
            canvas.setFont('Runbook', 9)
            canvas.drawString(46, 25, f'项目运维排查手册 | 2026-10-23 | 第 {doc.page} 页')
        SimpleDocTemplate(str(target), pagesize=(595, 842), leftMargin=46, rightMargin=46,
                          topMargin=38, bottomMargin=45).build(story, onFirstPage=footer, onLaterPages=footer)
        print(target)


if __name__ == '__main__':
    build()
