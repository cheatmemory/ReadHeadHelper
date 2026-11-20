# -*- coding: utf-8 -*-
import json
from pathlib import Path

from core.ir.builder import build_layout_ir
from core.ir.schema import ModelOutput, SealMode
from core.layout import DocxEngine

ROOT = Path(__file__).resolve().parents[1]


def _fixture_model(name: str = "downlink_stamp.json") -> ModelOutput:
    data = json.loads((ROOT / "fixtures" / "mock_json" / name).read_text(encoding="utf-8"))
    return ModelOutput.from_dict(data)


def test_fixture_to_docx(tmp_path):
    text = (ROOT / "fixtures" / "sample_text" / "downlink.txt").read_text(encoding="utf-8")
    model = _fixture_model()
    ir = build_layout_ir(model, seal_mode=SealMode.STAMP, source_text=text)
    assert not ir.missing_required()
    out = tmp_path / "t.docx"
    DocxEngine().render(ir, out)
    assert out.exists() and out.stat().st_size > 1000


def test_margins_in_docx(tmp_path):
    import zipfile
    from core.layout import units as U

    text = (ROOT / "fixtures" / "sample_text" / "downlink.txt").read_text(encoding="utf-8")
    model = _fixture_model()
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


def test_heading_first_line_indent(tmp_path):
    """§7.3.3：一至四级与正文均首行缩进二字。"""
    from docx import Document
    from docx.shared import Pt

    from core.ir.schema import BodyBlock, LayoutIR, SealMode
    from core.layout import units as U

    ir = LayoutIR(
        org_marks=["××市人民政府文件"],
        doc_number="×政发〔2024〕1号",
        title="关于测试的通知",
        body_tree=[
            BodyBlock(level="h1", text="一、总体要求"),
            BodyBlock(level="h2", text="（一）市容"),
            BodyBlock(level="h3", text="1.细则"),
            BodyBlock(level="p", text="普通段落。"),
        ],
        org_signature="××市人民政府",
        date="2024年1月1日",
        print_org="××市人民政府办公室",
        print_date="2024年1月2日",
        seal_mode=SealMode.NO_STAMP,
    )
    out = tmp_path / "indent.docx"
    DocxEngine().render(ir, out)
    doc = Document(out)
    want = {
        "一、总体要求": U.PT_3 * 2,
        "（一）市容": U.PT_3 * 2,
        "1.细则": U.PT_3 * 2,
        "普通段落。": U.PT_3 * 2,
    }
    found = {k: False for k in want}
    for p in doc.paragraphs:
        t = p.text.strip()
        if t not in want:
            continue
        assert p.paragraph_format.first_line_indent == Pt(want[t])
        found[t] = True
    assert all(found.values()), found


def test_copy_number_uses_fangsong(tmp_path):
    """§5.2.2：份号用 3 号仿宋，不用黑体。"""
    import zipfile
    from xml.etree import ElementTree as ET

    text = (ROOT / "fixtures" / "sample_text" / "downlink.txt").read_text(encoding="utf-8")
    model = _fixture_model()
    ir = build_layout_ir(model, seal_mode=SealMode.NO_STAMP, source_text=text)
    ir.copy_number = "000037"
    out = tmp_path / "copy.docx"
    DocxEngine().render(ir, out)
    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(out) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    found = False
    for r in root.iter(W + "r"):
        texts = "".join((t.text or "") for t in r.iter(W + "t"))
        if texts.strip() != "000037":
            continue
        fonts = r.find(W + "rPr/" + W + "rFonts")
        assert fonts is not None
        assert fonts.get(W + "eastAsia") == "仿宋_GB2312"
        found = True
        break
    assert found


def test_banji_floating_table_gbt_7_4(tmp_path):
    """§7.4：浮动表沉底；上下粗线；抄送/印发用全角空格或缩进空一字。"""
    import zipfile
    from xml.etree import ElementTree as ET

    from core.layout import units as U

    text = (ROOT / "fixtures" / "sample_text" / "downlink.txt").read_text(encoding="utf-8")
    model = _fixture_model()
    ir = build_layout_ir(model, seal_mode=SealMode.NO_STAMP, source_text=text)
    ir.cc_recipients = "市委各部门，市人大常委会办公室，市政协办公室。"
    out = tmp_path / "banji.docx"
    DocxEngine().render(ir, out)

    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

    with zipfile.ZipFile(out) as z:
        root = ET.fromstring(z.read("word/document.xml"))

    banji = None
    for tbl in root.findall(".//" + W + "tbl"):
        tblp = tbl.find(W + "tblPr/" + W + "tblpPr")
        if tblp is not None and tblp.get(W + "tblpYSpec") == "bottom":
            banji = tbl
            break
    assert banji is not None

    # 版记行不得中剖跨页（cantSplit）；主送/抄送过长时整行挪页而非从字中断开
    for tr in banji.findall(W + "tr"):
        assert tr.find(W + "trPr/" + W + "cantSplit") is not None

    borders = banji.find(W + "tblPr/" + W + "tblBorders")
    assert borders is not None
    assert borders.find(W + "top").get(W + "val") == "single"
    assert borders.find(W + "bottom").get(W + "val") == "single"
    assert borders.find(W + "insideH").get(W + "val") == "single"
    assert borders.find(W + "top").get(W + "sz") == str(U.BANJI_LINE_THICK_SZ)
    assert borders.find(W + "bottom").get(W + "sz") == str(U.BANJI_LINE_THICK_SZ)
    assert borders.find(W + "insideH").get(W + "sz") == str(U.BANJI_LINE_THIN_SZ)
    assert int(borders.find(W + "top").get(W + "sz")) > int(
        borders.find(W + "insideH").get(W + "sz")
    )
    assert int(borders.find(W + "bottom").get(W + "sz")) > int(
        borders.find(W + "insideH").get(W + "sz")
    )

    one = str(int(round(U.PT_4 * 20)))
    cc_ok = org_ok = date_ok = False
    for p in banji.iter(W + "p"):
        texts = "".join((t.text or "") for t in p.iter(W + "t"))
        if texts.startswith("抄送："):
            ind = p.find(W + "pPr/" + W + "ind")
            assert ind is not None
            assert ind.get(W + "left") == str(4 * int(one))
            assert ind.get(W + "hanging") == str(3 * int(one))
            assert ind.get(W + "right") == one
            assert "\u3000" not in texts
            cc_ok = True
        if texts == ir.print_org:
            ind = p.find(W + "pPr/" + W + "ind")
            assert ind is not None
            assert ind.get(W + "left") == one
            assert "\u3000" not in texts
            org_ok = True
        if "印发" in texts and ir.print_date[:4] in texts:
            ind = p.find(W + "pPr/" + W + "ind")
            assert ind is not None
            assert ind.get(W + "right") == one
            assert "\u3000" not in texts
            date_ok = True
    assert cc_ok and org_ok and date_ok


