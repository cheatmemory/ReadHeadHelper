# -*- coding: utf-8 -*-
"""纪要文种：判定、字段归一与从原文抽取（口径见 docs/baselines/纪要.md）。"""
from __future__ import annotations

import re
from typing import Any

from core.ir.schema import DocKind, LayoutIR

_ATTEND_LINE_RE = re.compile(r"^出席\s*[：:]")
_LIST_LINE_RE = re.compile(r"^(出席|请假|列席)\s*[：:]\s*(.*)$")
_ISSUE_RE = re.compile(r"第\s*(\d+)\s*期")
_LABEL_PREFIX_RE = re.compile(r"^(出席|请假|列席)\s*[：:]\s*")


def format_issue_no(raw: str) -> str:
    """展示唯一形态：无空格「第{N}期」。无法解析则返回空串。"""
    s = (raw or "").strip()
    if not s:
        return ""
    m = _ISSUE_RE.search(s)
    if m:
        return f"第{int(m.group(1))}期"
    if s.isdigit():
        return f"第{int(s)}期"
    m2 = re.search(r"(\d+)", s)
    if m2:
        return f"第{int(m2.group(1))}期"
    return ""


_WIN_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def minutes_export_basename(ir: LayoutIR) -> str:
    """纪要导出文件名：纪要标志 + 期号（如有）。例：江州市人民政府专题会议纪要第7期.docx"""
    mark = (ir.primary_org_mark() or "").strip() or "会议纪要"
    issue = format_issue_no(ir.issue_no)
    stem = _WIN_BAD_CHARS.sub("", mark + issue).strip(" .") or "会议纪要"
    return stem + ".docx"


def normalize_name_list(text: str) -> str:
    """名单：去名目前缀；多人统一顿号；末尾不加句号。"""
    t = (text or "").strip()
    if not t:
        return ""
    t = _LABEL_PREFIX_RE.sub("", t).strip()
    t = t.rstrip("。.;；")
    parts = [p.strip() for p in re.split(r"[、，,；;]+", t) if p.strip()]
    return "、".join(parts)


def looks_like_minutes(
    *,
    org_marks: list[str] | None = None,
    title: str = "",
    source_text: str = "",
) -> bool:
    """baseline §1 自动判定（自上而下任一命中）。"""
    for m in org_marks or []:
        if str(m).strip().endswith("纪要"):
            return True
    t = (title or "").strip()
    if t.endswith("纪要") or "会议纪要" in t:
        return True
    for line in (source_text or "").splitlines():
        if _ATTEND_LINE_RE.match(line.strip()):
            return True
    return False


def extract_minutes_lists(source_text: str) -> dict[str, str]:
    """从原文抽取出席/请假/列席（兼容逗号，归一为顿号）。"""
    out = {"attendance": "", "leave": "", "liexi": ""}
    key_map = {"出席": "attendance", "请假": "leave", "列席": "liexi"}
    for line in (source_text or "").splitlines():
        m = _LIST_LINE_RE.match(line.strip())
        if not m:
            continue
        field = key_map[m.group(1)]
        # 同名多行：后行覆盖前行（通常一文一块）
        out[field] = normalize_name_list(m.group(2))
    return out


def extract_issue_no(source_text: str, *, doc_number: str = "") -> str:
    """优先文号槽里的期号形态，否则扫全文「第N期」。"""
    formatted = format_issue_no(doc_number)
    if formatted:
        return formatted
    for line in (source_text or "").splitlines()[:40]:
        m = _ISSUE_RE.search(line)
        if m:
            return f"第{int(m.group(1))}期"
    return ""


def ensure_minutes_mark(mark: str) -> str:
    """输入已含「纪要」则不重复拼接；空则仍空（由校验拦）。"""
    t = (mark or "").strip()
    if not t:
        return ""
    if t.endswith("纪要"):
        return t
    # 误带「文件」后缀时剥掉再判
    if t.endswith("文件"):
        t2 = t[: -len("文件")].strip()
        if t2.endswith("纪要"):
            return t2
    return t


def apply_minutes_to_ir(
    ir: LayoutIR,
    source_text: str = "",
    *,
    model: Any | None = None,
) -> LayoutIR:
    """识别命中后写入纪要字段；不改动非纪要 IR。"""
    if not looks_like_minutes(
        org_marks=ir.org_marks,
        title=ir.title,
        source_text=source_text,
    ):
        return ir

    ir.doc_kind = DocKind.MINUTES
    ir.seal_mode = None
    # 主体不排主送；有主送则进版记
    if ir.recipient.strip():
        ir.recipients_in_footer = True

    marks = [ensure_minutes_mark(m) for m in (ir.org_marks or [])]
    marks = [m for m in marks if m]
    if not marks:
        # 标题以纪要结尾时，可作标志候选
        title = (ir.title or "").strip()
        if title.endswith("纪要") and "关于" not in title[:2]:
            marks = [title]
    ir.org_marks = marks

    # 正则识别器挂在 model 上的纪要字段优先
    if model is not None:
        for attr, dest in (
            ("_minutes_issue_no", "issue_no"),
            ("_minutes_attendance", "attendance"),
            ("_minutes_leave", "leave"),
            ("_minutes_liexi", "liexi"),
        ):
            val = getattr(model, attr, "") or ""
            if val and not getattr(ir, dest, "").strip():
                setattr(ir, dest, val)
        # bridge 也会从 _sdk_cc 写入；此处补全，避免只走 model_to_partial_ir 时丢抄送
        sdk_cc = getattr(model, "_sdk_cc", "") or ""
        if sdk_cc and not ir.cc_recipients.strip():
            ir.cc_recipients = str(sdk_cc).strip()

    lists = extract_minutes_lists(source_text)
    if lists["attendance"] and not ir.attendance.strip():
        ir.attendance = lists["attendance"]
    if lists["leave"] and not ir.leave.strip():
        ir.leave = lists["leave"]
    if lists["liexi"] and not ir.liexi.strip():
        ir.liexi = lists["liexi"]
    ir.attendance = normalize_name_list(ir.attendance)
    ir.leave = normalize_name_list(ir.leave)
    ir.liexi = normalize_name_list(ir.liexi)

    issue = extract_issue_no(source_text, doc_number=ir.doc_number)
    if not ir.issue_no.strip() and issue:
        ir.issue_no = issue
    elif ir.issue_no:
        ir.issue_no = format_issue_no(ir.issue_no)
    if format_issue_no(ir.doc_number):
        ir.doc_number = ""

    # 纪要不使用署名；误识别可清空以免 UI 干扰（用户仍可在非纪要切回）
    # 保留 org_signature 原文以便切回通用，但不参与纪要导出校验
    return ir


def minutes_payload_fields(ir: LayoutIR) -> dict[str, Any]:
    return {
        "doc_kind": ir.doc_kind.value if ir.doc_kind else DocKind.GENERAL.value,
        "issue_no": format_issue_no(ir.issue_no) or ir.issue_no,
        "attendance": ir.attendance,
        "leave": ir.leave,
        "liexi": ir.liexi,
        "attendance_absent_confirmed": bool(ir.attendance_absent_confirmed),
    }
