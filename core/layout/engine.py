# -*- coding: utf-8 -*-
"""DocxEngine：模板骨架 + OOXML 补洞，LayoutIR → docx。"""
from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor, Twips

from core.body_structure.parser import normalize_structure_markers
from core.ir.schema import BodyBlock, LayoutIR, SealMode
from core.layout import units as U
from core.layout.attach_merge import append_docx_body, load_attachment_bytes
from core.layout.font_measure import max_one_line_font_pt
from core.layout.office_measure import layout_text_width_pt


def _add_page_break(doc: Document) -> None:
    p = doc.add_paragraph()
    run = p.add_run()
    br = OxmlElement("w:br")
    br.set(qn("w:type"), "page")
    run._r.append(br)


def _attachment_caption_lines(caption: str) -> list[str]:
    """§7.3.4 多附件拆成多行；兼容误粘成「1.甲 2.乙」的单行。"""
    raw = (caption or "").strip()
    if not raw:
        return []
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if len(lines) == 1:
        s = re.sub(r"^附件\s*[:：]\s*", "", lines[0]).strip()
        parts = [p.strip() for p in re.split(r"(?=\d+\s*[\.．、])", s) if p.strip()]
        if len(parts) > 1:
            return parts
    return lines


def _set_run_font(run, *, name: str, size_pt: float, bold: bool = False, color: RGBColor | None = None):
    run.bold = bold
    run.font.size = Pt(size_pt)
    if color is not None:
        run.font.color.rgb = color
    r = run._element
    rPr = r.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.insert(0, rFonts)
    for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rFonts.set(qn(attr), name)


def _set_paragraph_spacing(paragraph, *, before_pt=0, after_pt=0, line_pt=None, rule=WD_LINE_SPACING.EXACTLY):
    pf = paragraph.paragraph_format
    pf.space_before = Pt(before_pt)
    pf.space_after = Pt(after_pt)
    if line_pt is not None:
        pf.line_spacing_rule = rule
        pf.line_spacing = Pt(line_pt)


def _disable_snap_to_grid(paragraph):
    """大字号段落关闭网格对齐，否则 WPS/Word 会按网格行高裁切字形。"""
    pPr = paragraph._p.get_or_add_pPr()
    snap = pPr.find(qn("w:snapToGrid"))
    if snap is None:
        snap = OxmlElement("w:snapToGrid")
        pPr.append(snap)
    snap.set(qn("w:val"), "0")


def _set_spacing_for_font(paragraph, font_pt: float, *, grid_line_pt: float, before_pt=0, after_pt=0):
    """固定行距至少能装下字号，避免红头/标题上半截被挡。"""
    line_pt = max(float(font_pt) * 1.25, float(grid_line_pt))
    _set_paragraph_spacing(paragraph, before_pt=before_pt, after_pt=after_pt, line_pt=line_pt)
    _disable_snap_to_grid(paragraph)


def _max_one_line_mark_font_pt(text: str, font_face: str = "方正小标宋简体") -> float:
    """单一红头字号：版心内一行能放下的最大 pt。

    本机有该字体时用 GDI 实测字宽；否则按字宽≈1.12×字号、版心 92% 可用宽保守估算。
    """
    t = (text or "").strip()
    if not t:
        return U.PT_MARK_DEFAULT
    return max_one_line_font_pt(
        t,
        body_width_mm=U.PAGE["body_width_mm"],
        font_face=font_face,
    )


def _grid_line_pt() -> float:
    """版心高 / 22 行 → 网格行高（磅）。"""
    body_height_inch = U.PAGE["body_height_mm"] / U.MM_PER_INCH
    return body_height_inch * 72.0 / U.GRID_ROWS


def _empty_grid_lines(doc: Document, n: int, line_pt: float):
    for _ in range(max(0, n)):
        p = doc.add_paragraph()
        _set_paragraph_spacing(p, before_pt=0, after_pt=0, line_pt=line_pt)
        run = p.add_run("")
        _set_run_font(run, name="仿宋_GB2312", size_pt=U.PT_3)


def _add_page_field(run) -> None:
    """在 run 中写入 PAGE 域（begin / instrText / separate / 占位 / end）。"""
    r = run._r

    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    r.append(begin)

    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    r.append(instr)

    sep = OxmlElement("w:fldChar")
    sep.set(qn("w:fldCharType"), "separate")
    r.append(sep)

    # 占位数字；打开时由 Word/WPS 按域更新
    t = OxmlElement("w:t")
    t.text = "1"
    r.append(t)

    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    r.append(end)


def _fill_page_number_paragraph(paragraph, *, odd: bool, font_name: str) -> None:
    """7.5：4 号半角宋体数字，左右各一条一字线；单页居右空一字，双页居左空一字。"""
    paragraph.clear()
    pf = paragraph.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    # 空一字 ≈ 4 号汉字宽
    one_char = Pt(U.PT_4)
    if odd:
        paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        pf.right_indent = one_char
        pf.left_indent = Pt(0)
    else:
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        pf.left_indent = one_char
        pf.right_indent = Pt(0)

    dash = U.PAGE_NUMBER_DASH
    r0 = paragraph.add_run(dash)
    _set_run_font(r0, name=font_name, size_pt=U.PT_4)
    r_page = paragraph.add_run()
    _set_run_font(r_page, name=font_name, size_pt=U.PT_4)
    _add_page_field(r_page)
    r1 = paragraph.add_run(dash)
    _set_run_font(r1, name=font_name, size_pt=U.PT_4)
    _disable_snap_to_grid(paragraph)


def _setup_page_numbers(doc: Document, *, songti: str = "宋体") -> None:
    """GB/T 9704-2012 §7.5 页码：奇偶页脚 + PAGE 域。"""
    doc.settings.odd_and_even_pages_header_footer = True
    section = doc.sections[0]
    # 一字线上距版心下边缘 7mm → 页脚距纸底 = 下白边 - 7
    section.footer_distance = Mm(U.PAGE["bottom_mm"] - U.PAGE_NUMBER_BELOW_BODY_MM)

    odd_footer = section.footer
    odd_footer.is_linked_to_previous = False
    odd_p = odd_footer.paragraphs[0] if odd_footer.paragraphs else odd_footer.add_paragraph()
    _fill_page_number_paragraph(odd_p, odd=True, font_name=songti)

    even_footer = section.even_page_footer
    even_footer.is_linked_to_previous = False
    even_p = even_footer.paragraphs[0] if even_footer.paragraphs else even_footer.add_paragraph()
    _fill_page_number_paragraph(even_p, odd=False, font_name=songti)


