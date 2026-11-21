# -*- coding: utf-8 -*-
"""用本机 Word/WPS 测文本排版宽（与落款所见一致）。无 Office 时回退估算。"""
from __future__ import annotations

import atexit
from functools import lru_cache

# 半角数字在仿宋下的进宽（相对字号）。按 WPS「2026年11月8日」≈7.75em 标定。
_ASCII_DIGIT_EM = 0.6786
_ASCII_OTHER_EM = 0.5

_app = None
_app_failed = False


def _get_app():
    global _app, _app_failed
    if _app_failed:
        return None
    if _app is not None:
        return _app
    try:
        import win32com.client  # type: ignore
    except ImportError:
        _app_failed = True
        return None
    for prog in ("Kwps.Application", "wps.Application", "Word.Application"):
        try:
            app = win32com.client.Dispatch(prog)
            app.Visible = False
            _app = app
            return _app
        except Exception:
            continue
    _app_failed = True
    return None


def _shutdown_app():
    global _app
    if _app is None:
        return
    try:
        _app.Quit()
    except Exception:
        pass
    _app = None


atexit.register(_shutdown_app)


def estimate_layout_width_pt(text: str, size_pt: float) -> float:
    """无 Office 时的仿宋落款宽估算：汉字 1em，半角数字约 0.68em。"""
    t = (text or "").strip()
    if not t or size_pt <= 0:
        return 0.0
    w = 0.0
    for c in t:
        o = ord(c)
        if "0" <= c <= "9":
            w += _ASCII_DIGIT_EM
        elif o < 0x80:
            w += _ASCII_OTHER_EM
        else:
            w += 1.0
    return w * size_pt


@lru_cache(maxsize=256)
def office_measure_width_pt(text: str, font_face: str, size_pt: float) -> float | None:
    """Word/WPS 光标位移测宽（pt）。失败返回 None。

    大字号时默认版心会折行，光标 Δx 只覆盖首行 → 宽度严重偏小。
    测宽前加宽页、禁止折行，避免联合红头误选过大字号。
    """
    t = (text or "").strip()
    if not t:
        return 0.0
    if size_pt <= 0:
        return None
    app = _get_app()
    if app is None:
        return None
    doc = None
    try:
        doc = app.Documents.Add()
        doc.Content.Delete()
        # 给足页宽，避免测宽文本在默认 A4 版心内折行
        try:
            sec = doc.Sections(1)
            sec.PageSetup.PageWidth = float(size_pt) * max(len(t), 1) * 1.5 + 144.0  # pt
            sec.PageSetup.LeftMargin = 36.0
            sec.PageSetup.RightMargin = 36.0
        except Exception:
            pass
        doc.Range(0, 0).InsertAfter(t)
        rng = doc.Range(0, len(t))
        rng.Font.NameFarEast = font_face
        try:
            rng.Font.NameAscii = font_face
        except Exception:
            pass
        rng.Font.Size = float(size_pt)
        try:
            rng.ParagraphFormat.WordWrap = False
        except Exception:
            pass
        start = rng.Duplicate
        start.Collapse(1)  # wdCollapseStart
        end = rng.Duplicate
        end.Collapse(0)  # wdCollapseEnd
        # wdHorizontalPositionRelativeToPage = 5
        x0 = float(start.Information(5))
        x1 = float(end.Information(5))
        width = x1 - x0
        if width <= 0:
            return None
        return width
    except Exception:
        return None
    finally:
        if doc is not None:
            try:
                doc.Close(False)
            except Exception:
                pass


def layout_text_width_pt(text: str, font_face: str, size_pt: float) -> float:
    """排版宽度：优先 Word/WPS 实测；若明显小于汉字 1em 估算则取估算（防大字号折行测窄）。"""
    estimated = estimate_layout_width_pt(text, size_pt)
    measured = office_measure_width_pt(text, font_face, size_pt)
    if measured is None:
        return estimated
    # 实测若小于估算的 75%，视为折行/测宽失败，改用估算
    if estimated > 0 and measured < estimated * 0.75:
        return estimated
    return measured
