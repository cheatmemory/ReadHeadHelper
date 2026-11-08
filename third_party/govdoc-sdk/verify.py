# -*- coding: utf-8 -*-
"""Self-check for the packaged SDK: model hash + end-to-end extraction.

Run:  python verify.py
Expected output ends with:  ALL CHECKS PASSED
"""
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EXPECTED_MD5 = "48deed668f7191fe79e3fee92e317d02"

def main():
    # 1) model file integrity
    path = os.path.join(HERE, "model.onnx")
    h = hashlib.md5(open(path, "rb").read()).hexdigest()
    print("model.onnx md5:", h)
    if h != EXPECTED_MD5:
        print("FAIL: model.onnx does NOT match the original trained model")
        return 1

    # 2) end-to-end extraction on the bundled sample
    sys.path.insert(0, os.path.join(HERE, "sdk"))
    from govdoc_sdk import GovDocExtractor
    ex = GovDocExtractor(path, os.path.join(HERE, "vocab.txt"))
    text = open(os.path.join(HERE, "example_text.txt"), encoding="utf-8").read().strip()
    r = ex.extract(text, ["发文字号", "标题", "成文日期"])

    def got(field):
        return [x["text"] for x in r.get(field, [])]

    checks = [
        ("发文字号", got("发文字号"), ["江府办发〔2024〕25号"]),
        ("成文日期", got("成文日期"), ["2024年4月20日"]),
    ]
    ok = True
    for name, actual, expect in checks:
        if actual != expect:
            ok = False
            print(f"FAIL {name}: got {actual}, expect {expect}")
        else:
            print(f"OK   {name}: {actual}")
    if not got("标题"):
        ok = False
        print("FAIL biaoti empty")
    else:
        print("OK   biaoti:", got("标题")[0][:20], "...")

    if ok:
        print("ALL CHECKS PASSED")
        return 0
    return 1

if __name__ == "__main__":
    sys.exit(main())
