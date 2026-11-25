# -*- coding: utf-8 -*-
"""字段识别溯源：模型 / 模型+正则(postprocess) / 纠错(review)。"""
from __future__ import annotations

import copy
from typing import Any

# UI 字段 id ← SDK 中文名
FIELD_UI_MAP: dict[str, str] = {
    "份号": "f-copy",
    "密级": "f-secret",
    "保密期限": "f-secret-period",  # 可并入 secret 展示
    "紧急程度": "f-urgency",
    "发文机关标志": "f-org",
    "发文字号": "f-docno",
    "期号": "f-issue",
    "令号": "f-order",
    "标题": "f-title",
    "主送机关": "f-to",
    "附件说明": "f-attach",
    "发文机关署名": "f-orgsig",
    "签署职务": "f-order-titles",
    "签署姓名": "f-order-titles-name",  # 并入职务区展示（无独立输入框）
    "成文日期": "f-date",
    "附注": "f-note",
    "抄送机关": "f-cc",
    "印发机关": "f-print-org",
    "印发日期": "f-print-date",
    "签发人": "f-signers",
    "出席": "f-attendance",
    "请假": "f-leave",
    "列席": "f-liexi",
}

SOURCE_LABELS = {
    "model": "模型",
    "postprocess": "模型+正则(postprocess)",
    "review": "纠错(review)",
    "user": "用户改过",
}

# 名单类 / 联合机关：按 span 拆开展示
MULTI_SPAN_FIELDS = {
    "出席",
    "请假",
    "列席",
    "附件说明",
    "签发人",
    "签署职务",
    "签署姓名",
    "发文机关署名",
    "发文机关标志",
}


def _item_text(it: dict[str, Any] | None) -> str:
    if not it:
        return ""
    # 联合机关内部换行改顿号，避免溯源/摘要里两家粘成一串
    return str(it.get("text") or "").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "、").strip()


def _expand_joint_org_items(cn: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """一条里用换行写了多家机关时，拆成多条 span（与确认页顿号展示一致）。"""
    if cn not in ("发文机关署名", "发文机关标志"):
        return items
    out: list[dict[str, Any]] = []
    for it in items:
        raw = str(it.get("text") or "").replace("\r\n", "\n").replace("\r", "\n")
        if "\n" not in raw and "、" not in raw:
            out.append(it)
            continue
        parts: list[str] = []
        for ln in raw.split("\n"):
            s = ln.strip()
            if not s or s in ("文件", "函"):
                continue
            if s.endswith("文件") and len(s) > 2:
                s = s[:-2].strip()
            for p in s.split("、"):
                p = p.strip()
                if p and p not in ("文件", "函"):
                    parts.append(p)
        if len(parts) <= 1:
            out.append(it)
            continue
        for p in parts:
            piece = dict(it)
            piece["text"] = p
            out.append(piece)
    return out


def _item_confidence(it: dict[str, Any] | None) -> float | None:
    """仅模型置信度；正则/纠错返回 None → UI 显示「-」。"""
    if not it:
        return None
    src = str(it.get("source") or "")
    if src.startswith("review") or src == "regex" or src.startswith("regex"):
        return None
    for key in ("probability", "prob"):
        if key in it and it[key] is not None:
            try:
                return round(float(it[key]), 4)
            except (TypeError, ValueError):
                return None
    return None


def _classify_item(it: dict[str, Any]) -> str:
    src = str(it.get("source") or "")
    if src.startswith("review"):
        return "review"
    if src == "regex" or src.startswith("regex"):
        return "postprocess"
    return "model"


def _span_payload(it: dict[str, Any], *, cn_name: str) -> dict[str, Any]:
    source = _classify_item(it)
    conf = _item_confidence(it) if source == "model" else None
    start = it.get("start")
    end = it.get("end")
    try:
        start_i = int(start) if start is not None else None
        end_i = int(end) if end is not None else None
    except (TypeError, ValueError):
        start_i, end_i = None, None
    reason = ""
    raw_src = str(it.get("source") or "")
    if raw_src.startswith("review:"):
        reason = raw_src.split(":", 1)[-1]
    return {
        "field_cn": cn_name,
        "text": _item_text(it),
        "source": source,
        "source_label": SOURCE_LABELS[source],
        "confidence": conf,  # None → 前端显示 "-"
        "start": start_i,
        "end": end_i,
        "reason": reason,
    }


def build_field_trace(final_result: dict[str, Any] | None) -> dict[str, Any]:
    """从最终 SDK 结果（postprocess ± review 之后）生成按 UI 字段分组的溯源。"""
    final_result = final_result or {}
    fields: dict[str, Any] = {}
    for cn, ui in FIELD_UI_MAP.items():
        items = [it for it in (final_result.get(cn) or []) if isinstance(it, dict) and _item_text(it)]
        items = _expand_joint_org_items(cn, items)
        items = [it for it in items if _item_text(it)]
        if not items:
            continue
        if cn in MULTI_SPAN_FIELDS or len(items) > 1:
            spans = [_span_payload(it, cn_name=cn) for it in items]
        else:
            spans = [_span_payload(items[0], cn_name=cn)]
        # 密级+期限都映射到 secret 区：期限单独一条挂到同一 field 的 spans
        if ui == "f-secret-period":
            host = fields.setdefault(
                "f-secret",
                {"label": "密级/保密期限", "ui": "f-secret", "spans": []},
            )
            for sp in spans:
                sp["field_cn"] = "保密期限"
                host["spans"].append(sp)
            continue
        if ui == "f-secret":
            host = fields.setdefault(
                "f-secret",
                {"label": "密级/保密期限", "ui": "f-secret", "spans": []},
            )
            host["spans"].extend(spans)
            continue
        # 命令：签署姓名无独立框，挂到职务字段下展示置信度
        if ui == "f-order-titles-name":
            host = fields.setdefault(
                "f-order-titles",
                {"label": "签署职务/姓名", "ui": "f-order-titles", "spans": []},
            )
            for sp in spans:
                sp["field_cn"] = "签署姓名"
                host["spans"].append(sp)
            continue
        if ui == "f-order-titles":
            host = fields.setdefault(
                "f-order-titles",
                {"label": "签署职务", "ui": "f-order-titles", "spans": []},
            )
            host["spans"].extend(spans)
            continue
        fields[ui] = {
            "label": cn,
            "ui": ui,
            "spans": spans,
        }
    return {"fields": fields}


def snapshot_pipeline(
    *,
    model_raw: dict[str, Any],
    after_postprocess: dict[str, Any],
    after_review: dict[str, Any] | None,
    ran_review: bool,
) -> dict[str, Any]:
    """保留三阶段快照（调试用）；对外展示以最终结果 + source 标签为准。"""
    return {
        "ran_review": bool(ran_review),
        "model": copy.deepcopy(model_raw or {}),
        "postprocess": copy.deepcopy(after_postprocess or {}),
        "review": copy.deepcopy(after_review or after_postprocess or {}),
    }
