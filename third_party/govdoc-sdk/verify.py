# -*- coding: utf-8 -*-
"""Self-check for the packaged SDK: model hash, doc-kind routing, end-to-end extraction.

Run:  python verify.py
Expected output ends with:  ALL CHECKS PASSED

Three samples are checked, one per doc kind:
  example_text.txt    通用公文 -> COMMON_FIELDS  (16)
  example_order.txt   命令     -> ORDER_FIELDS   (10)
  example_letter.txt  信函     -> LETTER_FIELDS  (13)
"""
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EXPECTED_MD5 = "0dbf791e0bf0e276621335b3410a4063"

FAILS = []


def check(name, actual, expect):
    if actual != expect:
        FAILS.append(name)
        print("FAIL %s: got %r, expect %r" % (name, actual, expect))
    else:
        print("OK   %s: %r" % (name, actual))


def main():
    # 1) model file integrity
    path = os.path.join(HERE, "model.onnx")
    h = hashlib.md5(open(path, "rb").read()).hexdigest()
    print("model.onnx md5:", h, "(%.1f MB)" % (os.path.getsize(path) / 1048576.0))
    if h != EXPECTED_MD5:
        print("FAIL: model.onnx does NOT match the original trained model")
        return 1

    # 2) imports
    sys.path.insert(0, os.path.join(HERE, "sdk"))
    sys.path.insert(0, HERE)
    from govdoc_sdk import GovDocExtractor
    from postprocess import postprocess
    import doc_kind

    ex = GovDocExtractor(path, os.path.join(HERE, "vocab.txt"))

    samples = [
        ("example_text.txt", doc_kind.KIND_GENERAL),
        ("example_order.txt", doc_kind.KIND_ORDER),
        ("example_letter.txt", doc_kind.KIND_LETTER),
    ]

    # 3) doc-kind routing
    for fname, want_kind in samples:
        text = open(os.path.join(HERE, fname), encoding="utf-8").read().strip()
        got_kind = doc_kind.detect(text)
        check("doc_kind.detect(%s)" % fname, got_kind, want_kind)
        check("schema_for(%s) 字段数" % want_kind, len(doc_kind.schema_for(got_kind)),
              len(doc_kind.schema_for(want_kind)))

    # 4) end-to-end extraction per doc kind
    def run(fname):
        text = open(os.path.join(HERE, fname), encoding="utf-8").read().strip()
        schema = doc_kind.schema_for(doc_kind.detect(text))
        return postprocess(ex.extract(text, schema), text)

    def got(r, field):
        return [x["text"] for x in r.get(field, [])]

    # 4a) 通用公文
    r = run("example_text.txt")
    check("通用·发文字号", got(r, "发文字号"), ["江府办发〔2024〕25号"])
    check("通用·成文日期", got(r, "成文日期"), ["2024年4月20日"])
    check("通用·标题非空", bool(got(r, "标题")), True)

    # 4b) 命令（令）：令号 + 签署职务/签署姓名 是命令专有字段
    r = run("example_order.txt")
    check("命令·令号", got(r, "令号"), ["第九号"])
    check("命令·签署职务", got(r, "签署职务"), ["中华人民共和国主席"])
    check("命令·签署姓名", got(r, "签署姓名"), ["林海涛"])
    check("命令·印发机关", got(r, "印发机关"), ["全国人大常委会办公厅"])

    # 4c) 信函：无印发机关/印发日期，附件说明带值
    r = run("example_letter.txt")
    check("信函·发文字号", got(r, "发文字号"), ["粤办函〔2026〕253号"])
    check("信函·主送机关", got(r, "主送机关"),
          ["广州市人民政府，省公安厅、交通运输厅、农业农村厅"])
    check("信函·附件说明非空", bool(got(r, "附件说明")), True)
    check("信函·无印发机关字段", "印发机关" in doc_kind.LETTER_FIELDS, False)

    if FAILS:
        print("FAILED CHECKS: %d -> %s" % (len(FAILS), ", ".join(FAILS)))
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
