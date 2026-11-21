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
_ATTACH_ANY = re.compile(r"附件\s*[:：]")
_CC = re.compile(r"^抄送\s*[:：]")
_CC_ANY = re.compile(r"抄送\s*[:：]")
_NOTE = re.compile(r"^[（(]\s*此件")
_NOTE_ANY = re.compile(r"[（(]\s*此件")
_DATE_LINE = re.compile(r"^\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日\s*$")
_DATE_ANY = re.compile(r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日")
_PRINT_TAIL = re.compile(r"印发\s*$")
_PRINT_ANY = re.compile(r".{2,40}印发\s*$", re.M)
_DOC_NO = re.compile(r"[〔\[]\d{4}[〕\]].*号")
_RECIP_TAIL = re.compile(r"各[^：:\n]{0,60}[：:]")
_MINUTES_LIST = re.compile(r"^(出席|请假|列席)\s*[:：]")
_MINUTES_LIST_ANY = re.compile(r"(?:^|\n)(出席|请假|列席)\s*[:：]")
_SECRET_LINE = re.compile(
    r"^(绝密|机密|秘密)(?:\s*[★*]\s*(长期|\d{1,3}年|\d{1,3}个月))?$"
)
_URGENCY_LINE = re.compile(r"^(特提|特急|加急|平急)(?:文件)?$")
_COPY_LINE = re.compile(r"^\d{6}$")
_ISSUE_LINE = re.compile(r"^第\s*\d+\s*期$")
_MARK_LINE = re.compile(r"^[\u4e00-\u9fa5A-Za-z0-9（）()\-·、]{2,40}纪要$")
# 命令令号行（阿拉伯/中文数字）
_ORDER_NO_LINE = re.compile(
    r"^第\s*[0-9〇零一二三四五六七八九十百两]+\s*号\s*$"
)
_ORDER_MARK_TAIL = re.compile(r"(?:命令|令)$")


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


def _find_substr(text: str, needle: str, *, lo: int = 0, hi: int | None = None) -> int | None:
    """在 text[lo:hi] 找 needle 首次出现；先精确，再去空白匹配。"""
    if not needle or not text:
        return None
    hi = len(text) if hi is None else min(hi, len(text))
    lo = max(0, lo)
    if lo >= hi:
        return None
    chunk = text[lo:hi]
    exact = needle
    i = chunk.find(exact)
    if i >= 0:
        return lo + i
    # 去空白：在原文上滑窗对齐 flat(needle)
    flat_n = _flat(_norm_punct(needle))
    if len(flat_n) < 4:
        return None
    flat_c = []
    map_idx = []  # flat 下标 → 原文下标
    for j, ch in enumerate(chunk):
        if ch in " \t\u3000\r":
            continue
        flat_c.append(ch)
        map_idx.append(lo + j)
    flat_s = _flat(_norm_punct("".join(flat_c)))
    # flat_c 已无空白，再 norm
    flat_joined = "".join(flat_c)
    flat_joined = _norm_punct(flat_joined).replace(" ", "")
    k = flat_joined.find(flat_n)
    if k < 0:
        # 用较短前缀
        prefix = flat_n[: min(12, len(flat_n))]
        k = flat_joined.find(prefix)
        if k < 0:
            return None
    return map_idx[k] if k < len(map_idx) else None


def _skip_colon_ws(text: str, pos: int) -> int:
    """跳过字段后残留的空白与全角/半角冒号（模型 end 常不含冒号）。"""
    n = len(text)
    while pos < n and text[pos] in " \t\u3000":
        pos += 1
    if pos < n and text[pos] in "：:":
        pos += 1
        while pos < n and text[pos] in " \t\u3000":
            pos += 1
    return pos


def _is_standalone_date_at(text: str, start: int, end: int) -> bool:
    """成文日期锚点：必须像独立日期，排除「2025年11月25日下午…」正文起句。"""
    n = len(text or "")
    if start < 0 or end > n or end <= start:
        return False
    left = text[start - 1] if start > 0 else "\n"
    right = text[end] if end < n else "\n"
    if left not in "\n\r\t\u3000 ":
        return False
    # 日期后若紧跟「下午/上午/晚上/召开」等，是正文叙事，不是落款日期
    tail = text[end : end + 4]
    if re.match(r"^(上午|下午|晚上|傍晚|召开|，|,|、)", tail):
        return False
    if right not in "\n\r\t\u3000 （(":
        return False
    return True


def _is_header_noise_line(s: str, *, org_mark: str = "", title: str = "") -> bool:
    """文首版头行：不应进入正文。"""
    t = (s or "").replace("\u3000", " ").strip()
    if not t:
        return True
    if _COPY_LINE.fullmatch(t) or _SECRET_LINE.fullmatch(t) or _URGENCY_LINE.fullmatch(t):
        return True
    if _ISSUE_LINE.fullmatch(t):
        return True
    if _MARK_LINE.fullmatch(t):
        return True
    flat_t = _flat(_norm_punct(t)).rstrip("：:")
    for needle in (org_mark, title):
        n = _flat(_norm_punct(needle or "")).rstrip("：:")
        if n and len(n) >= 4 and (flat_t == n or flat_t.startswith(n) and len(flat_t) <= len(n) + 2):
            return True
    # 单独主送/抄送式短行（如「局属各单位：」）
    if (t.endswith("：") or t.endswith(":")) and len(t) <= 40 and not _is_struct_line(t):
        if "如下" in t:
            return False
        return True
    return False


def _after_field(text: str, start: int, field_len: int) -> int:
    """字段结束后跳过空白与全角/半角冒号。"""
    return _skip_colon_ws(text, start + field_len)


def _resolve_char_window(
    text: str,
    *,
    result: dict[str, Any] | None,
    title: str,
    recipient: str,
    date: str,
    org_signature: str,
) -> tuple[int, int, dict[str, Any]]:
    """正文窗口按字符偏移，兼容主送与正文粘在同一行。

    返回 (start, end, diag)；diag 供开发者溯源。
    """
    result = result or {}
    n = len(text or "")
    diag: dict[str, Any] = {
        "start_rule": "",
        "start_label": "",
        "end_rule": "",
        "end_label": "",
        "end_candidates": [],
    }
    if n == 0:
        diag["start_rule"] = "empty"
        diag["start_label"] = "空文本"
        diag["end_rule"] = "empty"
        diag["end_label"] = "空文本"
        return 0, 0, diag
    header_hi = max(80, min(n, int(n * 0.55) + 40))

    # ---- start ----
    start: int | None = None
    # 1) 模型偏移：主送 > 标题 > 令号（命令无主送/标题时用令号）
    cand_starts: list[tuple[int, int, str]] = []
    for sp in _items_to_spans(result, "主送机关"):
        if sp.end <= header_hi:
            cand_starts.append((0, sp.end, "主送机关"))
    for sp in _items_to_spans(result, "标题"):
        if sp.end <= header_hi:
            cand_starts.append((1, sp.end, "标题"))
    for sp in _items_to_spans(result, "令号"):
        if sp.end <= header_hi:
            cand_starts.append((2, sp.end, "令号"))
    if cand_starts:
        cand_starts.sort()
        # 模型主送 end 常不含冒号 → 正文会以单独「：」起头
        start = _skip_colon_ws(text, cand_starts[0][1])
        field_n = cand_starts[0][2]
        diag["start_rule"] = f"model:{field_n}.end"
        diag["start_label"] = f"模型偏移：{field_n} 结束处"

    # 2) 文首文本锚点
    if start is None:
        recip = (recipient or _first_text(result, "主送机关")).strip()
        tit = (title or _first_text(result, "标题")).strip()
        if recip:
            core = recip.rstrip("：:").strip()
            hit = _find_substr(text, recip, lo=0, hi=header_hi)
            if hit is None and core:
                hit = _find_substr(text, core, lo=0, hi=header_hi)
            if hit is not None:
                # 若命中的是带冒号版本
                if text.startswith(recip, hit):
                    start = _after_field(text, hit, len(recip))
                else:
                    start = _after_field(text, hit, len(core))
                diag["start_rule"] = "anchor:主送机关"
                diag["start_label"] = "文本锚点：主送机关之后"
        if start is None and tit:
            hit = _find_substr(text, tit, lo=0, hi=header_hi)
            if hit is not None:
                start = _after_field(text, hit, len(tit))
                diag["start_rule"] = "anchor:标题"
                diag["start_label"] = "文本锚点：标题之后"

    # 2b) 命令：令号文本 / 独立「第N号」行之后
    if start is None:
        ono = _first_text(result, "令号").strip()
        if ono:
            hit = _find_substr(text, ono, lo=0, hi=header_hi)
            if hit is not None:
                start = _after_field(text, hit, len(ono))
                diag["start_rule"] = "anchor:令号"
                diag["start_label"] = "文本锚点：令号之后"
        if start is None:
            lines, line_spans = _build_line_index(text)
            for i, ln in enumerate(lines[:20]):
                if not _ORDER_NO_LINE.match((ln or "").strip()):
                    continue
                # 行尾之后（跳过换行）即为正文起点
                start = line_spans[i][1]
                while start < n and text[start] in "\r\n":
                    start += 1
                diag["start_rule"] = "anchor:令号行"
                diag["start_label"] = "文本锚点：令号行之后"
                break

    # 3) 启发式：文首「各…：」
    if start is None:
        m = _RECIP_TAIL.search(text[:header_hi])
        if m:
            start = m.end()
            diag["start_rule"] = "heuristic:recipient_colon"
            diag["start_label"] = "启发式：文首「各…：」行末"

    if start is None:
        # 命令味版头：宁可从标志后第一段起，也不要盲砍 20 字误伤正文
        mark0 = _first_text(result, "发文机关标志").strip()
        if _ORDER_MARK_TAIL.search(mark0):
            hit = _find_substr(text, mark0, lo=0, hi=header_hi)
            if hit is not None:
                start = _after_field(text, hit, len(mark0))
                diag["start_rule"] = "fallback:order_mark"
                diag["start_label"] = "弱兜底：命令标志之后"
        if start is None:
            start = min(20, max(0, n // 10))
            diag["start_rule"] = "fallback:head_trim"
            diag["start_label"] = "弱兜底：裁切文首一段"

    start = max(0, min(start, n))
    start = _skip_colon_ws(text, start)

    # ---- end：起点之后最早的落款/附件/纪要名单类锚点 ----
    end_cands: list[tuple[int, str, str]] = []  # (pos, rule, label)
    for key in (
        "附件说明",
        "签署职务",  # 命令：正文止于职务行前
        "签署姓名",
        "发文机关署名",
        "成文日期",
        "附注",
        "抄送机关",
        "印发机关",
        "印发日期",
        "出席",
        "请假",
        "列席",
    ):
        for sp in _items_to_spans(result, key):
            if sp.start <= start:
                continue
            if key == "成文日期":
                if sp.start < n * 0.35:
                    continue
                if not _is_standalone_date_at(text, sp.start, sp.end):
                    continue
            end_cands.append((sp.start, f"model:{key}.start", f"模型偏移：{key} 开始处"))

    # 命令签署职务/姓名：模型漏偏移时，按整行文本锚点补
    lines_all, line_spans_all = _build_line_index(text)
    for key in ("签署职务", "签署姓名"):
        needle = _first_text(result, key).strip()
        if len(needle) < 2:
            continue
        for i, ln in enumerate(lines_all):
            if (ln or "").strip() != needle:
                continue
            pos = line_spans_all[i][0]
            if pos <= start:
                continue
            end_cands.append((pos, f"anchor:{key}", f"文本锚点：{key}"))

    for rx, rule, label in (
        (_ATTACH_ANY, "regex:附件", "正则：附件说明"),
        (_CC_ANY, "regex:抄送", "正则：抄送"),
        (_NOTE_ANY, "regex:附注", "正则：附注"),
        (_MINUTES_LIST_ANY, "regex:纪要名单", "正则：出席/请假/列席"),
    ):
        m = rx.search(text, start)
        if m:
            pos = m.start(1) if (rx is _MINUTES_LIST_ANY and m.lastindex) else m.start()
            if pos >= start:
                end_cands.append((pos, rule, label))

    needle_date = (date or _first_text(result, "成文日期")).strip()
    if needle_date:
        pos = start
        while True:
            hit = _find_substr(text, needle_date, lo=pos, hi=n)
            if hit is None or hit <= start:
                break
            hit_end = hit + len(needle_date)
            m_at = _DATE_ANY.match(text, hit)
            if m_at:
                hit_end = m_at.end()
            if _is_standalone_date_at(text, hit, hit_end):
                end_cands.append((hit, "anchor:成文日期", "文本锚点：独立成文日期"))
                break
            pos = hit + 1
    else:
        m = _DATE_ANY.search(text, start)
        while m:
            if m.start() >= start + max(30, int((n - start) * 0.25)):
                if _is_standalone_date_at(text, m.start(), m.end()):
                    end_cands.append((m.start(), "regex:日期行", "正则：独立日期行"))
                    break
            m = _DATE_ANY.search(text, m.end())

    sig = (org_signature or _first_text(result, "发文机关署名")).strip()
    if sig and len(sig) >= 4:
        pos = start
        last = None
        while True:
            hit = _find_substr(text, sig, lo=pos, hi=n)
            if hit is None:
                break
            last = hit
            pos = hit + 1
        if last is not None and last >= start + max(20, int((n - start) * 0.2)):
            end_cands.append((last, "anchor:发文机关署名", "文本锚点：发文机关署名"))

    m = _PRINT_ANY.search(text[start:])
    if m:
        end_cands.append((start + m.start(), "regex:印发", "正则：印发行"))

    diag["end_candidates"] = [
        {"pos": p, "rule": r, "label": lb} for p, r, lb in sorted(end_cands, key=lambda x: x[0])[:12]
    ]

    if end_cands:
        end, erule, elabel = min(end_cands, key=lambda x: x[0])
        diag["end_rule"] = erule
        diag["end_label"] = elabel
    else:
        end = n
        diag["end_rule"] = "eof"
        diag["end_label"] = "文末（未找到落款/附件锚点）"

    end = max(0, min(end, n))
    if end <= start:
        start = min(start, max(0, n // 8))
        end = max(start + 1, n - max(10, n // 10))
        diag["start_rule"] = "fallback:window_repair"
        diag["start_label"] = "弱兜底：窗口修复（end≤start）"
        diag["end_rule"] = "fallback:window_repair"
        diag["end_label"] = "弱兜底：窗口修复（end≤start）"
    return start, end, diag


def _merge_soft_wraps(filtered: list[str]) -> list[str]:
    """合并 PDF/复制造成的假换行；结构小标题默认「行尾即结束」。

    仅当结构行明显未写完（只剩序号、极短、或以连写虚字收尾）时，才与下行拼成回行续写。
    「为」不再当作未完成标记，避免「三、禁止行为」被误拼正文。
    """

    def _struct_complete(prev: str) -> bool:
        t = _norm_punct(prev.strip())
        if t.endswith(("。", "；", ";", "！", "？", "：", ":")):
            return True
        rest = _STRUCT_START.sub("", t).strip()
        if not rest:
            return False
        if len(rest) <= 2:
            return False
        # 连写虚字：像「……的」「……和」——真回行续写；不含「为」（行为/认为等成词常见）
        if rest[-1] in "的各与和及在对从被将把按依":
            return False
        # 短结构标题：独占一行即视为写完（回行=标题结束）
        if len(t) <= 30:
            return True
        # 过长又无句末：更像被硬折的长标题，交给合并
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
        # 结构行写完 → 下行另起（不再额外要求 len<=30，与 _struct_complete 一致）
        if _is_struct_line(prev) and _struct_complete(prev):
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


def extract_body_with_trace(
    text: str,
    *,
    title: str = "",
    recipient: str = "",
    date: str = "",
    org_signature: str = "",
    org_mark: str = "",
    sdk_result: dict[str, Any] | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """与 extract_body_paragraphs 相同，额外返回裁切诊断。"""
    paras, diag = _extract_body_impl(
        text,
        title=title,
        recipient=recipient,
        date=date,
        org_signature=org_signature,
        org_mark=org_mark,
        sdk_result=sdk_result,
    )
    return paras, diag


def extract_body_paragraphs(
    text: str,
    *,
    title: str = "",
    recipient: str = "",
    date: str = "",
    org_signature: str = "",
    org_mark: str = "",
    sdk_result: dict[str, Any] | None = None,
) -> list[str]:
    """标题/主送之后、附件/落款之前 → 正文段落列表。

    窗口按字符切，避免「主送与正文同一行」时整段正文被丢到窗外。
    ONNX 只标字段、不标正文；本函数负责裁掉版头/落款。
    """
    paras, _diag = _extract_body_impl(
        text,
        title=title,
        recipient=recipient,
        date=date,
        org_signature=org_signature,
        org_mark=org_mark,
        sdk_result=sdk_result,
    )
    return paras


def _extract_body_impl(
    text: str,
    *,
    title: str = "",
    recipient: str = "",
    date: str = "",
    org_signature: str = "",
    org_mark: str = "",
    sdk_result: dict[str, Any] | None = None,
) -> tuple[list[str], dict[str, Any]]:
    text = text or ""
    empty_diag = {
        "start": 0,
        "end": 0,
        "start_rule": "empty",
        "start_label": "空文本",
        "end_rule": "empty",
        "end_label": "空文本",
        "preview": "",
        "end_candidates": [],
    }
    if not text.strip():
        return [], empty_diag

    sdk_result = sdk_result or {}
    mark = (org_mark or _first_text(sdk_result, "发文机关标志")).strip()
    tit = (title or _first_text(sdk_result, "标题")).strip()
    c0, c1, win_diag = _resolve_char_window(
        text,
        result=sdk_result,
        title=tit,
        recipient=recipient,
        date=date,
        org_signature=org_signature,
    )
    chunk = text[c0:c1]
    # 切段仍按行；粘连样本通常只有 1～2 行
    body_lines = [ln.strip() for ln in chunk.splitlines()]

    recip_flat = _flat(
        _norm_punct(recipient or _first_text(sdk_result, "主送机关"))
    ).rstrip("：:")

    filtered: list[str] = []
    header_strip = True
    for s in body_lines:
        if not s:
            continue
        # 主送冒号被切进正文窗时的孤儿行
        if s in ("：", ":"):
            continue
        if _ATTACH.match(s) or _CC.match(s) or _NOTE.match(s) or _MINUTES_LIST.match(s):
            break
        # 窗起点偏前时，连续丢掉文首版头/标志/主送短行
        if header_strip and _is_header_noise_line(s, org_mark=mark, title=tit):
            continue
        header_strip = False
        # 行内残余「附件：…」截断
        m_att = _ATTACH_ANY.search(s)
        if m_att and m_att.start() > 0:
            s = s[: m_att.start()].rstrip()
            if not s:
                break
        s_flat = _flat(_norm_punct(s)).rstrip("：:")
        if recip_flat and len(recip_flat) >= 4 and (
            s_flat == recip_flat
            or (s_flat.startswith(recip_flat) and len(s_flat) <= len(recip_flat) + 1)
        ):
            continue
        # 行首仍粘着主送时，剥掉主送前缀
        if recip_flat and len(recip_flat) >= 4:
            flat_s = _flat(_norm_punct(s))
            if flat_s.startswith(recip_flat):
                # 按 flat 长度从原文粗剥（允许冒号）
                core = recipient.strip().rstrip("：:") or recip_flat
                hit = s.find(core)
                if hit >= 0:
                    s = s[hit + len(core) :].lstrip("：: \t\u3000")
                else:
                    # 去空白对齐失败则整行丢弃若几乎等于主送
                    if len(flat_s) <= len(recip_flat) + 2:
                        continue
        if s:
            filtered.append(s)

    paras = _merge_soft_wraps(filtered)
    split_out = _split_inline_structures(paras)

    # 保留换行供前端 pre-wrap 预览；过长时按字符截断并标省略
    preview = chunk.strip()
    if len(preview) > 800:
        preview = preview[:800].rstrip() + "…"
    diag = {
        "start": c0,
        "end": c1,
        "start_rule": win_diag.get("start_rule", ""),
        "start_label": win_diag.get("start_label", ""),
        "end_rule": win_diag.get("end_rule", ""),
        "end_label": win_diag.get("end_label", ""),
        "end_candidates": win_diag.get("end_candidates") or [],
        "preview": preview,
        "paragraph_count": 0,
    }

    if split_out:
        diag["paragraph_count"] = len(split_out)
        return split_out, diag

    # 最后兜底：字符窗本身（仍滤版头噪声，禁止回退成全文）
    mid = [
        ln.strip()
        for ln in chunk.splitlines()
        if ln.strip() and not _is_header_noise_line(ln.strip(), org_mark=mark, title=tit)
    ]
    if mid:
        diag["paragraph_count"] = len(mid)
        diag["end_label"] = (diag["end_label"] or "") + " · 段落兜底"
        return mid, diag
    diag["paragraph_count"] = 0
    return [], diag
