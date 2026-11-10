# -*- coding: utf-8 -*-
"""乱换行 + 附件粘署名 不得卡死识别。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "third_party" / "govdoc-sdk"))

from postprocess import fill_attachment_caption, postprocess  # noqa: E402


MESSY = (ROOT / "fixtures" / "sample_text" / "lanshi_messy_break.txt").read_text(
    encoding="utf-8"
)


def test_attachment_glued_signature_no_hang():
    raw = {
        "发文机关署名": [{"text": "岚州市人民政府", "prob": 1.0}],
        "成文日期": [{"text": "2026年3月12日", "prob": 1.0}],
    }
    out = fill_attachment_caption(raw, MESSY)
    texts = [x["text"] for x in out.get("附件说明") or []]
    assert texts, "应抽出附件说明"
    joined = "".join(texts)
    assert "设施改造清单" in joined
    assert "责任单位分工表" in joined
    assert "人民政府" not in joined  # 署名不应并入附件


def test_postprocess_messy_no_hang():
    out = postprocess({}, MESSY)
    assert isinstance(out, dict)
