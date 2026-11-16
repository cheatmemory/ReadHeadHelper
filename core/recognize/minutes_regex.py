# -*- coding: utf-8 -*-
"""纪要字段正则抽取：绕过 ONNX / SDK postprocess，避免纪要文卡死。

抽不到的字段置空，不抛错、不阻塞。
"""
from __future__ import annotations

import re
from typing import Any

from core.ir.minutes import (
    ensure_minutes_mark,
    extract_minutes_lists,
    format_issue_no,
    looks_like_minutes,
    normalize_name_list,
)
from core.ir.schema import ModelOutput

_COPY_RE = re.compile(r"^(\d{6})$")
_SECRET_COMBO_RE = re.compile(
    r"^(绝密|机密|秘密)(?:\s*[★*]\s*(长期|\d{1,3}年|\d{1,3}个月))?$"
)
_URGENCY_RE = re.compile(r"^(特提|特急|加急|平急)(?:文件)?$")
_MARK_RE = re.compile(r"^[\u4e00-\u9fa5A-Za-z0-9（）()\-·、]{2,40}纪要$")
_ISSUE_LINE_RE = re.compile(r"^第\s*(\d+)\s*期$")
_NOTE_RE = re.compile(r"^[（(].+[）)]$")
_CC_RE = re.compile(r"^抄送\s*[：:]\s*(.+)$")
_PRINT_RE = re.compile(
    r"^(.+?)[ \u3000\t]+(\d{4}年\d{1,2}月\d{1,2}日)\s*印发?\s*$"
)
_PRINT_COMPACT_RE = re.compile(
    r"^(.+?)(\d{4}年\d{1,2}月\d{1,2}日)\s*印发?\s*$"
)
_DATE_RE = re.compile(r"^(\d{4}年\d{1,2}月\d{1,2}日)$")
_ATT_HEAD_RE = re.compile(r"^附件\s*[：:]?\s*(.*)$")
_ATT_ITEM_RE = re.compile(r"^(\d+)\s*[.．、]\s*(.+)$")
_LIST_HEAD_RE = re.compile(r"^(出席|请假|列席)\s*[：:]")


def _n(s: str) -> str:
    return (s or "").strip()


def _raw_lines(text: str) -> list[str]:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")


