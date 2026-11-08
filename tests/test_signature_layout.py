# -*- coding: utf-8 -*-
"""§7.3.5 有章/无章落款：半角日期 + 按实测/估算文本宽算右空。"""
from pathlib import Path
from unittest import mock

from docx import Document
from docx.shared import Pt

from core.ir.schema import BodyBlock, LayoutIR, SealMode
from core.layout import DocxEngine
from core.layout import units as U
from core.layout.engine import _signature_right_indents
from core.layout.office_measure import estimate_layout_width_pt


def test_guowuyuan_halfwidth_targets_with_estimate():
    """国务院 + 2026年11月8日：半角实测约 48/124.8pt → 有章≈2048、无章≈2816 twips。"""
    face = "仿宋_GB2312"
    sig, date = "国务院", "2026年11月8日"
    # 用用户给出的半角宽，避免测试依赖本机 WPS 微小差异
    widths = {sig: 48.0, date: 124.8}

    def fake_width(text, font_face, size_pt):
        return widths[text.strip()]

    with mock.patch("core.layout.engine.layout_text_width_pt", side_effect=fake_width):
        stamp = _signature_right_indents(sig, date, SealMode.STAMP, face)
        nostamp = _signature_right_indents(sig, date, SealMode.NO_STAMP, face)

    assert stamp[1] == Pt(U.PT_3 * 4).pt
    assert abs(stamp[0] * 20 - 2048) < 1e-6
    assert nostamp[1] == Pt(U.PT_3 * 2).pt
    assert abs(nostamp[0] * 20 - 2816) < 1e-6


def test_estimate_digits_narrower_than_char_count():
    """估算下半角日期应窄于「每字一格」，避免再走全角/字符数捷径。"""
    date = "2026年11月8日"
    est = estimate_layout_width_pt(date, U.PT_3)
    assert est < len(date) * U.PT_3
    assert est > 6 * U.PT_3  # 仍明显宽于「国务院」3 字


def _ir(*, seal_mode, sig="国务院", date="2026年11月8日", with_attach=True) -> LayoutIR:
    return LayoutIR(
        org_marks=["国务院文件"],
        doc_number="国发〔2026〕18号",
        title="关于测试的通知",
        body_tree=[BodyBlock(level="p", text="正文内容。")],
        attachment_caption="有关材料" if with_attach else "",
        org_signature=sig,
        date=date,
        print_org="国务院办公厅",
        print_date="2026年11月9日",
        seal_mode=seal_mode,
    )


def _paras_around_signature(doc: Document, sig: str, date: str):
    texts = [p.text for p in doc.paragraphs]
    i_sig = next(i for i, t in enumerate(texts) if t.strip() == sig)
    i_date = next(i for i, t in enumerate(texts) if t.strip() == date)
    return texts, i_sig, i_date


def test_stamp_no_blank_and_halfwidth_date(tmp_path: Path):
    ir = _ir(seal_mode=SealMode.STAMP)
    widths = {ir.org_signature: 48.0, ir.date: 124.8}

    with mock.patch(
        "core.layout.engine.layout_text_width_pt",
        side_effect=lambda t, f, s: widths[t.strip()],
    ):
        out = tmp_path / "stamp.docx"
        DocxEngine().render(ir, out)

    doc = Document(out)
    texts, i_sig, i_date = _paras_around_signature(doc, ir.org_signature, ir.date)
    assert i_date == i_sig + 1
    assert "附件" in texts[i_sig - 1]
    assert doc.paragraphs[i_date].text == ir.date  # 半角，非全角
    assert "０" not in doc.paragraphs[i_date].text
    assert abs(doc.paragraphs[i_sig].paragraph_format.right_indent.pt * 20 - 2048) < 1e-6
    assert abs(doc.paragraphs[i_date].paragraph_format.right_indent.pt - U.PT_3 * 4) < 1e-6


def test_no_stamp_blank_and_halfwidth_date(tmp_path: Path):
    ir = _ir(seal_mode=SealMode.NO_STAMP)
    widths = {ir.org_signature: 48.0, ir.date: 124.8}

    with mock.patch(
        "core.layout.engine.layout_text_width_pt",
        side_effect=lambda t, f, s: widths[t.strip()],
    ):
        out = tmp_path / "nostamp.docx"
        DocxEngine().render(ir, out)

    doc = Document(out)
    texts, i_sig, i_date = _paras_around_signature(doc, ir.org_signature, ir.date)
    assert texts[i_sig - 1].strip() == ""
    assert "附件" in texts[i_sig - 2]
    assert doc.paragraphs[i_date].text == ir.date
    assert abs(doc.paragraphs[i_sig].paragraph_format.right_indent.pt * 20 - 2816) < 1e-6
    assert abs(doc.paragraphs[i_date].paragraph_format.right_indent.pt - U.PT_3 * 2) < 1e-6
