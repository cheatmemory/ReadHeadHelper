# -*- coding: utf-8 -*-
"""OnnxFieldRecognizer：封装 govdoc-sdk v5，输出 §3 英文契约 ModelOutput。"""
from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

from core.body_structure.extract import extract_body_paragraphs, extract_body_with_trace
from core.ir.minutes import format_issue_no, looks_like_minutes, normalize_name_list
from core.ir.order import format_order_no, normalize_order_signers
from core.ir.schema import ModelOutput
from core.recognize.review import review_and_correct
from core.recognize.trace import build_field_trace


def _clean(v: str) -> str:
    return (v or "").replace("\n", "").strip()


def _first(result: dict, key: str) -> str:
    items = result.get(key) or []
    if not items:
        return ""
    return _clean(items[0].get("text", ""))


def _all_texts(result: dict, key: str) -> list[str]:
    """按模型返回顺序收集多值字段（不得去重）。"""
    items = result.get(key) or []
    out: list[str] = []
    for it in items:
        t = _clean(str(it.get("text") or ""))
        if t:
            out.append(t)
    return out


def _join_name_field(result: dict, key: str) -> str:
    """出席/请假/列席：合并多 span，顿号归一。"""
    parts = _all_texts(result, key)
    if not parts:
        return ""
    return normalize_name_list("、".join(parts))