def extract_minutes_fields(text: str) -> dict[str, Any]:
    lines = _raw_lines(text)
    stripped = [_n(x) for x in lines]
    nonempty = [(i, ln) for i, ln in enumerate(stripped) if ln]

    out: dict[str, Any] = {
        "doc_kind": "minutes",
        "header": {
            "copy_number": None,
            "secret_level": None,
            "retention_period": None,
            "urgency": None,
            "issuing_org_header": None,
            "issue_no": None,
        },
        "main": {
            "title": None,
            "recipients": None,
            "body": "",
            "attachment_caption": None,
            "attendance": None,
            "leave": None,
            "liexi": None,
            "date": None,
            "note": None,
        },
        "footer": {
            "cc_recipients": None,
            "print_org": None,
            "print_date": None,
        },
        "body_blocks": [],
    }
    if not nonempty:
        return out

    used: set[int] = set()
    mark_i: int | None = None
    issue_i: int | None = None

    # ---------- 文首版头 ----------
    for i, ln in nonempty[:16]:
        if _COPY_RE.fullmatch(ln) and not out["header"]["copy_number"]:
            out["header"]["copy_number"] = ln
            used.add(i)
            continue
        m = _SECRET_COMBO_RE.fullmatch(ln)
        if m and not out["header"]["secret_level"]:
            out["header"]["secret_level"] = m.group(1)
            out["header"]["retention_period"] = m.group(2)
            used.add(i)
            continue
        if _URGENCY_RE.fullmatch(ln) and not out["header"]["urgency"]:
            out["header"]["urgency"] = re.sub(r"文件$", "", ln)
            used.add(i)
            continue
        if _MARK_RE.fullmatch(ln) and not out["header"]["issuing_org_header"]:
            # 机关标志优先短名；「…工作会议纪要」更像标题，稍后处理
            if "工作" in ln and ln.endswith("会议纪要"):
                continue
            out["header"]["issuing_org_header"] = ensure_minutes_mark(ln)
            mark_i = i
            used.add(i)
            continue
        m = _ISSUE_LINE_RE.fullmatch(ln)
        if m and not out["header"]["issue_no"]:
            out["header"]["issue_no"] = f"第{int(m.group(1))}期"
            issue_i = i
            used.add(i)
            continue

    if not out["header"]["issuing_org_header"]:
        for i, ln in nonempty[:20]:
            if i in used:
                continue
            if _MARK_RE.fullmatch(ln) and "工作" not in ln:
                out["header"]["issuing_org_header"] = ensure_minutes_mark(ln)
                mark_i = i
                used.add(i)
                break
        if not out["header"]["issuing_org_header"]:
            for i, ln in nonempty[:20]:
                if ln.endswith("纪要") and "关于" not in ln:
                    out["header"]["issuing_org_header"] = ensure_minutes_mark(ln)
                    mark_i = i
                    used.add(i)
                    break

    if not out["header"]["issue_no"]:
        for i, ln in nonempty[:25]:
            m = _ISSUE_LINE_RE.fullmatch(ln)
            if m:
                out["header"]["issue_no"] = f"第{int(m.group(1))}期"
                issue_i = i
                used.add(i)
                break

    # ---------- 名单 / 附注 / 抄送 / 印发 ----------
    list_start = next((i for i, ln in nonempty if _LIST_HEAD_RE.match(ln)), None)
    lists = extract_minutes_lists(text)
    out["main"]["attendance"] = lists["attendance"] or None
    out["main"]["leave"] = lists["leave"] or None
    out["main"]["liexi"] = lists["liexi"] or None
    for i, ln in nonempty:
        if _LIST_HEAD_RE.match(ln):
            used.add(i)

    for i, ln in reversed(nonempty):
        if list_start is not None and i < list_start:
            break
        m = _CC_RE.match(ln)
        if m and not out["footer"]["cc_recipients"]:
            out["footer"]["cc_recipients"] = m.group(1).strip().rstrip("。")
            used.add(i)
            continue
        m = _PRINT_RE.match(ln) or _PRINT_COMPACT_RE.match(re.sub(r"[ \u3000\t]+", "", ln))
        if m and not out["footer"]["print_org"]:
            out["footer"]["print_org"] = m.group(1).strip()
            out["footer"]["print_date"] = m.group(2).strip()
            used.add(i)
            continue
        if _NOTE_RE.fullmatch(ln) and not out["main"]["note"]:
            out["main"]["note"] = ln
            used.add(i)
            continue
        if _DATE_RE.fullmatch(ln) and not out["main"]["date"]:
            out["main"]["date"] = ln
            used.add(i)

    # ---------- 附件说明 ----------
    att_start = next(
        (i for i, ln in nonempty if _ATT_HEAD_RE.match(ln) and (list_start is None or i < list_start)),
        None,
    )
    if att_start is not None:
        chunks: list[str] = []
        for i, ln in nonempty:
            if i < att_start:
                continue
            if list_start is not None and i >= list_start:
                break
            if i > att_start and (
                _LIST_HEAD_RE.match(ln) or _CC_RE.match(ln) or _NOTE_RE.fullmatch(ln)
            ):
                break
            if i == att_start:
                rest = _ATT_HEAD_RE.match(ln).group(1).strip()  # type: ignore[union-attr]
                if rest:
                    chunks.append(rest)
                used.add(i)
                continue
            if _ATT_ITEM_RE.match(ln) or (chunks and not ln.endswith("纪要")):
                chunks.append(ln)
                used.add(i)
            else:
                break
        if chunks:
            parts: list[str] = []
            for n, e in enumerate(chunks, 1):
                e = e.strip()
                if re.match(r"^\d+\s*[.．、]", e):
                    parts.append(re.sub(r"^(\d+)\s*[.．、]\s*", r"\1.", e))
                else:
                    parts.append(e if len(chunks) == 1 else f"{n}.{e}")
            out["main"]["attachment_caption"] = "\n".join(parts)

    # ---------- 标题 ----------
    start_after = max([x for x in (mark_i, issue_i) if x is not None] or [-1])
    title_i = None
    stop_i = att_start if att_start is not None else list_start
    for i, ln in nonempty:
        if i <= start_after:
            continue
        if stop_i is not None and i >= stop_i:
            break
        if i in used:
            continue
        if ln.startswith("附件"):
            break
        if out["header"]["issuing_org_header"] and ln == out["header"]["issuing_org_header"]:
            continue
        # 标题：以纪要结尾，或中等长度非结构序数行
        if ln.endswith("纪要") or (
            8 <= len(ln) <= 80
            and not re.match(r"^[一二三四五六七八九十\d（(]", ln)
            and "如下" not in ln
        ):
            out["main"]["title"] = ln
            title_i = i
            used.add(i)
            break

    # ---------- 正文 ----------
    body_lo = (title_i if title_i is not None else start_after) + 1
    body_hi = len(lines)
    if att_start is not None:
        body_hi = min(body_hi, att_start)
    if list_start is not None:
        body_hi = min(body_hi, list_start)
    body_paras = [stripped[i] for i in range(body_lo, body_hi) if stripped[i]]
    out["body_blocks"] = body_paras
    out["main"]["body"] = "\n".join(body_paras)

    if out["main"]["attendance"]:
        out["main"]["attendance"] = normalize_name_list(out["main"]["attendance"])
    if out["main"]["leave"]:
        out["main"]["leave"] = normalize_name_list(out["main"]["leave"])
    if out["main"]["liexi"]:
        out["main"]["liexi"] = normalize_name_list(out["main"]["liexi"])
    if out["header"]["issue_no"]:
        out["header"]["issue_no"] = format_issue_no(out["header"]["issue_no"])

    return out


