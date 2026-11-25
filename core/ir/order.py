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


DEFAULT_ORDER_MARK_SUFFIX = "令"


def extract_order_mark_suffix(raw: str) -> str:
    """从标志文本取尾缀：命令 / 令；无则空串。"""
    t = (raw or "").strip()
    if t.endswith("命令"):
        return "命令"
    if t.endswith("令") and not t.endswith("纪要"):
        return "令"
    return ""


def strip_order_mark_suffix(raw: str) -> str:
    """剥掉末尾「命令」或「令」（命令优先）。"""
    t = (raw or "").strip()
    if t.endswith("命令"):
        return t[: -len("命令")].rstrip(" 　")
    if t.endswith("令") and not t.endswith("纪要"):
        return t[:-1].rstrip(" 　")
    return t


def parse_order_org_marks(
    raw: str | list[str] | None,
    *,
    default_suffix: str = DEFAULT_ORDER_MARK_SUFFIX,
) -> tuple[list[str], str]:
    """拆联合机关 + 抽尾缀。

    返回 (干净机关名列表, 令|命令)。缺尾缀时用 default_suffix（默认「令」）。
    拆分：顿号/逗号；亦兼容全角空格分隔的双机关行。
    """
    if raw is None:
        return [], default_suffix
    if isinstance(raw, list):
        parts = [str(p).strip() for p in raw if str(p).strip()]
        joined = "、".join(parts)
    else:
        joined = str(raw).strip()
        parts = []

    suffix = extract_order_mark_suffix(joined)
    body = strip_order_mark_suffix(joined) if suffix else joined

    if not parts:
        # 顿号/逗号优先；否则按 2+ 全角/多空格切开（联合红头常见）
        if re.search(r"[、，,]", body):
            parts = [p.strip() for p in re.split(r"[、，,]+", body) if p.strip()]
        else:
            parts = [p.strip() for p in re.split(r"[\s　]{2,}|\s*　\s*", body) if p.strip()]
            if len(parts) == 1 and "　" in body:
                parts = [p.strip() for p in body.split("　") if p.strip()]

    names: list[str] = []
    for p in parts:
        n = strip_order_mark_suffix(ensure_order_mark(p) or p).strip()
        if n:
            names.append(n)
    if not names and body.strip():
        names = [body.strip()]

    if not suffix:
        suffix = default_suffix if names else ""
    return names, suffix


def compose_order_mark(names: list[str], suffix: str) -> str:
    """单机关：名+后缀；联合展示串（UI）：顿号连接 + 后缀。"""
    s = (suffix or DEFAULT_ORDER_MARK_SUFFIX).strip() or DEFAULT_ORDER_MARK_SUFFIX
    clean = [strip_order_mark_suffix(n).strip() for n in names if str(n).strip()]
    clean = [n for n in clean if n]
    if not clean:
        return ""
    if len(clean) == 1:
        return clean[0] + s
    return "、".join(clean) + s


def order_export_basename(ir: LayoutIR) -> str:
    """命令导出文件名：标志 + 令号。例：江州市人民政府令第1号.docx"""
    suffix = (getattr(ir, "order_mark_suffix", "") or "").strip() or DEFAULT_ORDER_MARK_SUFFIX
    names = [str(m).strip() for m in (ir.org_marks or []) if str(m).strip()]
    mark = compose_order_mark(names, suffix) or "命令"
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
    # 联合标志可较长（多机关全称 + 令）
    max_len = 120 if ("、" in t or "　" in t) else 40
    if t.endswith("命令"):
        return len(t) <= max_len
    if t.endswith("令") and not t.endswith("纪要"):
        # 排除过长正文行；过短如「市令」也不当标志
        return 4 <= len(t) <= max_len and not t.startswith("关于")
    return False


