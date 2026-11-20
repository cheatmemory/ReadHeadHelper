# -*- coding: utf-8 -*-
"""信函特定格式：对齐 docs/baselines/信函.md。"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn

import core.layout.office_measure as om
from core.ir.builder import model_to_partial_ir
from core.ir.letter import (
    apply_letter_to_ir,
    letter_export_basename,
    looks_like_letter,
    normalize_urgency,
    strip_cc_prefix,
    strip_recipient_colon,
    strip_wenjian_suffix,
)
from core.ir.schema import BodyBlock, DocKind, LayoutIR, SealMode
from core.layout import units as U
from core.layout.engine import DocxEngine
from core.recognize.letter_regex import extract_letter_fields, recognize_letter

om._app_failed = True
om._app = None

SAMPLE = """\
江州市人民政府
江政函〔2026〕15号

关于商洽联合举办2026年冬季应急演练有关事宜的函

江州省应急管理厅：

　　为提升应急处置能力，拟于2026年12月联合举办冬季应急演练，现就有关事宜函商如下。

　　一、演练时间
　　拟于12月中旬择日举行。

附件：演练方案（草案）

江州市人民政府
2026年11月10日

抄送：省委办公厅。
"""


def _paras_text(doc: Document) -> list[str]:
    return [(p.text or "").strip() for p in doc.paragraphs]


def _all_text(doc: Document) -> str:
    parts = _paras_text(doc)
    for tbl in doc.tables:
        for row in tbl.rows:
            for cell in row.cells:
                parts.append((cell.text or "").strip())
    return "\n".join(parts)


def _red_double_line_tables(doc: Document) -> list:
    """找出含红色顶边框的表（双线由两张表+间隔组成）。"""
    found = []
    for tbl in doc.tables:
        tblPr = tbl._tbl.tblPr
        if tblPr is None:
            continue
        borders = tblPr.find(qn("w:tblBorders"))
        if borders is None:
            continue
        top = borders.find(qn("w:top"))
        if top is None:
            continue
        if (top.get(qn("w:color")) or "").upper() != "FF0000":
            continue
        tblW = tblPr.find(qn("w:tblW"))
        w = int(tblW.get(qn("w:w"))) if tblW is not None else 0
        sz = int(top.get(qn("w:sz")) or 0)
        found.append({"width_twips": w, "sz": sz, "tbl": tbl})
    return found


def _minimal_letter(**kwargs) -> LayoutIR:
    ir = LayoutIR(
        doc_kind=DocKind.LETTER,
        seal_mode=SealMode.RESERVED,
        org_marks=["江州市人民政府"],
        doc_number="江政函〔2026〕15号",
        title="关于商洽联合举办2026年冬季应急演练有关事宜的函",
        recipient="江州省应急管理厅",
        body_tree=[BodyBlock(level="p", text="为提升应急处置能力，现函商有关事宜。")],
        org_signature="江州市人民政府",
        date="2026年11月10日",
    )
    for k, v in kwargs.items():
        setattr(ir, k, v)
    return ir


def test_looks_like_letter_by_docno_or_title():
    assert looks_like_letter(doc_number="江政函〔2026〕15号")
    assert looks_like_letter(title="关于商洽有关事宜的函")
    assert looks_like_letter(title="关于××的复函")
    assert looks_like_letter(source_text=SAMPLE)
    assert not looks_like_letter(source_text="正文偶尔出现函字，但无字号无标题\n来函收悉。\n")
    assert not looks_like_letter(title="关于召开会议的通知")


def test_strip_helpers():
    assert strip_wenjian_suffix("江州市人民政府文件") == "江州市人民政府"
    assert strip_recipient_colon("江州省应急管理厅：") == "江州省应急管理厅"
    assert strip_cc_prefix("抄送：省委办公厅。") == "省委办公厅"
    assert normalize_urgency("加急") == "加急"
    assert normalize_urgency("平急") == ""
    assert normalize_urgency("特提") == ""


def test_letter_regex_extract():
    fields = extract_letter_fields(SAMPLE)
    assert "函" in fields["doc_number"]
    assert fields["doc_number"].startswith("江政函")
    assert fields["title"].endswith("函")
    assert fields["recipient"] == "江州省应急管理厅"
    assert "：" not in fields["recipient"]
    assert fields["org_signature"]
    assert fields["date"] == "2026年11月10日"
    assert fields["cc"] == "省委办公厅"
    assert fields["body_blocks"]
    model = recognize_letter(SAMPLE)
    assert getattr(model, "_is_letter", False)
    ir = model_to_partial_ir(model, source_text=SAMPLE)
    assert ir.is_letter()
    assert ir.seal_mode == SealMode.RESERVED


def test_letter_export_basename():
    ir = _minimal_letter()
    assert letter_export_basename(ir) == "江政函〔2026〕15号.docx"


def test_secret_coexist_and_mark_wenjian():
    ir = _minimal_letter(secret_level="秘密", secret_period="")
    miss = ir.missing_required()
    assert any("同进同退" in m for m in miss)

    ir2 = _minimal_letter(org_marks=["江州市人民政府文件"])
    miss2 = ir2.missing_required()
    assert any("文件" in m for m in miss2)

    ir3 = _minimal_letter(urgency="平急")
    miss3 = ir3.missing_required()
    assert any("特急" in m or "加急" in m for m in miss3)


def test_letter_minimal_export(tmp_path):
    ir = _minimal_letter(cc_recipients="省委办公厅")
    out = tmp_path / "letter.docx"
    DocxEngine().render(ir, out)
    assert out.exists()
    doc = Document(out)
    text = _all_text(doc)
    assert "江州市人民政府" in text
    assert "江政函〔2026〕15号" in text
    assert "江州省应急管理厅：" in text
    # 引擎加冒号；IR 无冒号
    assert ir.recipient == "江州省应急管理厅"
    assert "印发" not in text or "印发机关" not in text


def test_letter_no_banji_separator(tmp_path):
    ir = _minimal_letter(cc_recipients="省委办公厅")
    out = tmp_path / "letter_banji.docx"
    DocxEngine().render(ir, out)
    doc = Document(out)
    text = _all_text(doc)
    assert "抄送：省委办公厅。" in text
    # 抄送为流式段落后，正文表中不应再有带黑分隔线的「抄送」版记表
    for tbl in doc.tables:
        cell_texts = [c.text.strip() for row in tbl.rows for c in row.cells]
        joined = "\n".join(cell_texts)
        if "抄送" not in joined:
            continue
        tblPr = tbl._tbl.tblPr
        borders = tblPr.find(qn("w:tblBorders")) if tblPr is not None else None
        if borders is None:
            continue
        for edge in ("top", "bottom", "insideH"):
            el = borders.find(qn(f"w:{edge}"))
            if el is None:
                continue
            color = (el.get(qn("w:color")) or "").upper()
            # 允许页脚红双线表；禁止黑色版记分隔线
            assert color in {"", "AUTO", "FF0000"} or el.get(qn("w:val")) in {
                "nil",
                "none",
            }


def test_letter_double_line_geometry(tmp_path):
    ir = _minimal_letter()
    out = tmp_path / "letter_lines.docx"
    DocxEngine().render(ir, out)
    # 底双线在页眉；第一条双线+标志在正文（纸面绝对定位，避免撑高页眉）
    expect_w = U.mm_to_twips(U.LETTER_DOUBLE_LINE_WIDTH_MM)
    expect_x = U.mm_to_twips(
        U.PAGE["left_mm"] - (U.LETTER_DOUBLE_LINE_WIDTH_MM - U.PAGE["body_width_mm"]) / 2.0
    )
    thick = max(2, int(round(U.LETTER_DOUBLE_LINE_THICK_PT * 8)))
    thin = max(2, int(round(U.LETTER_DOUBLE_LINE_THIN_PT * 8)))
    with zipfile.ZipFile(out) as z:
        header_xmls = [n for n in z.namelist() if n.startswith("word/header")]
        assert header_xmls
        joined_h = "".join(z.read(n).decode("utf-8") for n in header_xmls)
        assert "FF0000" in joined_h.upper() or "ff0000" in joined_h
        assert "tblpPr" in joined_h
        assert f'w:w="{expect_w}"' in joined_h or str(expect_w) in joined_h
        assert str(thick) in joined_h and str(thin) in joined_h
        assert f'w:tblpX="{expect_x}"' in joined_h or str(expect_x) in joined_h

        body = z.read("word/document.xml").decode("utf-8")
        assert "FF0000" in body.upper() or "ff0000" in body
        assert "tblpPr" in body
        assert f'w:tblpX="{expect_x}"' in body or str(expect_x) in body
        assert str(thick) in body and str(thin) in body
        # 固定布局以 gridCol 为准；须与 170mm 一致，不能残留版心宽 8845
        assert f'w:gridCol w:w="{expect_w}"' in body or f'w:w="{expect_w}"' in body
        body_w = U.mm_to_twips(U.PAGE["body_width_mm"])
        # 红线表不应只有版心宽列而无 170mm 列
        assert expect_w != body_w

        footers = [n for n in z.namelist() if n.startswith("word/footer")]
        assert footers
        has_page = False
        for n in footers:
            xml = z.read(n).decode("utf-8")
            if "PAGE" in xml:
                has_page = True
                assert "FF0000" not in xml.upper()
        assert has_page


def test_letter_meta_row_uses_grid_line_pt(tmp_path):
    """份号/密级/紧急行距应为版心网格行距，不是 3 号单倍 16pt。"""
    ir = _minimal_letter(
        copy_number="000001",
        secret_level="机密",
        secret_period="10年",
        urgency="特急",
    )
    out = tmp_path / "letter_meta.docx"
    DocxEngine().render(ir, out)
    doc = Document(out)
    expect = int(round(DocxEngine().line_pt * 20))
    found = False
    for tbl in doc.tables:
        texts = [c.text.strip() for row in tbl.rows for c in row.cells]
        if not any("000001" in t for t in texts):
            continue
        found = True
        assert len(tbl.rows) >= 3
        for row in tbl.rows:
            trPr = row._tr.get_or_add_trPr()
            th = trPr.find(qn("w:trHeight"))
            assert th is not None
            assert int(th.get(qn("w:val"))) == expect
            assert th.get(qn("w:hRule")) == "exact"
            for cell in row.cells:
                tcPr = cell._tc.get_or_add_tcPr()
                vAlign = tcPr.find(qn("w:vAlign"))
                assert vAlign is not None
                assert vAlign.get(qn("w:val")) == "top"
        break
    assert found


def test_letter_first_page_no_page_number(tmp_path):
    ir = _minimal_letter()
    out = tmp_path / "letter_page.docx"
    DocxEngine().render(ir, out)
    with zipfile.ZipFile(out) as z:
        sect = z.read("word/document.xml").decode("utf-8")
        assert "titlePg" in sect
        footers = [n for n in z.namelist() if n.startswith("word/footer")]
        assert len(footers) >= 2
        # 至少一个 footer 无 PAGE（首页），至少一个有 PAGE
        has_page = ["PAGE" in z.read(n).decode("utf-8") for n in footers]
        assert any(has_page)
        assert not all(has_page)


def test_letter_joint_2_and_3_signature(tmp_path):
    ir2 = _minimal_letter(org_signature="江州市人民政府\n江州市应急管理局")
    out2 = tmp_path / "letter_j2.docx"
    DocxEngine().render(ir2, out2)
    doc2 = Document(out2)
    text2 = _all_text(doc2)
    assert "江州市人民政府" in text2 and "江州市应急管理局" in text2

    ir3 = _minimal_letter(
        org_signature="甲市人民政府\n乙市人民政府\n丙市人民政府"
    )
    out3 = tmp_path / "letter_j3.docx"
    DocxEngine().render(ir3, out3)
    assert out3.exists()


def test_letter_keeps_body_top_margin_37mm(tmp_path):
    ir = _minimal_letter()
    out = tmp_path / "letter_margin.docx"
    DocxEngine().render(ir, out)
    doc = Document(out)
    sec = doc.sections[0]
    assert abs(float(sec.top_margin.mm) - U.PAGE["top_mm"]) <= 0.6


def test_letter_attachment_hanging_indent(tmp_path):
    ir = _minimal_letter(attachment_caption="演练方案（草案）")
    out = tmp_path / "letter_attach.docx"
    DocxEngine().render(ir, out)
    doc = Document(out)
    found = False
    for p in doc.paragraphs:
        t = (p.text or "").strip()
        if not t.startswith("附件"):
            continue
        found = True
        pPr = p._p.get_or_add_pPr()
        ind = pPr.find(qn("w:ind"))
        assert ind is not None
        assert ind.get(qn("w:hanging"))
        assert int(ind.get(qn("w:left") or "0")) > int(ind.get(qn("w:hanging") or "0"))
        break
    assert found


def test_letter_rejects_missing_recipient(tmp_path):
    ir = _minimal_letter(recipient="")
    miss = ir.missing_required()
    assert "主送机关" in miss
    with pytest.raises(ValueError, match="主送"):
        DocxEngine().render(ir, tmp_path / "bad.docx")


def test_apply_letter_strips_wenjian_on_detect():
    ir = LayoutIR(
        org_marks=["江州市人民政府文件"],
        doc_number="江政函〔2026〕1号",
        title="关于××的函",
        recipient="各单位：",
        body_tree=[BodyBlock(level="p", text="正文。")],
        org_signature="江州市人民政府",
        date="2026年1月1日",
    )
    out = apply_letter_to_ir(ir, source_text="江政函〔2026〕1号\n关于××的函\n")
    assert out.is_letter()
    assert out.primary_org_mark() == "江州市人民政府"
    assert out.recipient == "各单位"
    assert out.seal_mode == SealMode.RESERVED