def _set_page_and_grid(doc: Document):
    section = doc.sections[0]
    section.page_width = Mm(U.PAGE["width_mm"])
    section.page_height = Mm(U.PAGE["height_mm"])
    section.top_margin = Mm(U.PAGE["top_mm"])
    section.left_margin = Mm(U.PAGE["left_mm"])
    section.right_margin = Mm(U.PAGE["right_mm"])
    section.bottom_margin = Mm(U.PAGE["bottom_mm"])

    # 文档网格：22 行 × 28 字（通过 sectPr/docGrid）
    sectPr = section._sectPr
    docGrid = sectPr.find(qn("w:docGrid"))
    if docGrid is None:
        docGrid = OxmlElement("w:docGrid")
        sectPr.append(docGrid)
    # linePitch 单位：twips。版心高/22
    line_pitch = U.mm_to_twips(U.PAGE["body_height_mm"] / U.GRID_ROWS)
    char_pitch = U.mm_to_twips(U.PAGE["body_width_mm"] / U.GRID_COLS)
    docGrid.set(qn("w:type"), "linesAndChars")
    docGrid.set(qn("w:linePitch"), str(line_pitch))
    docGrid.set(qn("w:charSpace"), str(char_pitch))


def _pt_to_mm(pt: float) -> float:
    return float(pt) / 72.0 * U.MM_PER_INCH


def _mark_line_pt(font_pt: float, grid_line_pt: float) -> float:
    return max(float(font_pt) * 1.25, float(grid_line_pt))


def _mark_ink_inset_mm(font_pt: float, grid_line_pt: float) -> float:
    """红头首行：行框顶 → 红色墨迹顶（字身上沿）的空隙。"""
    line_pt = _mark_line_pt(font_pt, grid_line_pt)
    return _pt_to_mm(max(0.0, (line_pt - float(font_pt)) * U.RED_HEADER_INK_ABOVE_RATIO))


def _docno_glyph_below_mm(line_pt: float, font_pt: float = U.PT_3) -> float:
    """发文字号行：字身下缘 → 行框底的空隙（进入红线间距的测量）。"""
    return _pt_to_mm(max(0.0, (float(line_pt) - float(font_pt)) * U.RED_LINE_GLYPH_BELOW_RATIO))


def _add_banner_red_line(doc: Document, *, docno_line_pt: float | None = None) -> None:
    """§7.2.7：发文字号下 4mm、与版心等宽的红色分隔线。

    不用发文字号段的 pBdr：上行文左空一字会使边框跟着右移。
    用「空距段 + 定宽表顶边」：红线在表格顶缘，避免底边框再叠加行高把间距撑到 >4mm。
    空距按「字身下缘→红线」计，扣掉发文字号网格行内字身以下的空白。
    """
    line_pt = float(docno_line_pt) if docno_line_pt is not None else _grid_line_pt()
    gap_mm = max(0.5, U.RED_LINE_GAP_MM - _docno_glyph_below_mm(line_pt, U.PT_3))
    gap_pt = gap_mm / U.MM_PER_INCH * 72.0
    spacer = doc.add_paragraph()
    _set_paragraph_spacing(spacer, before_pt=0, after_pt=0, line_pt=gap_pt)
    _disable_snap_to_grid(spacer)
    _set_run_font(spacer.add_run(""), name="仿宋_GB2312", size_pt=0.5)

    body_w = U.mm_to_twips(U.PAGE["body_width_mm"])
    table = doc.add_table(rows=1, cols=1)
    table.autofit = False
    tbl = table._tbl
    tblPr = tbl.tblPr
    if tblPr is None:
        tblPr = OxmlElement("w:tblPr")
        tbl.insert(0, tblPr)

    for tag in ("tblW", "tblBorders", "tblCellMar", "tblLayout", "tblInd", "jc"):
        for old in tblPr.findall(qn(f"w:{tag}")):
            tblPr.remove(old)

    tblW = OxmlElement("w:tblW")
    tblW.set(qn("w:w"), str(body_w))
    tblW.set(qn("w:type"), "dxa")
    tblPr.append(tblW)

    tblInd = OxmlElement("w:tblInd")
    tblInd.set(qn("w:w"), "0")
    tblInd.set(qn("w:type"), "dxa")
    tblPr.append(tblInd)

    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tblPr.append(layout)

    borders = OxmlElement("w:tblBorders")
    line_sz = max(2, int(round(U.RED_LINE_PT * 8)))
    for edge, val, sz, color in (
        ("top", "single", line_sz, "FF0000"),
        ("left", "nil", 0, "auto"),
        ("bottom", "nil", 0, "auto"),
        ("right", "nil", 0, "auto"),
        ("insideH", "nil", 0, "auto"),
        ("insideV", "nil", 0, "auto"),
    ):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), val)
        el.set(qn("w:sz"), str(sz))
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), color)
        borders.append(el)
    tblPr.append(borders)

    cellMar = OxmlElement("w:tblCellMar")
    for side in ("top", "left", "bottom", "right"):
        m = OxmlElement(f"w:{side}")
        m.set(qn("w:w"), "0")
        m.set(qn("w:type"), "dxa")
        cellMar.append(m)
    tblPr.append(cellMar)

    cell = table.rows[0].cells[0]
    tcPr = cell._tc.get_or_add_tcPr()
    for old in tcPr.findall(qn("w:tcW")):
        tcPr.remove(old)
    tcW = OxmlElement("w:tcW")
    tcW.set(qn("w:w"), str(body_w))
    tcW.set(qn("w:type"), "dxa")
    tcPr.append(tcW)

    cell.text = ""
    cp = cell.paragraphs[0]
    # 行高压到最小，红线即表顶，不再额外占 4mm 以外的空隙
    _set_paragraph_spacing(cp, before_pt=0, after_pt=0, line_pt=0.5)
    _disable_snap_to_grid(cp)


