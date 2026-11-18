# -*- coding: utf-8 -*-
"""用 fixtures 样例 JSON 生成 examples/out 示例 docx（不经过识别器）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.ir.builder import build_layout_ir
from core.ir.schema import ModelOutput, SealMode
from core.layout import DocxEngine


def _load_model() -> tuple[ModelOutput, str]:
    text = (ROOT / "fixtures" / "sample_text" / "downlink.txt").read_text(encoding="utf-8")
    data = json.loads(
        (ROOT / "fixtures" / "mock_json" / "downlink_stamp.json").read_text(encoding="utf-8")
    )
    return ModelOutput.from_dict(data), text


def main():
    model, text = _load_model()
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
