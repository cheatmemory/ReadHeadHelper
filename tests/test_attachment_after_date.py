# -*- coding: utf-8 -*-
"""成文日期之后的「附件：」仍应被后处理抽出。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "third_party" / "govdoc-sdk"))

from postprocess import fill_attachment_caption, postprocess  # noqa: E402


SAMPLE = """教育部文件
教发〔2026〕8号
教育部关于推进高等教育教学质量提升工作的通知
各省、自治区、直辖市教育厅（教委）：
现就有关事项通知如下。
一、总体要求
坚持社会主义办学方向。
教育部
2026年2月20日
附件：高等教育教学质量提升工作重点任务清单
抄送：国务院办公厅。
教育部办公厅 2026年2月21日印发
"""


def test_attachment_after_date_fill():
    raw = {
        "发文机关署名": [{"text": "教育部", "prob": 1.0}],
        "成文日期": [{"text": "2026年2月20日", "prob": 1.0}],
    }
    out = fill_attachment_caption(raw, SAMPLE)
    texts = [x["text"] for x in out.get("附件说明") or []]
    assert any("重点任务清单" in t for t in texts)


def test_attachment_after_date_postprocess():
    out = postprocess({}, SAMPLE)
    texts = [x["text"] for x in out.get("附件说明") or []]
    assert any("重点任务清单" in t for t in texts)