def _secret_display(ir: LayoutIR) -> str:
    if ir.secret_level and ir.secret_period:
        if "★" in ir.secret_level:
            return ir.secret_level
        return f"{ir.secret_level}★{ir.secret_period}"
    return ir.secret_level or ""


def _font_for_level(level: str) -> tuple[str, float, bool]:
    if level == "h1":
        return "黑体", U.PT_3, False
    if level == "h2":
        return "楷体_GB2312", U.PT_3, False
    return "仿宋_GB2312", U.PT_3, False


def _signature_right_indents(
    org_signature: str,
    date: str,
    seal_mode: SealMode,
    font_face: str,
    size_pt: float = U.PT_3,
) -> tuple[float, float]:
    """§7.3.5 落款右空 → (署名右空 pt, 成文日期右空 pt)。

    文本宽用 Word/WPS 实测（半角阿拉伯数字）；「右空 N 字」按 3 号一字 = size_pt。
    """
    one = float(size_pt)
    sig_w = layout_text_width_pt(org_signature, font_face, size_pt)
    date_w = layout_text_width_pt(date, font_face, size_pt)

    if seal_mode == SealMode.STAMP:
        # 日期右空四字；署名前一行、以日期为准居中（右端不必齐）
        date_right = 4.0 * one
        sig_right = date_right + (date_w - sig_w) / 2.0
        return max(0.0, sig_right), date_right

    # 无章：二选一（与多机关 _no_stamp_multi_layout 同一原则）
    # 日期不长于署名 → 署名右空二字，日期右空 = 署名宽 - 日期宽（首字右移二字）
    date_right_if_sig2 = sig_w - date_w
    if date_right_if_sig2 >= 0:
        return 2.0 * one, date_right_if_sig2
    # 日期更长 → 只锚日期右空二字，署名右空相应加大
    return date_w - sig_w + 4.0 * one, 2.0 * one


def _no_stamp_multi_layout(
    orgs: list[str],
    date: str,
    font_face: str,
    size_pt: float = U.PT_3,
) -> dict:
    """§7.3.5.2 无章多机关落款：按「日期是否长于最长署名」二选一锚定。

    - 日期不长于署名：只锚首字（署名右空二字，日期首字右移二字）→ 日期仅左缩进
    - 日期更长：只锚右端（日期右空二字）→ 日期仅右缩进右齐；署名首字再左移二字

    禁止日期段同时设左、右缩进：两者叠加会把可用宽压成「测得字宽」，
    实测略宽时就会把末字挤到下一行。
    """
    one = float(size_pt)
    body_pt = _body_width_pt()
    max_w = max(layout_text_width_pt(o, font_face, size_pt) for o in orgs)
    date_w = layout_text_width_pt(date, font_face, size_pt)

    if date_w <= max_w:
        # 首字分支：可用宽 = max_w ≥ date_w，日期只设左缩进
        sig_left = max(0.0, body_pt - 2.0 * one - max_w)
        return {
            "branch": "first_char",
            "sig_left": sig_left,
            "date_left": sig_left + 2.0 * one,
            "date_right": None,
        }

    # 右空分支：日期只设右缩进；署名随日期左缘左移二字
    date_right = 2.0 * one
    date_left = body_pt - date_right - date_w
    sig_left = max(0.0, date_left - 2.0 * one)
    return {
        "branch": "date_right",
        "sig_left": sig_left,
        "date_left": None,
        "date_right": date_right,
    }


_SPLIT_ORG_RE = re.compile(r"[、，,；;]+")


def _strip_wenjian_suffix(name: str) -> str:
    t = (name or "").strip()
    if t.endswith("文件"):
        t = t[: -len("文件")].rstrip()
    return t


def _split_org_list(raw: str) -> list[str]:
    """署名/机关列表：支持换行与顿号分隔。"""
    out: list[str] = []
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in _SPLIT_ORG_RE.split(line) if p.strip()]
        out.extend(parts or [line])
    return out


def _raw_org_marks(ir: LayoutIR) -> list[str]:
    return [str(m).strip() for m in (ir.org_marks or []) if str(m).strip()]


def _resolve_signature_orgs(ir: LayoutIR) -> list[str]:
    """落款机关顺序：优先署名字段；多机关时可回退红头机关（去「文件」）。"""
    sigs = _split_org_list(ir.org_signature)
    if len(sigs) >= 2:
        return sigs
    marks = [_strip_wenjian_suffix(m) for m in _raw_org_marks(ir)]
    marks = [m for m in marks if m]
    if len(marks) >= 2:
        return marks
    if sigs:
        return sigs
    if marks:
        return marks
    return []


def _chunk_list(items: list[str], n: int) -> list[list[str]]:
    return [items[i : i + n] for i in range(0, len(items), n)]


def _join_org_row(orgs: list[str]) -> str:
    """同行多个机关：2 个用双全角空格，3 个用单全角空格（对齐样例）。"""
    if len(orgs) >= 3:
        return "　".join(orgs)
    return "　　".join(orgs)


def _clear_tbl_borders(tbl_pr) -> None:
    for tag in ("tblBorders",):
        for old in tbl_pr.findall(qn(f"w:{tag}")):
            tbl_pr.remove(old)
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "nil")
        el.set(qn("w:sz"), "0")
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), "auto")
        borders.append(el)
    tbl_pr.append(borders)


def _set_cell_width(cell, twips: int) -> None:
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    for old in tcPr.findall(qn("w:tcW")):
        tcPr.remove(old)
    tcW = OxmlElement("w:tcW")
    tcW.set(qn("w:w"), str(int(twips)))
    tcW.set(qn("w:type"), "dxa")
    tcPr.append(tcW)
    vAlign = tcPr.find(qn("w:vAlign"))
    if vAlign is None:
        vAlign = OxmlElement("w:vAlign")
        tcPr.append(vAlign)
    vAlign.set(qn("w:val"), "center")


def _body_width_pt() -> float:
    return U.PAGE["body_width_mm"] / U.MM_PER_INCH * 72.0


