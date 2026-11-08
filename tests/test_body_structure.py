# -*- coding: utf-8 -*-
from core.body_structure.parser import parse_body_blocks, renumber_blocks


def test_parse_levels():
    blocks = parse_body_blocks([
        "一、总体要求",
        "（一）市容",
        "1. 细则",
        "（1）子项",
        "普通段落",
    ])
    assert [b.level for b in blocks] == ["h1", "h2", "h3", "h4", "p"]


def test_renumber():
    blocks = parse_body_blocks(["三、甲", "一、乙", "正文"])
    blocks[0].level = "h1"
    blocks[1].level = "h1"
    out = renumber_blocks(blocks)
    assert out[0].text.startswith("一、")
    assert out[1].text.startswith("二、")
