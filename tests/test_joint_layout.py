# -*- coding: utf-8 -*-
"""联合行文：红头成块+文件、多签发人、有章/无章多署名。"""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

from core.ir.schema import BodyBlock, LayoutIR, SealMode
from core.layout import units as U
from core.layout.engine import (
    DocxEngine,
    _body_width_pt,
    _no_stamp_multi_layout,
    _resolve_signature_orgs,
)
from core.layout.office_measure import layout_text_width_pt


def _base(**kwargs) -> LayoutIR:
    data = dict(
        doc_number="X应急发〔2026〕31号",
        title="关于加强校园安全管理的通知",
        recipient="各县（市、区）应急管理局、教育局，市属各学校：",
        body_tree=[BodyBlock(level="p", text="现就有关事项通知如下。")],
        date="2026年11月14日",
        print_org="××市应急管理局办公室",
        print_date="2026年11月14日",
        seal_mode=SealMode.STAMP,
    )
    data.update(kwargs)
    return LayoutIR(**data)


def test_resolve_signature_falls_back_to_marks():
    ir = _base(
        org_marks=["××市应急管理局", "××市教育局"],
        org_signature="××市应急管理局",
    )
    assert _resolve_signature_orgs(ir) == ["××市应急管理局", "××市教育局"]


def test_sample1_joint_header_and_stamp_row(tmp_path: Path):
    """样本1：2 机关红头表 + 有章一行两署名 + 日期右空四字。"""
    ir = _base(
        org_marks=["××市应急管理局", "××市教育局"],
        org_signature="××市应急管理局、××市教育局",
        seal_mode=SealMode.STAMP,
    )
    out = tmp_path / "joint1.docx"
    DocxEngine().render(ir, out)
    doc = Document(str(out))

    # 首张内容表：左名称 / 右「文件」
    header = doc.tables[0]
    left = [p.text for p in header.rows[0].cells[0].paragraphs if p.text.strip()]
    right = [p.text for p in header.rows[0].cells[1].paragraphs if p.text.strip()]
    assert left == ["××市应急管理局", "××市教育局"]
    assert right == ["文件"]
    for p in header.rows[0].cells[0].paragraphs:
        for r in p.runs:
            if r.text.strip():
                assert r.font.color.rgb is not None

    texts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    assert any("××市应急管理局　　××市教育局" == t for t in texts)
    # 日期右空四字；末行署名为左缩进（最右机关中心对齐日期）
    one = U.PT_3
    date_p = next(p for p in doc.paragraphs if p.text.strip() == ir.date)
    assert abs(float(date_p.paragraph_format.right_indent.pt) - 4 * one) < 0.6
    sig_row = next(
        p for p in doc.paragraphs if p.text.strip() == "××市应急管理局　　××市教育局"
    )
    assert sig_row.paragraph_format.left_indent is not None
    assert float(sig_row.paragraph_format.left_indent.pt) > 1.0


def test_sample2_signers_matrix_and_no_stamp(tmp_path: Path):
    """样本2：3 签发人两行；无章三行署名首字对齐。"""
    ir = _base(
        org_marks=["××市应急管理局", "××市财政局", "××市水利局"],
        doc_number="X应急发〔2026〕47号",
        title="关于申请防汛应急资金的请示",
        recipient="××市人民政府：",
        org_signature="××市应急管理局\n××市财政局\n××市水利局",
        seal_mode=SealMode.NO_STAMP,
        signers=["张××", "李××", "王××"],
        body_tree=[
            BodyBlock(level="p", text="现就申请防汛应急资金有关事项请示如下。"),
            BodyBlock(level="p", text="妥否，请批示。"),
        ],
    )
    out = tmp_path / "joint2.docx"
    DocxEngine().render(ir, out)
    doc = Document(str(out))

    header = doc.tables[0]
    left = [p.text for p in header.rows[0].cells[0].paragraphs if p.text.strip()]
    assert left == ["××市应急管理局", "××市财政局", "××市水利局"]
    assert header.rows[0].cells[1].paragraphs[0].text.strip() == "文件"

    # 首行签发人（右齐）
    first = next(p for p in doc.paragraphs if "签发人：" in "".join(r.text or "" for r in p.runs))
    assert first.alignment is not None
    joined = "".join(r.text or "" for r in first.runs)
    assert "张××" in joined and "李××" in joined

    # 字号行含王××
    found_docno = False
    for p in doc.paragraphs:
        t = "".join(r.text or "" for r in p.runs)
        if ir.doc_number in t and "王××" in t:
            found_docno = True
            pPr = p._p.find(qn("w:pPr"))
            ind = pPr.find(qn("w:ind"))
            assert ind.get(qn("w:left")) == str(int(round(U.PT_3 * 20)))
            break
    assert found_docno

    sig_paras = [
        p
        for p in doc.paragraphs
        if p.text.strip() in {"××市应急管理局", "××市财政局", "××市水利局"}
    ]
    assert len(sig_paras) == 3
    lefts = [float(p.paragraph_format.left_indent.pt) for p in sig_paras]
    assert max(lefts) - min(lefts) < 0.5
    # 无章：按宽度二选一锚定；日期段不得左右缩进同时非零（否则易折行）
    one = U.PT_3
    face = "仿宋_GB2312"
    date_p = next(p for p in doc.paragraphs if p.text.strip() == ir.date)
    left_i = float(date_p.paragraph_format.left_indent.pt or 0)
    right_i = float(date_p.paragraph_format.right_indent.pt or 0)
    assert not (left_i > 0.5 and right_i > 0.5)
    planned = _no_stamp_multi_layout(
        ["××市应急管理局", "××市财政局", "××市水利局"], ir.date, face, one
    )
    if planned["branch"] == "date_right":
        assert abs(right_i - 2 * one) < 0.6
        assert left_i < 0.5
    else:
        assert abs(left_i - lefts[0] - 2 * one) < 1.0
        assert right_i < 0.5


