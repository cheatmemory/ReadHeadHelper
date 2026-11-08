# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from docx import Document


def extract_text_from_docx(path: str | Path) -> str:
    """从 docx 抽取纯文本，供识别链路使用。"""
    doc = Document(str(path))
    parts: list[str] = []
    for p in doc.paragraphs:
        t = p.text.strip()
        if t:
            parts.append(p.text.rstrip())
    # 表格单元格一并抽出
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append("\t".join(cells))
    return "\n".join(parts).strip()
