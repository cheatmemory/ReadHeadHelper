# -*- coding: utf-8 -*-
"""版头几何：墨迹顶 35mm、红线距字身 4mm（与样例无关的通用换算）。"""
from core.layout import units as U
from core.layout.engine import (
    _docno_glyph_below_mm,
    _grid_line_pt,
    _mark_ink_inset_mm,
)


def test_mark_ink_target_always_35mm():
    line = _grid_line_pt()
    for top_n in (0, 1, 2, 3):
        for font_pt in (22.0, 31.0, 39.0, 43.0, 48.0, 60.0):
            used = top_n * (U.PAGE["body_height_mm"] / U.GRID_ROWS)
            inset = _mark_ink_inset_mm(font_pt, line)
            spacer = max(0.0, U.RED_HEADER_FROM_BODY_TOP_MM - used - inset)
            assert abs(used + spacer + inset - U.RED_HEADER_FROM_BODY_TOP_MM) < 1e-6


def test_red_line_gap_targets_4mm_from_glyph():
    line = _grid_line_pt()
    below = _docno_glyph_below_mm(line, U.PT_3)
    spacer = max(0.5, U.RED_LINE_GAP_MM - below)
    assert abs(below + spacer - U.RED_LINE_GAP_MM) < 1e-6
    assert below > 0.5  # 网格行高于 3 号字，必有下行隙
