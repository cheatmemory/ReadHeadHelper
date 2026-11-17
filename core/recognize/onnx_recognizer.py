# -*- coding: utf-8 -*-
"""OnnxFieldRecognizer：封装 govdoc-sdk，输出 §3 英文契约 ModelOutput。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from core.body_structure.extract import extract_body_paragraphs
from core.ir.minutes import format_issue_no, looks_like_minutes, normalize_name_list
from core.ir.schema import ModelOutput
from core.recognize.review import review_and_correct

# SDK 中文 schema（不可改名）——通用 16 字段（V4）
SDK_SCHEMA = [
    "份号", "密级", "保密期限", "紧急程度", "发文机关标志", "发文字号",
    "标题", "主送机关", "附件说明", "发文机关署名", "成文日期",
    "附注", "抄送机关", "印发机关", "印发日期", "签发人",
]

# 会议纪要 17 字段（V4）：无发文字号/签发人/发文机关署名，含期号与三类名单
SDK_SCHEMA_MINUTES = [
    "份号", "密级", "保密期限", "紧急程度", "发文机关标志", "期号",
    "标题", "主送机关", "附件说明", "出席", "请假", "列席",
    "成文日期", "附注", "抄送机关", "印发机关", "印发日期",
]


def _clean(v: str) -> str:
    return (v or "").replace("\n", "").strip()


def _first(result: dict, key: str) -> str:
    items = result.get(key) or []
    if not items:
        return ""
    return _clean(items[0].get("text", ""))


def _join_name_field(result: dict, key: str) -> str:
    """出席/请假/列席：合并多 span，顿号归一。"""
    items = result.get(key) or []
    parts: list[str] = []
    for it in items:
        t = _clean(str(it.get("text") or ""))
        if t:
            parts.append(t)
    if not parts:
        return ""
    return normalize_name_list("、".join(parts))


def _join_attachment_captions(result: dict) -> str:
    """合并全部「附件说明」条目（_first 只会丢掉第 2 条起）。

    单附件不加序号；多附件才补阿拉伯数字顺序号（§7.3.4）。
    """
    items = result.get("附件说明") or []
    cleaned: list[str] = []
    for it in items:
        t = _clean(str(it.get("text") or ""))
        if not t:
            continue
        t = re.sub(r"^附件\s*[:：]\s*", "", t)
        cleaned.append(t)
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    parts: list[str] = []
    for i, t in enumerate(cleaned, 1):
        if not re.match(r"^\d+\s*[\.．、]", t):
            t = f"{i}.{t}"
        parts.append(t)
    return "\n".join(parts)


def _guess_body_blocks(text: str, result: dict) -> list[str]:
    """从原文抽取正文段落（不做层级；层级由 parse_body_blocks 负责）。"""
    return extract_body_paragraphs(
        text,
        title=_first(result, "标题"),
        recipient=_first(result, "主送机关"),
        date=_first(result, "成文日期"),
        org_signature=_first(result, "发文机关署名"),
        org_mark=_first(result, "发文机关标志"),
        sdk_result=result,
    )


class OnnxFieldRecognizer:
    def __init__(
        self,
        onnx_path: str | Path,
        vocab_path: str | Path,
        *,
        position_prob: float = 0.5,
        sdk_root: str | Path | None = None,
    ):
        self.onnx_path = Path(onnx_path)
        self.vocab_path = Path(vocab_path)
        if not self.onnx_path.exists():
            raise FileNotFoundError(f"ONNX 模型不存在: {self.onnx_path}")
        if not self.vocab_path.exists():
            raise FileNotFoundError(f"词表不存在: {self.vocab_path}")

        root = Path(sdk_root) if sdk_root else self.onnx_path.parent
        # 允许 `from sdk.govdoc_sdk` 与 `from postprocess`
        root_s = str(root)
        if root_s not in sys.path:
            sys.path.insert(0, root_s)

        from sdk.govdoc_sdk import GovDocExtractor  # type: ignore
        from postprocess import postprocess  # type: ignore

        self._postprocess = postprocess
        self._extractor = GovDocExtractor(
            onnx_path=str(self.onnx_path),
            vocab_path=str(self.vocab_path),
            position_prob=position_prob,
        )
        self._last_sdk_result: dict | None = None

    def recognize(self, text: str) -> ModelOutput:
        text = text or ""
        as_minutes = looks_like_minutes(source_text=text)
        schema = SDK_SCHEMA_MINUTES if as_minutes else SDK_SCHEMA

        raw = self._extractor.extract(text, schema)
        raw = self._postprocess(raw, text)
        # SDK「只填空」改不了模型错值；本层用原文强规则审查覆盖
        if not as_minutes:
            raw = review_and_correct(raw, text)
        self._last_sdk_result = raw

        # 抽取后若标志/标题表明纪要，仍按纪要字段挂载
        org_mark = _first(raw, "发文机关标志")
        title = _first(raw, "标题")
        as_minutes = as_minutes or looks_like_minutes(
            org_marks=[org_mark] if org_mark else None,
            title=title,
            source_text=text,
        )

        secret = _first(raw, "密级")
        period = _first(raw, "保密期限")
        # 国标展示常用 密级★期限；期限单独保留
        if period and "★" in secret:
            parts = secret.split("★", 1)
            secret, period = parts[0], parts[1] if len(parts) > 1 else period

        body_blocks = _guess_body_blocks(text, raw)
        data = {
            "header": {
                "copy_number": _first(raw, "份号"),
                "secret_level": secret,
                "secret_period": period,
                "urgency": _first(raw, "紧急程度"),
                "issuer_sign": _first(raw, "签发人"),
                "org_mark": org_mark,
                "doc_number": "" if as_minutes else _first(raw, "发文字号"),
            },
            "main": {
                "title": title,
                "recipient": _first(raw, "主送机关"),
                "body_blocks": body_blocks,
                "attachment_caption": _join_attachment_captions(raw),
            },
            "footer": {
                "date": _first(raw, "成文日期"),
                "note": _first(raw, "附注"),
                "attachment": "",
                "org_signature": "" if as_minutes else _first(raw, "发文机关署名"),
                "print_org": _first(raw, "印发机关"),
                "print_date": _first(raw, "印发日期"),
            },
        }
        model = ModelOutput.from_dict(data)
        model._sdk_cc = _first(raw, "抄送机关")  # type: ignore[attr-defined]
        if as_minutes:
            model._minutes_issue_no = format_issue_no(_first(raw, "期号"))  # type: ignore[attr-defined]
            model._minutes_attendance = _join_name_field(raw, "出席")  # type: ignore[attr-defined]
            model._minutes_leave = _join_name_field(raw, "请假")  # type: ignore[attr-defined]
            model._minutes_liexi = _join_name_field(raw, "列席")  # type: ignore[attr-defined]
        return model
