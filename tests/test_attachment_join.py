# -*- coding: utf-8 -*-
from core.recognize.onnx_recognizer import _join_attachment_captions


def test_join_two_attachment_items():
    raw = {
        "附件说明": [
            {"text": "岚州市生活垃圾分类设施改造清单", "prob": 1.0, "source": "regex"},
            {"text": "岚州市垃圾分类责任单位分工表", "prob": 1.0, "source": "regex"},
        ]
    }
    got = _join_attachment_captions(raw)
    assert "1.岚州市生活垃圾分类设施改造清单" in got
    assert "2.岚州市垃圾分类责任单位分工表" in got
    assert got.count("\n") == 1


def test_join_keeps_existing_numbers():
    raw = {
        "附件说明": [
            {"text": "1.清单甲", "prob": 1.0},
            {"text": "2.清单乙", "prob": 1.0},
        ]
    }
    assert _join_attachment_captions(raw) == "1.清单甲\n2.清单乙"
