# -*- coding: utf-8 -*-
"""§7.3.4 多附件说明：分行编号，勿串成一段。"""
from docx.shared import Pt

from core.ir.schema import BodyBlock, LayoutIR, SealMode
from core.layout import units as U
from core.layout.engine import DocxEngine, _attachment_caption_lines


def test_split_jammed_attachment_line():
    got = _attachment_caption_lines(
        "1.岚州市生活垃圾分类设施改造清单 2.岚州市垃圾分类责任单位分工表"
    )
    assert got == [
        "1.岚州市生活垃圾分类设施改造清单",
        "2.岚州市垃圾分类责任单位分工表",
    ]


def test_multi_attachment_one_line_each(tmp_path):
    from docx import Document

    ir = LayoutIR(
        org_marks=["岚州市人民政府"],
        doc_number="岚政发〔2026〕8号",
        title="岚州市人民政府关于加强城市生活垃圾分类管理工作的通知",
        recipient="各县（市、区）人民政府，市政府各部门：",
        body_tree=[BodyBlock(level="p", text="现就有关事项通知如下：")],
        attachment_caption=(
            "1.岚州市生活垃圾分类设施改造清单\n"
            "2.岚州市垃圾分类责任单位分工表"
        ),
        org_signature="岚州市人民政府",
        date="2026年3月12日",
        print_org="岚州市人民政府办公室",
        print_date="2026年3月13日",
        seal_mode=SealMode.STAMP,
    )
    out = tmp_path / "attach.docx"
    DocxEngine().render(ir, out)
    doc = Document(out)
    attach_paras = []
    for p in doc.paragraphs:
        t = p.text.strip()
        if t.startswith("附件：") or (t[:1].isdigit() and "." in t[:4]):
            attach_paras.append(p)
    assert len(attach_paras) == 2
    assert attach_paras[0].text.startswith("附件：1.")
    assert attach_paras[1].text.startswith("2.")
    name_align = Pt(U.PT_3 * 5)
    assert attach_paras[0].paragraph_format.left_indent == name_align
    assert attach_paras[0].paragraph_format.first_line_indent == Pt(-U.PT_3 * 3)
    assert attach_paras[1].paragraph_format.left_indent == name_align
