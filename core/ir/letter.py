# -*- coding: utf-8 -*-
"""信函文种：判定、字段归一与挂载（口径见 docs/baselines/信函.md）。"""
from __future__ import annotations

import re
from typing import Any

from core.ir.schema import DocKind, LayoutIR, SealMode

_WIN_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# 发文字号含「函」代字：如 江政函〔2026〕15号 / ××函〔YYYY〕N号
_DOCNO_HAN_RE = re.compile(
    r"[\u4e00-\u9fffA-Za-z0-9]*函\s*[〔\[]\s*\d{4}\s*[〕\]]\s*\d+\s*号"
)
_ALLOWED_URGENCY = frozenset({"特急", "加急"})
_SECRET_LEVELS = frozenset({"秘密", "机密", "绝密"})


def strip_wenjian_suffix(mark: str) -> str:
    """信函标志不加「文件」；误带则剥掉。"""
    t = (mark or "").strip()
    if t.endswith("文件"):
        t = t[: -len("文件")].rstrip()
    return t


def strip_recipient_colon(raw: str) -> str:
    """主送只存机关名，不含冒号。"""
    t = (raw or "").strip()
    return t.rstrip("：:").rstrip()


def strip_cc_prefix(raw: str) -> str:
    """抄送只存机关名串；剥「抄送：」与末尾句号。"""
    t = (raw or "").strip()
    t = re.sub(r"^抄送\s*[:：]\s*", "", t)
    t = t.rstrip("。.;；")
    return t.strip()


def normalize_urgency(raw: str) -> str:
    """仅特急/加急；平急/特提等置空。"""
    t = (raw or "").strip()
    if t in _ALLOWED_URGENCY:
        return t
    return ""


def normalize_secret_pair(level: str, period: str) -> tuple[str, str]:
    """密级与期限分字段；展示层再拼 ★。从「秘密★1年」拆开亦可。"""
    lv = (level or "").strip()
    pd = (period or "").strip().lstrip("★*")
    if "★" in lv:
        a, b = lv.split("★", 1)
        lv, pd = a.strip(), (b.strip() or pd)
    if lv and lv not in _SECRET_LEVELS:
        # 容错：带「密」的常见写法
        for cand in ("绝密", "机密", "秘密"):
            if cand in lv:
                lv = cand
                break
    return lv, pd


def secret_display(level: str, period: str) -> str:
    lv, pd = normalize_secret_pair(level, period)
    if lv and pd:
        return f"{lv}★{pd}"
    return lv or ""


def doc_number_has_han(doc_number: str) -> bool:
    s = (doc_number or "").strip()
    if not s:
        return False
    if _DOCNO_HAN_RE.search(s):
        return True
    # 宽松：含「函」且含六角/方括号年份结构
    if "函" in s and ("〔" in s or "[" in s) and "号" in s:
        return True
    return False


def title_ends_with_han(title: str) -> bool:
    t = (title or "").strip()
    return bool(t) and t.endswith("函")


def looks_like_letter(
    *,
    doc_number: str = "",
    title: str = "",
    source_text: str = "",
) -> bool:
    """baseline §1：字号含函代字，或标题以「函」结尾（勿因正文偶现「函」误切）。"""
    if doc_number_has_han(doc_number):
        return True
    if title_ends_with_han(title):
        return True
    # 扫原文前若干非空行：独立成行的字号/标题
    nonempty = [ln.strip() for ln in (source_text or "").splitlines() if ln.strip()]
    for ln in nonempty[:30]:
        if doc_number_has_han(ln):
            return True
        if title_ends_with_han(ln) and ("关于" in ln or "函" == ln[-1:]):
            # 标题行通常含「关于」或以函结尾且较短
            if len(ln) <= 80:
                return True
    return False


def ensure_letter_mark(mark: str) -> str:
    return strip_wenjian_suffix(mark)


def letter_export_basename(ir: LayoutIR) -> str:
    """信函导出文件名：优先发文字号。"""
    stem = (ir.doc_number or "").strip() or (ir.title or "").strip() or "信函"
    stem = _WIN_BAD_CHARS.sub("", stem).strip(" .") or "信函"
    return stem + ".docx"


def apply_letter_layout_locks(ir: LayoutIR) -> LayoutIR:
    """layout 三项锁定：首页无页码 / 有章位 reserved / 版记无分隔线。"""
    ir.seal_mode = SealMode.RESERVED
    ir.recipients_in_footer = False
    return ir


def letter_validation_errors(ir: LayoutIR) -> list[str]:
    """baseline §17：必填 + 同进同退 + 紧急枚举 + 标志不加文件 + layout 锁定。"""
    missing: list[str] = []
    mark = ensure_letter_mark(ir.primary_org_mark())
    if not mark:
        missing.append("发文机关标志")
    elif (ir.primary_org_mark() or "").strip().endswith("文件"):
        missing.append("信函标志不加『文件』")
    if not ir.doc_number.strip():
        missing.append("发文字号")
    if not ir.title.strip():
        missing.append("标题")
    if not strip_recipient_colon(ir.recipient):
        missing.append("主送机关")
    if not any(b.text.strip() for b in ir.body_tree):
        missing.append("正文")
    if not ir.org_signature.strip():
        missing.append("发文机关署名")
    if not ir.date.strip():
        missing.append("成文日期")

    lv = (ir.secret_level or "").strip()
    pd = (ir.secret_period or "").strip()
    if "★" in lv:
        a, b = lv.split("★", 1)
        lv, pd = a.strip(), (b.strip() or pd)
    if bool(lv) != bool(pd):
        missing.append("密级与保密期限须同进同退")

    urg = (ir.urgency or "").strip()
    if urg and urg not in _ALLOWED_URGENCY:
        missing.append("紧急程度仅允许特急/加急")

    if ir.seal_mode is not None and ir.seal_mode != SealMode.RESERVED:
        missing.append("信函落款须为有章口径(reserved)")
    return missing


def apply_letter_to_ir(
    ir: LayoutIR,
    source_text: str = "",
    *,
    model: Any | None = None,
) -> LayoutIR:
    """识别命中后写入信函字段；不改动非信函 IR。"""
    model_letter = bool(model is not None and getattr(model, "_is_letter", False))
    if not model_letter and not looks_like_letter(
        doc_number=ir.doc_number,
        title=ir.title,
        source_text=source_text,
    ):
        return ir

    ir.doc_kind = DocKind.LETTER
    apply_letter_layout_locks(ir)

    marks = [ensure_letter_mark(m) for m in (ir.org_marks or [])]
    marks = [m for m in marks if m]
    # 联合只用主办：只保留第一个标志
    if len(marks) > 1:
        marks = [marks[0]]
    if not marks and model is not None:
        om = getattr(getattr(model, "header", None), "org_mark", "") or ""
        om = ensure_letter_mark(om)
        if om:
            marks = [om]
    ir.org_marks = marks

    ir.recipient = strip_recipient_colon(ir.recipient)
    ir.cc_recipients = strip_cc_prefix(ir.cc_recipients)
    ir.urgency = normalize_urgency(ir.urgency)
    lv, pd = normalize_secret_pair(ir.secret_level, ir.secret_period)
    ir.secret_level, ir.secret_period = lv, pd

    if model is not None:
        sdk_cc = getattr(model, "_sdk_cc", "") or ""
        if sdk_cc and not ir.cc_recipients.strip():
            ir.cc_recipients = strip_cc_prefix(str(sdk_cc))

    # 信函不排签发人版头、不要求印发
    ir.signers = []
    # 印发可清空以免通用校验干扰（letter 不校验印发）
    return ir
