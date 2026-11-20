# -*- coding: utf-8 -*-
"""国标尺寸换算。"""
from __future__ import annotations

# OOXML: 1 inch = 914400 EMUs; 1 pt = 12700 EMUs
# python-docx uses twips for some (1 inch = 1440 twips); Pt for font

MM_PER_INCH = 25.4


def mm_to_twips(mm: float) -> int:
    return int(round(mm / MM_PER_INCH * 1440))


def mm_to_emu(mm: float) -> int:
    return int(round(mm / MM_PER_INCH * 914400))


def pt_to_half_points(pt: float) -> int:
    """w:sz 用半磅。"""
    return int(round(pt * 2))


# 版心 156×225mm → 右 26、下 35（相对 A4 210×297、上 37、左 28）
PAGE = {
    "width_mm": 210.0,
    "height_mm": 297.0,
    "top_mm": 37.0,
    "left_mm": 28.0,
    "right_mm": 26.0,
    "bottom_mm": 35.0,
    "body_width_mm": 156.0,
    "body_height_mm": 225.0,
}

# 红头上边缘距版心上边缘 35mm → 距纸顶 ≈ 37+35 = 72mm
RED_HEADER_FROM_BODY_TOP_MM = 35.0
# 命令（令）标志墨迹顶距版心上边缘 20mm → 距纸顶 57mm（docs/baselines/命令.md §3.1）
ORDER_MARK_FROM_BODY_TOP_MM = 20.0
# 签名章占位：扁长方 45×20 mm（高须 ≤ 空二行 ≈ 20.5 mm）
ORDER_SEAL_WIDTH_MM = 45.0
ORDER_SEAL_HEIGHT_MM = 20.0
ORDER_SEAL_BORDER_PT = 0.5
# 红头行框内：字身上方空白占 (line_pt - font_pt) 的比例（Word/WPS 非居中）
# 垫高时扣掉这段，使「红色墨迹顶」而非行框顶落在 35mm
RED_HEADER_INK_ABOVE_RATIO = 0.59
# 发文字号下到红线：目标 4mm（字身下缘 → 红线上缘）
RED_LINE_GAP_MM = 4.0
# 发文字号网格行内：字身下缘到行框底占 (line_pt - font_pt) 的比例
# 红线空距段要扣掉这段，否则会在 4mm 之上再叠一行内下行隙
RED_LINE_GLYPH_BELOW_RATIO = 0.28
# 红线厚度（pt）；过粗时观感不像式样图，取约 0.75pt
RED_LINE_PT = 0.75

# 7.5 页码：一字线上距版心下边缘 7mm → 页脚距纸底 = 下白边 - 7
PAGE_NUMBER_BELOW_BODY_MM = 7.0
# 一字线（排在页码数字两侧）
PAGE_NUMBER_DASH = "—"

# 7.4.1 版记分隔线 → OOXML sz 单位 1/8 pt
# 推荐 0.35mm/0.25mm；实际渲染上加大反差，避免 WPS 看起来一样粗
# §7.4.1：首条/末条 0.35mm、中间 0.25mm → OOXML sz = pt×8（1/8 pt）
BANJI_LINE_THICK_SZ = 8  # 0.35mm ≈ 0.99pt
BANJI_LINE_THIN_SZ = 6  # 0.25mm ≈ 0.71pt

# 网格
GRID_ROWS = 22
GRID_COLS = 28

# 字号
PT_2 = 22.0
PT_3 = 16.0
PT_4 = 14.0
PT_MARK_DEFAULT = 60.0
