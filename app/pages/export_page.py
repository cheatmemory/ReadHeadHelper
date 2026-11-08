# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.session import AppSession
from core.config_loader import project_root
from core.layout import DocxEngine


class ExportPage(QWidget):
    def __init__(self, session: AppSession, parent=None):
        super().__init__(parent)
        self.session = session
        self.out_path = str(project_root() / "examples" / "out" / "导出公文.docx")
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        t = QLabel("生成导出")
        t.setStyleSheet("font-size:20px;font-weight:700;")
        s = QLabel("按 LayoutIR 生成 docx。验收以 WPS 打开核对国标数值为准。")
        s.setObjectName("Hint")
        root.addWidget(t)
        root.addWidget(s)

        self.path_label = QLabel(self.out_path)
        self.path_label.setWordWrap(True)
        root.addWidget(self.path_label)

        row = QHBoxLayout()
        browse = QPushButton("更改路径…")
        browse.clicked.connect(self.browse)
        self.btn_export = QPushButton("生成 docx")
        self.btn_export.setObjectName("Accent")
        self.btn_export.clicked.connect(self.export)
        self.btn_wps = QPushButton("用 WPS 打开")
        self.btn_wps.setEnabled(False)
        self.btn_wps.clicked.connect(self.open_wps)
        row.addWidget(browse)
        row.addWidget(self.btn_export)
        row.addWidget(self.btn_wps)
        row.addStretch(1)
        root.addLayout(row)

        self.status = QLabel("")
        self.status.setObjectName("Hint")
        root.addWidget(self.status)
        root.addStretch(1)

    def browse(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存 docx", self.out_path, "Word (*.docx)")
        if path:
            if not path.lower().endswith(".docx"):
                path += ".docx"
            self.out_path = path
            self.path_label.setText(path)

    def export(self) -> bool:
        ir = self.session.ir
        missing = ir.missing_required()
        if missing:
            QMessageBox.warning(self, "无法导出", "缺少：" + "、".join(missing))
            return False
        try:
            engine = DocxEngine()
            out = engine.render(ir, self.out_path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "生成失败", str(exc))
            return False
        self.session.last_export_path = str(out)
        self.btn_wps.setEnabled(True)
        self.status.setText(f"已生成：{out}")
        QMessageBox.information(self, "完成", f"已生成\n{out}")
        return True

    def open_wps(self):
        path = self.session.last_export_path or self.out_path
        if not path or not Path(path).exists():
            QMessageBox.warning(self, "文件不存在", "请先生成 docx")
            return
        # 软依赖：优先 startfile，WPS 若关联 docx 会被唤起
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except Exception:
            subprocess.Popen(["cmd", "/c", "start", "", path], shell=False)
