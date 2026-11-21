# -*- coding: utf-8 -*-
from core.body_structure.extract import _merge_soft_wraps
from core.body_structure.parser import (
    normalize_structure_markers,
    parse_body_blocks,
    renumber_blocks,
)


def test_parse_levels():
    blocks = parse_body_blocks([
        "一、总体要求",
        "（一）市容",
        "1. 细则",
        "（1）子项",
        "普通段落",
    ])
    assert [b.level for b in blocks] == ["h1", "h2", "h3", "h4", "p"]
    # 二级全角括号；三级序数后无空格
    assert blocks[1].text.startswith("（一）")
    assert blocks[2].text.startswith("1.")
    assert "1. " not in blocks[2].text[:4]
    assert blocks[3].text.startswith("(1)")


def test_normalize_markers():
    assert normalize_structure_markers("(一)市容") == "（一）市容"
    assert normalize_structure_markers("1. 细则") == "1.细则"
    assert normalize_structure_markers("（1）子项") == "(1)子项"


def test_renumber():
    blocks = parse_body_blocks(["三、甲", "一、乙", "正文"])
    blocks[0].level = "h1"
    blocks[1].level = "h1"
    out = renumber_blocks(blocks)
    assert out[0].text.startswith("一、")
    assert out[1].text.startswith("二、")


def test_renumber_h2_h3():
    blocks = parse_body_blocks(["（二）甲", "3. 乙"])
    out = renumber_blocks(blocks)
    assert out[0].text == "（一）甲"
    assert out[1].text == "1.乙"


def test_merge_soft_wraps_struct_title_ends_at_line():
    """短结构标题行尾即结束；「…行为」不得因末字「为」与正文粘连。"""
    lines = [
        "一、戒严区域",
        "南山等镇街范围内的全部林区。",
        "三、禁止行为",
        "戒严期内，戒严区域内严禁一切野外用火。",
        "四、管控措施",
        "各镇人民政府要落实巡护。",
    ]
    out = _merge_soft_wraps(lines)
    assert "三、禁止行为" in out
    assert out[out.index("三、禁止行为") + 1].startswith("戒严期内")
    assert not any(x.startswith("三、禁止行为戒严") for x in out)


def test_merge_soft_wraps_struct_still_joins_incomplete():
    """序号后极短或「……的」收尾，仍视为标题回行未完。"""
    out = _merge_soft_wraps(["一、", "总体要求"])
    assert out == ["一、总体要求"]
    out2 = _merge_soft_wraps(["二、关于进一步规范管理的", "若干措施"])
    assert len(out2) == 1
    assert out2[0].startswith("二、关于进一步规范管理的若干")
