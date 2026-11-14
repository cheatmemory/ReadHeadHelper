# -*- coding: utf-8 -*-
"""上传附件另页：附件N + 空行 + 原文（含表格）。"""
from __future__ import annotations

import base64
import io
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

from core.ir.schema import AttachmentDocx, BodyBlock, LayoutIR, SealMode
from core.layout.engine import DocxEngine


def _make_attach_docx_bytes(*, title: str, with_table: bool = True) -> bytes:
    doc = Document()
    doc.add_paragraph(title)
    doc.add_paragraph("附件正文第一段。")
    if with_table:
        table = doc.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "项目"
        table.cell(0, 1).text = "数量"
        table.cell(1, 0).text = "沙袋"
        table.cell(1, 1).text = "100"
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _base_ir(**kwargs) -> LayoutIR:
    data = dict(
        org_marks=["XX市应急管理局"],
        doc_number="X应急发〔2026〕47号",
        title="关于加强汛期安全生产工作的通知",
        recipient="各县（市、区）应急管理局：",
        body_tree=[BodyBlock(level="p", text="现将有关事项通知如下。")],
        attachment_caption="1. 检查表\n2. 物资清单",
        org_signature="XX市应急管理局",
        date="2026年11月14日",
        print_org="XX市应急管理局办公室",
        print_date="2026年11月14日",
        seal_mode=SealMode.NO_STAMP,
    )
    data.update(kwargs)
    return LayoutIR(**data)


def test_attachment_pages_label_and_table(tmp_path: Path):
    a1 = _make_attach_docx_bytes(title="汛期重点行业领域安全检查表")
    a2 = _make_attach_docx_bytes(title="防汛应急物资储备清单")
    ir = _base_ir(
        attachments=[
            AttachmentDocx(name="检查表.docx", data_b64=base64.b64encode(a1).decode("ascii")),
            AttachmentDocx(name="清单.docx", data_b64=base64.b64encode(a2).decode("ascii")),
        ]
    )
    out = tmp_path / "with_attach.docx"
    DocxEngine().render(ir, out)

    doc = Document(str(out))
    texts = [p.text.strip() for p in doc.paragraphs]
    assert "附件1" in texts
    assert "附件2" in texts
    i1 = texts.index("附件1")
    i2 = texts.index("附件2")
    assert i2 > i1
    # 「附件N」后应有空行，再接原文标题
    assert texts[i1 + 1] == ""
    assert texts[i1 + 2] == "汛期重点行业领域安全检查表"
    assert texts[i2 + 2] == "防汛应急物资储备清单"

    # 分页符：附件标题段前的段落含 page break
    def has_page_break_before(label: str) -> bool:
        for i, p in enumerate(doc.paragraphs):
            if p.text.strip() != label:
                continue
            if i == 0:
                return False
            prev = doc.paragraphs[i - 1]
            for br in prev._p.iter(qn("w:br")):
                if br.get(qn("w:type")) == "page":
                    return True
        return False

    assert has_page_break_before("附件1")
    assert has_page_break_before("附件2")
    assert len(doc.tables) >= 2


def test_sample_attach_merge_smoke(tmp_path: Path):
    """样例国标带附件 docx 可作为附件正文接入（冒烟）。"""
    sample = Path(__file__).resolve().parents[1] / "examples" / "国标样本_通知（带附件）.docx"
    if not sample.is_file():
        return
    raw = sample.read_bytes()
    ir = _base_ir(
        attachments=[
            AttachmentDocx(name=sample.name, data_b64=base64.b64encode(raw).decode("ascii")),
        ]
    )
    out = tmp_path / "sample_as_attach.docx"
    DocxEngine().render(ir, out)
    doc = Document(str(out))
    assert any(p.text.strip() == "附件1" for p in doc.paragraphs)
    assert len(doc.tables) >= 1
