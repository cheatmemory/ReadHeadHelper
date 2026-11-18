# -*- coding: utf-8 -*-
from pathlib import Path

import pytest

from core.body_structure.extract import extract_body_paragraphs
from core.body_structure.parser import parse_body_blocks
from core.config_loader import load_config, project_root
from core.ir.builder import model_to_partial_ir
from core.ir.schema import ModelOutput
from core.recognize.factory import create_recognizer

ROOT = Path(__file__).resolve().parents[1]


def _require_onnx():
    onnx = project_root() / "third_party" / "govdoc-sdk" / "model.onnx"
    if not onnx.is_file():
        pytest.skip("缺少 model.onnx，跳过 ONNX 端到端用例")


def test_jiangcheng_messy_structure():
    text = (ROOT / "fixtures" / "sample_text" / "jiangcheng_messy.txt").read_text(encoding="utf-8")
    paras = extract_body_paragraphs(
        text,
        title="江城市人民政府办公室关于印发《江城市全面推行涉企行政执法“综合查一次”实施方案》的通知",
        recipient="各县（市、区）人民政府，市直各委、办、局，各直属事业单位",
        date="2024年4月20日",
        org_signature="江城市人民政府办公室",
    )
    assert len(paras) > 5
    assert max(len(p) for p in paras) < len(text) * 0.9

    tree = parse_body_blocks(paras)
    levels = [b.level for b in tree]
    assert "h1" in levels
    assert "h2" in levels
    assert "h3" in levels
    texts = "\n".join(b.text for b in tree)
    assert "一、总体目标" in texts
    assert "二、重点任务" in texts


def test_jiangcheng_with_onnx_offsets():
    """端到端：模型偏移锚定 + 脏样本不应整篇一段。"""
    _require_onnx()
    text = (ROOT / "fixtures" / "sample_text" / "jiangcheng_messy.txt").read_text(encoding="utf-8")
    rec, name = create_recognizer(load_config(), project_root())
    model = rec.recognize(text)
    assert len(model.main.body_blocks) > 5
    ir = model_to_partial_ir(model, source_text=text)
    levels = {b.level for b in ir.body_tree}
    assert "h1" in levels and "h2" in levels
    # 文末印发机关不应把正文起点带跑
    assert not ir.body_tree[0].text.startswith("江府办发")


def test_recipient_colon_not_orphan_body_line():
    """模型主送 end 不含冒号时，正文不得以单独「：」起头。"""
    text = (
        "澄江县人民政府文件\n"
        "澄江县人民政府关于请求批准设立临港产业园的请示\n"
        "云岭市人民政府：\n"
        "为承接产业转移，培育新的经济增长点，我县拟在临港片区设立省级产业园。"
        "现将有关情况请示如下：\n"
        "一、选址范围\n"
        "园区规划面积3.6平方公里。\n"
        "澄江县人民政府\n"
        "2024年5月10日\n"
    )
    title = "澄江县人民政府关于请求批准设立临港产业园的请示"
    recip_core = "云岭市人民政府"
    t0 = text.index(title)
    r0 = text.index(recip_core)
    sdk = {
        "标题": [{"text": title, "start": t0, "end": t0 + len(title), "probability": 0.99}],
        "主送机关": [
            {
                "text": recip_core,
                "start": r0,
                "end": r0 + len(recip_core),  # 故意不含冒号
                "probability": 0.99,
            }
        ],
        "发文机关署名": [
            {
                "text": "澄江县人民政府",
                "start": text.rindex("澄江县人民政府"),
                "end": text.rindex("澄江县人民政府") + len("澄江县人民政府"),
                "probability": 0.99,
            }
        ],
        "成文日期": [
            {
                "text": "2024年5月10日",
                "start": text.index("2024年5月10日"),
                "end": text.index("2024年5月10日") + len("2024年5月10日"),
                "probability": 0.99,
            }
        ],
    }
    paras = extract_body_paragraphs(
        text,
        title=title,
        recipient=recip_core,
        date="2024年5月10日",
        org_signature="澄江县人民政府",
        sdk_result=sdk,
    )
    assert paras
    assert paras[0] not in ("：", ":")
    assert not paras[0].startswith("：")
    assert "为承接产业转移" in paras[0]


