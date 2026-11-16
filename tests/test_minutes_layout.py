# -*- coding: utf-8 -*-
"""纪要特定格式：对齐 docs/baselines/纪要.md。"""
from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn

import core.layout.office_measure as om
from core.ir.minutes import (
    format_issue_no,
    looks_like_minutes,
    normalize_name_list,
    apply_minutes_to_ir,
)
from core.ir.schema import BodyBlock, DocKind, LayoutIR
from core.layout.engine import DocxEngine

# 避免本机 WPS/Word COM 卡住测试
om._app_failed = True
om._app = None

OUT = Path(__file__).resolve().parents[1] / "examples" / "out" / "test_minutes"


def _paras_text(doc: Document) -> list[str]:
    return [(p.text or "").strip() for p in doc.paragraphs]


def _has_red_banner_line(doc: Document) -> bool:
    """通用红线用顶边框红色表；纪要不应出现。"""
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


def _minimal_minutes(**kwargs) -> LayoutIR:
    ir = LayoutIR(
        doc_kind=DocKind.MINUTES,
        org_marks=["江州市人民政府常务会议纪要"],
        body_tree=[BodyBlock(level="p", text="会议研究了有关事项。")],
        attendance_absent_confirmed=True,
    )
    for k, v in kwargs.items():
        setattr(ir, k, v)
    return ir


def test_format_issue_no_no_space():
    assert format_issue_no("第 18 期") == "第18期"
    assert format_issue_no("18") == "第18期"
    assert format_issue_no("第18期") == "第18期"


def test_minutes_export_basename():
    from core.ir.minutes import minutes_export_basename

    ir = _minimal_minutes(issue_no="第 7 期")
    assert minutes_export_basename(ir) == "江州市人民政府常务会议纪要第7期.docx"
    ir2 = _minimal_minutes(issue_no="")
    assert minutes_export_basename(ir2) == "江州市人民政府常务会议纪要.docx"


def test_normalize_name_list_顿号():
    assert normalize_name_list("甲，乙,丙") == "甲、乙、丙"
    assert normalize_name_list("列席：张三，李四") == "张三、李四"


def test_detect_minutes_priority():
    assert looks_like_minutes(org_marks=["某某纪要"])
    assert looks_like_minutes(title="市政府常务会议纪要")
    assert looks_like_minutes(source_text="……\n出席：张三\n")
    assert not looks_like_minutes(title="关于加强纪要工作的通知", source_text="正文")


def test_minutes_minimal_export(tmp_path):
    ir = _minimal_minutes()
    path = tmp_path / "min.docx"
    DocxEngine().render(ir, path)
    doc = Document(str(path))
    texts = _paras_text(doc)
    assert any("纪要" in t for t in texts)
    assert any("会议研究了有关事项" in t for t in texts)
    assert not _has_red_banner_line(doc)
    assert ir.seal_mode is None


def test_minutes_rejects_without_attendance(tmp_path):
    ir = _minimal_minutes(attendance_absent_confirmed=False, attendance="")
    with pytest.raises(ValueError, match="出席"):
        DocxEngine().render(ir, tmp_path / "bad.docx")


def test_minutes_full_elements(tmp_path):
    ir = _minimal_minutes(
        attendance_absent_confirmed=False,
        issue_no="第 18 期",
        title="市政府第18次常务会议纪要",
        attachment_caption="会议议题清单",
        attendance="市长张明远、常务副市长李强",
        leave="副市长王芳",
        liexi="市发展改革委主任刘志强，市财政局局长赵敏",  # 逗号应归一
        date="2026年11月12日",
        note="此件发至县团级",
        print_org="江州市人民政府办公室",
        print_date="2026年11月12日",
        cc_recipients="市委办，市政府各部门",
        body_tree=[
            BodyBlock(level="h1", text="一、总体要求"),
            BodyBlock(level="h2", text="（一）工作目标"),
            BodyBlock(level="h1", text="一、关于冬季安全生产"),
            BodyBlock(level="p", text="会议强调要压实责任。"),
            BodyBlock(level="p", text="会议研究了有关事项。"),
        ],
    )
    # 模拟 bridge 归一
    ir.liexi = normalize_name_list(ir.liexi)
    ir.issue_no = format_issue_no(ir.issue_no)
    path = tmp_path / "full.docx"
    DocxEngine().render(ir, path)
    doc = Document(str(path))
    joined = "\n".join(_paras_text(doc))
    assert "第18期" in joined
    assert "第 18 期" not in joined
    assert "出席：" in joined or "出席" in joined
    assert "、" in joined
    assert "，" not in ir.liexi
    assert not _has_red_banner_line(doc)

    # 标题→标题不得 keep_with_next（否则 Word/WPS 整链挤页，大片留白）
    # 标题→正文才 keep
    by_text = {(p.text or "").strip(): p for p in doc.paragraphs if (p.text or "").strip()}
    assert by_text["一、总体要求"].paragraph_format.keep_with_next is not True
    assert by_text["（一）工作目标"].paragraph_format.keep_with_next is not True
    assert by_text["一、关于冬季安全生产"].paragraph_format.keep_with_next is True

    # 版记浮动钉底；表后有 1pt 空段（对齐样例 / baseline §13）
    assert len(doc.tables) >= 1
    tbl_pr = doc.tables[0]._tbl.tblPr
    assert tbl_pr is not None and tbl_pr.find(qn("w:tblpPr")) is not None
    last = doc.paragraphs[-1]
    assert (last.text or "") == ""
    sp = last._p.find(qn("w:pPr"))
    spacing = sp.find(qn("w:spacing")) if sp is not None else None
    assert spacing is not None and spacing.get(qn("w:line")) == "20"


def test_minutes_no_seal_in_missing():
    ir = _minimal_minutes()
    miss = ir.missing_required()
    assert "seal_mode" not in " ".join(miss)
    assert "落款版式" not in " ".join(miss)


def test_apply_minutes_from_source():
    ir = LayoutIR(
        org_marks=["江州市人民政府常务会议纪要"],
        title="市政府第18次常务会议纪要",
        body_tree=[BodyBlock(level="p", text="会议认为…")],
        doc_number="第 18 期",
    )
    text = "江州市人民政府常务会议纪要\n第18期\n…\n出席：张三，李四\n列席：王五\n"
    apply_minutes_to_ir(ir, text)
    assert ir.doc_kind == DocKind.MINUTES
    assert ir.issue_no == "第18期"
    assert ir.attendance == "张三、李四"
    assert ir.liexi == "王五"
    assert ir.seal_mode is None


def test_minutes_empty_lines_issue_to_title(tmp_path):
    """标志→期号空1；期号→标题空2；标题→正文空1（以空段计数近似）。"""
    ir = _minimal_minutes(
        issue_no="第18期",
        title="标题甲",
        attendance="张三",
        attendance_absent_confirmed=False,
    )
    path = tmp_path / "sp.docx"
    DocxEngine().render(ir, path)
    doc = Document(str(path))
    texts = [(p.text or "") for p in doc.paragraphs]
    # 找标志、期号、标题相对位置
    i_mark = next(i for i, t in enumerate(texts) if "纪要" in t and "标题" not in t)
    i_issue = next(i for i, t in enumerate(texts) if t.strip() == "第18期")
    i_title = next(i for i, t in enumerate(texts) if t.strip() == "标题甲")
    assert i_issue - i_mark == 2  # 中间 1 个空段
    assert i_title - i_issue == 3  # 中间 2 个空段
