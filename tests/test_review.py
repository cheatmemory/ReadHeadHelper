# -*- coding: utf-8 -*-
from core.recognize.review import review_and_correct


def test_fix_print_org_truncated():
    text = (
        "××市人民政府文件\n"
        "关于测试的通知\n"
        "各区县人民政府，市政府各部门：\n"
        "现将有关事项通知如下。\n"
        "××市人民政府\n"
        "2024年3月15日\n"
        "××市人民政府办公室　　2024年3月16日印发\n"
    )
    raw = {
        "标题": [{"text": "关于测试的通知", "prob": 0.9}],
        "主送机关": [{"text": "各区县人民政府，市政府各部门", "prob": 0.9}],
        "印发机关": [{"text": "人民政府办公室", "prob": 0.8}],
        "印发日期": [{"text": "2024年3月16日", "prob": 0.8}],
    }
    out = review_and_correct(raw, text)
    assert out["印发机关"][0]["text"] == "××市人民政府办公室"
    assert "印发机关" in " ".join(out.get("_review_notes") or [])


def test_fix_recipient_from_source_when_model_wrong():
    text = (
        "关于做好某某工作的通知\n"
        "各县（市、区）人民政府，市政府各部门：\n"
        "为进一步推进工作，现通知如下。\n"
        "××县人民政府办公室 2026年1月1日印发\n"
    )
    raw = {
        "标题": [{"text": "关于做好某某工作的通知"}],
        "主送机关": [{"text": "各县", "prob": 0.5}],
        "印发机关": [{"text": "人民政府办公室"}],
    }
    out = review_and_correct(raw, text)
    assert out["主送机关"][0]["text"] == "各县（市、区）人民政府，市政府各部门"
    assert out["印发机关"][0]["text"] == "××县人民政府办公室"
    # 偏移应覆盖到冒号，便于正文切片跳过主送行
    assert out["主送机关"][0]["end"] > out["主送机关"][0]["start"]
    span = text[out["主送机关"][0]["start"] : out["主送机关"][0]["end"]]
    assert "：" in span or span.endswith("门")


def test_review_keeps_good_values():
    text = (
        "关于测试的通知\n"
        "各有关单位：\n"
        "内容。\n"
        "××市人民政府办公室 2024年1月2日印发\n"
    )
    raw = {
        "标题": [{"text": "关于测试的通知"}],
        "主送机关": [{"text": "各有关单位"}],
        "印发机关": [{"text": "××市人民政府办公室"}],
        "印发日期": [{"text": "2024年1月2日"}],
    }
    out = review_and_correct(raw, text)
    assert out["主送机关"][0]["text"] == "各有关单位"
    assert out["印发机关"][0]["text"] == "××市人民政府办公室"
    assert out.get("_review_notes") == []