def _join_org_signature(result: dict) -> str:
    """发文机关署名：多机关用换行保留顺序（条目内换行也保留，供联合落款）。"""
    parts: list[str] = []
    for it in result.get("发文机关署名") or []:
        t = str(it.get("text") or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not t:
            continue
        lines = [ln.strip() for ln in t.split("\n") if ln.strip()]
        if lines:
            parts.append("\n".join(lines))
    return "\n".join(parts)


def _org_mark_field(result: dict) -> str:
    """发文机关标志：保留换行，供联合红头按行拆机关；不去掉 \\n。"""
    items = result.get("发文机关标志") or []
    if not items:
        return ""
    t = str(items[0].get("text") or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = [ln.strip() for ln in t.split("\n") if ln.strip()]
    return "\n".join(lines)


def _join_cc_field(result: dict) -> str:
    """抄送机关：合并全部 span（_first 会丢掉第 2 段起）。

    postprocess 通常已归一成整行单条；若仍多段，用顿号拼接。
    """
    parts = _all_texts(result, "抄送机关")
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return "、".join(parts)


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
        # 允许 `from sdk.govdoc_sdk` / `from postprocess` / `import doc_kind`
        root_s = str(root)
        if root_s not in sys.path:
            sys.path.insert(0, root_s)

        from sdk.govdoc_sdk import GovDocExtractor  # type: ignore
        from postprocess import postprocess  # type: ignore
        import doc_kind  # type: ignore

        self._doc_kind = doc_kind
        self._postprocess = postprocess
        self._extractor = GovDocExtractor(
            onnx_path=str(self.onnx_path),
            vocab_path=str(self.vocab_path),
            position_prob=position_prob,
        )
        self._last_sdk_result: dict | None = None
        self._last_field_trace: dict | None = None
        self._last_body_trace: dict | None = None
        self._last_doc_kind: str | None = None

    def recognize(self, text: str, *, with_trace: bool = False) -> ModelOutput:
        # UTF-8 BOM 会导致版头「…纪要」等行首正则失配；统一剥掉
        text = (text or "").lstrip("\ufeff")
        dk = self._doc_kind
        # 少换行命令稿：先按版式锚点补软换行，再判文种/抽字段（span 模型吃换行边界）
        soften = getattr(dk, "soften_layout_breaks", None)
        if callable(soften):
            text = soften(text)
        kind = dk.detect(text)
        schema = dk.schema_for(kind)
        self._last_doc_kind = kind

        model_raw = self._extractor.extract(text, schema)
        after_pp = self._postprocess(copy.deepcopy(model_raw), text)
        # 仅通用文走应用侧 review；纪要/命令/信函只信 SDK postprocess
        if kind == dk.KIND_GENERAL:
            final = review_and_correct(copy.deepcopy(after_pp), text)
        else:
            final = after_pp
        self._last_sdk_result = final

        as_minutes = kind == dk.KIND_MINUTES
        as_order = kind == dk.KIND_ORDER
        as_letter = kind == dk.KIND_LETTER

        org_mark = _org_mark_field(final)
        title = "" if as_order else _first(final, "标题")
        # 抽取后二次确认纪要（标志/标题），避免仅靠文首判定漏切
        if not as_order and not as_letter:
            as_minutes = as_minutes or looks_like_minutes(
                org_marks=[org_mark] if org_mark else None,
                title=title,
                source_text=text,
            )

        secret = _first(final, "密级")
        period = _first(final, "保密期限")
        if period and "★" in secret:
            parts = secret.split("★", 1)
            secret, period = parts[0], parts[1] if len(parts) > 1 else period

        recipient = "" if as_order else _first(final, "主送机关")
        org_signature = ""
        if not as_minutes and not as_order:
            org_signature = _join_org_signature(final)

        if with_trace:
            body_blocks, body_diag = extract_body_with_trace(
                text,
                title=title,
                recipient=recipient,
                date=_first(final, "成文日期"),
                org_signature=org_signature,
                org_mark=org_mark,
                sdk_result=final,
            )
            self._last_field_trace = build_field_trace(final)
            self._last_body_trace = body_diag
        else:
            body_blocks = extract_body_paragraphs(
                text,
                title=title,
                recipient=recipient,
                date=_first(final, "成文日期"),
                org_signature=org_signature,
                org_mark=org_mark,
                sdk_result=final,
            )
            self._last_field_trace = None
            self._last_body_trace = None

        data = {
            "header": {
                "copy_number": "" if as_order else _first(final, "份号"),
                "secret_level": "" if as_order else secret,
                "secret_period": "" if as_order else period,
                "urgency": "" if as_order else _first(final, "紧急程度"),
                "issuer_sign": "" if (as_minutes or as_order or as_letter) else _first(final, "签发人"),
                "org_mark": org_mark,
                "doc_number": "" if (as_minutes or as_order) else _first(final, "发文字号"),
            },
            "main": {
                "title": title,
                "recipient": recipient,
                "body_blocks": body_blocks,
                "attachment_caption": _join_attachment_captions(final),
            },
            "footer": {
                "date": _first(final, "成文日期"),
                "note": _first(final, "附注"),
                "attachment": "",
                "org_signature": org_signature,
                "print_org": "" if as_letter else _first(final, "印发机关"),
                "print_date": "" if as_letter else _first(final, "印发日期"),
            },
        }
        model = ModelOutput.from_dict(data)
        model._sdk_cc = _join_cc_field(final)  # type: ignore[attr-defined]

        if as_minutes:
            model._minutes_issue_no = format_issue_no(_first(final, "期号"))  # type: ignore[attr-defined]
            model._minutes_attendance = _join_name_field(final, "出席")  # type: ignore[attr-defined]
            model._minutes_leave = _join_name_field(final, "请假")  # type: ignore[attr-defined]
            model._minutes_liexi = _join_name_field(final, "列席")  # type: ignore[attr-defined]

        if as_order:
            model._is_order = True  # type: ignore[attr-defined]
            raw_no = _first(final, "令号")
            model._order_no = format_order_no(raw_no) or raw_no  # type: ignore[attr-defined]
            # 签署职务按文中顺序；姓名单独字段，不进职务文本
            titles = normalize_order_signers(_all_texts(final, "签署职务"))
            model._order_signers = titles  # type: ignore[attr-defined]

        if as_letter:
            model._is_letter = True  # type: ignore[attr-defined]

        return model
