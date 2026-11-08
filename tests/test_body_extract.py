# -*- coding: utf-8 -*-
from pathlib import Path

from core.body_structure.extract import extract_body_paragraphs
from core.body_structure.parser import parse_body_blocks
from core.config_loader import load_config, project_root
from core.ir.builder import model_to_partial_ir
from core.recognize.factory import create_recognizer

ROOT = Path(__file__).resolve().parents[1]


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
    text = (ROOT / "fixtures" / "sample_text" / "jiangcheng_messy.txt").read_text(encoding="utf-8")
    rec, name = create_recognizer(load_config(), project_root())
    model = rec.recognize(text)
    assert len(model.main.body_blocks) > 5
    ir = model_to_partial_ir(model, source_text=text)
    levels = {b.level for b in ir.body_tree}
    assert "h1" in levels and "h2" in levels
    # 文末印发机关不应把正文起点带跑
    assert not ir.body_tree[0].text.startswith("江府办发")


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
