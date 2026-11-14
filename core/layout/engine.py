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


def _add_banner_red_line(doc: Document) -> None:
    """§7.2.7：发文字号下 4mm、与版心等宽的红色分隔线。

    不用发文字号段的 pBdr：上行文左空一字会使边框跟着右移；
    段落下边框本身也常比版心略窄。改为「空距段 + 定宽单列表底边」。
    """
    gap_pt = U.RED_LINE_GAP_MM / U.MM_PER_INCH * 72.0
    spacer = doc.add_paragraph()
    _set_paragraph_spacing(spacer, before_pt=0, after_pt=0, line_pt=gap_pt)
    _disable_snap_to_grid(spacer)
    _set_run_font(spacer.add_run(""), name="仿宋_GB2312", size_pt=1.0)

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
    line_sz = int(round(U.RED_LINE_PT * 8))
    for edge, val, sz, color in (
        ("top", "nil", 0, "auto"),
        ("left", "nil", 0, "auto"),
        ("bottom", "single", line_sz, "FF0000"),
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
    _set_paragraph_spacing(cp, before_pt=0, after_pt=0, line_pt=1.0)
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

    # 无章：署名右空二字时，日期右空 = 署名宽 - 日期宽（首字右移二字）
    date_right_if_sig2 = sig_w - date_w
    if date_right_if_sig2 >= 0:
        return 2.0 * one, date_right_if_sig2
    # 日期更长：日期右空二字，相应增加署名右空
    return date_w - sig_w + 4.0 * one, 2.0 * one


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

        # 红头距版心顶 35mm：用空网格行垫到约 35mm（减去已占顶栏行）
        # 已占 top_items 行；目标空行数 ≈ 35mm / 行高
        mm_per_line = U.PAGE["body_height_mm"] / U.GRID_ROWS
        target_lines = int(round(U.RED_HEADER_FROM_BODY_TOP_MM / mm_per_line))
        pad = max(0, target_lines - len(top_items))
        _empty_grid_lines(doc, pad, self.line_pt)

        # 发文机关标志（单一红头：字号 = 一行能放下的最大 pt）
        marks = [m.strip() for m in (ir.org_marks or []) if str(m).strip()]
        if not marks:
            marks = [""]
        mark_face = self.fonts["xiaobiaosong"]
        for mark in marks:
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            # 联合红头以后再做侧排「文件」；暂先各行独立按一行最大字号
            size_pt = _max_one_line_mark_font_pt(mark, mark_face)
            _set_spacing_for_font(p, size_pt, grid_line_pt=self.line_pt)
            run = p.add_run(mark)
            _set_run_font(
                run,
                name=mark_face,
                size_pt=size_pt,
                color=RGBColor(255, 0, 0),
            )

        # 标志下空二行
        _empty_grid_lines(doc, 2, self.line_pt)

        # 发文字号：下行居中；上行（有签发人）§7.2.5/7.2.6 左空一字 + 签发人右空一字同行
        if ir.signers:
            p = doc.add_paragraph()
            _set_paragraph_spacing(p, line_pt=self.line_pt)
            one_twips = int(round(U.PT_3 * 20))
            body_w = U.mm_to_twips(U.PAGE["body_width_mm"])
            pPr = p._p.get_or_add_pPr()
            # 只用绝对 twips（3 号一字 = 16pt = 320）。勿写 leftChars：
            # Word 会优先按字符网格折算，常变成约 11pt，且 COM 难清掉。
            ind = OxmlElement("w:ind")
            ind.set(qn("w:left"), str(one_twips))
            pPr.append(ind)
            tabs = OxmlElement("w:tabs")
            tab = OxmlElement("w:tab")
            tab.set(qn("w:val"), "right")
            # 右对齐制表位在版心右空一字处
            tab.set(qn("w:pos"), str(body_w - one_twips))
            tabs.append(tab)
            pPr.append(tabs)
            r1 = p.add_run(ir.doc_number)
            _set_run_font(r1, name=self.fonts["fangsong"], size_pt=U.PT_3)
            p.add_run("\t")
            # 「签发人」+ 全角冒号：3 号仿宋；姓名：3 号楷体
            r_label = p.add_run("签发人：")
            _set_run_font(r_label, name=self.fonts["fangsong"], size_pt=U.PT_3)
            names = "　".join(s.strip() for s in ir.signers if str(s).strip())
            r_names = p.add_run(names)
            _set_run_font(r_names, name=self.fonts["kaiti"], size_pt=U.PT_3)
        else:
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _set_paragraph_spacing(p, line_pt=self.line_pt)
            run = p.add_run(ir.doc_number)
            _set_run_font(run, name=self.fonts["fangsong"], size_pt=U.PT_3)

        # 红线独立于发文字号段（§7.2.7 版心等宽；上行左空一字不拖偏红线）
        _add_banner_red_line(doc)

        # 红线下空二行
        _empty_grid_lines(doc, 2, self.line_pt)

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
        sig_right_pt, date_right_pt = _signature_right_indents(
            ir.org_signature, ir.date, ir.seal_mode, face
        )

        # 署名 keep_with_next：若与成文日期装不下同一页，一并挪到下一页
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _set_paragraph_spacing(p, line_pt=self.line_pt)
        p.paragraph_format.right_indent = Pt(sig_right_pt)
        p.paragraph_format.keep_with_next = True
        p.paragraph_format.keep_together = True
        run = p.add_run(ir.org_signature)
        _set_run_font(run, name=face, size_pt=U.PT_3)

        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _set_paragraph_spacing(p, line_pt=self.line_pt)
        p.paragraph_format.right_indent = Pt(date_right_pt)
        p.paragraph_format.keep_together = True
        # 成文日期用半角阿拉伯数字（与国标图示、页码条款、文内其它数字一致）
        run = p.add_run(ir.date)
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
