# -*- coding: utf-8 -*-
"""信函正则识别器：暂代 ONNX，接口保持 ModelOutput 便于日后替换。"""
from __future__ import annotations

import re

from core.body_structure.parser import parse_body_blocks
from core.ir.letter import (
    ensure_letter_mark,
    normalize_secret_pair,
    normalize_urgency,
    strip_cc_prefix,
    strip_recipient_colon,
    strip_wenjian_suffix,
)
from core.ir.schema import ModelOutput

_DOCNO = re.compile(
    r"^([\u4e00-\u9fffA-Za-z0-9·\-]+函)\s*[〔\[]\s*(\d{4})\s*[〕\]]\s*(\d+)\s*号\s*$"
)
_DOCNO_LOOSE = re.compile(
    r"([\u4e00-\u9fffA-Za-z0-9·\-]*函)\s*[〔\[]\s*(\d{4})\s*[〕\]]\s*(\d+)\s*号"
)
_COPY = re.compile(r"^(\d{6})\s*$")
_SECRET = re.compile(
    r"^((?:绝密|机密|秘密))(?:\s*[★*]\s*|\s+)(\d+\s*年)?\s*$"
)
_SECRET_COMBO = re.compile(r"^(绝密|机密|秘密)★(.+)$")
_URGENCY = re.compile(r"^(特急|加急|平急|特提)\s*$")
_ATTACH = re.compile(r"^附件\s*[:：]")
_NOTE = re.compile(r"^[（(].+[）)]$")
_CC = re.compile(r"^抄送\s*[:：]")
_DATE = re.compile(
    r"^((?:\d{4}|[〇零一二三四五六七八九十]{2,4})年"
    r"(?:[01]?\d|[〇零一二三四五六七八九十]+)月"
    r"(?:[0-3]?\d|[〇零一二三四五六七八九十]+)日)\s*$"
)
_TITLE_HINT = re.compile(r"关于.+函$|.+的(?:复)?函$")
# 机关名：较短、常含人民政府/办公室/厅/局 等
_ORG_HINT = re.compile(
    r"^(?:[\u4e00-\u9fff]{2,20}(?:人民政府|委员会|办公厅|办公室|管理局|局|厅|部|署|院))"
    r"(?:文件)?$"
)


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in (text or "").splitlines()]


def _format_docno(m: re.Match) -> str:
    return f"{m.group(1)}〔{m.group(2)}〕{int(m.group(3))}号"


