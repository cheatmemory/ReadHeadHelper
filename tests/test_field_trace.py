# -*- coding: utf-8 -*-
from core.body_structure.extract import extract_body_with_trace
from core.recognize.trace import SOURCE_LABELS, build_field_trace


def test_build_field_trace_sources_and_confidence():
    final = {
        "标题": [{"text": "关于加强XX的通知", "start": 10, "end": 20, "probability": 0.97}],
        "成文日期": [{"text": "2026年1月1日", "start": 100, "end": 110, "prob": 1.0, "source": "regex"}],
        "主送机关": [
            {
                "text": "各区县人民政府",
                "start": 30,
                "end": 38,
                "prob": 1.0,
                "source": "review:recipient",
            }
        ],
        "出席": [
            {"text": "张三（市长）", "start": 200, "end": 207, "probability": 0.88},
            {"text": "李四（副市长）", "start": 208, "end": 216, "source": "regex", "prob": 1.0},
        ],
    }
    trace = build_field_trace(final)
    fields = trace["fields"]

    title = fields["f-title"]["spans"][0]
    assert title["source"] == "model"
    assert title["source_label"] == SOURCE_LABELS["model"]
    assert title["confidence"] == 0.97

    date = fields["f-date"]["spans"][0]
    assert date["source"] == "postprocess"
    assert date["source_label"] == SOURCE_LABELS["postprocess"]
    assert date["confidence"] is None

    recip = fields["f-to"]["spans"][0]
    assert recip["source"] == "review"
    assert recip["confidence"] is None
    assert recip["reason"] == "recipient"

    att = fields["f-attendance"]["spans"]
    assert len(att) == 2
    assert att[0]["source"] == "model" and att[0]["confidence"] == 0.88
    assert att[1]["source"] == "postprocess" and att[1]["confidence"] is None


def test_build_field_trace_order_fields():
    """命令新字段：令号 / 签署职务 / 签署姓名 进开发者溯源。"""
    final = {
        "令号": [{"text": "第7号", "start": 12, "end": 15, "probability": 0.991}],
        "签署职务": [
            {"text": "区长", "start": 400, "end": 402, "probability": 0.95},
            {"text": "市长", "start": 410, "end": 412, "probability": 0.94},
        ],
        "签署姓名": [{"text": "张三", "start": 403, "end": 405, "probability": 0.9}],
    }
    fields = build_field_trace(final)["fields"]
    order = fields["f-order"]["spans"][0]
    assert order["source"] == "model"
    assert order["confidence"] == 0.991
    assert order["text"] == "第7号"

    titles = fields["f-order-titles"]["spans"]
    assert len(titles) == 3  # 两职务 + 一姓名
    assert titles[0]["field_cn"] == "签署职务" and titles[0]["confidence"] == 0.95
    assert titles[1]["text"] == "市长"
    assert any(sp["field_cn"] == "签署姓名" and sp["text"] == "张三" for sp in titles)


def test_body_with_trace_reports_window():
    text = (
        "某某市人民政府文件\n"
        "某某〔2026〕1号\n"
        "关于测试的通知\n"
        "各单位：\n"
        "现将有关事项通知如下。\n"
        "一、第一条。\n"
        "附件：清单\n"
        "某某市人民政府\n"
        "2026年1月2日\n"
    )
    sdk = {
        "标题": [{"text": "关于测试的通知", "start": text.find("关于测试的通知"), "end": text.find("关于测试的通知") + len("关于测试的通知"), "probability": 0.9}],
        "主送机关": [{"text": "各单位", "start": text.find("各单位"), "end": text.find("各单位") + 3, "probability": 0.9}],
        "附件说明": [{"text": "清单", "start": text.find("清单"), "end": text.find("清单") + 2, "probability": 0.5}],
    }
    paras, diag = extract_body_with_trace(
        text,
        title="关于测试的通知",
        recipient="各单位：",
        sdk_result=sdk,
    )
    assert paras
    assert diag["start"] < diag["end"]
    assert diag["start_rule"]
    assert diag["end_rule"]
    assert "start_label" in diag and "end_label" in diag
