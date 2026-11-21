# -*- coding: utf-8 -*-
"""命令（令）文种：判定、令号归一与字段挂载（口径见 docs/baselines/命令.md）。"""
from __future__ import annotations

import re
from typing import Any

from core.ir.schema import DocKind, LayoutIR

_ORDER_NO_RE = re.compile(r"第\s*([0-9〇零一二三四五六七八九十百两]+)\s*号")
# 职务后常见「全角空格/空格 + 姓名」权宜写法 → 只留职务
_TITLE_STRIP_NAME_RE = re.compile(
    r"^(.+?)(?:[\s　]+[\u4e00-\u9fff·•]{2,8}|[\s　]*签发)$"
)
_WIN_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_CN_DIGITS = {
    "〇": 0,
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def _cn_numeral_to_int(token: str) -> int | None:
    """中文令号数字 → int（支持 九 / 十二 / 二十三 / 一百 等常见形态）。"""
    s = (token or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if s == "十":
        return 10
    if s == "百":
        return 100
    # 一百 / 一百零五 / 一百二十
    if "百" in s:
        left, _, right = s.partition("百")
        hundreds = 1 if not left else _CN_DIGITS.get(left)
        if hundreds is None:
            return None
        if not right:
            return hundreds * 100
        if right.startswith("零") and len(right) == 2:
            ones = _CN_DIGITS.get(right[1])
            return hundreds * 100 + ones if ones is not None else None
        rest = _cn_numeral_to_int(right)
        return hundreds * 100 + rest if rest is not None else None
    # 二十 / 十二 / 二十三
    if "十" in s:
        left, _, right = s.partition("十")
        tens = 1 if not left else _CN_DIGITS.get(left)
        if tens is None:
            return None
        if not right:
            return tens * 10
        ones = _CN_DIGITS.get(right)
        return tens * 10 + ones if ones is not None and len(right) == 1 else None
    if len(s) == 1 and s in _CN_DIGITS:
        return _CN_DIGITS[s]
    return None


def format_order_no(raw: str) -> str:
    """展示唯一形态：无空格「第{N}号」（阿拉伯数字）。无法解析则返回空串。

    不含发文字号结构（〔〕等）；纯数字或中文数字按 N 补成「第N号」。
    """
    s = (raw or "").strip()
    if not s:
        return ""
    # 发文字号形态一律拒绝
    if "〔" in s or "〕" in s or "[" in s or "]" in s:
        return ""
    m = _ORDER_NO_RE.fullmatch(s) or _ORDER_NO_RE.search(s)
    if m and re.fullmatch(r"第\s*[0-9〇零一二三四五六七八九十百两]+\s*号", s):
        n = _cn_numeral_to_int(m.group(1))
        return f"第{n}号" if n is not None else ""
    if s.isdigit():
        return f"第{int(s)}号"
    n = _cn_numeral_to_int(s)
    if n is not None:
        return f"第{n}号"
    return ""


def order_export_basename(ir: LayoutIR) -> str:
    """命令导出文件名：标志 + 令号。例：江州市人民政府令第1号.docx"""
    mark = (ir.primary_org_mark() or "").strip() or "命令"
    ono = format_order_no(ir.order_no)
    stem = _WIN_BAD_CHARS.sub("", mark + ono).strip(" .") or "命令"
    return stem + ".docx"


def mark_is_order(mark: str) -> bool:
    """发文机关标志是否以「命令」或「令」结尾（baseline §1）。"""
    t = (mark or "").strip()
    if not t:
        return False
    # 正文套语，不是发文机关标志
    if t in {"此令", "特此令", "令"}:
        return False
    if t.endswith("命令"):
        return len(t) <= 40
    if t.endswith("令") and not t.endswith("纪要"):
        # 排除过长正文行；过短如「市令」也不当标志
        return 4 <= len(t) <= 40 and not t.startswith("关于")
    return False


def looks_like_order(
    *,
    org_marks: list[str] | None = None,
    source_text: str = "",
) -> bool:
    """baseline §1：仅按标志槽以「命令/令」结尾判定；不因正文偶现「命令」误切。"""
    for m in org_marks or []:
        if mark_is_order(m):
            return True
    # 原文前若干行：独立成行的短标志
    for line in (source_text or "").splitlines()[:20]:
        s = line.strip()
        if mark_is_order(s):
            return True
    return False


def ensure_order_mark(mark: str) -> str:
    """已以命令/令结尾则不重复拼接；剥误带的「文件」。"""
    t = (mark or "").strip()
    if not t:
        return ""
    if t.endswith("文件"):
        t2 = t[: -len("文件")].strip()
        if mark_is_order(t2):
            return t2
    return t


def strip_signer_title(raw: str) -> str:
    """职务行只留职衔；去掉「市长　张明远」类姓名。"""
    t = (raw or "").strip()
    if not t:
        return ""
    # 已是纯短职务
    if "　" in t or "  " in t:
        t = re.split(r"[\s　]+", t, maxsplit=1)[0].strip()
    else:
        m = _TITLE_STRIP_NAME_RE.match(t)
        if m and len(m.group(1)) <= 12:
            t = m.group(1).strip()
    return t.strip("：:、，,")


def extract_order_no(source_text: str, *, doc_number: str = "") -> str:
    formatted = format_order_no(doc_number)
    if formatted:
        return formatted
    for line in (source_text or "").splitlines()[:40]:
        formatted = format_order_no(line.strip())
        if formatted:
            return formatted
    return ""


def normalize_order_signers(raw: list[str] | str | None) -> list[str]:
    """归一职务列表；顿号/逗号拆分；去姓名。"""
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = [p.strip() for p in re.split(r"[、，,；;]+", raw) if p.strip()]
    else:
        parts = [str(p).strip() for p in raw if str(p).strip()]
    out: list[str] = []
    for p in parts:
        title = strip_signer_title(p)
        if title:
            out.append(title)
    return out


def apply_order_to_ir(
    ir: LayoutIR,
    source_text: str = "",
    *,
    model: Any | None = None,
) -> LayoutIR:
    """识别命中后写入命令字段；不改动非命令 IR。"""
    # 模型侧已挂命令字段时也强制切入
    model_order = bool(
        model is not None
        and (
            getattr(model, "_order_no", None)
            or getattr(model, "_order_signers", None)
            or getattr(model, "_is_order", False)
        )
    )
    if not model_order and not looks_like_order(
        org_marks=ir.org_marks,
        source_text=source_text,
    ):
        return ir

    ir.doc_kind = DocKind.ORDER
    ir.seal_mode = None
    # 公布令主体不排主送；有则进版记
    if ir.recipient.strip():
        ir.recipients_in_footer = True

    marks = [ensure_order_mark(m) for m in (ir.org_marks or [])]
    marks = [m for m in marks if m]
    if not marks and model is not None:
        om = getattr(getattr(model, "header", None), "org_mark", "") or ""
        if mark_is_order(om):
            marks = [ensure_order_mark(om)]
    if not marks:
        for line in (source_text or "").splitlines()[:20]:
            s = line.strip()
            if mark_is_order(s):
                marks = [s]
                break
    ir.org_marks = marks

    if model is not None:
        ono = getattr(model, "_order_no", "") or ""
        if ono and not ir.order_no.strip():
            ir.order_no = format_order_no(str(ono)) or str(ono).strip()
        titles = getattr(model, "_order_signers", None)
        if titles:
            ir.signers = normalize_order_signers(list(titles))
        sdk_cc = getattr(model, "_sdk_cc", "") or ""
        if sdk_cc and not ir.cc_recipients.strip():
            ir.cc_recipients = str(sdk_cc).strip()

    if not ir.order_no.strip():
        ir.order_no = extract_order_no(source_text, doc_number=ir.doc_number)
    else:
        ir.order_no = format_order_no(ir.order_no) or ir.order_no

    # 令号槽占用发文字号时清空，避免通用校验干扰
    if format_order_no(ir.doc_number) or "〔" in (ir.doc_number or "") or "］" in (ir.doc_number or ""):
        ir.doc_number = ""
    ir.doc_number = ""

    # 命令 signers = 职务；若仍像「市长　张三」则剥姓名
    if ir.signers:
        ir.signers = normalize_order_signers(ir.signers)

    # 命令不排标题/机关署名
    ir.title = ""
    ir.org_signature = ""
    return ir


def order_payload_fields(ir: LayoutIR) -> dict[str, Any]:
    return {
        "doc_kind": ir.doc_kind.value if ir.doc_kind else DocKind.GENERAL.value,
        "order_no": format_order_no(ir.order_no) or ir.order_no,
        "signer_titles": list(ir.signers or []),
    }
