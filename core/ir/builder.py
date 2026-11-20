# -*- coding: utf-8 -*-
"""ModelOutput → LayoutIR 构建。"""
from __future__ import annotations

import re
from typing import Iterable

from core.body_structure.parser import parse_body_blocks
from core.ir.minutes import apply_minutes_to_ir
from core.ir.order import apply_order_to_ir, looks_like_order
from core.ir.schema import DocKind, LayoutIR, ModelOutput, SealMode


_SPLIT_RE = re.compile(r"[、，,；;/\s]+")


def split_names(raw: str) -> list[str]:
    raw = (raw or "").strip()
    if not raw:
        return []
    parts = [p.strip() for p in _SPLIT_RE.split(raw) if p.strip()]
    return parts or ([raw] if raw else [])


def model_to_partial_ir(model: ModelOutput, source_text: str = "") -> LayoutIR:
    """把模型 JSON 映射为可编辑的 LayoutIR（不含 seal_mode）。"""
    body_paras = list(model.main.body_blocks or [])
    if not body_paras and source_text:
        # 兜底仍走正文抽取，禁止把密级/标志/名单整篇灌进正文
        from core.body_structure.extract import extract_body_paragraphs

        body_paras = extract_body_paragraphs(
            source_text,
            title=model.main.title,
            recipient=model.main.recipient,
            date=model.footer.date,
            org_signature=model.footer.org_signature,
            org_mark=model.header.org_mark,
        )
        if not body_paras:
            # 再退一步：按单行切，仍滤版头并在名单/附件处截断
            from core.body_structure.extract import (
                _ATTACH,
                _CC,
                _MINUTES_LIST,
                _NOTE,
                _is_header_noise_line,
            )

            mark = model.header.org_mark
            tit = model.main.title
            kept: list[str] = []
            stripping = True
            for ln in source_text.splitlines():
                s = ln.strip()
                if not s:
                    continue
                if _ATTACH.match(s) or _CC.match(s) or _NOTE.match(s) or _MINUTES_LIST.match(s):
                    break
                if stripping and _is_header_noise_line(s, org_mark=mark, title=tit):
                    continue
                stripping = False
                kept.append(s)
            body_paras = kept

    org_marks = split_names(model.header.org_mark)
    signers = split_names(model.header.issuer_sign)

    ir = LayoutIR(
        copy_number=model.header.copy_number.strip(),
        secret_level=model.header.secret_level.strip(),
        secret_period=model.header.secret_period.strip(),
        urgency=model.header.urgency.strip(),
        title=model.main.title.strip(),
        recipient=model.main.recipient.strip(),
        attachment_caption=model.main.attachment_caption.strip(),
        date=model.footer.date.strip(),
        note=model.footer.note.strip(),
        org_signature=model.footer.org_signature.strip(),
        print_org=model.footer.print_org.strip(),
        print_date=model.footer.print_date.strip(),
        doc_number=model.header.doc_number.strip(),
        signers=signers,
        org_marks=org_marks,
        body_tree=parse_body_blocks(body_paras),
    )
    # 命令优先：标志以命令/令结尾，或正则识别器已挂 _is_order
    if looks_like_order(org_marks=org_marks, source_text=source_text) or getattr(
        model, "_is_order", False
    ):
        return apply_order_to_ir(ir, source_text=source_text, model=model)
    return apply_minutes_to_ir(ir, source_text=source_text, model=model)


def build_layout_ir(
    model: ModelOutput,
    *,
    seal_mode: SealMode | str | None,
    source_text: str = "",
    cc_recipients: str = "",
    recipients_in_footer: bool = False,
    signers: Iterable[str] | None = None,
    org_marks: Iterable[str] | None = None,
    body_tree=None,
    absent_flags: dict[str, bool] | None = None,
    overrides: dict | None = None,
) -> LayoutIR:
    ir = model_to_partial_ir(model, source_text=source_text)
    if isinstance(seal_mode, str):
        seal_mode = SealMode(seal_mode) if seal_mode else None
    # 纪要/命令不校验、不写入 seal_mode
    if ir.is_minutes() or ir.is_order():
        ir.seal_mode = None
    else:
        ir.seal_mode = seal_mode
    ir.cc_recipients = (cc_recipients or "").strip()
    ir.recipients_in_footer = bool(recipients_in_footer) or ir.recipients_in_footer
    if signers is not None:
        ir.signers = [s.strip() for s in signers if str(s).strip()]
    if org_marks is not None:
        ir.org_marks = [s.strip() for s in org_marks if str(s).strip()]
    if body_tree is not None:
        ir.body_tree = list(body_tree)
    ir.absent_flags = dict(absent_flags or {})

    if overrides:
        for k, v in overrides.items():
            if hasattr(ir, k) and k not in {"seal_mode", "body_tree", "signers", "org_marks", "doc_kind"}:
                setattr(ir, k, v)
            if k == "doc_kind" and v:
                ir.doc_kind = DocKind(v) if not isinstance(v, DocKind) else v
                if ir.is_minutes() or ir.is_order():
                    ir.seal_mode = None
    return ir