def minutes_fields_to_model(fields: dict[str, Any]) -> ModelOutput:
    h = fields.get("header") or {}
    m = fields.get("main") or {}
    f = fields.get("footer") or {}
    body_blocks = list(fields.get("body_blocks") or [])
    if not body_blocks and m.get("body"):
        body_blocks = [p.strip() for p in str(m["body"]).splitlines() if p.strip()]

    model = ModelOutput.from_dict(
        {
            "header": {
                "copy_number": h.get("copy_number") or "",
                "secret_level": h.get("secret_level") or "",
                "secret_period": h.get("retention_period") or "",
                "urgency": h.get("urgency") or "",
                "issuer_sign": "",
                "org_mark": h.get("issuing_org_header") or "",
                "doc_number": "",
            },
            "main": {
                "title": m.get("title") or "",
                "recipient": m.get("recipients") or "",
                "body_blocks": body_blocks,
                "attachment_caption": m.get("attachment_caption") or "",
            },
            "footer": {
                "date": m.get("date") or "",
                "note": m.get("note") or "",
                "attachment": "",
                "org_signature": "",
                "print_org": f.get("print_org") or "",
                "print_date": f.get("print_date") or "",
            },
        }
    )
    model._sdk_cc = f.get("cc_recipients") or ""  # type: ignore[attr-defined]
    model._minutes_issue_no = h.get("issue_no") or ""  # type: ignore[attr-defined]
    model._minutes_attendance = m.get("attendance") or ""  # type: ignore[attr-defined]
    model._minutes_leave = m.get("leave") or ""  # type: ignore[attr-defined]
    model._minutes_liexi = m.get("liexi") or ""  # type: ignore[attr-defined]
    return model


class MinutesRegexRecognizer:
    def recognize(self, text: str) -> ModelOutput:
        return minutes_fields_to_model(extract_minutes_fields(text or ""))


def try_recognize_minutes(text: str) -> ModelOutput | None:
    if not looks_like_minutes(source_text=text or ""):
        return None
    return MinutesRegexRecognizer().recognize(text or "")