def extract_letter_fields(text: str) -> dict:
    """从原文抽信函字段；抽不到的置空，不抛错。"""
    raw_lines = _lines(text)
    nonempty = [(i, ln) for i, ln in enumerate(raw_lines) if ln]

    org_mark = ""
    doc_number = ""
    copy_number = ""
    secret_level = ""
    secret_period = ""
    urgency = ""
    title = ""
    recipient = ""
    mark_idx = -1
    docno_idx = -1
    title_idx = -1
    recip_idx = -1

    # 版头区：份号 / 密级 / 紧急 / 标志 / 字号
    for i, ln in nonempty[:25]:
        if _COPY.match(ln) and not copy_number:
            copy_number = ln
            continue
        m_sc = _SECRET_COMBO.match(ln) or _SECRET.match(ln)
        if m_sc and not secret_level:
            secret_level, secret_period = normalize_secret_pair(
                m_sc.group(1), (m_sc.group(2) or "").strip()
            )
            continue
        if _URGENCY.match(ln) and not urgency:
            urgency = normalize_urgency(ln)
            continue
        m_dn = _DOCNO.match(ln) or (
            _DOCNO_LOOSE.fullmatch(ln) if "函" in ln and "号" in ln else None
        )
        if m_dn and not doc_number:
            doc_number = _format_docno(m_dn)
            docno_idx = i
            continue
        if _ORG_HINT.match(ln) and not org_mark:
            org_mark = ensure_letter_mark(strip_wenjian_suffix(ln))
            mark_idx = i
            continue

    # 标题：含「关于…函」或以函结尾
    search_from = max(mark_idx, docno_idx, 0) + 1
    for i, ln in nonempty:
        if i < search_from:
            continue
        if _TITLE_HINT.search(ln) or (ln.endswith("函") and "关于" in ln):
            title = ln
            title_idx = i
            break
        if ln.endswith("函") and 4 <= len(ln) <= 80 and not doc_number:
            # 无「关于」的短标题
            title = ln
            title_idx = i
            break

    # 主送：标题下一非空行（非正文长段）
    if title_idx >= 0:
        for i, ln in nonempty:
            if i <= title_idx:
                continue
            if _ATTACH.match(ln) or _CC.match(ln) or _DATE.match(ln) or _NOTE.match(ln):
                break
            # 主送通常较短且常带冒号
            cand = strip_recipient_colon(ln)
            if cand and len(cand) <= 60 and not cand.startswith("一、"):
                recipient = cand
                recip_idx = i
            break

    # 文末：附件 / 署名 / 日期 / 附注 / 抄送
    attachment_caption = ""
    note = ""
    cc = ""
    date = ""
    org_signature = ""
    footer_zone_start = len(raw_lines)

    for i in range(len(raw_lines) - 1, -1, -1):
        ln = raw_lines[i].strip()
        if not ln:
            continue
        if _CC.match(ln):
            cc = strip_cc_prefix(ln)
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
        # 署名：短机关名，位于日期之上
        if date and not org_signature:
            if _ORG_HINT.match(ln) or (
                2 <= len(ln) <= 40
                and not ln.endswith("函")
                and "〔" not in ln
                and not ln.startswith("关于")
            ):
                org_signature = ln
                footer_zone_start = min(footer_zone_start, i)
                for j in range(i - 1, -1, -1):
                    prev = raw_lines[j].strip()
                    if not prev:
                        continue
                    if _ORG_HINT.match(prev) or (
                        2 <= len(prev) <= 40
                        and not prev.endswith("函")
                        and "〔" not in prev
                        and not prev.startswith("关于")
                        and not _DATE.match(prev)
                        and not _ATTACH.match(prev)
                    ):
                        org_signature = prev + "\n" + org_signature
                        footer_zone_start = min(footer_zone_start, j)
                        continue
                    break
                break
        # 非落款特征 → 停止
        break

    body_start = 0
    if recip_idx >= 0:
        body_start = recip_idx + 1
    elif title_idx >= 0:
        body_start = title_idx + 1
    elif docno_idx >= 0:
        body_start = docno_idx + 1
    elif mark_idx >= 0:
        body_start = mark_idx + 1

    body_paras: list[str] = []
    for i in range(body_start, min(footer_zone_start, len(raw_lines))):
        s = raw_lines[i].strip()
        if not s:
            continue
        if s == title or s == org_mark or s == doc_number:
            continue
        if recipient and strip_recipient_colon(s) == recipient:
            continue
        body_paras.append(s)

    # 若标志仍空：扫原文中的机关全称/简称（可误带「文件」）
    if not org_mark:
        for _, ln in nonempty[:15]:
            if "函" in ln and ("〔" in ln or "号" in ln):
                continue
            if (
                ("人民政府" in ln or "办公厅" in ln or "办公室" in ln)
                and not ln.endswith("函")
                and len(ln) <= 30
            ):
                org_mark = ensure_letter_mark(ln)
                break

    secret_level, secret_period = normalize_secret_pair(secret_level, secret_period)

    return {
        "org_mark": org_mark,
        "doc_number": doc_number,
        "copy_number": copy_number,
        "secret_level": secret_level,
        "secret_period": secret_period,
        "urgency": urgency,
        "title": title,
        "recipient": recipient,
        "body_blocks": body_paras,
        "attachment_caption": attachment_caption,
        "org_signature": org_signature,
        "date": date,
        "note": note,
        "cc": cc,
    }


def recognize_letter(text: str) -> ModelOutput:
    """正则识别入口：返回 ModelOutput，挂 _is_letter / _sdk_cc 供 builder 使用。"""
    fields = extract_letter_fields(text)
    data = {
        "header": {
            "copy_number": fields["copy_number"],
            "secret_level": fields["secret_level"],
            "secret_period": fields["secret_period"],
            "urgency": fields["urgency"],
            "issuer_sign": "",
            "org_mark": fields["org_mark"],
            "doc_number": fields["doc_number"],
        },
        "main": {
            "title": fields["title"],
            "recipient": fields["recipient"],
            "body_blocks": fields["body_blocks"],
            "attachment_caption": fields["attachment_caption"],
        },
        "footer": {
            "date": fields["date"],
            "note": fields["note"],
            "attachment": "",
            "org_signature": fields["org_signature"],
            "print_org": "",
            "print_date": "",
        },
    }
    model = ModelOutput.from_dict(data)
    model._is_letter = True  # type: ignore[attr-defined]
    model._sdk_cc = fields["cc"]  # type: ignore[attr-defined]
    _ = parse_body_blocks(fields["body_blocks"])
    return model
