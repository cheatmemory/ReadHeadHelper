# -*- coding: utf-8 -*-
"""Minimal integration example for govdoc-sdk.

Run:  python example.py
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

from sdk.govdoc_sdk import GovDocExtractor
from postprocess import postprocess

SCHEMA = ["份号", "密级", "保密期限", "紧急程度", "发文机关标志", "发文字号",
          "标题", "主送机关", "附件说明", "发文机关署名", "成文日期",
          "附注", "抄送机关", "印发机关", "印发日期"]

ex = GovDocExtractor(
    onnx_path=os.path.join(HERE, "model.onnx"),
    vocab_path=os.path.join(HERE, "vocab.txt"),
)

text = open(os.path.join(HERE, "example_text.txt"), encoding="utf-8").read().strip()

result = ex.extract(text, SCHEMA)
result = postprocess(result, text)  # regex fallback: 份号 + 附件说明

print(json.dumps(result, ensure_ascii=False, indent=2))
