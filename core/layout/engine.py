# -*- coding: utf-8 -*-
"""DocxEngine：模板骨架 + OOXML 补洞，LayoutIR → docx。"""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor, Twips

from core.ir.schema import BodyBlock, LayoutIR, SealMode
from core.layout import units as U
from core.layout.font_measure import max_one_line_font_pt


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


def _add_bottom_border_red(paragraph, *, sz_eighths: int = 16, space_pt: float = 4.0):
    """段落底边框作红色分隔线。sz 单位为 1/8 pt；2pt → 16。"""
    pPr = paragraph._p.get_or_add_pPr()
    pBdr = pPr.find(qn("w:pBdr"))
    if pBdr is None:
        pBdr = OxmlElement("w:pBdr")
        pPr.append(pBdr)
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(sz_eighths))
    bottom.set(qn("w:space"), str(int(round(space_pt))))
    bottom.set(qn("w:color"), "FF0000")
    # 清旧 bottom
    for old in pBdr.findall(qn("w:bottom")):
        pBdr.remove(old)
    pBdr.append(bottom)


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
        self._write_banji(doc, ir)

        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(out_path))
        return out_path

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

        for _, text in top_items:
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            _set_paragraph_spacing(p, line_pt=self.line_pt)
            run = p.add_run(text)
            _set_run_font(run, name=self.fonts["heiti"], size_pt=U.PT_3)

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

        # 发文字号（上行文时与签发人同行——v1 先做下行居中；有签发人则左右分列）
        if ir.signers:
            p = doc.add_paragraph()
            _set_paragraph_spacing(p, line_pt=self.line_pt)
            # 简化：用制表位模拟左右
            pPr = p._p.get_or_add_pPr()
            tabs = OxmlElement("w:tabs")
            tab = OxmlElement("w:tab")
            tab.set(qn("w:val"), "right")
            tab.set(qn("w:pos"), str(U.mm_to_twips(U.PAGE["body_width_mm"])))
            tabs.append(tab)
            pPr.append(tabs)
            r1 = p.add_run(ir.doc_number)
            _set_run_font(r1, name=self.fonts["fangsong"], size_pt=U.PT_3)
            p.add_run("\t")
            r2 = p.add_run("签发人：" + "　".join(ir.signers[:2]))
            _set_run_font(r2, name=self.fonts["fangsong"], size_pt=U.PT_3)
            # 姓名楷体无法轻易拆，v1 整段仿宋+后续增强
        else:
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _set_paragraph_spacing(p, line_pt=self.line_pt)
            run = p.add_run(ir.doc_number)
            _set_run_font(run, name=self.fonts["fangsong"], size_pt=U.PT_3)

        # 红线：字号下 4mm，2pt，版心等宽（段落底边框）
        _add_bottom_border_red(
            p,
            sz_eighths=int(U.RED_LINE_PT * 8),
            space_pt=U.RED_LINE_GAP_MM / 25.4 * 72.0,  # mm→pt 近似写入 space
        )

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

        # 附件说明
        if ir.attachment_caption.strip():
            _empty_grid_lines(doc, 1, self.line_pt)
            p = doc.add_paragraph()
            _set_paragraph_spacing(p, line_pt=self.line_pt)
            # 左空二字：首行缩进 2 字符
            p.paragraph_format.first_line_indent = Pt(U.PT_3 * 2)
            cap = ir.attachment_caption.strip()
            if not cap.startswith("附件"):
                cap = "附件：" + cap
            run = p.add_run(cap)
            _set_run_font(run, name=self.fonts["fangsong"], size_pt=U.PT_3)

    def _write_block(self, doc: Document, block: BodyBlock):
        p = doc.add_paragraph()
        _set_paragraph_spacing(p, line_pt=self.line_pt)
        font, size, bold = _font_for_level(block.level)
        if block.level == "p":
            p.paragraph_format.first_line_indent = Pt(size * 2)
        run = p.add_run(block.text)
        # 映射字体名
        name = {
            "黑体": self.fonts["heiti"],
            "楷体_GB2312": self.fonts["kaiti"],
            "仿宋_GB2312": self.fonts["fangsong"],
        }.get(font, font)
        _set_run_font(run, name=name, size_pt=size, bold=bold)

    def _write_signature(self, doc: Document, ir: LayoutIR):
        _empty_grid_lines(doc, 1, self.line_pt)
        # 右对齐近似：有章 → 日期右空四字；无章 → 署名右空二字、日期再右移二字
        if ir.seal_mode == SealMode.STAMP:
            # 署名居中于日期（单一机关简化：右缩进约 4 字）
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            _set_paragraph_spacing(p, line_pt=self.line_pt)
            p.paragraph_format.right_indent = Pt(U.PT_3 * 4)
            run = p.add_run(ir.org_signature)
            _set_run_font(run, name=self.fonts["fangsong"], size_pt=U.PT_3)

            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            _set_paragraph_spacing(p, line_pt=self.line_pt)
            p.paragraph_format.right_indent = Pt(U.PT_3 * 4)
            run = p.add_run(ir.date)
            _set_run_font(run, name=self.fonts["fangsong"], size_pt=U.PT_3)
        else:
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            _set_paragraph_spacing(p, line_pt=self.line_pt)
            p.paragraph_format.right_indent = Pt(U.PT_3 * 2)
            run = p.add_run(ir.org_signature)
            _set_run_font(run, name=self.fonts["fangsong"], size_pt=U.PT_3)

            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            _set_paragraph_spacing(p, line_pt=self.line_pt)
            p.paragraph_format.right_indent = Pt(U.PT_3 * 0)  # 日期比署名右移二字 → 右缩进更小
            # 署名右空二字；日期首字比署名首字右移二字 ⇒ 日期右空 0 字（相对版心右）
            run = p.add_run(ir.date)
            _set_run_font(run, name=self.fonts["fangsong"], size_pt=U.PT_3)

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
        # 版记分隔线（粗）
        def banji_line(thick: bool):
            p = doc.add_paragraph()
            _set_paragraph_spacing(p, line_pt=self.line_pt * 0.6)
            pPr = p._p.get_or_add_pPr()
            pBdr = OxmlElement("w:pBdr")
            top = OxmlElement("w:top")
            # 0.35mm ≈ 1pt；0.25mm ≈ 0.7pt → sz 单位 1/8 pt
            sz = 8 if thick else 6
            top.set(qn("w:val"), "single")
            top.set(qn("w:sz"), str(sz))
            top.set(qn("w:space"), "1")
            top.set(qn("w:color"), "000000")
            pBdr.append(top)
            pPr.append(pBdr)
            return p

        banji_line(True)
        if ir.recipients_in_footer and ir.recipient:
            p = doc.add_paragraph()
            _set_paragraph_spacing(p, line_pt=self.line_pt * 0.85)
            run = p.add_run("主送：" + ir.recipient.rstrip("：:"))
            _set_run_font(run, name=self.fonts["fangsong"], size_pt=U.PT_4)
            banji_line(False)

        if ir.cc_recipients.strip():
            p = doc.add_paragraph()
            _set_paragraph_spacing(p, line_pt=self.line_pt * 0.85)
            cc = ir.cc_recipients.strip()
            if not cc.startswith("抄送"):
                cc = "抄送：" + cc
            if not cc.endswith("。"):
                cc = cc + "。"
            run = p.add_run(cc)
            _set_run_font(run, name=self.fonts["fangsong"], size_pt=U.PT_4)
            banji_line(False)

        p = doc.add_paragraph()
        _set_paragraph_spacing(p, line_pt=self.line_pt * 0.85)
        # 印发机关 / 印发日期 左右分列
        pPr = p._p.get_or_add_pPr()
        tabs = OxmlElement("w:tabs")
        tab = OxmlElement("w:tab")
        tab.set(qn("w:val"), "right")
        tab.set(qn("w:pos"), str(U.mm_to_twips(U.PAGE["body_width_mm"])))
        tabs.append(tab)
        pPr.append(tabs)
        r1 = p.add_run(ir.print_org)
        _set_run_font(r1, name=self.fonts["fangsong"], size_pt=U.PT_4)
        p.add_run("\t")
        print_date = ir.print_date.strip()
        if print_date and not print_date.endswith("印发"):
            print_date = print_date + "印发"
        r2 = p.add_run(print_date)
        _set_run_font(r2, name=self.fonts["fangsong"], size_pt=U.PT_4)
        banji_line(True)
