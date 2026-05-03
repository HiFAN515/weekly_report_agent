"""
多格式导出器

功能：
  - Markdown 写文件
  - DOCX 导出（python-docx）
"""

from __future__ import annotations

from datetime import date
from pathlib import Path


class Exporter:
    """周报导出器"""

    def __init__(self, output_dir: str | Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def export_markdown(self, content: str, week_start: date, week_end: date,
                        filename: str = None) -> Path:
        """导出为 Markdown 文件"""
        if not filename:
            filename = f"{week_start.isoformat()}_{week_end.isoformat()}_weekly_report.md"
        filepath = self.output_dir / filename
        filepath.write_text(content, encoding="utf-8")
        return filepath

    def export_docx(self, content: str, week_start: date, week_end: date,
                    filename: str = None) -> Path:
        """导出为 DOCX 文件"""
        from docx import Document
        from docx.shared import Pt, Inches
        from docx.enum.text import WD_ALIGN_PARAGRAPH

        if not filename:
            filename = f"{week_start.isoformat()}_{week_end.isoformat()}_weekly_report.docx"
        filepath = self.output_dir / filename

        doc = Document()

        # 设置默认字体
        style = doc.styles['Normal']
        style.font.name = 'Microsoft YaHei'
        style.font.size = Pt(11)

        # 按行解析 Markdown 并写入
        lines = content.split("\n")
        for line in lines:
            line = line.rstrip()

            if line.startswith("# "):
                doc.add_heading(line[2:], level=1)
            elif line.startswith("## "):
                doc.add_heading(line[3:], level=2)
            elif line.startswith("### "):
                doc.add_heading(line[4:], level=3)
            elif line.startswith("- [ ] ") or line.startswith("- "):
                text = line.lstrip("- ").lstrip("[ ] ")
                doc.add_paragraph(text, style='List Bullet')
            elif line.startswith("|") and "---" not in line:
                # 简单表格处理
                cells = [c.strip() for c in line.split("|")[1:-1]]
                if cells:
                    doc.add_paragraph(" | ".join(cells))
            elif line.startswith("> "):
                p = doc.add_paragraph(line[2:])
                p.style = doc.styles['Quote'] if 'Quote' in [s.name for s in doc.styles] else doc.styles['Normal']
            elif line.strip():
                doc.add_paragraph(line)

        doc.save(str(filepath))
        return filepath
