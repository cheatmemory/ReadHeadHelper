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
RED_LINE_GAP_MM = 4.0
RED_LINE_PT = 2.0

# 7.5 页码：一字线上距版心下边缘 7mm → 页脚距纸底 = 下白边 - 7
PAGE_NUMBER_BELOW_BODY_MM = 7.0
# 一字线（排在页码数字两侧）
PAGE_NUMBER_DASH = "—"

# 网格
GRID_ROWS = 22
GRID_COLS = 28

# 字号
PT_2 = 22.0
PT_3 = 16.0
PT_4 = 14.0
PT_MARK_DEFAULT = 60.0
