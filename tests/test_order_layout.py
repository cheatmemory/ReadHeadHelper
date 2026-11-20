# -*- coding: utf-8 -*-
"""命令（令）特定格式：对齐 docs/baselines/命令.md。"""
from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn

import core.layout.office_measure as om
from core.ir.order import (
    apply_order_to_ir,
    format_order_no,
    looks_like_order,
    order_export_basename,
    strip_signer_title,
)
from core.ir.schema import BodyBlock, DocKind, LayoutIR
from core.layout import units as U
from core.layout.engine import DocxEngine
from core.recognize.order_regex import extract_order_fields, recognize_order

om._app_failed = True
om._app = None

OUT = Path(__file__).resolve().parents[1] / "examples" / "out" / "test_order"


def _paras_text(doc: Document) -> list[str]:
    return [(p.text or "").strip() for p in doc.paragraphs]


def _all_text(doc: Document) -> str:
    parts = _paras_text(doc)
    for tbl in doc.tables:
        for row in tbl.rows:
            for cell in row.cells:
                parts.append((cell.text or "").strip())
    return "\n".join(parts)


def _has_red_banner_line(doc: Document) -> bool:
    for tbl in doc.tables:
        tblPr = tbl._tbl.tblPr
        if tblPr is None:
            continue
        borders = tblPr.find(qn("w:tblBorders"))
        if borders is None:
            continue
        top = borders.find(qn("w:top"))
        if top is not None and (top.get(qn("w:color")) or "").upper() == "FF0000":
            return True
    return False


def _minimal_order(**kwargs) -> LayoutIR:
    ir = LayoutIR(
        doc_kind=DocKind.ORDER,
        org_marks=["江州市人民政府令"],
        order_no="第1号",
        body_tree=[BodyBlock(level="p", text="《……办法》已经……现予公布，自2027年1月1日起施行。")],
        signers=["市长"],
        date="2026年10月25日",
    )
    for k, v in kwargs.items():
        setattr(ir, k, v)
    return ir


def test_format_order_no_no_space():
    assert format_order_no("第 1 号") == "第1号"
    assert format_order_no("1") == "第1号"
    assert format_order_no("第1号") == "第1号"
    assert format_order_no("江政发〔2026〕1号") == ""
    assert " " not in format_order_no("第 18 号")


def test_order_export_basename():
    ir = _minimal_order(order_no="第 1 号")
    assert order_export_basename(ir) == "江州市人民政府令第1号.docx"


def test_detect_order_by_mark_only():
    assert looks_like_order(org_marks=["江州市人民政府令"])
    assert looks_like_order(org_marks=["某某市人民政府命令"])
    assert looks_like_order(source_text="江州市人民政府令\n第1号\n正文\n")
    assert not looks_like_order(source_text="正文提及命令二字，但无机关标志")
    assert not looks_like_order(source_text="第1号\n仅有令号无标志")
    assert not looks_like_order(source_text="现予公布。\n此令\n")


def test_strip_signer_title_no_name():
    assert strip_signer_title("市长　张明远") == "市长"
    assert strip_signer_title("市长 张明远") == "市长"
    assert strip_signer_title("市长") == "市长"


def test_order_minimal_export(tmp_path):
    ir = _minimal_order()
    path = tmp_path / "order.docx"
    DocxEngine().render(ir, path)
    doc = Document(str(path))
    texts = _paras_text(doc)
    joined = _all_text(doc)
    assert any("人民政府令" in t for t in texts)
    assert "第1号" in joined
    assert "第 1 号" not in joined
    assert "现予公布" in joined
    assert "市长" in joined
    assert "张明远" not in joined
    assert not _has_red_banner_line(doc)
    assert ir.seal_mode is None
    assert "办法》已经" in joined


def test_order_rejects_missing_required(tmp_path):
    ir = _minimal_order(order_no="")
    with pytest.raises(ValueError, match="令号"):
        DocxEngine().render(ir, tmp_path / "bad.docx")
    ir2 = _minimal_order(signers=[])
    with pytest.raises(ValueError, match="职务"):
        DocxEngine().render(ir2, tmp_path / "bad2.docx")


def test_order_no_seal_in_missing():
    ir = _minimal_order()
    miss = ir.missing_required()
    assert "seal_mode" not in " ".join(miss)
    assert "落款版式" not in " ".join(miss)
    assert not miss


