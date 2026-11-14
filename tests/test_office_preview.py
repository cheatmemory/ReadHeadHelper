# -*- coding: utf-8 -*-
"""Office 预览：有 WPS/Word 时能渲出页图；无则优雅失败。"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.ir.schema import BodyBlock, LayoutIR, SealMode
from core.layout.engine import DocxEngine
from core.layout.office_preview import render_docx_preview


def _sample_ir() -> LayoutIR:
    return LayoutIR(
        org_marks=["××市人民政府"],
        doc_number="×政发〔2024〕1号",
        title="关于测试预览的通知",
        recipient="各有关单位：",
        body_tree=[BodyBlock(level="p", text="现就有关事项通知如下。")],
        org_signature="××市人民政府",
        date="2024年1月1日",
        print_org="××市人民政府办公室",
        print_date="2024年1月2日",
        seal_mode=SealMode.NO_STAMP,
    )


def test_render_docx_preview_smoke(tmp_path: Path):
    docx = tmp_path / "preview.docx"
    DocxEngine().render(_sample_ir(), docx)
    assert docx.is_file()

    out = render_docx_preview(docx, max_pages=1, zoom=1.2)
    assert "ok" in out
    if out["ok"]:
        assert out["pages"]
        assert out["pages"][0].startswith("data:image/png;base64,")
        assert out.get("engine") in {"wps", "word"}
    else:
        # 无 Office / 环境限制时允许失败，但错误信息应可读
        assert out.get("error")
        pytest.skip("本机无可用 WPS/Word 预览：" + str(out.get("error")))
