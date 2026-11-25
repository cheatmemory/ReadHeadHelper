# -*- coding: utf-8 -*-
"""版头机关与落款同名时，署名不得抽成两条。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "third_party" / "govdoc-sdk"))

from postprocess import postprocess  # noqa: E402

LETTER = """002145
特急

金华市文化广电旅游局

金文旅函〔2026〕58号

关于商请协助做好非物质文化遗产普查工作的函

金华市财政局：

为高质量完成全市非物质文化遗产资源普查工作，商请你单位协助。

金华市文化广电旅游局
2026年4月28日

（联系人：方惠芳；联系电话：0579-82468136）
"""


def test_letter_same_mark_and_sig_not_duplicated():
    # 模拟模型：版头 + 落款各抽一条同名署名
    raw = {
        "发文机关标志": [{"text": "金华市文化广电旅游局", "start": 11, "end": 21, "prob": 0.9}],
        "发文字号": [{"text": "金文旅函〔2026〕58号", "start": 23, "end": 38, "prob": 0.9}],
        "标题": [
            {
                "text": "关于商请协助做好非物质文化遗产普查工作的函",
                "start": 40,
                "end": 62,
                "prob": 0.9,
            }
        ],
        "发文机关署名": [
            {"text": "金华市文化广电旅游局", "start": 11, "end": 21, "probability": 0.3},
            {"text": "金华市文化广电旅游局", "start": 120, "end": 130, "probability": 0.4},
        ],
        "成文日期": [{"text": "2026年4月28日", "prob": 1.0}],
    }
    out = postprocess(raw, LETTER)
    sigs = [x["text"] for x in out.get("发文机关署名") or []]
    assert sigs == ["金华市文化广电旅游局"]
    mark = (out.get("发文机关标志") or [{}])[0].get("text") or ""
    assert mark == "金华市文化广电旅游局"
    assert "文件" not in mark
