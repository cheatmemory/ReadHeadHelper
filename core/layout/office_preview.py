# -*- coding: utf-8 -*-
"""本机 Word/WPS 将 docx 渲成预览页图（接近一比一）。"""
from __future__ import annotations

import base64
import tempfile
from pathlib import Path


def _export_docx_to_pdf(docx_path: Path, pdf_path: Path) -> str:
    """返回使用的引擎名：wps / word。失败抛异常。"""
    import pythoncom  # type: ignore
    import win32com.client  # type: ignore

    pythoncom.CoInitialize()
    app = None
    doc = None
    engine = ""
    try:
        last_err: Exception | None = None
        for prog, name in (
            ("Kwps.Application", "wps"),
            ("wps.Application", "wps"),
            ("Word.Application", "word"),
        ):
            try:
                app = win32com.client.Dispatch(prog)
                app.Visible = False
                try:
                    app.DisplayAlerts = 0
                except Exception:
                    pass
                engine = name
                break
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                app = None
        if app is None:
            raise RuntimeError(f"未找到 WPS/Word（{last_err}）")

        doc = app.Documents.Open(str(docx_path), ReadOnly=True)
        # wdExportFormatPDF = 17；Range=0 导出全文
        doc.ExportAsFixedFormat(
            OutputFileName=str(pdf_path),
            ExportFormat=17,
            OpenAfterExport=False,
            OptimizeFor=0,
            Range=0,
            Item=0,
            IncludeDocProps=False,
            KeepIRM=True,
            CreateBookmarks=0,
            DocStructureTags=True,
            BitmapMissingFonts=True,
            UseISO19005_1=False,
        )
        return engine
    finally:
        if doc is not None:
            try:
                doc.Close(False)
            except Exception:
                pass
        if app is not None:
            try:
                app.Quit()
            except Exception:
                pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


def _pdf_to_png_data_urls(pdf_path: Path, *, max_pages: int = 3, zoom: float = 1.5) -> list[str]:
    import pymupdf  # type: ignore

    pages: list[str] = []
    doc = pymupdf.open(str(pdf_path))
    try:
        n = min(len(doc), max(1, max_pages))
        mat = pymupdf.Matrix(zoom, zoom)
        for i in range(n):
            pix = doc[i].get_pixmap(matrix=mat, alpha=False)
            png = pix.tobytes("png")
            pages.append("data:image/png;base64," + base64.b64encode(png).decode("ascii"))
    finally:
        doc.close()
    return pages


def render_docx_preview(
    docx_path: str | Path,
    *,
    max_pages: int = 3,
    zoom: float = 1.5,
) -> dict:
    """
    docx →（WPS/Word）PDF →（PyMuPDF）PNG data URL。

    返回 {"ok": True, "engine": "wps"|"word", "pages": [...], "page_count": N}
    或 {"ok": False, "error": "..."}。
    """
    src = Path(docx_path)
    if not src.is_file():
        return {"ok": False, "error": f"找不到文件：{src}"}

    tmp_dir = Path(tempfile.mkdtemp(prefix="govdoc_preview_"))
    pdf_path = tmp_dir / (src.stem + ".pdf")
    try:
        engine = _export_docx_to_pdf(src, pdf_path)
        if not pdf_path.is_file() or pdf_path.stat().st_size < 64:
            return {"ok": False, "error": "Office 导出 PDF 失败"}
        pages = _pdf_to_png_data_urls(pdf_path, max_pages=max_pages, zoom=zoom)
        if not pages:
            return {"ok": False, "error": "PDF 未生成预览页"}
        return {
            "ok": True,
            "engine": engine,
            "pages": pages,
            "page_count": len(pages),
        }
    except ImportError as exc:
        return {"ok": False, "error": f"缺少预览依赖：{exc}（请安装 pymupdf / pywin32）"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    finally:
        for p in tmp_dir.glob("*"):
            try:
                p.unlink()
            except OSError:
                pass
        try:
            tmp_dir.rmdir()
        except OSError:
            pass
