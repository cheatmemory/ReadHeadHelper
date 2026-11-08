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
    """Word/WPS 光标位移测宽（pt）。失败返回 None。"""
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
        doc.Range(0, 0).InsertAfter(t)
        rng = doc.Range(0, len(t))
        rng.Font.NameFarEast = font_face
        try:
            rng.Font.NameAscii = font_face
        except Exception:
            pass
        rng.Font.Size = float(size_pt)
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
    """落款用宽度：优先 Word/WPS 实测，否则估算。"""
    measured = office_measure_width_pt(text, font_face, size_pt)
    if measured is not None:
        return measured
    return estimate_layout_width_pt(text, size_pt)