class DocxEngine:
    def __init__(self, fonts: dict | None = None):
        self.fonts = {
            "xiaobiaosong": "方正小标宋简体",
            "heiti": "黑体",
            "kaiti": "楷体_GB2312",
            "fangsong": "仿宋_GB2312",
            "songti": "宋体",
            **(fonts or {}),
        }
        self.line_pt = _grid_line_pt()

    def render(self, ir: LayoutIR, out_path: str | Path) -> Path:
        if ir.seal_mode is None:
            raise ValueError("seal_mode 未设置，拒绝导出")
        missing = ir.missing_required()
        if missing:
            raise ValueError("必填缺失：" + "、".join(missing))

        doc = Document()
        _set_page_and_grid(doc)
        _setup_page_numbers(doc, songti=self.fonts["songti"])
        # 清空默认空段
        if doc.paragraphs:
            p0 = doc.paragraphs[0]
            p0.clear()

        self._write_banner(doc, ir)
        self._write_body(doc, ir)
        self._write_signature(doc, ir)
        self._write_note(doc, ir)
        self._write_attachment_pages(doc, ir)
        self._write_banji(doc, ir)

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(out_path))
        return out_path

    def _write_attachment_pages(self, doc: Document, ir: LayoutIR) -> None:
        """附件另页：不做国标标题居中等排版；仅「附件N」+ 空行 + 原文。"""
        items = list(ir.attachments or [])
        if not items:
            return
        heiti = self.fonts["heiti"]
        for i, item in enumerate(items, start=1):
            raw = load_attachment_bytes(item)
            if not raw:
                continue
            _add_page_break(doc)
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            _set_paragraph_spacing(p, line_pt=self.line_pt)
            run = p.add_run(f"附件{i}")
            _set_run_font(run, name=heiti, size_pt=U.PT_3)
            _empty_grid_lines(doc, 1, self.line_pt)
            append_docx_body(doc, raw)

    def _write_banner(self, doc: Document, ir: LayoutIR):
        # 份号 / 密级 / 紧急：有则自上而下顶格
        top_items = []
        if ir.copy_number.strip():
            top_items.append(("copy", ir.copy_number.strip()))
        secret = _secret_display(ir)
        if secret:
            top_items.append(("secret", secret))
        if ir.urgency.strip():
            top_items.append(("urgency", ir.urgency.strip()))

        for kind, text in top_items:
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            _set_paragraph_spacing(p, line_pt=self.line_pt)
            run = p.add_run(text)
            # §5.2.2：份号一般用 3 号仿宋；密级/紧急仍用黑体
            face = self.fonts["fangsong"] if kind == "copy" else self.fonts["heiti"]
            _set_run_font(run, name=face, size_pt=U.PT_3)

        # 发文机关标志：单机关单行；联合机关 → 名称成块 + 右侧「文件」
        # 先定字号/行框，再按「墨迹顶 = 版心顶 + 35mm」反推垫高（扣行内字身上方空白）
        marks = _raw_org_marks(ir)
        if not marks:
            marks = [""]
        mark_face = self.fonts["xiaobiaosong"]
        joint_plan = None
        if len(marks) >= 2:
            joint_names = [_strip_wenjian_suffix(m) or m for m in marks]
            joint_plan = self._plan_joint_header(joint_names, mark_face)
            mark_font_pt = float(joint_plan["size_pt"])
        else:
            mark_font_pt = float(_max_one_line_mark_font_pt(marks[0], mark_face))

        mm_per_line = U.PAGE["body_height_mm"] / U.GRID_ROWS
        used_mm = len(top_items) * mm_per_line
        ink_inset_mm = _mark_ink_inset_mm(mark_font_pt, self.line_pt)
        spacer_mm = max(
            0.0,
            U.RED_HEADER_FROM_BODY_TOP_MM - used_mm - ink_inset_mm,
        )
        if spacer_mm > 0.05:
            spacer_pt = spacer_mm / U.MM_PER_INCH * 72.0
            sp = doc.add_paragraph()
            _set_paragraph_spacing(sp, before_pt=0, after_pt=0, line_pt=spacer_pt)
            _disable_snap_to_grid(sp)
            _set_run_font(sp.add_run(""), name=self.fonts["fangsong"], size_pt=0.5)

        if joint_plan is not None:
            self._write_joint_header_table(doc, mark_face, joint_plan)
        else:
            mark = marks[0]
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _set_spacing_for_font(p, mark_font_pt, grid_line_pt=self.line_pt)
            run = p.add_run(mark)
            _set_run_font(
                run,
                name=mark_face,
                size_pt=mark_font_pt,
                color=RGBColor(255, 0, 0),
            )

        # 标志下空二行
        _empty_grid_lines(doc, 2, self.line_pt)

        # 发文字号 / 签发人（§7.2.5 / 7.2.6）
        self._write_docno_and_signers(doc, ir)

        # 红线独立于发文字号段（§7.2.7 版心等宽；上行左空一字不拖偏红线）
        _add_banner_red_line(doc, docno_line_pt=self.line_pt)

        # 红线下空二行
        _empty_grid_lines(doc, 2, self.line_pt)

    def _pack_joint_header_rows(
        self,
        marks: list[str],
        mark_face: str,
        size_pt: float,
        max_width_pt: float,
    ) -> list[str] | None:
        """把机关名排成行。单个机关名绝不拆开；装不下则返回 None（需缩小字号）。

        ≤3 个：强制每行一个。≥4 个：同行两个仅当整行（含两机关名）测宽装得下。
        """
        pad = 1.10  # 相对 Word/WPS 实测多留余量，避免格内再折行
        # 任一单名本身超宽 → 此字号不可用
        for name in marks:
            if layout_text_width_pt(name, mark_face, size_pt) * pad > max_width_pt:
                return None

        allow_pair = len(marks) >= 4
        rows: list[str] = []
        i = 0
        while i < len(marks):
            if allow_pair and i + 1 < len(marks):
                paired = _join_org_row([marks[i], marks[i + 1]])
                if layout_text_width_pt(paired, mark_face, size_pt) * pad <= max_width_pt:
                    rows.append(paired)
                    i += 2
                    continue
            rows.append(marks[i])
            i += 1
        return rows

    def _plan_joint_header(self, marks: list[str], mark_face: str) -> dict:
        """选定联合红头字号、行内容与列宽（供垫高计算与写表共用）。"""
        body_w = U.mm_to_twips(U.PAGE["body_width_mm"])
        body_pt = _body_width_pt()
        pad = 1.10

        size_pt = float(U.PT_3)
        rows = list(marks)
        file_w = int(round(size_pt * 2.2 * 20))
        names_w = body_w - file_w

        for trial in [x * 0.5 for x in range(int(U.PT_MARK_DEFAULT * 2), int(U.PT_3 * 2) - 1, -1)]:
            file_pt = layout_text_width_pt("文件", mark_face, trial) * pad
            gap_pt = trial * 0.35  # 名称块与「文件」之间留约 1/3 字缝
            file_need_pt = file_pt + gap_pt
            max_names_pt = body_pt - file_need_pt
            if max_names_pt < trial * 4:
                continue
            packed = self._pack_joint_header_rows(marks, mark_face, trial, max_names_pt)
            if packed is None:
                continue
            content_pt = max(
                layout_text_width_pt(line, mark_face, trial) for line in packed
            ) * pad
            names_pt = min(max_names_pt, max(content_pt, trial * 2))
            fw = max(1, int(round(file_need_pt * 20)))
            nw = max(1, int(round(names_pt * 20)))
            if nw + fw > body_w:
                nw = body_w - fw
            size_pt = float(trial)
            file_w, names_w = fw, nw
            rows = packed
            break

        return {
            "size_pt": size_pt,
            "rows": rows,
            "names_w": names_w,
            "file_w": file_w,
        }

    def _write_joint_header_table(self, doc: Document, mark_face: str, plan: dict) -> None:
        """联合红头：左列机关分行 + 右列「文件」垂直居中。

        列宽按内容自动调：右列只留「文件」二字+小间隙；左列随最长机关名往右拉。
        整表按内容总宽居中，避免「文件」格虚占半个版心。
        """
        size_pt = float(plan["size_pt"])
        rows = list(plan["rows"])
        names_w = int(plan["names_w"])
        file_w = int(plan["file_w"])
        table_w = names_w + file_w
        table = doc.add_table(rows=1, cols=2)
        table.autofit = False
        tbl = table._tbl
        tblPr = tbl.tblPr
        if tblPr is None:
            tblPr = OxmlElement("w:tblPr")
            tbl.insert(0, tblPr)
        for tag in ("tblW", "tblBorders", "tblCellMar", "tblLayout", "tblInd", "jc"):
            for old in tblPr.findall(qn(f"w:{tag}")):
                tblPr.remove(old)

        tblW = OxmlElement("w:tblW")
        tblW.set(qn("w:w"), str(table_w))
        tblW.set(qn("w:type"), "dxa")
        tblPr.append(tblW)
        jc = OxmlElement("w:jc")
        jc.set(qn("w:val"), "center")
        tblPr.append(jc)
        layout = OxmlElement("w:tblLayout")
        layout.set(qn("w:type"), "fixed")
        tblPr.append(layout)
        _clear_tbl_borders(tblPr)
        cellMar = OxmlElement("w:tblCellMar")
        for side in ("top", "left", "bottom", "right"):
            m = OxmlElement(f"w:{side}")
            m.set(qn("w:w"), "0")
            m.set(qn("w:type"), "dxa")
            cellMar.append(m)
        tblPr.append(cellMar)

        for old in tbl.findall(qn("w:tblGrid")):
            tbl.remove(old)
        grid = OxmlElement("w:tblGrid")
        for w in (names_w, file_w):
            gc = OxmlElement("w:gridCol")
            gc.set(qn("w:w"), str(int(w)))
            grid.append(gc)
        tblPr.addnext(grid)

        left, right = table.rows[0].cells
        _set_cell_width(left, names_w)
        _set_cell_width(right, file_w)
        # 禁止格内自动折行：单个机关名必须整行显示（字号已按测宽收敛）
        for cell in (left, right):
            tcPr = cell._tc.get_or_add_tcPr()
            if tcPr.find(qn("w:noWrap")) is None:
                tcPr.append(OxmlElement("w:noWrap"))

        # 左列：每段一整行（已测宽）；noWrap 禁止在机关名中间折行
        left.paragraphs[0].clear()
        for i, line in enumerate(rows):
            p = left.paragraphs[0] if i == 0 else left.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _set_spacing_for_font(p, size_pt, grid_line_pt=self.line_pt)
            run = p.add_run(line)
            _set_run_font(run, name=mark_face, size_pt=size_pt, color=RGBColor(255, 0, 0))

        # 右列：文件（左齐贴名称块；格已收成二字宽）
        rp = right.paragraphs[0]
        rp.clear()
        rp.alignment = WD_ALIGN_PARAGRAPH.LEFT
        _set_spacing_for_font(rp, size_pt, grid_line_pt=self.line_pt)
        rr = rp.add_run("文件")
        _set_run_font(rr, name=mark_face, size_pt=size_pt, color=RGBColor(255, 0, 0))

    def _write_docno_and_signers(self, doc: Document, ir: LayoutIR) -> None:
        """发文字号 + 签发人。1–2 人同行；≥3 人按每行两人并与字号行联动。"""
        signers = [s.strip() for s in (ir.signers or []) if str(s).strip()]
        fangsong = self.fonts["fangsong"]
        kaiti = self.fonts["kaiti"]
        one_twips = int(round(U.PT_3 * 20))
        body_w = U.mm_to_twips(U.PAGE["body_width_mm"])
        body_pt = _body_width_pt()

        if not signers:
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _set_paragraph_spacing(p, line_pt=self.line_pt)
            run = p.add_run(ir.doc_number)
            _set_run_font(run, name=fangsong, size_pt=U.PT_3)
            return

        label = "签发人："
        label_w = layout_text_width_pt(label, fangsong, U.PT_3)

        def add_signer_runs(paragraph, names: list[str], *, with_label: bool) -> None:
            if with_label:
                r_label = paragraph.add_run(label)
                _set_run_font(r_label, name=fangsong, size_pt=U.PT_3)
            for i, name in enumerate(names):
                if i:
                    gap = paragraph.add_run("　")
                    _set_run_font(gap, name=fangsong, size_pt=U.PT_3)
                rn = paragraph.add_run(name)
                _set_run_font(rn, name=kaiti, size_pt=U.PT_3)

        # ≤2 人：保持原版「字号左空一字 + 右侧签发人」单行
        if len(signers) <= 2:
            p = doc.add_paragraph()
            _set_paragraph_spacing(p, line_pt=self.line_pt)
            pPr = p._p.get_or_add_pPr()
            ind = OxmlElement("w:ind")
            ind.set(qn("w:left"), str(one_twips))
            pPr.append(ind)
            tabs = OxmlElement("w:tabs")
            tab = OxmlElement("w:tab")
            tab.set(qn("w:val"), "right")
            tab.set(qn("w:pos"), str(body_w - one_twips))
            tabs.append(tab)
            pPr.append(tabs)
            r1 = p.add_run(ir.doc_number)
            _set_run_font(r1, name=fangsong, size_pt=U.PT_3)
            p.add_run("\t")
            add_signer_runs(p, signers, with_label=True)
            return

        # ≥3 人：除末行外每行 2 人；末行与发文字号同行
        pairs: list[list[str]] = []
        buf = list(signers)
        while len(buf) > 2:
            pairs.append(buf[:2])
            buf = buf[2:]
        last = buf

        first_names = pairs[0]
        names_w = layout_text_width_pt("　".join(first_names), kaiti, U.PT_3)
        first_w = label_w + names_w
        # 右空一字右齐后，第一姓名左缘
        first_name_x = body_pt - U.PT_3 - first_w + label_w
        first_name_tw = max(0, int(round(first_name_x * 20)))

        # 首行：签发人：甲　乙（居右空一字）
        p0 = doc.add_paragraph()
        p0.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _set_paragraph_spacing(p0, line_pt=self.line_pt)
        p0.paragraph_format.right_indent = Pt(U.PT_3)
        add_signer_runs(p0, first_names, with_label=True)

        # 中间续行：与第一姓名左齐
        for pair in pairs[1:]:
            p = doc.add_paragraph()
            _set_paragraph_spacing(p, line_pt=self.line_pt)
            p.paragraph_format.left_indent = Pt(first_name_x)
            add_signer_runs(p, pair, with_label=False)

        # 末行：发文字号左空一字 + 制表位到第一姓名位置排剩余签发人
        p_last = doc.add_paragraph()
        _set_paragraph_spacing(p_last, line_pt=self.line_pt)
        pPr = p_last._p.get_or_add_pPr()
        ind = OxmlElement("w:ind")
        ind.set(qn("w:left"), str(one_twips))
        pPr.append(ind)
        tabs = OxmlElement("w:tabs")
        tab = OxmlElement("w:tab")
        tab.set(qn("w:val"), "left")
        tab.set(qn("w:pos"), str(max(first_name_tw, one_twips + 1)))
        tabs.append(tab)
        pPr.append(tabs)
        r_doc = p_last.add_run(ir.doc_number)
        _set_run_font(r_doc, name=fangsong, size_pt=U.PT_3)
        p_last.add_run("\t")
        add_signer_runs(p_last, last, with_label=False)

    def _write_body(self, doc: Document, ir: LayoutIR):
        # 标题（2号小标宋，同样避免网格裁切）
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _set_spacing_for_font(p, U.PT_2, grid_line_pt=self.line_pt)
        run = p.add_run(ir.title)
        _set_run_font(run, name=self.fonts["xiaobiaosong"], size_pt=U.PT_2)

        # 标题下空一行 + 主送（顶格；末尾必须全角冒号）
        if ir.recipient and not ir.recipients_in_footer:
            _empty_grid_lines(doc, 1, self.line_pt)
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            _set_paragraph_spacing(p, line_pt=self.line_pt)
            recip = ir.recipient.strip().rstrip("：:").rstrip() + "："
            run = p.add_run(recip)
            _set_run_font(run, name=self.fonts["fangsong"], size_pt=U.PT_3)

        for block in ir.body_tree:
            self._write_block(doc, block)

        # 附件说明 §7.3.4：正文下空一行、左空二字；多附件各占一行编号；
        # 名称回行与上一行附件名称首字对齐（勿串成一段自然换行）。
        if ir.attachment_caption.strip():
            _empty_grid_lines(doc, 1, self.line_pt)
            lines = _attachment_caption_lines(ir.attachment_caption)
            # 续行对齐点 = 左空 2 +「附件：」3 = 5 字
            name_align = Pt(U.PT_3 * 5)
            for i, line in enumerate(lines):
                p = doc.add_paragraph()
                _set_paragraph_spacing(p, line_pt=self.line_pt)
                if i == 0:
                    if not line.startswith("附件"):
                        line = "附件：" + line
                    p.paragraph_format.left_indent = name_align
                    p.paragraph_format.first_line_indent = Pt(-U.PT_3 * 3)
                else:
                    p.paragraph_format.left_indent = name_align
                run = p.add_run(line)
                _set_run_font(run, name=self.fonts["fangsong"], size_pt=U.PT_3)

    def _write_block(self, doc: Document, block: BodyBlock):
        p = doc.add_paragraph()
        _set_paragraph_spacing(p, line_pt=self.line_pt)
        font, size, bold = _font_for_level(block.level)
        # §7.3.3：正文自然段（含一、（一）、1. 等层次）均左空二字
        if block.level in {"h1", "h2", "h3", "h4", "p"}:
            p.paragraph_format.first_line_indent = Pt(size * 2)
        text = block.text
        if block.level in {"h2", "h3", "h4"}:
            text = normalize_structure_markers(text)
        run = p.add_run(text)
        # 映射字体名
        name = {
            "黑体": self.fonts["heiti"],
            "楷体_GB2312": self.fonts["kaiti"],
            "仿宋_GB2312": self.fonts["fangsong"],
        }.get(font, font)
        _set_run_font(run, name=name, size_pt=size, bold=bold)

    def _write_signature(self, doc: Document, ir: LayoutIR):
        # 有章：印章顶距正文/附件「一行之内」→ 不空行；无章：正文/附件下空一行
        if ir.seal_mode != SealMode.STAMP:
            _empty_grid_lines(doc, 1, self.line_pt)

        face = self.fonts["fangsong"]
        orgs = _resolve_signature_orgs(ir)
        if len(orgs) <= 1:
            sig = orgs[0] if orgs else (ir.org_signature or "")
            sig_right_pt, date_right_pt = _signature_right_indents(
                sig, ir.date, ir.seal_mode, face
            )
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            _set_paragraph_spacing(p, line_pt=self.line_pt)
            _disable_snap_to_grid(p)  # 关字网格，否则右空常被撑大约 1 字
            p.paragraph_format.right_indent = Pt(sig_right_pt)
            p.paragraph_format.keep_with_next = True
            p.paragraph_format.keep_together = True
            run = p.add_run(sig)
            _set_run_font(run, name=face, size_pt=U.PT_3)

            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            _set_paragraph_spacing(p, line_pt=self.line_pt)
            _disable_snap_to_grid(p)
            p.paragraph_format.right_indent = Pt(date_right_pt)
            p.paragraph_format.keep_together = True
            run = p.add_run(ir.date)
            _set_run_font(run, name=face, size_pt=U.PT_3)
            return

        if ir.seal_mode == SealMode.STAMP:
            self._write_multi_signature_stamp(doc, orgs, ir.date, face)
        else:
            self._write_multi_signature_no_stamp(doc, orgs, ir.date, face)

    def _write_multi_signature_stamp(
        self, doc: Document, orgs: list[str], date: str, face: str
    ) -> None:
        """有章联合署名：每排最多 3 个；日期右空四字；末排最右机关中心与日期中心对齐。"""
        rows = _chunk_list(orgs, 3)
        body_pt = _body_width_pt()
        one = float(U.PT_3)
        date_w = layout_text_width_pt(date, face, U.PT_3)
        date_right = 4.0 * one
        date_center = body_pt - date_right - date_w / 2.0

        for i, row in enumerate(rows):
            is_last = i == len(rows) - 1
            row_text = _join_org_row(row)
            p = doc.add_paragraph()
            _set_paragraph_spacing(p, line_pt=self.line_pt)
            _disable_snap_to_grid(p)
            p.paragraph_format.keep_with_next = True
            p.paragraph_format.keep_together = True
            if is_last:
                # 末行：左缩进使最右机关中心落在日期中心上（同单机关「以日期为准居中」）
                last_w = layout_text_width_pt(row[-1], face, U.PT_3)
                row_w = layout_text_width_pt(row_text, face, U.PT_3)
                row_left = date_center - (row_w - last_w / 2.0)
                row_left = max(0.0, min(row_left, body_pt - row_w))
                p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                p.paragraph_format.left_indent = Pt(row_left)
            else:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = p.add_run(row_text)
            _set_run_font(run, name=face, size_pt=U.PT_3)

        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _set_paragraph_spacing(p, line_pt=self.line_pt)
        _disable_snap_to_grid(p)
        p.paragraph_format.right_indent = Pt(date_right)
        p.paragraph_format.keep_together = True
        run = p.add_run(date)
        _set_run_font(run, name=face, size_pt=U.PT_3)

    def _write_multi_signature_no_stamp(
        self, doc: Document, orgs: list[str], date: str, face: str
    ) -> None:
        """无章联合署名：每行一个、首字对齐；日期按 §7.3.5.2 二选一锚定（绝不左右缩进同时设）。"""
        layout = _no_stamp_multi_layout(orgs, date, face, U.PT_3)

        for org in orgs:
            p = doc.add_paragraph()
            _set_paragraph_spacing(p, line_pt=self.line_pt)
            _disable_snap_to_grid(p)
            p.paragraph_format.left_indent = Pt(layout["sig_left"])
            p.paragraph_format.keep_with_next = True
            p.paragraph_format.keep_together = True
            run = p.add_run(org)
            _set_run_font(run, name=face, size_pt=U.PT_3)

        p = doc.add_paragraph()
        _set_paragraph_spacing(p, line_pt=self.line_pt)
        _disable_snap_to_grid(p)
        p.paragraph_format.keep_together = True
        if layout["branch"] == "first_char":
            # 只锚首字：左齐 + 左缩进；不设右缩进，避免与测宽抢宽度
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            p.paragraph_format.left_indent = Pt(layout["date_left"])
            p.paragraph_format.right_indent = Pt(0)
        else:
            # 只锚右端：右齐 + 右空二字；不设左缩进
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            p.paragraph_format.left_indent = Pt(0)
            p.paragraph_format.right_indent = Pt(layout["date_right"])
        run = p.add_run(date)
        _set_run_font(run, name=face, size_pt=U.PT_3)

    def _write_note(self, doc: Document, ir: LayoutIR):
        if not ir.note.strip():
            return
        note = ir.note.strip()
        if not (note.startswith("（") or note.startswith("(")):
            note = f"（{note}）"
        p = doc.add_paragraph()
        _set_paragraph_spacing(p, line_pt=self.line_pt)
        p.paragraph_format.first_line_indent = Pt(U.PT_3 * 2)
        run = p.add_run(note)
        _set_run_font(run, name=self.fonts["fangsong"], size_pt=U.PT_3)

    def _write_banji(self, doc: Document, ir: LayoutIR):
        """版记：浮动表沉底；上下粗/中间细；空一字用绝对 twips 缩进（不写进正文全角空格）。"""
        body_w = U.mm_to_twips(U.PAGE["body_width_mm"])
        one = int(round(U.PT_4 * 20))  # 4 号一字
        row_pt = U.PT_4 * 1.15
        fangsong = self.fonts["fangsong"]

        upper_lines: list[str] = []
        if ir.recipients_in_footer and ir.recipient.strip():
            upper_lines.append("主送：" + ir.recipient.strip().rstrip("：:"))
        if ir.cc_recipients.strip():
            cc = ir.cc_recipients.strip()
            if not cc.startswith("抄送"):
                cc = "抄送：" + cc
            elif not cc.startswith("抄送："):
                cc = "抄送：" + cc[len("抄送") :].lstrip("：:")
            if not cc.endswith("。"):
                cc += "。"
            upper_lines.append(cc)

        has_upper = bool(upper_lines)
        table = doc.add_table(rows=2 if has_upper else 1, cols=2)
        table.autofit = False
        if has_upper:
            table.rows[0].cells[0].merge(table.rows[0].cells[1])

        tbl = table._tbl
        tblPr = tbl.tblPr
        if tblPr is None:
            tblPr = OxmlElement("w:tblPr")
            tbl.insert(0, tblPr)

        for tag in (
            "w:tblW",
            "w:tblpPr",
            "w:tblOverlap",
            "w:tblBorders",
            "w:tblLayout",
            "w:tblCellMar",
            "w:jc",
        ):
            for old in tblPr.findall(qn(tag)):
                tblPr.remove(old)
        for old in tbl.findall(qn("w:tblGrid")):
            tbl.remove(old)

        half = body_w // 2
        grid = OxmlElement("w:tblGrid")
        for w in (half, body_w - half):
            gc = OxmlElement("w:gridCol")
            gc.set(qn("w:w"), str(w))
            grid.append(gc)
        tbl.insert(tbl.index(tblPr) + 1, grid)

        tblW = OxmlElement("w:tblW")
        tblW.set(qn("w:w"), str(body_w))
        tblW.set(qn("w:type"), "dxa")
        tblPr.append(tblW)

        tblpPr = OxmlElement("w:tblpPr")
        for k, v in (
            ("w:leftFromText", "0"),
            ("w:rightFromText", "0"),
            ("w:topFromText", "0"),
            ("w:bottomFromText", "0"),
            ("w:vertAnchor", "margin"),
            ("w:horzAnchor", "margin"),
            ("w:tblpXSpec", "left"),
            ("w:tblpYSpec", "bottom"),
        ):
            tblpPr.set(qn(k), v)
        tblPr.append(tblpPr)

        overlap = OxmlElement("w:tblOverlap")
        overlap.set(qn("w:val"), "never")
        tblPr.append(overlap)

        layout = OxmlElement("w:tblLayout")
        layout.set(qn("w:type"), "fixed")
        tblPr.append(layout)

        # 一律 single，靠 sz 控粗细（thick 常忽略 sz，Word 读回 LineWidth=-1）
        borders = OxmlElement("w:tblBorders")
        for edge, val, sz in (
            ("top", "single", U.BANJI_LINE_THICK_SZ),
            ("left", "nil", 0),
            ("bottom", "single", U.BANJI_LINE_THICK_SZ),
            ("right", "nil", 0),
            ("insideH", "single", U.BANJI_LINE_THIN_SZ if has_upper else 0),
            ("insideV", "nil", 0),
        ):
            el = OxmlElement(f"w:{edge}")
            if val == "nil" or sz <= 0:
                el.set(qn("w:val"), "nil")
                el.set(qn("w:sz"), "0")
                el.set(qn("w:space"), "0")
                el.set(qn("w:color"), "auto")
            else:
                el.set(qn("w:val"), val)
                el.set(qn("w:sz"), str(sz))
                el.set(qn("w:space"), "0")
                el.set(qn("w:color"), "000000")
            borders.append(el)
        tblPr.append(borders)

        cellMar = OxmlElement("w:tblCellMar")
        for side in ("top", "left", "bottom", "right"):
            m = OxmlElement(f"w:{side}")
            m.set(qn("w:w"), "0")
            m.set(qn("w:type"), "dxa")
            cellMar.append(m)
        tblPr.append(cellMar)

        def _set_tc_width(cell, width_twips: int):
            tcPr = cell._tc.get_or_add_tcPr()
            for old in tcPr.findall(qn("w:tcW")):
                tcPr.remove(old)
            tcW = OxmlElement("w:tcW")
            tcW.set(qn("w:w"), str(width_twips))
            tcW.set(qn("w:type"), "dxa")
            tcPr.append(tcW)

        def _cell_para(cell, *, clear=True):
            if clear:
                cell.text = ""
            p = cell.paragraphs[0]
            _set_paragraph_spacing(p, before_pt=0, after_pt=0, line_pt=row_pt)
            _disable_snap_to_grid(p)
            return p

        def _set_ind(paragraph, *, left: int = 0, right: int = 0, hanging: int = 0):
            """段落缩进（twips）。首行位置 = left - hanging。"""
            pPr = paragraph._p.get_or_add_pPr()
            ind = pPr.find(qn("w:ind"))
            if ind is None:
                ind = OxmlElement("w:ind")
                pPr.append(ind)
            else:
                for a in list(ind.attrib):
                    del ind.attrib[a]
            if left:
                ind.set(qn("w:left"), str(left))
            if right:
                ind.set(qn("w:right"), str(right))
            if hanging:
                ind.set(qn("w:hanging"), str(hanging))

        print_row = table.rows[1] if has_upper else table.rows[0]

        if has_upper:
            cell = table.rows[0].cells[0]
            _set_tc_width(cell, body_w)
            first = True
            for line in upper_lines:
                if first:
                    p = _cell_para(cell, clear=True)
                    first = False
                else:
                    p = cell.add_paragraph()
                    _set_paragraph_spacing(p, before_pt=0, after_pt=0, line_pt=row_pt)
                    _disable_snap_to_grid(p)
                # §7.4.2：左右各空一字；回行对齐冒号后
                # 首行起点 = left-hanging = 1 字；续行起点 = 4 字（空一字+「抄送：」）
                _set_ind(p, left=4 * one, right=one, hanging=3 * one)
                run = p.add_run(line)
                _set_run_font(run, name=fangsong, size_pt=U.PT_4)

        left_c, right_c = print_row.cells[0], print_row.cells[1]
        _set_tc_width(left_c, half)
        _set_tc_width(right_c, body_w - half)

        # §7.4.3：机关左空一字、日期右空一字（绝对 twips，不写进正文全角空格）
        p_l = _cell_para(left_c, clear=True)
        p_l.alignment = WD_ALIGN_PARAGRAPH.LEFT
        _set_ind(p_l, left=one)
        org = (ir.print_org or "").strip()
        r1 = p_l.add_run(org)
        _set_run_font(r1, name=fangsong, size_pt=U.PT_4)

        p_r = _cell_para(right_c, clear=True)
        p_r.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _set_ind(p_r, right=one)
        print_date = (ir.print_date or "").strip()
        if print_date and not print_date.endswith("印发"):
            print_date = print_date + "印发"
        r2 = p_r.add_run(print_date)
        _set_run_font(r2, name=fangsong, size_pt=U.PT_4)