def test_joint_header_never_breaks_single_org_name(tmp_path: Path):
    """单个机关名不得被折到下一行；装不下同行就拆成两行或缩小字号。"""
    orgs = [
        "国务院",
        "中共中央",
        "河北省人民政府",
        "重庆市发改委",
        "教育部",
        "河南省发改委",
    ]
    ir = _base(
        org_marks=orgs,
        org_signature="、".join(orgs),
        seal_mode=SealMode.STAMP,
        title="关于测试的通知",
    )
    out = tmp_path / "joint_nowrap.docx"
    DocxEngine().render(ir, out)
    doc = Document(str(out))
    header = doc.tables[0]
    left_lines = [p.text for p in header.rows[0].cells[0].paragraphs if p.text.strip()]
    # 每个机关名必须完整出现在某一行中（不被拆成「河南省发」「改委」）
    for name in orgs:
        assert any(name in line for line in left_lines), name
        for line in left_lines:
            # 若行内只有半截名称则失败
            if "河南省" in line and "发改委" in line:
                assert "河南省发改委" in line
            if line.endswith("河南省发") or line == "改委":
                raise AssertionError(f"机关名被折行: {left_lines!r}")

    # 「文件」列只占二字量级，左列随最长机关名拉宽
    grid_cols = header._tbl.findall(qn("w:tblGrid") + "/" + qn("w:gridCol"))
    assert len(grid_cols) == 2
    left_tw = int(grid_cols[0].get(qn("w:w")))
    right_tw = int(grid_cols[1].get(qn("w:w")))
    assert left_tw > right_tw * 2
    size_pt = None
    for p in header.rows[0].cells[1].paragraphs:
        for r in p.runs:
            if r.text.strip() == "文件" and r.font.size is not None:
                size_pt = r.font.size.pt
                break
    assert size_pt is not None
    assert right_tw < int(round(size_pt * 3.2 * 20))


def test_joint_header_three_orgs_same_size_no_wrap(tmp_path: Path):
    """三机关联合红头：每名一行不拆字，三行字号一致。"""
    from core.layout.office_measure import office_measure_width_pt

    office_measure_width_pt.cache_clear()
    orgs = ["浙江省教育厅", "浙江省财政厅", "浙江省卫生健康委员会"]
    ir = _base(
        org_marks=orgs,
        org_signature="\n".join(orgs),
        doc_number="浙教基〔2026〕42号",
        title="浙江省教育厅　浙江省财政厅　浙江省卫生健康委员会关于加强中小学教室照明改造工作的通知",
        seal_mode=SealMode.STAMP,
    )
    out = tmp_path / "joint_zhejiang3.docx"
    DocxEngine().render(ir, out)
    doc = Document(str(out))
    left = [p.text for p in doc.tables[0].rows[0].cells[0].paragraphs if p.text.strip()]
    assert left == orgs
    sizes = []
    for p in doc.tables[0].rows[0].cells[0].paragraphs:
        for r in p.runs:
            if r.text.strip() and r.font.size is not None:
                sizes.append(round(r.font.size.pt, 1))
    assert sizes, "红头应有字号"
    assert len(set(sizes)) == 1, sizes
    assert sizes[0] <= U.PT_MARK_DEFAULT


def test_sample3_header_rows_and_stamp_two_rows(tmp_path: Path):
    """样本3：5 机关红头 2+2+1；有章署名 3+2。"""
    orgs = [
        "××市应急管理局",
        "××市财政局",
        "××市水利局",
        "××市交通运输局",
        "××市卫生健康委员会",
    ]
    ir = _base(
        org_marks=orgs,
        doc_number="X应急发〔2026〕52号",
        title="关于开展安全生产联合检查的通知",
        org_signature="、".join(orgs),
        seal_mode=SealMode.STAMP,
    )
    out = tmp_path / "joint3.docx"
    DocxEngine().render(ir, out)
    doc = Document(str(out))

    left = [p.text for p in doc.tables[0].rows[0].cells[0].paragraphs if p.text.strip()]
    assert left == [
        "××市应急管理局　　××市财政局",
        "××市水利局　　××市交通运输局",
        "××市卫生健康委员会",
    ]
    assert doc.tables[0].rows[0].cells[1].text.strip() == "文件"

    texts = [p.text.strip() for p in doc.paragraphs]
    assert "××市应急管理局　××市财政局　××市水利局" in texts
    assert "××市交通运输局　　××市卫生健康委员会" in texts
