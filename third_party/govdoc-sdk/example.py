# -*- coding: utf-8 -*-
"""Minimal integration example for govdoc-sdk.

Run:  python example.py                 # 跑三个样例：通用公文 / 命令 / 信函
      python example.py mydoc.txt       # 跑自己的公文

流程三步：判文种 -> 取该文种字段表 -> 抽字段 + 后处理。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

from sdk.govdoc_sdk import GovDocExtractor
from postprocess import postprocess
import doc_kind

SAMPLES = ["example_text.txt", "example_order.txt", "example_letter.txt"]


def main(paths):
    ex = GovDocExtractor(
        onnx_path=os.path.join(HERE, "model.onnx"),
        vocab_path=os.path.join(HERE, "vocab.txt"),
    )
    for rel in paths:
        if not os.path.isabs(rel):
            rel = os.path.join(HERE, rel)
        text = open(rel, encoding="utf-8").read().strip()

        kind = doc_kind.detect(text)                  # 1) 判文种
        schema = doc_kind.schema_for(kind)            # 2) 取字段表
        result = ex.extract(text, schema)             # 3) 只问该文种的字段
        result = postprocess(result, text)            #    校验 + 规则兜底

        print("=" * 70)
        print("文件：%s" % os.path.basename(rel))
        print("文种：%s    字段数：%d" % (kind, len(schema)))
        print("=" * 70)
        for field in schema:
            values = [x["text"].replace("\n", "") for x in result.get(field, [])]
            print("%-8s %s" % (field, json.dumps(values, ensure_ascii=False)))
        print()


if __name__ == "__main__":
    main(sys.argv[1:] or SAMPLES)
