# -*- coding: utf-8 -*-
"""正文四层结构识别与编号接续。"""
from __future__ import annotations

import re

from core.ir.schema import BodyBlock

_CN = "一二三四五六七八九十"

_H1 = re.compile(r"^([一二三四五六七八九十百]+)[、．.]\s*(.*)$")
_H2 = re.compile(r"^[（(]([一二三四五六七八九十百]+)[）)]\s*(.*)$")
_H3 = re.compile(r"^(\d+)[．.、]\s*(.*)$")
_H4 = re.compile(r"^[（(](\d+)[）)]\s*(.*)$")


def parse_paragraph(text: str) -> BodyBlock:
    # 去掉全角空格等，避免「　　一、」匹配失败
    t = (text or "").replace("\u3000", " ").strip()
    if not t:
        return BodyBlock(level="p", text="")
    m = _H1.match(t)
    if m:
        return BodyBlock(level="h1", label=m.group(1) + "、", text=t)
    m = _H2.match(t)
    if m:
        return BodyBlock(level="h2", label=f"（{m.group(1)}）", text=t)
    m = _H3.match(t)
    if m:
        return BodyBlock(level="h3", label=f"{m.group(1)}.", text=t)
    m = _H4.match(t)
    if m:
        return BodyBlock(level="h4", label=f"（{m.group(1)}）", text=t)
    return BodyBlock(level="p", text=t)


def parse_body_blocks(paragraphs: list[str]) -> list[BodyBlock]:
    return [parse_paragraph(p) for p in paragraphs if str(p).strip()]


def _strip_marker(text: str, level: str) -> str:
    t = (text or "").replace("\u3000", " ").strip()
    if level == "h1":
        return _H1.sub(r"\2", t).strip() or t
    if level == "h2":
        return _H2.sub(r"\2", t).strip() or t
    if level == "h3":
        return _H3.sub(r"\2", t).strip() or t
    if level == "h4":
        return _H4.sub(r"\2", t).strip() or t
    return t


def _mark(rest: str, level: str, index: int) -> str:
    if level == "h1":
        return f"{_CN[index]}、{rest}"
    if level == "h2":
        return f"（{_CN[index]}）{rest}"
    if level == "h3":
        return f"{index + 1}. {rest}"
    if level == "h4":
        return f"（{index + 1}）{rest}"
    return rest


def renumber_blocks(blocks: list[BodyBlock]) -> list[BodyBlock]:
    counters = {"h1": 0, "h2": 0, "h3": 0, "h4": 0}
    out: list[BodyBlock] = []
    for b in blocks:
        level = b.level
        if level not in counters:
            out.append(BodyBlock(level="p", text=b.text, label=""))
            continue
        rest = _strip_marker(b.text, level)
        text = _mark(rest, level, counters[level])
        label = text[: text.find(rest[0]) + 0] if rest else text
        # 简单 label
        if level == "h1":
            label = f"{_CN[counters[level]]}、"
        elif level == "h2":
            label = f"（{_CN[counters[level]]}）"
        elif level == "h3":
            label = f"{counters[level] + 1}."
        else:
            label = f"（{counters[level] + 1}）"
        counters[level] += 1
        if level == "h1":
            counters["h2"] = counters["h3"] = counters["h4"] = 0
        elif level == "h2":
            counters["h3"] = counters["h4"] = 0
        elif level == "h3":
            counters["h4"] = 0
        out.append(BodyBlock(level=level, text=text, label=label))
    return out
