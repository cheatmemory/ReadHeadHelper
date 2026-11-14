# -*- coding: utf-8 -*-
"""把附件 docx 正文原样接入主文档（不做国标附件另面排版）。

每个附件由引擎负责：分页 →「附件N」→ 空一行 → 再调用本模块复制源 body。
图片 / 图表等通过复制 OPC 部件并重写 rId 接入目标文档。
"""
from __future__ import annotations

import base64
import io
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from docx import Document
from docx.opc.packuri import PackURI
from docx.opc.part import Part
from docx.oxml.ns import qn

_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _is_rid_value(val: str) -> bool:
    return bool(re.fullmatch(r"rId\d+", val or ""))


def _rid_attrs(element) -> list[tuple[Any, str, str]]:
    found: list[tuple[Any, str, str]] = []
    prefix = "{" + _REL_NS + "}"
    for el in element.iter():
        for name, value in el.attrib.items():
            if name.startswith(prefix) and _is_rid_value(value):
                found.append((el, name, value))
    return found


def _unique_partname(package, hint_uri: str) -> PackURI:
    """按源部件名生成不冲突的 /word/attachments/... 路径。"""
    raw = hint_uri if hint_uri.startswith("/") else f"/{hint_uri}"
    base = raw.rsplit("/", 1)[-1] or "part.bin"
    stem, dot, ext = base.partition(".")
    stem = re.sub(r"[^\w\-]+", "_", stem) or "part"
    n = 1
    while True:
        name = f"/word/attachments/{stem}_{n}{dot}{ext}" if ext else f"/word/attachments/{stem}_{n}"
        candidate = PackURI(name)
        if candidate not in {p.partname for p in package.parts}:
            return candidate
        n += 1


def _copy_related_part(src_part, dst_part, src_rid: str, rid_map: dict[str, str]) -> str | None:
    if src_rid in rid_map:
        return rid_map[src_rid]
    try:
        rel = src_part.rels[src_rid]
    except KeyError:
        return None

    if rel.is_external:
        new_rid = dst_part.rels.get_or_add_ext_rel(rel.reltype, rel.target_ref)
        rid_map[src_rid] = new_rid
        return new_rid

    src_rel_part = rel.target_part
    package = dst_part.package
    partname = _unique_partname(package, str(src_rel_part.partname))
    new_part = Part(partname, src_rel_part.content_type, src_rel_part.blob, package)
    new_rid = dst_part.relate_to(new_part, rel.reltype)
    rid_map[src_rid] = new_rid

    # 图表等部件内部还有关系（嵌入 xlsx、theme…）
    child_map: dict[str, str] = {}
    for child_rid in list(src_rel_part.rels.keys()):
        _copy_related_part(src_rel_part, new_part, child_rid, child_map)
    if child_map and "+xml" in (new_part.content_type or ""):
        try:
            text = new_part.blob.decode("utf-8")
            for old, new in child_map.items():
                text = text.replace(f'"{old}"', f'"{new}"')
            new_part._blob = text.encode("utf-8")  # noqa: SLF001
        except Exception:
            pass
    return new_rid


def _remap_element_rids(element, src_part, dst_part, rid_map: dict[str, str]) -> None:
    for el, attr, old_rid in _rid_attrs(element):
        new_rid = _copy_related_part(src_part, dst_part, old_rid, rid_map)
        if new_rid:
            el.set(attr, new_rid)


def append_docx_body(dst: Document, src_bytes: bytes) -> None:
    """把源 docx 的 body 子节点（除 sectPr）深拷到目标 body（插在 sectPr 前）。"""
    if not src_bytes:
        return
    src = Document(io.BytesIO(src_bytes))
    src_body = src.element.body
    dst_body = dst.element.body
    dst_part = dst.part
    src_part = src.part
    rid_map: dict[str, str] = {}

    insert_at = len(dst_body)
    for i, child in enumerate(dst_body):
        if child.tag == qn("w:sectPr"):
            insert_at = i
            break

    for child in list(src_body):
        if child.tag == qn("w:sectPr"):
            continue
        cloned = deepcopy(child)
        _remap_element_rids(cloned, src_part, dst_part, rid_map)
        dst_body.insert(insert_at, cloned)
        insert_at += 1


def load_attachment_bytes(item: Any) -> bytes:
    """LayoutIR 附件项 → bytes。支持 data_b64 / path / bytes。"""
    if item is None:
        return b""
    if isinstance(item, (bytes, bytearray)):
        return bytes(item)
    if isinstance(item, dict):
        b64 = item.get("data_b64") or item.get("b64") or ""
        if b64:
            return base64.b64decode(b64, validate=False)
        path = item.get("path") or ""
        if path and Path(path).is_file():
            return Path(path).read_bytes()
        return b""
    b64 = getattr(item, "data_b64", "") or ""
    if b64:
        return base64.b64decode(b64, validate=False)
    path = getattr(item, "path", "") or ""
    if path and Path(path).is_file():
        return Path(path).read_bytes()
    return b""
