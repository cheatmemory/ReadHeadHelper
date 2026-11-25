# -*- coding: utf-8 -*-
"""命令无换行 / 少换行：文种判定 + 字段兜底 + 软换行。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "third_party" / "govdoc-sdk"))

import doc_kind  # noqa: E402
from postprocess import fill_order_fields, postprocess  # noqa: E402

NO_NL = (
    "中华人民共和国主席令 第九号 《中华人民共和国生活垃圾分类管理办法》"
    "已经中华人民共和国第13届全国人民代表大会常务委员会第16次会议通过，"
    "现予公布，自2027年2月4日起施行。各地各部门要认真贯彻执行，确保各项任务落到实处。"
    " 中华人民共和国主席：陈德胜 二〇二六年七月二十四日"
)

WITH_NL = """中华人民共和国主席令
第九号

《中华人民共和国生活垃圾分类管理办法》已经中华人民共和国第13届全国人民代表大会常务委员会第16次会议通过，现予公布，自2027年2月4日起施行。各地各部门要认真贯彻执行，确保各项任务落到实处。

中华人民共和国主席：陈德胜
二〇二六年七月二十四日
"""


def test_detect_order_without_newlines():
    assert doc_kind.detect(NO_NL) == doc_kind.KIND_ORDER
    assert doc_kind.detect(WITH_NL) == doc_kind.KIND_ORDER


def test_soften_inserts_breaks():
    soft = doc_kind.soften_layout_breaks(NO_NL)
    assert soft.count("\n") >= 3
    assert "主席令" in soft.split("\n")[0]
    assert any("第九号" in ln or "第 九 号" in ln for ln in soft.split("\n"))
    # 已有换行的不折腾
    assert doc_kind.soften_layout_breaks(WITH_NL) == WITH_NL


def test_fill_order_fields_no_nl():
    soft = doc_kind.soften_layout_breaks(NO_NL)
    out = postprocess({}, soft)
    assert (out.get("发文机关标志") or [{}])[0].get("text", "").endswith("令")
    assert "九" in ((out.get("令号") or [{}])[0].get("text") or "")
    assert "主席" in ((out.get("签署职务") or [{}])[0].get("text") or "")
    assert ((out.get("签署姓名") or [{}])[0].get("text") or "") == "陈德胜"
    assert "二〇二六" in ((out.get("成文日期") or [{}])[0].get("text") or "")


def test_fill_order_does_not_invent_on_notice():
    notice = "岚州市人民政府文件\n岚政发〔2026〕1号\n关于做好某项工作的通知\n各县区：\n现通知如下。\n岚州市人民政府\n2026年1月1日\n"
    out = fill_order_fields({}, notice)
    assert not out.get("令号")
    assert not out.get("签署职务")
