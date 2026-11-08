# -*- coding: utf-8 -*-
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
