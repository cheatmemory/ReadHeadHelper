# -*- coding: utf-8 -*-
"""模型契约 JSON 与 LayoutIR 数据结构。"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class SealMode(str, Enum):
    STAMP = "stamp_layout"
    NO_STAMP = "no_stamp_layout"


@dataclass
class HeaderFields:
    copy_number: str = ""
    secret_level: str = ""
    secret_period: str = ""
    urgency: str = ""
    issuer_sign: str = ""
    org_mark: str = ""
    doc_number: str = ""


@dataclass
class MainFields:
    title: str = ""
    recipient: str = ""
    body_blocks: list[str] = field(default_factory=list)
    attachment_caption: str = ""


@dataclass
class FooterFields:
    date: str = ""
    note: str = ""
    attachment: str = ""
    org_signature: str = ""
    print_org: str = ""
    print_date: str = ""


@dataclass
class ModelOutput:
    """§3 模型输出契约（程序侧适配）。"""

    header: HeaderFields = field(default_factory=HeaderFields)
    main: MainFields = field(default_factory=MainFields)
    footer: FooterFields = field(default_factory=FooterFields)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ModelOutput":
        data = data or {}
        h = data.get("header") or {}
        m = data.get("main") or {}
        f = data.get("footer") or {}
        return cls(
            header=HeaderFields(
                copy_number=str(h.get("copy_number") or ""),
                secret_level=str(h.get("secret_level") or ""),
                secret_period=str(h.get("secret_period") or ""),
                urgency=str(h.get("urgency") or ""),
                issuer_sign=str(h.get("issuer_sign") or ""),
                org_mark=str(h.get("org_mark") or ""),
                doc_number=str(h.get("doc_number") or ""),
            ),
            main=MainFields(
                title=str(m.get("title") or ""),
                recipient=str(m.get("recipient") or ""),
                body_blocks=[str(x) for x in (m.get("body_blocks") or [])],
                attachment_caption=str(m.get("attachment_caption") or ""),
            ),
            footer=FooterFields(
                date=str(f.get("date") or ""),
                note=str(f.get("note") or ""),
                attachment=str(f.get("attachment") or ""),
                org_signature=str(f.get("org_signature") or ""),
                print_org=str(f.get("print_org") or ""),
                print_date=str(f.get("print_date") or ""),
            ),
        )


@dataclass
class BodyBlock:
    """正文结构树节点。level: h1|h2|h3|h4|p"""

    level: str = "p"
    text: str = ""
    label: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"level": self.level, "text": self.text, "label": self.label}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BodyBlock":
        return cls(
            level=str(data.get("level") or "p"),
            text=str(data.get("text") or ""),
            label=str(data.get("label") or ""),
        )


@dataclass
class OptionalConfirm:
    """选填字段：用户是否确认本件无此项。"""

    confirmed_absent: bool = False


@dataclass
class AttachmentDocx:
    """用户上传的附件 docx（不做国标另面排版，导出时原样接入）。"""

    name: str = ""
    data_b64: str = ""
    path: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "data_b64": self.data_b64, "path": self.path}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AttachmentDocx":
        data = data or {}
        return cls(
            name=str(data.get("name") or ""),
            data_b64=str(data.get("data_b64") or data.get("b64") or ""),
            path=str(data.get("path") or ""),
        )


@dataclass
class LayoutIR:
    """排版引擎唯一输入。"""

    # 模型映射后的要素
    copy_number: str = ""
    secret_level: str = ""
    secret_period: str = ""
    urgency: str = ""
    title: str = ""
    recipient: str = ""
    attachment_caption: str = ""
    date: str = ""
    note: str = ""
    org_signature: str = ""
    print_org: str = ""
    print_date: str = ""
    doc_number: str = ""

    # 确认页 / LayoutIR 扩展
    seal_mode: SealMode | None = None
    recipients_in_footer: bool = False
    signers: list[str] = field(default_factory=list)
    org_marks: list[str] = field(default_factory=list)
    cc_recipients: str = ""
    body_tree: list[BodyBlock] = field(default_factory=list)
    # 上传的附件正文（另页：附件N + 空行 + 原文）
    attachments: list[AttachmentDocx] = field(default_factory=list)

    # 选填确认（字段名 → 是否确认无此项）
    absent_flags: dict[str, bool] = field(default_factory=dict)

    def primary_org_mark(self) -> str:
        if self.org_marks:
            return self.org_marks[0]
        return ""

    def missing_required(self) -> list[str]:
        missing: list[str] = []
        if not (self.org_marks or [""])[0].strip():
            missing.append("发文机关标志")
        if not self.doc_number.strip():
            missing.append("发文字号")
        if not self.title.strip():
            missing.append("标题")
        if not any(b.text.strip() for b in self.body_tree):
            missing.append("正文")
        if not self.org_signature.strip():
            missing.append("发文机关署名")
        if not self.date.strip():
            missing.append("成文日期")
        if not self.print_org.strip():
            missing.append("印发机关")
        if not self.print_date.strip():
            missing.append("印发日期")
        if self.seal_mode is None:
            missing.append("落款版式(seal_mode)")
        return missing

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["seal_mode"] = self.seal_mode.value if self.seal_mode else None
        d["attachments"] = [a.to_dict() if hasattr(a, "to_dict") else dict(a) for a in self.attachments]
        return d
