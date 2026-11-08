# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.config_loader import project_root
from core.text_extract import extract_text_from_docx


class ImportPage(QWidget):
    recognize_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(12)

        head = QHBoxLayout()
        title_box = QVBoxLayout()
        t = QLabel("导入文稿")
        t.setStyleSheet("font-size:20px;font-weight:700;")
        s = QLabel("粘贴纯文本，或上传 docx（仅抽取文本）。识别走本地 Mock/ONNX，不上传网络。")
        s.setObjectName("Hint")
        s.setWordWrap(True)
        title_box.addWidget(t)
        title_box.addWidget(s)
        head.addLayout(title_box, 1)
        btn_sample = QPushButton("载入样例")
        btn_sample.clicked.connect(self.load_sample)
        head.addWidget(btn_sample)
        root.addLayout(head)

        btn_file = QPushButton("选择 Word 文件（.docx）")
        btn_file.clicked.connect(self.pick_docx)
        root.addWidget(btn_file)

        root.addWidget(QLabel("或粘贴文本"))
        self.text = QTextEdit()
        self.text.setPlaceholderText("在此粘贴公文全文……")
        root.addWidget(self.text, 1)

        self.meta = QLabel("0 字")
        self.meta.setObjectName("Hint")
        root.addWidget(self.meta)
        self.text.textChanged.connect(self._on_changed)

    def _on_changed(self):
        n = len(self.text.toPlainText())
        self.meta.setText(f"{n} 字")

    def load_sample(self):
        path = project_root() / "fixtures" / "sample_text" / "downlink.txt"
        self.text.setPlainText(path.read_text(encoding="utf-8"))

    def pick_docx(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择公文 docx", "", "Word (*.docx)")
        if not path:
            return
        try:
            text = extract_text_from_docx(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "读取失败", str(exc))
            return
        self.text.setPlainText(text)

    def current_text(self) -> str:
        return self.text.toPlainText().strip()
