# -*- coding: utf-8 -*-
import re
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


def test_order_leadin_not_stripped_as_recipient():
    """命令正文起句「经研究决定：」不得被当成主送短行丢掉。"""
    text = (
        "兰州市人民政府令\n"
        "第65号\n"
        "\n"
        "　　根据工作需要，经研究决定：\n"
        "　　任命谭惠芳为兰州市自然资源和规划局局长；\n"
        "　　任命郝思齐为兰州市民政局局长；\n"
        "\n"
        "市长　　钟丽萍\n"
        "2026年12月21日\n"
    )
    sdk = {
        "发文机关标志": [{"text": "兰州市人民政府令", "start": 0, "end": 8, "probability": 0.99}],
        "令号": [{"text": "第65号", "start": text.index("第65号"), "end": text.index("第65号") + 4, "probability": 0.99}],
        "签署职务": [{"text": "市长", "start": text.index("市长"), "end": text.index("市长") + 2, "probability": 0.99}],
        "成文日期": [
            {
                "text": "2026年12月21日",
                "start": text.index("2026年12月21日"),
                "end": text.index("2026年12月21日") + len("2026年12月21日"),
                "probability": 0.99,
            }
        ],
    }
    paras = extract_body_paragraphs(
        text, org_mark="兰州市人民政府令", date="2026年12月21日", sdk_result=sdk
    )
    joined = "\n".join(paras)
    assert "根据工作需要，经研究决定" in joined
    assert "任命谭惠芳" in joined
    assert "市长" not in joined


def test_letter_leadin_not_stripped_as_recipient():
    """信函导语「……协助做好以下工作：」不得被当成主送丢掉。"""
    text = (
        "云南省市场监督管理局\n"
        "滇市监函〔2026〕85号\n"
        "关于商请协助做好生物医药产业发展工作的函\n"
        "云南省生态环境局：\n"
        "　　为统筹推进生物医药产业发展工作，形成工作合力，商请你单位协助做好以下工作：\n"
        "　　一、安排专人负责对接联络。\n"
        "　　二、做好数据汇总。\n"
        "云南省市场监督管理局\n"
        "2026年4月1日\n"
    )
    recip = "云南省生态环境局"
    title = "关于商请协助做好生物医药产业发展工作的函"
    sdk = {
        "标题": [{"text": title, "start": text.index(title), "end": text.index(title) + len(title)}],
        "主送机关": [
            {"text": recip, "start": text.index(recip), "end": text.index(recip) + len(recip)}
        ],
        "发文机关署名": [
            {
                "text": "云南省市场监督管理局",
                "start": text.rindex("云南省市场监督管理局"),
                "end": text.rindex("云南省市场监督管理局") + len("云南省市场监督管理局"),
            }
        ],
        "成文日期": [
            {
                "text": "2026年4月1日",
                "start": text.index("2026年4月1日"),
                "end": text.index("2026年4月1日") + len("2026年4月1日"),
            }
        ],
    }
    paras = extract_body_paragraphs(
        text, title=title, recipient=recip, date="2026年4月1日", sdk_result=sdk
    )
    joined = "\n".join(paras)
    assert "商请你单位协助做好以下工作" in joined
    assert "一、安排专人" in joined
    assert not joined.startswith("一、")


def test_minutes_glued_mark_issue_keeps_year_digit():
    """纪要标志与期号粘同一行时，不得盲砍吞掉正文年份首位。"""
    body_lead = "2025年1月6日下午，市长丁春华在台州市人民政府第一会议室主持召开专题会议。"
    text = (
        "台州市人民政府专题会议纪要第79期\n"
        "\n"
        f"{body_lead}\n"
        "\n"
        "一、会议认为。做好总部经济培育工作。\n"
        "\n"
        "出席：陈丽萍、郝晓岚。\n"
        "列席：汪传伟。\n"
        "\n"
        "2026年8月19日\n"
        "\n"
        "抄送：台州市委办公室。\n"
    )
    # 模拟 SDK 只标到「…纪要」、无期号字段（通用 schema）
    mark = "台州市人民政府专题会议纪要"
    sdk = {
        "发文机关标志": [
            {"text": mark, "start": 0, "end": len(mark), "probability": 0.99}
        ],
        "出席": [
            {
                "text": "陈丽萍",
                "start": text.index("陈丽萍"),
                "end": text.index("陈丽萍") + 3,
                "probability": 0.9,
            }
        ],
        "成文日期": [
            {
                "text": "2026年8月19日",
                "start": text.index("2026年8月19日"),
                "end": text.index("2026年8月19日") + len("2026年8月19日"),
                "probability": 0.9,
            }
        ],
    }
    paras = extract_body_paragraphs(text, org_mark=mark, date="2026年8月19日", sdk_result=sdk)
    joined = "\n".join(paras)
    assert paras
    assert paras[0].startswith("2025年")
    assert not paras[0].startswith("025年")
    assert body_lead[:10] in joined
    assert "出席" not in joined
    assert "第79期" not in joined


def test_body_start_never_splits_year_token():
    """契约：正文起点不得落在「YYYY年」中间。"""
    from core.body_structure.extract import extract_body_with_trace

    text = (
        "台州市人民政府专题会议纪要第79期\n\n"
        "2025年1月6日下午召开会议。\n"
        "出席：甲。\n"
        "2026年8月19日\n"
    )
    _paras, diag = extract_body_with_trace(text, org_mark="台州市人民政府专题会议纪要")
    start = int(diag["start"])
    # 起点处若紧邻数字年，必须是完整四位年之首
    tail = text[start : start + 8]
    if "年" in tail:
        m = re.match(r"(\d{4})年", text[start:])
        assert m, f"start={start} splits year-like token: {tail!r}"


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


def test_order_body_window_after_order_no_before_signer():
    """命令：起点在令号后，终点在签署职务前；不盲砍正文、不吞职务。"""
    text = (
        "重庆市南岸区人民政府令\n"
        "第7号\n"
        "为有效预防和扑救森林火灾，保护森林资源。\n"
        "一、戒严区域\n"
        "南山等镇街范围内的全部林区。\n"
        "三、禁止行为\n"
        "戒严期内严禁一切野外用火。\n"
        "区长\n"
        "2026年11月28日\n"
        "（此件公开发布）\n"
    )
    ono = "第7号"
    signer = "区长"
    date = "2026年11月28日"
    sdk = {
        "发文机关标志": [
            {
                "text": "重庆市南岸区人民政府令",
                "start": 0,
                "end": len("重庆市南岸区人民政府令"),
                "probability": 0.99,
            }
        ],
        "令号": [
            {
                "text": ono,
                "start": text.index(ono),
                "end": text.index(ono) + len(ono),
                "probability": 0.99,
            }
        ],
        "签署职务": [
            {
                "text": signer,
                "start": text.index(signer),
                "end": text.index(signer) + len(signer),
                "probability": 0.99,
            }
        ],
        "成文日期": [
            {
                "text": date,
                "start": text.index(date),
                "end": text.index(date) + len(date),
                "probability": 0.99,
            }
        ],
    }
    paras = extract_body_paragraphs(
        text,
        date=date,
        org_mark="重庆市南岸区人民政府令",
        sdk_result=sdk,
    )
    joined = "\n".join(paras)
    assert joined.startswith("为有效预防")
    assert "三、禁止行为" in joined
    assert "戒严期内严禁一切野外用火" in joined
    assert "区长" not in joined
    assert "2026年11月28日" not in joined
    assert "人民政府令" not in joined
    assert "第7号" not in joined
