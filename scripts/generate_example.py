# -*- coding: utf-8 -*-
"""用 Mock fixture 生成 examples/out 示例 docx。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.ir.builder import build_layout_ir
from core.ir.schema import SealMode
from core.layout import DocxEngine
from core.recognize import MockFieldRecognizer


def main():
    text = (ROOT / "fixtures" / "sample_text" / "downlink.txt").read_text(encoding="utf-8")
    model = MockFieldRecognizer().recognize(text)
    ir = build_layout_ir(model, seal_mode=SealMode.NO_STAMP, source_text=text)
    out = ROOT / "examples" / "out" / "下行文_无章_示例.docx"
    DocxEngine().render(ir, out)
    print("wrote", out)

    ir2 = build_layout_ir(model, seal_mode=SealMode.STAMP, source_text=text)
    out2 = ROOT / "examples" / "out" / "下行文_有章_示例.docx"
    DocxEngine().render(ir2, out2)
    print("wrote", out2)


if __name__ == "__main__":
    main()