def test_order_seal_placeholder_size(tmp_path):
    """占位 45×20 mm；右空四字定位。"""
    ir = _minimal_order()
    path = tmp_path / "seal.docx"
    DocxEngine().render(ir, path)
    doc = Document(str(path))
    assert len(doc.tables) >= 1
    # 签名章表：3 列，末列宽 ≈ 45mm
    seal_tbl = doc.tables[0]
    assert len(seal_tbl.columns) == 3
    tc = seal_tbl.rows[0].cells[2]._tc
    tcPr = tc.get_or_add_tcPr()
    tcW = tcPr.find(qn("w:tcW"))
    assert tcW is not None
    w = int(tcW.get(qn("w:w")))
    expect = U.mm_to_twips(U.ORDER_SEAL_WIDTH_MM)
    assert abs(w - expect) <= U.mm_to_twips(1.0)
    tr = seal_tbl.rows[0]._tr
    trH = tr.get_or_add_trPr().find(qn("w:trHeight"))
    assert trH is not None
    h = int(trH.get(qn("w:val")))
    expect_h = U.mm_to_twips(U.ORDER_SEAL_HEIGHT_MM)
    assert abs(h - expect_h) <= U.mm_to_twips(1.0)
    # 章框有边框
    borders = tcPr.find(qn("w:tcBorders"))
    assert borders is not None


def test_order_spacing_mark_order_body(tmp_path):
    """标志→令号空2；令号→正文空2。"""
    ir = _minimal_order()
    path = tmp_path / "sp.docx"
    DocxEngine().render(ir, path)
    doc = Document(str(path))
    texts = [(p.text or "") for p in doc.paragraphs]
    i_mark = next(i for i, t in enumerate(texts) if "人民政府令" in t)
    i_no = next(i for i, t in enumerate(texts) if t.strip() == "第1号")
    i_body = next(i for i, t in enumerate(texts) if "现予公布" in t)
    assert i_no - i_mark == 3  # 中间 2 个空段
    assert i_body - i_no == 3


def test_order_joint_signers(tmp_path):
    ir = _minimal_order(signers=["市长", "区长"])
    path = tmp_path / "joint.docx"
    DocxEngine().render(ir, path)
    doc = Document(str(path))
    # 两组签名表
    assert len(doc.tables) >= 2
    joined = _all_text(doc)
    assert "市长" in joined and "区长" in joined


def test_order_banji_1pt_tail(tmp_path):
    ir = _minimal_order(
        cc_recipients="市委办",
        print_org="江州市人民政府办公室",
        print_date="2026年10月25日",
    )
    path = tmp_path / "banji.docx"
    DocxEngine().render(ir, path)
    doc = Document(str(path))
    assert len(doc.tables) >= 2  # 签名章 + 版记
    last = doc.paragraphs[-1]
    assert (last.text or "") == ""
    sp = last._p.find(qn("w:pPr"))
    spacing = sp.find(qn("w:spacing")) if sp is not None else None
    assert spacing is not None and spacing.get(qn("w:line")) == "20"


def test_apply_order_from_source():
    ir = LayoutIR(
        org_marks=["江州市人民政府令"],
        body_tree=[BodyBlock(level="p", text="现予公布。")],
        doc_number="第 1 号",
        signers=["市长　张明远"],
        date="2026年10月25日",
    )
    text = "江州市人民政府令\n第 1 号\n现予公布。\n市长　张明远\n2026年10月25日\n"
    apply_order_to_ir(ir, text)
    assert ir.doc_kind == DocKind.ORDER
    assert ir.order_no == "第1号"
    assert ir.signers == ["市长"]
    assert ir.seal_mode is None
    assert ir.title == ""


def test_order_regex_sample_text():
    text = (
        "江州市人民政府令\n"
        "第 1 号\n"
        "\n"
        "《江州市某处管理办法》已经市人民政府第12次常务会议通过，现予公布，"
        "自2027年1月1日起施行。\n"
        "\n"
        "市长　张明远\n"
        "2026年10月25日\n"
    )
    fields = extract_order_fields(text)
    assert fields["org_mark"] == "江州市人民政府令"
    assert fields["order_no"] == "第1号"
    assert any("现予公布" in b for b in fields["body_blocks"])
    assert fields["signers"] == ["市长"]
    assert "张明远" not in "".join(fields["signers"])
    assert fields["date"] == "2026年10月25日"

    model = recognize_order(text)
    assert getattr(model, "_is_order") is True
    assert model.header.org_mark.endswith("令")
    assert model._order_no == "第1号"
