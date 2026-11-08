# -*- coding: utf-8 -*-
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.session import AppSession
from core.ir.builder import split_names
from core.ir.schema import SealMode


class ConfirmPage(QWidget):
    def __init__(self, session: AppSession, parent=None):
        super().__init__(parent)
        self.session = session
        self.fields: dict[str, QLineEdit | QTextEdit] = {}
        self.none_btns: dict[str, QPushButton] = {}
        self.seal_btns: dict[str, QPushButton] = {}
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        t = QLabel("确认要素")
        t.setStyleSheet("font-size:20px;font-weight:700;")
        s = QLabel("核对识别结果。必填为空会阻断导出；选填为空时点右侧「无此项」确认，或补填内容。")
        s.setObjectName("Hint")
        s.setWordWrap(True)
        root.addWidget(t)
        root.addWidget(s)

        self.alert = QLabel("请先选择有章 / 无章版式。未选择时无法进入导出。")
        self.alert.setStyleSheet(
            "background:#fff6e0;border:1px solid #f0d59a;border-radius:8px;padding:10px;color:#6b4a00;"
        )
        self.alert.setWordWrap(True)
        root.addWidget(self.alert)

        seal_box = QGroupBox("落款版式 *")
        seal_row = QHBoxLayout(seal_box)
        for key, title, desc in (
            ("stamp_layout", "有章版式", "日期右空四字；署名前一行相对日期居中；附件下不空行。"),
            ("no_stamp_layout", "无章版式", "附件下空一行；署名右空二字、日期首字右移二字；日期更长则日期右空二字并加大署名右空。"),
        ):
            btn = QPushButton(f"{title}\n{desc}")
            btn.setObjectName("SealOption")
            btn.setCheckable(True)
            btn.setProperty("selected", "false")
            btn.clicked.connect(lambda checked=False, k=key: self._pick_seal(k))
            self.seal_btns[key] = btn
            seal_row.addWidget(btn)
        root.addWidget(seal_box)

        header = QGroupBox("版头")
        hg = QGridLayout(header)
        self._add_optional(hg, 0, 0, "copy_number", "份号", "如 000001")
        self._add_optional(hg, 0, 1, "secret_combo", "密级/期限", "机密★10年")
        self._add_optional(hg, 1, 0, "urgency", "紧急程度", "特急 / 加急")
        self._add_optional(hg, 1, 1, "issuer_sign", "签发人", "上行文填写")
        self._add_required(hg, 2, 0, 2, "org_mark", "发文机关标志 *")
        self._add_required(hg, 3, 0, 2, "doc_number", "发文字号 *")
        root.addWidget(header)

        main = QGroupBox("主体")
        mg = QGridLayout(main)
        self._add_required(mg, 0, 0, 2, "title", "标题 *", multiline=True)
        self._add_optional(mg, 1, 0, "recipient", "主送机关", "", span=2)
        self._add_optional(mg, 2, 0, "attachment_caption", "附件说明", "", span=2)
        root.addWidget(main)

        foot = QGroupBox("落款与版记")
        fg = QGridLayout(foot)
        self._add_required(fg, 0, 0, 1, "org_signature", "发文机关署名 *")
        self._add_required(fg, 0, 1, 1, "date", "成文日期 *")
        self._add_optional(fg, 1, 0, "note", "附注", "（此件公开发布）")
        self._add_optional(fg, 1, 1, "cc_recipients", "抄送", "需人工或模型填写")
        self._add_required(fg, 2, 0, 1, "print_org", "印发机关 *")
        self._add_required(fg, 2, 1, 1, "print_date", "印发日期 *")
        root.addWidget(foot)
        root.addStretch(1)

    def _wrap_field(self, key: str, label: str, optional: bool) -> tuple[QWidget, QLineEdit | QTextEdit]:
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        row = QHBoxLayout()
        lab = QLabel(label + ("  选填" if optional else ""))
        row.addWidget(lab, 1)
        if optional:
            none_btn = QPushButton("无此项")
            none_btn.setObjectName("NoneToggle")
            none_btn.setCheckable(True)
            none_btn.setProperty("pressed", "false")
            none_btn.toggled.connect(lambda on, k=key: self._toggle_none(k, on))
            self.none_btns[key] = none_btn
            row.addWidget(none_btn)
        lay.addLayout(row)
        edit: QLineEdit | QTextEdit
        if key == "title":
            edit = QTextEdit()
            edit.setFixedHeight(64)
        else:
            edit = QLineEdit()
        self.fields[key] = edit
        lay.addWidget(edit)
        return box, edit

    def _add_optional(self, grid: QGridLayout, r: int, c: int, key: str, label: str, placeholder: str, span: int = 1):
        box, edit = self._wrap_field(key, label, True)
        if isinstance(edit, QLineEdit):
            edit.setPlaceholderText(placeholder)
        grid.addWidget(box, r, c, 1, span)

    def _add_required(self, grid: QGridLayout, r: int, c: int, span: int, key: str, label: str, multiline: bool = False):
        box, edit = self._wrap_field(key, label, False)
        if multiline and not isinstance(edit, QTextEdit):
            pass
        grid.addWidget(box, r, c, 1, span)

    def _toggle_none(self, key: str, on: bool):
        btn = self.none_btns[key]
        btn.setProperty("pressed", "true" if on else "false")
        btn.style().unpolish(btn)
        btn.style().polish(btn)
        edit = self.fields[key]
        edit.setDisabled(on)
        self.session.ir.absent_flags[key] = on

    def _pick_seal(self, key: str):
        for k, btn in self.seal_btns.items():
            selected = k == key
            btn.setChecked(selected)
            btn.setProperty("selected", "true" if selected else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self.session.set_seal_mode(SealMode(key))
        self.alert.hide()

    def load_from_session(self):
        ir = self.session.ir
        mapping = {
            "copy_number": ir.copy_number,
            "secret_combo": (f"{ir.secret_level}★{ir.secret_period}" if ir.secret_level and ir.secret_period and "★" not in ir.secret_level else (ir.secret_level or "")),
            "urgency": ir.urgency,
            "issuer_sign": "、".join(ir.signers),
            "org_mark": "、".join(ir.org_marks),
            "doc_number": ir.doc_number,
            "title": ir.title,
            "recipient": ir.recipient,
            "attachment_caption": ir.attachment_caption,
            "org_signature": ir.org_signature,
            "date": ir.date,
            "note": ir.note,
            "cc_recipients": ir.cc_recipients,
            "print_org": ir.print_org,
            "print_date": ir.print_date,
        }
        for k, v in mapping.items():
            w = self.fields.get(k)
            if w is None:
                continue
            if isinstance(w, QTextEdit):
                w.setPlainText(v)
            else:
                w.setText(v)
            if k in self.none_btns and not v.strip():
                self.none_btns[k].setChecked(True)
                self._toggle_none(k, True)
        if ir.seal_mode:
            self._pick_seal(ir.seal_mode.value)
            self.alert.hide()
        else:
            self.alert.show()

    def collect_to_session(self) -> list[str]:
        """写回 session.ir，返回阻断原因。"""
        ir = self.session.ir
        get = self._val
        secret = get("secret_combo")
        if "★" in secret:
            a, b = secret.split("★", 1)
            ir.secret_level, ir.secret_period = a.strip(), b.strip()
        else:
            ir.secret_level, ir.secret_period = secret, ""
        ir.copy_number = get("copy_number")
        ir.urgency = get("urgency")
        ir.signers = split_names(get("issuer_sign"))
        ir.org_marks = split_names(get("org_mark"))
        ir.doc_number = get("doc_number")
        ir.title = get("title")
        ir.recipient = get("recipient")
        ir.attachment_caption = get("attachment_caption")
        ir.org_signature = get("org_signature")
        ir.date = get("date")
        ir.note = get("note")
        ir.cc_recipients = get("cc_recipients")
        ir.print_org = get("print_org")
        ir.print_date = get("print_date")
        for k, btn in self.none_btns.items():
            ir.absent_flags[k] = btn.isChecked()
        return ir.missing_required()

    def _val(self, key: str) -> str:
        if self.none_btns.get(key) and self.none_btns[key].isChecked():
            return ""
        w = self.fields[key]
        if isinstance(w, QTextEdit):
            return w.toPlainText().strip()
        return w.text().strip()

    def seal_ok(self) -> bool:
        return self.session.ir.seal_mode is not None