def looks_like_order(
    *,
    org_marks: list[str] | None = None,
    source_text: str = "",
    order_mark_suffix: str = "",
) -> bool:
    """baseline §1：仅按标志槽以「命令/令」结尾判定；不因正文偶现「命令」误切。"""
    suffix = (order_mark_suffix or "").strip()
    marks = [str(m).strip() for m in (org_marks or []) if str(m).strip()]
    if marks and suffix in {"令", "命令"}:
        return True
    for m in marks:
        if mark_is_order(m):
            return True
        # 多机关已剥尾缀时，拼回再判
        if len(marks) >= 2 and mark_is_order(compose_order_mark(marks, DEFAULT_ORDER_MARK_SUFFIX)):
            return True
    for line in (source_text or "").splitlines()[:20]:
        s = line.strip()
        if mark_is_order(s):
            return True
    # 无换行：文首「…令」+「第N号」
    head = (source_text or "")[:240]
    if re.search(
        r"[\u4e00-\u9fa5（）]{4,30}(?:命令|令)\s*第\s*[0-9〇零一二三四五六七八九十百两]+\s*号",
        head,
    ) and "〔" not in head and "[" not in head:
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


def order_mark_ok(ir: LayoutIR) -> bool:
    """导出门槛：有机关名，且能还原为以令/命令结尾的标志。"""
    names = [str(m).strip() for m in (ir.org_marks or []) if str(m).strip()]
    if not names:
        return False
    suffix = (getattr(ir, "order_mark_suffix", "") or "").strip()
    if suffix not in {"令", "命令"}:
        # 兼容尚未拆尾缀的旧 IR：名本身已带令/命令
        if len(names) == 1 and mark_is_order(names[0]):
            return True
        suffix = DEFAULT_ORDER_MARK_SUFFIX
    composed = compose_order_mark(names, suffix)
    return bool(composed) and (
        mark_is_order(composed) or (len(names) >= 2 and suffix in {"令", "命令"})
    )


def strip_signer_title(raw: str) -> str:
    """职务行只留职衔；去掉「市长　张明远」「部长：孟桂英」类姓名。"""
    t = (raw or "").strip()
    if not t:
        return ""
    # 部长：姓名 / 市长:姓名
    if "：" in t or ":" in t:
        t = re.split(r"[:：]", t, maxsplit=1)[0].strip()
    # 已是纯短职务；或「职务　姓名」
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

    raw_marks = [ensure_order_mark(m) for m in (ir.org_marks or [])]
    raw_marks = [m for m in raw_marks if m]
    if not raw_marks and model is not None:
        om = getattr(getattr(model, "header", None), "org_mark", "") or ""
        if mark_is_order(om) or "、" in om:
            raw_marks = [ensure_order_mark(om)]
    if not raw_marks:
        for line in (source_text or "").splitlines()[:20]:
            s = line.strip()
            if mark_is_order(s):
                raw_marks = [s]
                break

    model_suffix = ""
    if model is not None:
        model_suffix = str(getattr(model, "_order_mark_suffix", "") or "").strip()
        ono = getattr(model, "_order_no", "") or ""
        if ono and not ir.order_no.strip():
            ir.order_no = format_order_no(str(ono)) or str(ono).strip()
        titles = getattr(model, "_order_signers", None)
        if titles:
            ir.signers = normalize_order_signers(list(titles))
        sdk_cc = getattr(model, "_sdk_cc", "") or ""
        if sdk_cc and not ir.cc_recipients.strip():
            ir.cc_recipients = str(sdk_cc).strip()
        model_names = getattr(model, "_order_org_marks", None)
        if model_names:
            raw_marks = [str(x).strip() for x in model_names if str(x).strip()] or raw_marks

    names, suffix = parse_order_org_marks(
        raw_marks if len(raw_marks) > 1 else (raw_marks[0] if raw_marks else ""),
        default_suffix=model_suffix or DEFAULT_ORDER_MARK_SUFFIX,
    )
    if model_suffix in {"令", "命令"}:
        suffix = model_suffix
    if not names and raw_marks:
        names, suffix2 = parse_order_org_marks("、".join(raw_marks))
        if not suffix or suffix == DEFAULT_ORDER_MARK_SUFFIX:
            suffix = suffix2
    ir.org_marks = names
    ir.order_mark_suffix = suffix if suffix in {"令", "命令"} else DEFAULT_ORDER_MARK_SUFFIX

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
