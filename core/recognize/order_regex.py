# -*- coding: utf-8 -*-
"""命令（令）正则识别器：暂代 ONNX，接口保持 ModelOutput 便于日后替换。"""
from __future__ import annotations

import re

from core.body_structure.parser import parse_body_blocks
from core.ir.order import (
    format_order_no,
    mark_is_order,
    normalize_order_signers,
    strip_signer_title,
)
from core.ir.schema import ModelOutput

_ORDER_NO_LINE = re.compile(r"^第\s*(\d+)\s*号\s*$")
_ATTACH = re.compile(r"^附件\s*[:：]")
_NOTE = re.compile(r"^[（(].+[）)]$")
_CC = re.compile(r"^抄送\s*[:：]")
_PRINT_ORG = re.compile(r"^印发机关\s*[:：]\s*(.+)$")
_PRINT_DATE = re.compile(r"^(?:印发日期\s*[:：]\s*)?(.+?印发)\s*$")
# 版记常见一行：「机关　　YYYY年M月D日印发」
_PRINT_LINE = re.compile(
    r"^(.+?)[\s　]+"
    r"((?:\d{4}|[〇零一二三四五六七八九十]{2,4})年"
    r"(?:[01]?\d|[〇零一二三四五六七八九十]+)月"
    r"(?:[0-3]?\d|[〇零一二三四五六七八九十]+)日)\s*印发\s*$"
)
_DATE = re.compile(
    r"^((?:\d{4}|[〇零一二三四五六七八九十]{2,4})年"
    r"(?:[01]?\d|[〇零一二三四五六七八九十]+)月"
    r"(?:[0-3]?\d|[〇零一二三四五六七八九十]+)日)\s*$"
)
# 常见职务词；其后可带姓名（将被剥掉）
_TITLE_LINE = re.compile(
    r"^("
    r"市长|副市长|代市长|区长|县长|旗长|州长|盟长|"
    r"省长|自治区主席|主席|总理|部长|主任|局长|厅长|署长|司长|"
    r"秘书长|总督察|总监|行长|院长|检察长|政委|司令员|"
    r"[\u4e00-\u9fff]{1,8}(?:长|官|使|员|理|监)"
    r")"
    r"(?:[\s　]+[\u4e00-\u9fff·•]{2,8})?\s*$"
)


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in (text or "").splitlines()]


def extract_order_fields(text: str) -> dict:
    """从原文抽命令字段；抽不到的置空，不抛错。"""
    raw_lines = _lines(text)
    nonempty = [(i, ln) for i, ln in enumerate(raw_lines) if ln]

    org_mark = ""
    order_no = ""
    mark_idx = -1
    order_idx = -1

    for i, ln in nonempty:
        if mark_is_order(ln):
            org_mark = ln
            mark_idx = i
            break

    search_from = mark_idx + 1 if mark_idx >= 0 else 0
    for i, ln in nonempty:
        if i < search_from:
            continue
        m = _ORDER_NO_LINE.match(ln) or re.match(r"^第\s*(\d+)\s*号", ln)
        if m:
            order_no = format_order_no(ln)
            order_idx = i
            break

    # 落款职务 / 日期 / 附件 / 附注 / 抄送 / 印发：从文末向前扫
    attachment_caption = ""
    note = ""
    cc = ""
    print_org = ""
    print_date = ""
    date = ""
    signers: list[str] = []

    body_end = len(raw_lines)
    # 自下而上收集版记/落款，截断正文终点
    footer_zone_start = len(raw_lines)
    for i in range(len(raw_lines) - 1, -1, -1):
        ln = raw_lines[i].strip()
        if not ln:
            continue
        if _CC.match(ln):
            cc = re.sub(r"^抄送\s*[:：]\s*", "", ln).strip()
            footer_zone_start = min(footer_zone_start, i)
            continue
        m_po = _PRINT_ORG.match(ln)
        if m_po:
            print_org = m_po.group(1).strip()
            footer_zone_start = min(footer_zone_start, i)
            continue
        m_pl = _PRINT_LINE.match(ln)
        if m_pl:
            print_org = m_pl.group(1).strip()
            print_date = m_pl.group(2).strip()
            footer_zone_start = min(footer_zone_start, i)
            continue
        m_pd = _PRINT_DATE.match(ln)
        if m_pd and "印发" in ln:
            # 避免把「机关＋日期印发」整行误塞进日期
            rest = m_pd.group(1).replace("印发", "").strip()
            if _DATE.match(rest):
                print_date = rest
            elif not print_org and not print_date:
                print_date = rest
            footer_zone_start = min(footer_zone_start, i)
            continue
        if _NOTE.match(ln) or (ln.startswith("（") and ln.endswith("）")):
            note = ln
            footer_zone_start = min(footer_zone_start, i)
            continue
        if _DATE.match(ln):
            date = _DATE.match(ln).group(1)
            footer_zone_start = min(footer_zone_start, i)
            continue
        if _ATTACH.match(ln):
            attachment_caption = re.sub(r"^附件\s*[:：]\s*", "", ln).strip()
            footer_zone_start = min(footer_zone_start, i)
            continue
        tm = _TITLE_LINE.match(ln)
        if tm:
            title = strip_signer_title(ln)
            if title:
                signers.insert(0, title)
            footer_zone_start = min(footer_zone_start, i)
            continue
        # 遇到正文或标志/令号则停止上溯
        if mark_is_order(ln) or _ORDER_NO_LINE.match(ln) or format_order_no(ln):
            break
        # 非落款特征的实文：视为正文区，停止
        break

    body_start = 0
    if order_idx >= 0:
        body_start = order_idx + 1
    elif mark_idx >= 0:
        body_start = mark_idx + 1

    body_paras: list[str] = []
    for i in range(body_start, min(footer_zone_start, len(raw_lines))):
        s = raw_lines[i].strip()
        if not s:
            continue
        if mark_is_order(s) or _ORDER_NO_LINE.match(s):
            continue
        if format_order_no(s) and len(s) <= 12:
            continue
        body_paras.append(s)

    signers = normalize_order_signers(signers)

    return {
        "org_mark": org_mark,
        "order_no": order_no,
        "body_blocks": body_paras,
        "attachment_caption": attachment_caption,
        "note": note,
        "cc": cc,
        "print_org": print_org,
        "print_date": print_date,
        "date": date,
        "signers": signers,
    }


def recognize_order(text: str) -> ModelOutput:
    """正则识别入口：返回 ModelOutput，并挂 _order_* / _is_order 供 builder 使用。"""
    fields = extract_order_fields(text)
    data = {
        "header": {
            "copy_number": "",
            "secret_level": "",
            "secret_period": "",
            "urgency": "",
            "issuer_sign": "、".join(fields["signers"]),
            "org_mark": fields["org_mark"],
            "doc_number": "",
        },
        "main": {
            "title": "",
            "recipient": "",
            "body_blocks": fields["body_blocks"],
            "attachment_caption": fields["attachment_caption"],
        },
        "footer": {
            "date": fields["date"],
            "note": fields["note"],
            "attachment": "",
            "org_signature": "",
            "print_org": fields["print_org"],
            "print_date": fields["print_date"],
        },
    }
    model = ModelOutput.from_dict(data)
    model._is_order = True  # type: ignore[attr-defined]
    model._order_no = fields["order_no"]  # type: ignore[attr-defined]
    model._order_signers = list(fields["signers"])  # type: ignore[attr-defined]
    model._sdk_cc = fields["cc"]  # type: ignore[attr-defined]
    # 保证 body 已是段落列表（builder 还会 parse）
    _ = parse_body_blocks(fields["body_blocks"])
    return model