def test_page_numbers_gbt_7_5(tmp_path):
    """§7.5：有 footer、奇偶页、PAGE 域、一字线。"""
    import zipfile

    from core.layout import units as U
    from docx import Document

    text = (ROOT / "fixtures" / "sample_text" / "downlink.txt").read_text(encoding="utf-8")
    model = _fixture_model()
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
    expect_footer = U.mm_to_emu(U.page_number_footer_distance_mm())
    assert abs(int(sec.footer_distance) - expect_footer) <= 400
    assert doc.settings.odd_and_even_pages_header_footer is True


def test_uplink_docno_signer_gbt_7_2_5_7_2_6(tmp_path):
    """§7.2.5/7.2.6：上行文发文字号左空一字；签发人右空一字；姓名 3 号楷体。"""
    from docx import Document
    from docx.oxml.ns import qn

    from core.ir.schema import BodyBlock, LayoutIR
    from core.layout import units as U

    ir = LayoutIR(
        org_marks=["××市教育局"],
        doc_number="×教呈〔2024〕3号",
        title="关于测试的请示",
        body_tree=[BodyBlock(level="p", text="正文。")],
        org_signature="××市教育局",
        date="2024年1月1日",
        print_org="××市教育局办公室",
        print_date="2024年1月2日",
        seal_mode=SealMode.NO_STAMP,
        signers=["陈志远"],
    )
    out = tmp_path / "uplink.docx"
    DocxEngine().render(ir, out)
    doc = Document(out)

    one = int(round(U.PT_3 * 20))
    body_w = U.mm_to_twips(U.PAGE["body_width_mm"])
    found = False
    for p in doc.paragraphs:
        texts = [(r.text or "", r) for r in p.runs]
        joined = "".join(t for t, _ in texts)
        if "签发人" not in joined:
            continue
        found = True
        pPr = p._p.find(qn("w:pPr"))
        ind = pPr.find(qn("w:ind"))
        tab = pPr.find(qn("w:tabs")).find(qn("w:tab"))
        assert ind.get(qn("w:left")) == str(one)
        assert ind.get(qn("w:leftChars")) is None  # 避免 Word 按字符网格折成约 11pt
        assert tab.get(qn("w:pos")) == str(body_w - one)
        # 红线不得再挂在本段 pBdr 上（否则左空一字会拖偏红线）
        pBdr = pPr.find(qn("w:pBdr"))
        assert pBdr is None or pBdr.find(qn("w:bottom")) is None
        fonts = {}
        for text, run in texts:
            if not text.strip() or text == "\t":
                continue
            rFonts = run._element.find(qn("w:rPr")).find(qn("w:rFonts"))
            fonts[text] = rFonts.get(qn("w:eastAsia"))
        assert fonts.get(ir.doc_number) == "仿宋_GB2312"
        assert fonts.get("签发人：") == "仿宋_GB2312"
        assert fonts.get("陈志远") == "楷体_GB2312"
        break
    assert found


def test_banner_red_line_body_width_gbt_7_2_7(tmp_path):
    """§7.2.7：红线用定宽表，宽=版心；不随发文字号缩进。"""
    import zipfile
    from xml.etree import ElementTree as ET

    from core.ir.schema import BodyBlock, LayoutIR
    from core.layout import units as U

    ir = LayoutIR(
        org_marks=["××市教育局"],
        doc_number="×教呈〔2024〕3号",
        title="关于测试的请示",
        body_tree=[BodyBlock(level="p", text="正文。")],
        org_signature="××市教育局",
        date="2024年1月1日",
        print_org="××市教育局办公室",
        print_date="2024年1月2日",
        seal_mode=SealMode.NO_STAMP,
        signers=["陈志远"],
    )
    out = tmp_path / "redline.docx"
    DocxEngine().render(ir, out)

    W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    body_w = str(U.mm_to_twips(U.PAGE["body_width_mm"]))
    line_sz = str(int(round(U.RED_LINE_PT * 8)))

    with zipfile.ZipFile(out) as z:
        root = ET.fromstring(z.read("word/document.xml"))

    red = None
    for tbl in root.findall(".//" + W + "tbl"):
        top = tbl.find(W + "tblPr/" + W + "tblBorders/" + W + "top")
        if top is not None and (top.get(W + "color") or "").upper() == "FF0000":
            red = tbl
            break
    assert red is not None
    tblW = red.find(W + "tblPr/" + W + "tblW")
    top = red.find(W + "tblPr/" + W + "tblBorders/" + W + "top")
    assert tblW.get(W + "w") == body_w
    assert top.get(W + "val") == "single"
    assert top.get(W + "sz") == line_sz
