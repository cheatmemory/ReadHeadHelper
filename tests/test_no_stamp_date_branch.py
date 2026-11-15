# -*- coding: utf-8 -*-
"""§7.3.5.2 无章日期锚定：长/短日期二选一，禁止左右缩进同时挤压行宽。"""
from __future__ import annotations

from pathlib import Path
from unittest import mock

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

from core.ir.schema import BodyBlock, LayoutIR, SealMode
from core.layout import units as U
from core.layout.engine import DocxEngine, _no_stamp_multi_layout


def test_layout_helper_branches_by_width():
    face = "仿宋_GB2312"
    orgs = ["河北省人民政府"]  # 7 字
    short_date = "11月8日"
    long_date = "2026年11月8日"

    widths = {
        "河北省人民政府": 112.0,
        short_date: 64.0,
        long_date: 130.0,
    }

    def fake(text, font_face, size_pt):
        return widths[text.strip()]

    with mock.patch("core.layout.engine.layout_text_width_pt", side_effect=fake):
        short = _no_stamp_multi_layout(orgs, short_date, face)
        long = _no_stamp_multi_layout(orgs, long_date, face)

    assert short["branch"] == "first_char"
    assert short["date_left"] is not None and short["date_right"] is None
    assert long["branch"] == "date_right"
    assert long["date_right"] == U.PT_3 * 2 and long["date_left"] is None


def test_rendered_date_never_has_both_indents(tmp_path: Path):
    """日期更长时只右锚；可用宽 = 版心 − 右空二字，不得再被左缩进吃掉。"""
    orgs = [
        "国务院",
        "中共中央",
        "河北省人民政府",
        "重庆市发改委",
        "教育部",
        "河南省发改委",
    ]
    date = "2026年11月8日"
    widths = {
        "国务院": 48.0,
        "中共中央": 64.0,
        "河北省人民政府": 112.0,
        "重庆市发改委": 96.0,
        "教育部": 48.0,
        "河南省发改委": 96.0,
        date: 130.0,
    }

    ir = LayoutIR(
        org_marks=orgs,
        doc_number="国发〔2026〕18号",
        title="关于测试的通知",
        body_tree=[BodyBlock(level="p", text="正文。")],
        org_signature="、".join(orgs),
        date=date,
        print_org="国务院办公厅",
        print_date="2026年11月9日",
        seal_mode=SealMode.NO_STAMP,
        note="此件公开发布",
    )

    with mock.patch(
        "core.layout.engine.layout_text_width_pt",
        side_effect=lambda t, f, s: widths.get(t.strip(), len(t.strip()) * s),
    ):
        out = tmp_path / "nostamp_long_date.docx"
        DocxEngine().render(ir, out)

    doc = Document(str(out))
    date_p = next(p for p in doc.paragraphs if p.text.strip() == date)
    left_i = float(date_p.paragraph_format.left_indent.pt or 0)
    right_i = float(date_p.paragraph_format.right_indent.pt or 0)
    assert date_p.alignment == WD_ALIGN_PARAGRAPH.RIGHT
    assert left_i < 0.5
    assert abs(right_i - U.PT_3 * 2) < 0.6
    # 单段完整日期（折行是渲染现象；OOXML 侧不得再左右同时缩进）
    assert date_p.text.strip() == date
    body_pt = U.PAGE["body_width_mm"] / U.MM_PER_INCH * 72.0
    assert body_pt - right_i > widths[date] + 1.0
