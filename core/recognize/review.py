# -*- coding: utf-8 -*-
"""模型识别结果审查与修正。

SDK 后处理原则是「只填空不覆盖」：模型填了错值就不会改。
本层在 SDK postprocess 之后运行，用原文强格式证据覆盖明显错误。
"""
from __future__ import annotations

import re
from typing import Any

_FW = str.maketrans("０１２３４５６７８９〔〕（）：．", "0123456789[]():.")

# 印发行：机关 + 日期 + 印发
_PRINT_RE = re.compile(
    r"^(.{2,40}?)\s*(\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日)\s*印\s*发?$"
)
# 主送：标题后、以冒号结尾；或「各…」机关列举行（原文偶发漏冒号）
_MAIN_COLON_RE = re.compile(r"^([^：:]{2,80})[：:]$")
_MAIN_LOOSE_RE = re.compile(
    r"^(各[\u4e00-\u9fa5（）()、，,]{2,70}"
    r"(人民政府|各部门|各单位|各直属|机关|机构|委员会).{0,40})$"
)
_BODY_OPEN_RE = re.compile(r"(如下|通知如下|报告如下|请示如下|公告|现将|为了|根据|按照).{0,6}$")
# 明显截断的印发机关（缺行政区前缀）
_TRUNC_PRINT_ORG_RE = re.compile(
    r"^(人民政府办公室|政府办公室|办公室|秘书科|人民政府|办公厅)$"
)
_TITLE_HINT_RE = re.compile(r"关于|的通知|的意见|的通报|的决定|的函")


def _n(s: str) -> str:
    return (s or "").translate(_FW).strip()


def _flat(s: str) -> str:
    return _n(s).replace("\n", "").replace(" ", "")


def _item_text(result: dict[str, Any], key: str) -> str:
    items = result.get(key) or []
    if not items:
        return ""
    return (items[0].get("text") or "").replace("\n", "").strip()


def _set_field(result: dict[str, Any], key: str, text: str, *, reason: str) -> None:
    text = (text or "").strip()
    if not text:
        return
    old = result.get(key) or []
    start = old[0].get("start") if old else None
    end = old[0].get("end") if old else None
    item: dict[str, Any] = {"text": text, "prob": 1.0, "source": f"review:{reason}"}
    if start is not None:
        item["start"] = start
    if end is not None:
        item["end"] = end
    # 尽量用原文定位，便于正文切片
    result[key] = [item]


def _lines(text: str) -> list[tuple[int, str, str]]:
    return [(i, ln, _n(ln)) for i, ln in enumerate((text or "").split("\n"))]


def _title_line_index(lines: list[tuple[int, str, str]], result: dict[str, Any]) -> int | None:
    title = _flat(_item_text(result, "标题"))
    if title:
        head = title[: min(16, len(title))]
        for i, _raw, nl in lines:
            if head and head in _flat(nl):
                return i
    for i, _raw, nl in lines:
        if len(nl) >= 10 and _TITLE_HINT_RE.search(nl) and "〔" not in nl:
            return i
    return None


def _find_print_line(lines: list[tuple[int, str, str]]) -> tuple[str, str] | None:
    """返回 (印发机关, 印发日期)。优先文末匹配；容忍空格与「印」「发」断行。"""
    hit = None
    # 拼两行，处理「日印\n发」
    for i in range(len(lines)):
        raw_a, nl_a = lines[i][1], lines[i][2]
        if not nl_a:
            continue
        candidates = [nl_a]
        if i + 1 < len(lines) and lines[i + 1][2] in ("发", "印发"):
            candidates.append(nl_a + lines[i + 1][2])
        for cand in candidates:
            compact = re.sub(r"\s+", "", cand)
            m = _PRINT_RE.match(compact)
            if not m:
                continue
            org, date = m.group(1), re.sub(r"\s+", "", m.group(2))
            # 机关名去掉末尾「秘书科」等印发承办尾巴（可选保留；国标印发机关常含办公室）
            hit = (org, date)
            break
    return hit


def _print_org_bad(model_org: str, evidence_org: str) -> bool:
    m = _flat(model_org)
    e = _flat(evidence_org)
    if not m:
        return True
    if _TRUNC_PRINT_ORG_RE.fullmatch(m):
        return True
    if e and m != e:
        # 模型值是证据的真后缀（缺前缀）或证据包含更完整机关名
        if e.endswith(m) and len(e) > len(m):
            return True
        if m in e and len(m) < len(e) * 0.85:
            return True
        # 模型值在原文印发行中根本对不上完整机关
        if m not in e and e not in m:
            # 若模型过短（常见截断）
            if len(m) <= 8:
                return True
    return False


