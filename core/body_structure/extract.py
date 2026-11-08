# -*- coding: utf-8 -*-
"""从全文抽取正文段落。

优先级（从稳到弱）：
1. 模型字段的字符偏移 start/end（SDK 自带）
2. 文首区域内的「首次」文本锚点（主送 > 标题）
3. 版式启发式（主送冒号行、附件/抄送/落款）
4. 失败时保守裁切首尾，绝不把整篇当一段（除非全文极短）

层级识别不在此文件；见 parser.parse_body_blocks。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


# 全角/半角括号都认
_STRUCT_START = re.compile(
    r"^(?:"
    r"[一二三四五六七八九十百]+[、．.]"
    r"|[（(][一二三四五六七八九十百]+[）)]"
    r"|[（(]\d+[）)]"
    r"|\d+[．.、]"
    r")"
)

_ATTACH = re.compile(r"^附件\s*[:：]")
_CC = re.compile(r"^抄送\s*[:：]")
_NOTE = re.compile(r"^[（(]\s*此件")
_DATE_LINE = re.compile(r"^\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日\s*$")
_PRINT_TAIL = re.compile(r"印发\s*$")
_DOC_NO = re.compile(r"[〔\[]\d{4}[〕\]].*号")


def _flat(s: str) -> str:
    return (
        (s or "")
        .replace(" ", "")
        .replace("\u3000", "")
        .replace("\t", "")
        .replace("\r", "")
    )


def _norm_punct(s: str) -> str:
    """半角括号等归一，便于匹配。"""
    return (
        (s or "")
        .replace("(", "（")
        .replace(")", "）")
        .replace(",", "，")
        .replace(":", "：")
    )


def _is_struct_line(s: str) -> bool:
    return bool(_STRUCT_START.match(_norm_punct(s.strip())))


@dataclass
class FieldSpan:
    name: str
    text: str
    start: int  # 字符偏移，含
    end: int  # 不含
    probability: float = 0.0


def _items_to_spans(result: dict[str, Any] | None, key: str) -> list[FieldSpan]:
    out: list[FieldSpan] = []
    for it in (result or {}).get(key) or []:
        try:
            start = int(it.get("start", -1))
            end = int(it.get("end", -1))
        except (TypeError, ValueError):
            continue
        text = str(it.get("text") or "")
        if start < 0 or end <= start:
            continue
        out.append(
            FieldSpan(
                name=key,
                text=text,
                start=start,
                end=end,
                probability=float(it.get("probability") or 0),
            )
        )
    return out


def _first_text(result: dict[str, Any] | None, key: str) -> str:
    spans = _items_to_spans(result, key)
    if spans:
        return _flat(spans[0].text.replace("\n", ""))
    # 兼容只传了清洗后字符串的调用
    return ""


def _build_line_index(text: str) -> tuple[list[str], list[tuple[int, int]]]:
    """返回 (行文本列表, 每行 [start,end) 字符区间)。"""
    lines: list[str] = []
    spans: list[tuple[int, int]] = []
    i = 0
    for ln in (text or "").splitlines(keepends=True):
        raw = ln[:-1] if ln.endswith("\n") else ln
        if ln.endswith("\r\n"):
            raw = ln[:-2]
        elif ln.endswith("\n") or ln.endswith("\r"):
            raw = ln[:-1]
        start = i
        end = i + len(raw)
        lines.append(raw.rstrip())
        spans.append((start, end))
        i += len(ln)
    if not lines and text:
        lines = [text]
        spans = [(0, len(text))]
    return lines, spans


def _char_to_line(spans: list[tuple[int, int]], pos: int, *, prefer_end: bool = False) -> int:
    """字符偏移 → 行号。prefer_end：落在边界时偏后一行（用于 body 起点）。"""
    if not spans:
        return 0
    if pos <= spans[0][0]:
        return 0
    for i, (a, b) in enumerate(spans):
        if a <= pos < b:
            return i
        if pos == b:
            return i + 1 if prefer_end and i + 1 < len(spans) else i
    return len(spans) - 1


def _pick_body_start_by_offsets(
    spans_map: list[tuple[int, int]],
    result: dict[str, Any],
) -> int | None:
    """正文起点：主送 end 优先，否则标题 end。取文首出现的那条（start 最小）。"""
    candidates: list[tuple[int, int]] = []  # (char_end, priority) priority 小更优先用主送
    for sp in _items_to_spans(result, "主送机关"):
        candidates.append((sp.end, 0))
    for sp in _items_to_spans(result, "标题"):
        candidates.append((sp.end, 1))
    if not candidates:
        return None
    # 同一优先级取字符位置更靠前的；主送优先于标题
    candidates.sort(key=lambda x: (x[1], x[0]))
    char_end = candidates[0][0]
    # 只接受落在全文前 55% 的锚点，防止模型偶发错位
    total = spans_map[-1][1] if spans_map else 0
    if total and char_end > total * 0.55:
        # 若主送不合理，尝试标题
        for char_end2, pri in candidates:
            if char_end2 <= total * 0.55:
                return _char_to_line(spans_map, char_end2, prefer_end=True)
        return None
    return _char_to_line(spans_map, char_end, prefer_end=True)


def _pick_body_end_by_offsets(
    spans_map: list[tuple[int, int]],
    result: dict[str, Any],
    body_start_line: int,
) -> int | None:
    """正文终点：附件/署名/成文日期/附注/抄送/印发 中，取「在起点之后」最早出现的 start。"""
    keys = ["附件说明", "发文机关署名", "成文日期", "附注", "抄送机关", "印发机关", "印发日期"]
    total = spans_map[-1][1] if spans_map else 0
    start_char = spans_map[body_start_line][0] if body_start_line < len(spans_map) else 0

    ends: list[int] = []
    for key in keys:
        for sp in _items_to_spans(result, key):
            if sp.start <= start_char:
                continue
            # 成文日期若出现在文首（极少）忽略；印发日期可在文末
            if key == "成文日期" and total and sp.start < total * 0.35:
                continue
            ends.append(sp.start)
    if not ends:
        return None
    char_start = min(ends)
    return _char_to_line(spans_map, char_start, prefer_end=False)


def _find_first_line(lines: list[str], needle: str, lo: int, hi: int) -> int | None:
    """在 [lo, hi) 内找 needle 首次出现的行（扁平化包含匹配）。"""
    n = _flat(_norm_punct(needle))
    if len(n) < 4:
        return None
    # 用较长前缀，减少「人民政府办」误伤；但允许标题被截断
    prefix = n[: min(16, len(n))]
    for i in range(lo, min(hi, len(lines))):
        if prefix in _flat(_norm_punct(lines[i])):
            return i
    return None


def _heuristic_start(lines: list[str]) -> int:
    header_hi = max(6, min(len(lines), int(len(lines) * 0.45) + 1))
    # 主送：文首区以冒号结尾的行
    for i in range(header_hi):
        s = lines[i].strip()
        if len(s) >= 4 and (s.endswith("：") or s.endswith(":")) and "抄送" not in s:
            # 像「各…：」「市政府：」
            if "各" in s or s.endswith("政府：") or s.endswith("厅：") or s.endswith("局："):
                return i + 1
    # 文号行 / 标题粘连行
    start = 0
    if lines and (_DOC_NO.search(lines[0]) or "关于" in lines[0]):
        start = 1
    if start < len(lines) and (lines[start].endswith("：") or lines[start].endswith(":")):
        start += 1
    return start


def _heuristic_end(lines: list[str], start: int) -> int:
    end = len(lines)
    for i in range(len(lines) - 1, start - 1, -1):
        s = lines[i].strip()
        if not s:
            continue
        if _ATTACH.match(s) or _CC.match(s) or _NOTE.match(s):
            end = i
            continue
        if _PRINT_TAIL.search(s) or "秘书科" in s:
            end = min(end, i)
            continue
        if _DATE_LINE.match(_flat(s).replace("年", "年").replace(" ", "")) or _DATE_LINE.match(s.replace(" ", "")):
            end = min(end, i)
            continue
    return end


def _resolve_window(
    text: str,
    lines: list[str],
    line_spans: list[tuple[int, int]],
    *,
    result: dict[str, Any] | None,
    title: str,
    recipient: str,
    date: str,
    org_signature: str,
) -> tuple[int, int]:
    result = result or {}
    n = len(lines)
    if n == 0:
        return 0, 0

    # ---- 1) 模型偏移 ----
    start = _pick_body_start_by_offsets(line_spans, result)
    end = _pick_body_end_by_offsets(line_spans, result, start or 0) if start is not None else None

    # ---- 2) 文首首次文本锚点 ----
    header_hi = max(8, min(n, int(n * 0.45) + 1))
    if start is None:
        recip = recipient or _first_text(result, "主送机关")
        tit = title or _first_text(result, "标题")
        hit_r = _find_first_line(lines, recip, 0, header_hi) if recip else None
        hit_t = _find_first_line(lines, tit, 0, header_hi) if tit else None
        if hit_r is not None:
            start = hit_r + 1
        elif hit_t is not None:
            start = hit_t + 1
        else:
            start = _heuristic_start(lines)

    if end is None:
        # 文末区文本锚点：取最早（最靠前）的落款类行
        tail_lo = max(start, int(n * 0.4))
        cand: list[int] = []
        for key, val in (
            ("附件说明", ""),
            ("发文机关署名", org_signature),
            ("成文日期", date),
            ("附注", ""),
            ("抄送机关", ""),
        ):
            needle = val or _first_text(result, key)
            if key == "附件说明":
                for i in range(tail_lo, n):
                    if _ATTACH.match(lines[i].strip()):
                        cand.append(i)
                        break
                continue
            if not needle:
                continue
            hit = _find_first_line(lines, needle, tail_lo, n)
            if hit is not None:
                cand.append(hit)
        for i in range(tail_lo, n):
            s = lines[i].strip()
            if _CC.match(s) or _NOTE.match(s) or "秘书科" in s or _PRINT_TAIL.search(s):
                cand.append(i)
        end = min(cand) if cand else _heuristic_end(lines, start)

    # 校正
    start = max(0, min(start, n))
    end = max(0, min(end, n))
    if end <= start:
        start = min(_heuristic_start(lines), max(0, n - 3))
        end = max(start + 1, _heuristic_end(lines, start))
        if end <= start:
            start = min(1, n)
            end = max(start, n - 2)

    return start, end


def _merge_soft_wraps(filtered: list[str]) -> list[str]:
    def _struct_complete(prev: str) -> bool:
        t = _norm_punct(prev.strip())
        if t.endswith(("。", "；", ";", "！", "？")):
            return True
        rest = _STRUCT_START.sub("", t).strip()
        if not rest:
            return False
        if len(rest) <= 2:
            return False
        if rest[-1] in "的各与和及为在对从被将把按依":
            return False
        if len(t) <= 20:
            return True
        return False

    paras: list[str] = []
    for s in filtered:
        if not s:
            continue
        s = _norm_punct(s)
        if not paras:
            paras.append(s)
            continue
        if _is_struct_line(s):
            paras.append(s)
            continue
        prev = paras[-1]
        if _is_struct_line(prev) and _struct_complete(prev) and len(prev) <= 30:
            paras.append(s)
            continue
        if _is_struct_line(prev) and not _struct_complete(prev):
            paras[-1] = prev + s.lstrip()
            continue
        # 普通断行：上一段未结束标点则合并
        if not prev.endswith(("。", "！", "？", "；", ";", "：", ":")):
            paras[-1] = (prev[:-1] + s.lstrip()) if prev.endswith("-") else (prev + s.lstrip())
        else:
            paras.append(s)
    return paras


def _split_inline_structures(paras: list[str]) -> list[str]:
    split_out: list[str] = []
    for p in paras:
        parts = re.split(
            r"(?<=[。；;])\s*(?=[一二三四五六七八九十百]+[、．.]|[（(][一二三四五六七八九十百]+[）)])",
            p,
        )
        for part in parts:
            part = part.strip()
            if part:
                split_out.append(part)
    return split_out


def extract_body_paragraphs(
    text: str,
    *,
    title: str = "",
    recipient: str = "",
    date: str = "",
    org_signature: str = "",
    sdk_result: dict[str, Any] | None = None,
) -> list[str]:
    """标题/主送之后、附件/落款之前 → 正文段落列表。"""
    text = text or ""
    if not text.strip():
        return []

    lines, line_spans = _build_line_index(text)
    start, end = _resolve_window(
        text,
        lines,
        line_spans,
        result=sdk_result,
        title=title,
        recipient=recipient,
        date=date,
        org_signature=org_signature,
    )

    body_lines = [ln.strip() for ln in lines[start:end]]

    # 主送已单独入 LayoutIR：正文里再出现则丢掉（防模型偏移切在冒号前）
    recip_flat = _flat(_norm_punct(recipient or _first_text(result or {}, "主送机关")))
    recip_flat = recip_flat.rstrip("：:")

    filtered: list[str] = []
    for s in body_lines:
        if not s:
            continue
        if _ATTACH.match(s) or _CC.match(s) or _NOTE.match(s):
            break
        s_flat = _flat(_norm_punct(s)).rstrip("：:")
        if recip_flat and len(recip_flat) >= 4 and (
            s_flat == recip_flat or s_flat.startswith(recip_flat) and len(s_flat) <= len(recip_flat) + 1
        ):
            continue
        filtered.append(s)

    paras = _merge_soft_wraps(filtered)
    split_out = _split_inline_structures(paras)

    if split_out:
        return split_out

    # 最后兜底：不要整篇；尽量返回中间部分按行
    mid = [ln.strip() for ln in lines[min(2, len(lines)) : max(2, len(lines) - 3)] if ln.strip()]
    return mid or ([text.strip()] if len(text.strip()) < 80 else mid)
