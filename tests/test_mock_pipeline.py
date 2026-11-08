# -*- coding: utf-8 -*-
from pathlib import Path

from core.ir.builder import build_layout_ir
from core.ir.schema import SealMode
from core.layout import DocxEngine
from core.recognize import MockFieldRecognizer

ROOT = Path(__file__).resolve().parents[1]


def test_mock_to_docx(tmp_path):
    text = (ROOT / "fixtures" / "sample_text" / "downlink.txt").read_text(encoding="utf-8")
    model = MockFieldRecognizer().recognize(text)
    ir = build_layout_ir(model, seal_mode=SealMode.STAMP, source_text=text)
    assert not ir.missing_required()
    out = tmp_path / "t.docx"
    DocxEngine().render(ir, out)
    assert out.exists() and out.stat().st_size > 1000


def test_margins_in_docx(tmp_path):
    import zipfile
    from core.layout import units as U

    text = (ROOT / "fixtures" / "sample_text" / "downlink.txt").read_text(encoding="utf-8")
    model = MockFieldRecognizer().recognize(text)
    ir = build_layout_ir(model, seal_mode=SealMode.NO_STAMP, source_text=text)
    out = tmp_path / "m.docx"
    DocxEngine().render(ir, out)
    with zipfile.ZipFile(out) as z:
        xml = z.read("word/document.xml").decode("utf-8")
        # sectPr 在 document.xml 末尾
        assert "w:pgMar" in xml or True  # python-docx 可能写在 styles；再读 sect
    # 直接用 python-docx 回读边距
    from docx import Document

    doc = Document(out)
    sec = doc.sections[0]
    # python-docx 读回的是 EMU
    assert abs(int(sec.top_margin) - U.mm_to_emu(37)) <= 300
    assert abs(int(sec.left_margin) - U.mm_to_emu(28)) <= 300


def test_banji_pinned_to_body_bottom(tmp_path):
    """§7.4.1：版记沉底；末条为底边框（无线下空段）。"""
    import zipfile

    text = (ROOT / "fixtures" / "sample_text" / "downlink.txt").read_text(encoding="utf-8")
    model = MockFieldRecognizer().recognize(text)
    ir = build_layout_ir(model, seal_mode=SealMode.NO_STAMP, source_text=text)
    out = tmp_path / "banji.docx"
    DocxEngine().render(ir, out)
    with zipfile.ZipFile(out) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    assert 'w:yAlign="bottom"' in xml
    assert 'w:vAnchor="margin"' in xml
    assert "w:framePr" in xml


def test_page_numbers_gbt_7_5(tmp_path):
    """§7.5：有 footer、奇偶页、PAGE 域、一字线。"""
    import zipfile

    from core.layout import units as U
    from docx import Document

    text = (ROOT / "fixtures" / "sample_text" / "downlink.txt").read_text(encoding="utf-8")
    model = MockFieldRecognizer().recognize(text)
    ir = build_layout_ir(model, seal_mode=SealMode.NO_STAMP, source_text=text)
    out = tmp_path / "page.docx"
    DocxEngine().render(ir, out)

    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        assert "word/footer1.xml" in names
        assert "word/footer2.xml" in names
        settings = z.read("word/settings.xml").decode("utf-8")
        assert "evenAndOddHeaders" in settings
        footers = []
        for name in ("word/footer1.xml", "word/footer2.xml"):
            xml = z.read(name).decode("utf-8")
            footers.append(xml)
            assert "PAGE" in xml
            assert U.PAGE_NUMBER_DASH in xml

    doc = Document(out)
    sec = doc.sections[0]
    expect_footer = U.mm_to_emu(U.PAGE["bottom_mm"] - U.PAGE_NUMBER_BELOW_BODY_MM)
    assert abs(int(sec.footer_distance) - expect_footer) <= 400
    assert doc.settings.odd_and_even_pages_header_footer is True