def _correct_print(result: dict[str, Any], lines: list[tuple[int, str, str]]) -> list[str]:
    notes: list[str] = []
    hit = _find_print_line(lines)
    if not hit:
        return notes
    org, date = hit
    model_org = _item_text(result, "印发机关")
    model_date = _item_text(result, "印发日期")
    if _print_org_bad(model_org, org):
        _set_field(result, "印发机关", org, reason="print_org")
        notes.append(f"印发机关: {model_org!r} → {org!r}")
    if not model_date or _flat(model_date) != _flat(date):
        if not model_date or not re.fullmatch(r"\d{4}年\d{1,2}月\d{1,2}日", _flat(model_date)):
            _set_field(result, "印发日期", date, reason="print_date")
            notes.append(f"印发日期: {model_date!r} → {date!r}")
    return notes


def _find_recipient_line(
    lines: list[tuple[int, str, str]],
    result: dict[str, Any],
) -> str | None:
    """在文首找主送行，返回去冒号后的机关列表文本。"""
    title_i = _title_line_index(lines, result)
    lo = (title_i + 1) if title_i is not None else 0
    hi = min(len(lines), lo + 12)
    # 1) 标准：冒号结尾
    for i in range(lo, hi):
        raw, nl = lines[i][1], lines[i][2]
        if not nl or "抄送" in nl:
            continue
        m = _MAIN_COLON_RE.match(nl)
        if not m:
            continue
        body = m.group(1).strip()
        if _BODY_OPEN_RE.search(body):
            continue
        if "各" in body or body.endswith(("政府", "厅", "局", "部", "委", "办", "机构", "单位")):
            return re.sub(r"[：:]\s*$", "", raw.strip())
    # 2) 宽松：漏冒号的「各…」行
    for i in range(lo, hi):
        raw, nl = lines[i][1], lines[i][2]
        if not nl or "抄送" in nl or "关于" in nl:
            continue
        if _MAIN_LOOSE_RE.match(nl) and not _BODY_OPEN_RE.search(nl):
            return re.sub(r"[：:]\s*$", "", raw.strip())
    return None


def _recipient_bad(model: str, evidence: str) -> bool:
    m = _flat(model)
    e = _flat(evidence)
    if not e:
        return False
    if not m:
        return True
    if m == e:
        return False
    # 模型截断 / 多了正文碎片
    if e.startswith(m) and len(e) > len(m):
        return True
    if m.startswith(e) and len(m) > len(e) + 4:
        return True
    if m not in e and e not in m:
        return True
    return False


def _correct_recipient(result: dict[str, Any], lines: list[tuple[int, str, str]]) -> list[str]:
    notes: list[str] = []
    evidence = _find_recipient_line(lines, result)
    if not evidence:
        return notes
    model = _item_text(result, "主送机关")
    model_stripped = re.sub(r"[：:]\s*$", "", model).strip()
    if _recipient_bad(model_stripped, evidence):
        _set_field(result, "主送机关", evidence, reason="recipient")
        # 用原文重定位 start/end，便于正文从主送之后切开
        full = evidence
        text_join = "\n".join(ln[1] for ln in lines)
        # 在原文中找带冒号或不带冒号的首次出现
        idx = text_join.find(evidence + "：")
        span_len = len(evidence) + 1
        if idx < 0:
            idx = text_join.find(evidence + ":")
        if idx < 0:
            idx = text_join.find(evidence)
            span_len = len(evidence)
        if idx >= 0:
            result["主送机关"][0]["start"] = idx
            result["主送机关"][0]["end"] = idx + span_len
        notes.append(f"主送机关: {model_stripped!r} → {evidence!r}")
    return notes


def review_and_correct(result: dict[str, Any] | None, text: str) -> dict[str, Any]:
    """审查并修正模型结果。返回同一 dict（原地修改）。"""
    result = result or {}
    lines = _lines(text or "")
    notes: list[str] = []
    notes.extend(_correct_print(result, lines))
    notes.extend(_correct_recipient(result, lines))
    result["_review_notes"] = notes
    return result
