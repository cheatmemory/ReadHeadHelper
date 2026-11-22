# -*- coding: utf-8 -*-
"""文种判定（规则）与字段表门控。

模型没有文种概念，一次只回答一个字段问题。所以「问哪些字段」由这里决定：
先按版式规则判文种，再给该文种对应的字段表。少传即少问，避免串字段。

已支持四种文种：
  通用公文 16 字段   —— 版头以「文件」结尾，有发文字号
  会议纪要 17 字段   —— 版头以「纪要」结尾，有期号，出席/请假/列席
  命令（令）10 字段  —— 版头以「令」或「命令」结尾，有令号（第N号），签署职务/签署姓名
  信函     13 字段   —— 标题以「函」结尾（关于…的函/复函）；字段是通用公文真子集（无签发人、
                       无印发机关/印发日期）；「正文」由代码按版式推导，不是抽取字段
"""
import re

KIND_GENERAL = "通用公文"
KIND_MINUTES = "会议纪要"
KIND_ORDER = "命令"
KIND_LETTER = "信函"

# 通用公文：16 字段，顺序与版式一致
COMMON_FIELDS = [
    "份号", "密级", "保密期限", "紧急程度", "发文机关标志", "发文字号",
    "标题", "主送机关", "附件说明", "发文机关署名", "成文日期",
    "附注", "抄送机关", "印发机关", "印发日期", "签发人",
]

# 会议纪要：无发文字号、无签发人、无发文机关署名；增加期号、出席、请假、列席
MINUTES_FIELDS = [
    "份号", "密级", "保密期限", "紧急程度", "发文机关标志", "期号",
    "标题", "主送机关", "附件说明",
    "出席", "请假", "列席",
    "成文日期", "附注", "抄送机关", "印发机关", "印发日期",
]

# 命令（令）：无标题、无主送机关、无发文机关署名，也无份号、密级、保密期限、紧急程度；
# 增加令号、签署职务、签署姓名。落款只有「职务 + 签名章」，姓名常缺省，故职务与姓名分两个字段。
ORDER_FIELDS = [
    "发文机关标志", "令号",
    "附件说明", "签署职务", "签署姓名",
    "成文日期", "附注", "抄送机关", "印发机关", "印发日期",
]

# 信函：版头只有机关名（不带「文件」），发文字号必填，标题必填，主送机关必填；
# 比通用公文少「签发人、印发机关、印发日期」。
# 「正文」不是模型抽取字段：主送机关之后、附件说明/署名/落款之前的行区间就是正文，
# 由代码按版式推导，不问模型。
# 约束：紧急程度只有特急/加急；发文机关标志单值（联合行文只取主办机关）；
# 发文机关署名多值（联合行文每机关一个，按发文顺序）。
LETTER_FIELDS = [
    "份号", "密级", "保密期限", "紧急程度", "发文机关标志", "发文字号",
    "标题", "主送机关", "附件说明", "发文机关署名",
    "成文日期", "附注", "抄送机关",
]

# 全部字段（23 个），用于统计合并口径
ALL_FIELDS = COMMON_FIELDS + ["期号", "出席", "请假", "列席", "令号", "签署职务", "签署姓名"]

# 纪要版头行：以「纪要」结尾，没有「关于」。标题行常带「关于」，排除掉
_TAIL_RE = re.compile(r"^[\u4e00-\u9fa5A-Za-z0-9（）()《》、]{2,60}纪要$")

# 命令版头行：以「令」结尾的机关名（含「中华人民共和国主席令」「××市人民政府令」）
_ORDER_MARK_RE = re.compile(r"^[\u4e00-\u9fa5（）]{4,30}令$")

# 令号：独立一行「第1号」「第三号」
_ORDER_NO_RE = re.compile(r"^第\s*[0-9０-９〇一二三四五六七八九十百]{1,6}\s*号$")

# 信函标题行：关于…的函 / 复函 / 告知函；前面可带发文机关名，也可直接以「关于」开头。
# 国标与实务均常见「关于××的函」；通知/批复等不以「函」结尾，不会误中。
_LETTER_TITLE_RE = re.compile(
    r"^(?:[\u4e00-\u9fa5A-Za-z0-9（）()]{2,40})?关于.{2,80}的?(?:复|告知)?函$"
)

# 发文字号：有「〔2026〕」样式即视为通用公文，避免把带编号的普通公文误判为命令
_DOCNO_RE = re.compile(r"[〔\[（(]\s*\d{4}\s*[〕\]）)]")


def _strip_bom(text):
    """去掉 UTF-8 BOM（\\ufeff）。Windows 记事本另存常带，粘在首行会让版头正则失配。"""
    if not text:
        return ""
    return text.lstrip("\ufeff")


def _head_lines(text, head_lines=8):
    out = []
    for ln in _strip_bom(text).split("\n"):
        s = ln.strip().lstrip("\ufeff")
        if s:
            out.append(s)
            if len(out) >= head_lines:
                break
    return out


def detect(text, head_lines=8):
    """判文种。

    1. 前若干非空行出现「…纪要」版头行（不含「关于」）=> 会议纪要
    2. 版头行以「令」结尾 => 命令
    3. 有独立「第N号」行且全文没有发文字号 => 命令（版头被 OCR 打散时的退路）
    4. 前若干非空行出现「关于…的函/复函」标题行 => 信函
    5. 其余 => 通用公文
    """
    text = _strip_bom(text)
    head = _head_lines(text, head_lines)
    for s in head:
        if _TAIL_RE.match(s) and "关于" not in s:
            return KIND_MINUTES
    for s in head:
        if _ORDER_MARK_RE.match(s) and "关于" not in s:
            return KIND_ORDER
    if any(_ORDER_NO_RE.match(s) for s in head) and not _DOCNO_RE.search(text):
        return KIND_ORDER
    for s in head:
        if _LETTER_TITLE_RE.match(s):
            return KIND_LETTER
    return KIND_GENERAL


def schema_for(kind):
    """按文种取字段表。"""
    if kind == KIND_MINUTES:
        return list(MINUTES_FIELDS)
    if kind == KIND_ORDER:
        return list(ORDER_FIELDS)
    if kind == KIND_LETTER:
        return list(LETTER_FIELDS)
    return list(COMMON_FIELDS)


def schemas():
    """返回 {文种: 字段表}。"""
    return {
        KIND_GENERAL: list(COMMON_FIELDS),
        KIND_MINUTES: list(MINUTES_FIELDS),
        KIND_ORDER: list(ORDER_FIELDS),
        KIND_LETTER: list(LETTER_FIELDS),
    }


if __name__ == "__main__":
    import json
    import sys

    for path in sys.argv[1:]:
        cnt = {}
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            k = detect(json.loads(line)["text"])
            cnt[k] = cnt.get(k, 0) + 1
        print(path, cnt)
