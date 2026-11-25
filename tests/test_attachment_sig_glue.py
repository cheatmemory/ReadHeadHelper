# -*- coding: utf-8 -*-
"""附件说明与发文机关署名粘连：无空行 / 模型拼 span 都应拆开。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "third_party" / "govdoc-sdk"))

from postprocess import (  # noqa: E402
    _peel_trailing_org_names,
    fill_attachment_caption,
    postprocess,
)

FOSHAN = """三、工作要求
重大情况及时报告市人民政府。
附件：1.电动自行车全链条安全监管责任分工表
2.重点任务清单
佛山市人民政府办公室、佛山市应急管理局
2026年4月18日
（此件主动公开）
"""


def test_peel_glued_org_keeps_att_title():
    assert _peel_trailing_org_names("重点任务清单佛山市人民政府办公室") == "重点任务清单"
    assert _peel_trailing_org_names(
        "重点任务清单 佛山市人民政府办公室 佛山市应急管理局"
    ) == "重点任务清单"


def test_foshan_no_blank_line_split():
    out = postprocess({}, FOSHAN)
    atts = [x["text"] for x in out.get("附件说明") or []]
    sig = "\n".join(x["text"] for x in out.get("发文机关署名") or [])
    assert atts == [
        "电动自行车全链条安全监管责任分工表",
        "重点任务清单",
    ]
    assert "人民政府办公室" in sig
    assert "应急管理局" in sig
    assert "清单" not in sig
    assert "办公室" not in "".join(atts)
    assert "应急" not in "".join(atts)


def test_foshan_model_glued_span():
    text = """附件：1.电动自行车全链条安全监管责任分工表
2.重点任务清单
佛山市人民政府办公室、佛山市应急管理局
2026年4月18日
"""
    raw = {
        "附件说明": [
            {
                "text": "电动自行车全链条安全监管责任分工表",
                "start": 3,
                "end": 21,
                "prob": 0.99,
            },
            {
                "text": "重点任务清单佛山市人民政府办公室",
                "start": 22,
                "end": 42,
                "prob": 1.0,
            },
            {"text": "佛山市应急管理局", "start": 42, "end": 50, "prob": 1.0},
        ],
        "发文机关署名": [
            {"text": "佛山市人民政府办公室", "prob": 1.0},
            {"text": "佛山市应急管理局", "prob": 1.0},
        ],
    }
    out = postprocess(raw, text)
    atts = [x["text"] for x in out.get("附件说明") or []]
    assert atts == [
        "电动自行车全链条安全监管责任分工表",
        "重点任务清单",
    ]


def test_fill_with_known_joint_sig_does_not_swallow():
    out = fill_attachment_caption(
        {
            "发文机关署名": [
                {"text": "佛山市人民政府办公室"},
                {"text": "佛山市应急管理局"},
            ]
        },
        FOSHAN,
    )
    atts = [x["text"] for x in out.get("附件说明") or []]
    assert atts == [
        "电动自行车全链条安全监管责任分工表",
        "重点任务清单",
    ]