def test_glued_header_body_keeps_body_span():
    """主送与正文粘同一行时，仍应切出正文主体，而非只剩落款前一行或整篇。"""
    text = (ROOT / "fixtures" / "sample_text" / "lanshi_glued.txt").read_text(encoding="utf-8")
    paras = extract_body_paragraphs(
        text,
        title="岚州市人民政府关于加强城市生活垃圾分类管理工作的通知",
        recipient="各县（市、区）人民政府，市政府各部门：",
        date="2026年3月12日",
        org_signature="岚州市人民政府",
    )
    joined = "\n".join(paras)
    assert "为深入贯彻" in joined
    assert "保障措施" in joined or "市城管局" in joined
    assert "000037" not in joined
    assert "岚政发" not in joined
    assert "附件" not in joined
    assert "抄送" not in joined
    assert "印发" not in joined
    # 不应只剩最后一句
    assert len(joined) > 80
    assert not joined.startswith("市城管局")


def test_minutes_body_strips_secret_mark_and_list():
    """纪要：正文不得含密级/标志/主送短行/出席名单；日期叙事句不能截断正文窗。"""
    text = (
        "机密★10年\n"
        "临汾市自然资源和规划局工作会议纪要\n"
        "局属各单位：\n"
        "2025年11月25日下午，局长曹文静主持召开工作会议，研究食品安全监管工作。\n"
        "一、会议调度了食品安全监管进展情况。会议原则同意，要求进一步核实数据。\n"
        "二、会议研究了食品安全监管有关问题。会议要求建立台账。\n"
        "出席：崔美玲（局长）、韦雅琴（副局长）\n"
        "请假：毛雅琴（办公室主任）\n"
        "列席：尹建华（局长）\n"
        "2025年11月25日\n"
        "（此件发至县团级）\n"
        "临汾市自然资源和规划局 2025年11月27日印发\n"
    )
    mark = "临汾市自然资源和规划局工作会议纪要"
    paras = extract_body_paragraphs(
        text,
        date="2025年11月25日",
        org_mark=mark,
    )
    joined = "\n".join(paras)
    assert paras
    assert "2025年11月25日下午" in paras[0]
    assert "一、会议调度" in joined
    assert "机密" not in joined
    assert mark not in joined
    assert "局属各单位" not in joined
    assert "出席" not in joined
    assert "印发" not in joined

    # body_blocks 为空时 builder 也不得整篇回灌
    model = ModelOutput.from_dict(
        {
            "header": {
                "org_mark": mark,
                "secret_level": "机密",
                "secret_period": "10年",
            },
            "main": {"title": "", "recipient": "局属各单位", "body_blocks": []},
            "footer": {"date": "2025年11月25日"},
        }
    )
    ir = model_to_partial_ir(model, source_text=text)
    body = "\n".join(b.text for b in ir.body_tree)
    assert "机密" not in body
    assert mark not in body
    assert "局属各单位" not in body
    assert "出席" not in body
    assert "一、会议调度" in body


def test_footer_org_does_not_steal_start():
    """文末重复出现机关名时，起点仍应在文首主送之后。"""
    text = (
        "××市人民政府文件\n"
        "关于测试的通知\n"
        "各有关单位：\n"
        "一、第一条\n"
        "内容甲。\n"
        "二、第二条\n"
        "内容乙。\n"
        "附件：清单\n"
        "××市人民政府\n"
        "2024年1月1日\n"
        "××市人民政府办公室 2024年1月2日印发\n"
    )
    # 故意构造「标题/机关」也在文末出现的 sdk_result
    title = "关于测试的通知"
    t0 = text.index(title)
    recip = "各有关单位："
    r0 = text.index(recip)
    sdk = {
        "标题": [{"text": title, "start": t0, "end": t0 + len(title), "probability": 0.99}],
        "主送机关": [{"text": recip, "start": r0, "end": r0 + len(recip), "probability": 0.99}],
        "发文机关署名": [
            {
                "text": "××市人民政府",
                "start": text.rindex("××市人民政府"),
                "end": text.rindex("××市人民政府") + len("××市人民政府"),
                "probability": 0.99,
            }
        ],
        "成文日期": [
            {
                "text": "2024年1月1日",
                "start": text.index("2024年1月1日"),
                "end": text.index("2024年1月1日") + len("2024年1月1日"),
                "probability": 0.99,
            }
        ],
        "印发机关": [
            {
                "text": "××市人民政府办公室",
                "start": text.index("××市人民政府办公室"),
                "end": text.index("××市人民政府办公室") + len("××市人民政府办公室"),
                "probability": 0.99,
            }
        ],
    }
    paras = extract_body_paragraphs(
        text,
        title=title,
        recipient=recip,
        date="2024年1月1日",
        org_signature="××市人民政府",
        sdk_result=sdk,
    )
    joined = "\n".join(paras)
    assert "一、第一条" in joined
    assert "印发" not in joined
    assert not joined.startswith("××市人民政府文件")
