# -*- coding: utf-8 -*-
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.session import AppSession
from core.body_structure.parser import renumber_blocks
from core.ir.schema import BodyBlock


LEVEL_LABEL = {"h1": "一级", "h2": "二级", "h3": "三级", "h4": "四级", "p": "正文"}


class StructurePage(QWidget):
    def __init__(self, session: AppSession, parent=None):
        super().__init__(parent)
        self.session = session
        self.blocks: list[BodyBlock] = []
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        t = QLabel("正文结构")
        t.setStyleSheet("font-size:20px;font-weight:700;")
        s = QLabel("选中段落后点层级按钮改级；「重排编号」按同级顺序接续。")
        s.setObjectName("Hint")
        root.addWidget(t)
        root.addWidget(s)

        bar = QHBoxLayout()
        for level, name in (("h1", "一级 一、"), ("h2", "二级 （一）"), ("h3", "三级 1."), ("h4", "四级 （1）"), ("p", "正文")):
            btn = QPushButton(name)
            btn.clicked.connect(lambda checked=False, lv=level: self.set_level(lv))
            bar.addWidget(btn)
        ren = QPushButton("重排编号")
        ren.clicked.connect(self.renumber)
        bar.addWidget(ren)
        root.addLayout(bar)

        ops = QHBoxLayout()
        for text, slot in (("上移", self.move_up), ("下移", self.move_down), ("删除", self.delete_block)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            ops.addWidget(b)
        ops.addStretch(1)
        root.addLayout(ops)

        self.list = QListWidget()
        self.list.setSpacing(4)
        root.addWidget(self.list, 1)

    def load_from_session(self):
        self.blocks = [BodyBlock(level=b.level, text=b.text, label=b.label) for b in self.session.ir.body_tree]
        self.refresh()

    def refresh(self):
        self.list.clear()
        for b in self.blocks:
            item = QListWidgetItem(f"[{LEVEL_LABEL.get(b.level, b.level)}] {b.text}")
            item.setData(Qt.ItemDataRole.UserRole, b.level)
            self.list.addItem(item)

    def _selected_row(self) -> int:
        return self.list.currentRow()

    def set_level(self, level: str):
        row = self._selected_row()
        if row < 0:
            return
        self.blocks[row].level = level
        self.refresh()
        self.list.setCurrentRow(row)

    def renumber(self):
        self.blocks = renumber_blocks(self.blocks)
        self.refresh()

    def move_up(self):
        row = self._selected_row()
        if row <= 0:
            return
        self.blocks[row - 1], self.blocks[row] = self.blocks[row], self.blocks[row - 1]
        self.refresh()
        self.list.setCurrentRow(row - 1)

    def move_down(self):
        row = self._selected_row()
        if row < 0 or row >= len(self.blocks) - 1:
            return
        self.blocks[row + 1], self.blocks[row] = self.blocks[row], self.blocks[row + 1]
        self.refresh()
        self.list.setCurrentRow(row + 1)

    def delete_block(self):
        row = self._selected_row()
        if row < 0 or len(self.blocks) <= 1:
            return
        del self.blocks[row]
        self.refresh()
        self.list.setCurrentRow(min(row, len(self.blocks) - 1))

    def collect_to_session(self):
        # 同步列表文案（用户未直接编辑文本时保持原 text）
        self.session.set_body_tree(self.blocks)
