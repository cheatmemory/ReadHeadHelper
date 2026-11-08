# -*- coding: utf-8 -*-
"""红头字宽测量：优先本机字体实测，失败则保守估算。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from functools import lru_cache

# 估算：中文小标宋类字体字宽通常略大于「字号 pt」本身
ESTIMATE_EM_RATIO = 1.12
# 版心可用宽度比例（两侧留边，防 WPS 挤换行）
USABLE_WIDTH_RATIO = 0.92
# 实测宽再放大一点：Word/WPS 字距、对齐可能比 GDI 略宽
MEASURE_PAD = 1.03


class SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


def _gdi():
    gdi32 = ctypes.windll.gdi32
    user32 = ctypes.windll.user32
    return gdi32, user32


def _pt_to_lf_height(size_pt: float, dpi: int = 72) -> int:
    # CreateFont 的 lfHeight 用逻辑英寸；用 72dpi 的 pt→像素，再在同一 DC 上量宽，比值稳定
    return -int(round(size_pt * dpi / 72.0))


@lru_cache(maxsize=64)
def gdi_measure_width_px(text: str, font_face: str, size_pt: float) -> tuple[int, str] | None:
    """用 GDI 测文本像素宽。返回 (width_px, 实际选中的字体名)；失败返回 None。"""
    if not text or size_pt <= 0:
        return None
    try:
        gdi32, user32 = _gdi()
    except Exception:
        return None

    hdc = user32.GetDC(0)
    if not hdc:
        return None

    # GB2312_CHARSET = 134
    lf_height = _pt_to_lf_height(size_pt, 96)  # 屏幕 DC 常见 96dpi
    font = gdi32.CreateFontW(
        lf_height,
        0,
        0,
        0,
        400,  # FW_NORMAL
        0,
        0,
        0,
        134,  # GB2312_CHARSET
        0,
        0,
        4,  # ANTIALIASED_QUALITY / CLEARTYPE 近似
        0,
        font_face,
    )
    if not font:
        user32.ReleaseDC(0, hdc)
        return None

    old = gdi32.SelectObject(hdc, font)
    size = SIZE()
    ok = gdi32.GetTextExtentPoint32W(hdc, text, len(text), ctypes.byref(size))

    # 读出实际字体名，判断是否发生了静默替换
    actual = ctypes.create_unicode_buffer(64)
    gdi32.GetTextFaceW(hdc, 64, actual)

    gdi32.SelectObject(hdc, old)
    gdi32.DeleteObject(font)
    user32.ReleaseDC(0, hdc)

    if not ok or size.cx <= 0:
        return None
    return int(size.cx), actual.value


def _face_ok(requested: str, actual: str) -> bool:
    """GDI 是否真的选中了请求字体（而非静默替换）。"""
    if not actual:
        return False
    a, r = actual.strip(), requested.strip()
    if a == r:
        return True
    # 允许「方正小标宋简体」vs「方正小标宋」等前缀匹配
    if r in a or a in r:
        return True
    return False


def measure_text_width_pt(text: str, font_face: str, size_pt: float) -> float | None:
    """测 text 在指定字号下的宽度（pt）。仅当本机确有该字体时返回；否则 None。"""
    t = (text or "").strip()
    if not t:
        return 0.0
    # 只测用户配置的那一款；没有就不假装「实测」
    got = gdi_measure_width_px(t, font_face, size_pt)
    if not got:
        return None
    width_px, actual = got
    if not _face_ok(font_face, actual):
        return None
    # CreateFont 按 96dpi 建字，宽像素 / 96 * 72 = pt
    return width_px * 72.0 / 96.0


def estimate_text_width_pt(text: str, size_pt: float) -> float:
    """无字体时的保守估算宽。"""
    t = (text or "").strip()
    return len(t) * size_pt * ESTIMATE_EM_RATIO


def max_one_line_font_pt(
    text: str,
    *,
    body_width_mm: float,
    font_face: str = "方正小标宋简体",
    min_pt: float = 1.0,
    max_pt: float = 120.0,
) -> float:
    """版心一行能放下的最大字号。优先 GDI 实测，否则用保守估算。"""
    t = (text or "").strip()
    if not t:
        return 60.0

    usable_pt = body_width_mm / 25.4 * 72.0 * USABLE_WIDTH_RATIO

    # 先探一下实测是否可用
    probe = measure_text_width_pt(t, font_face, 60.0)
    use_measure = probe is not None

    def width_at(pt: float) -> float:
        if use_measure:
            w = measure_text_width_pt(t, font_face, pt)
            if w is not None:
                return w * MEASURE_PAD
        return estimate_text_width_pt(t, pt)

    # 二分最大字号
    lo, hi = float(min_pt), float(max_pt)
    best = float(min_pt)
    for _ in range(24):
        mid = (lo + hi) / 2.0
        if width_at(mid) <= usable_pt:
            best = mid
            lo = mid
        else:
            hi = mid
    return best
