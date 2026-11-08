# -*- coding: utf-8 -*-
"""ModelOutput → LayoutIR 构建。"""
from __future__ import annotations

import re
from typing import Iterable

from core.body_structure.parser import parse_body_blocks
from core.ir.schema import LayoutIR, ModelOutput, SealMode


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
        # 兜底：用全文按空行切，后续确认页/结构工具再改
        body_paras = [p.strip() for p in re.split(r"\n\s*\n", source_text) if p.strip()]

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
    return ir


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
    ir.seal_mode = seal_mode
    ir.cc_recipients = (cc_recipients or "").strip()
    ir.recipients_in_footer = bool(recipients_in_footer)
    if signers is not None:
        ir.signers = [s.strip() for s in signers if str(s).strip()]
    if org_marks is not None:
        ir.org_marks = [s.strip() for s in org_marks if str(s).strip()]
    if body_tree is not None:
        ir.body_tree = list(body_tree)
    ir.absent_flags = dict(absent_flags or {})

    if overrides:
        for k, v in overrides.items():
            if hasattr(ir, k) and k not in {"seal_mode", "body_tree", "signers", "org_marks"}:
                setattr(ir, k, v)
    return ir
