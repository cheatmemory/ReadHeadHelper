# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.pages.confirm_page import ConfirmPage
from app.pages.export_page import ExportPage
from app.pages.import_page import ImportPage
from app.pages.structure_page import StructurePage
from app.session import AppSession
from core.config_loader import load_config, project_root
from core.recognize import create_recognizer


class MainWindow(QMainWindow):
    STEPS = ["导入文稿", "确认要素", "正文结构", "生成导出"]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("公文排版助手")
        self.resize(1180, 780)
        self.session = AppSession()
        self.config = load_config()
        self.recognizer, self.session.recognizer_name = create_recognizer(self.config, project_root())
        self.step = 0
        self._build()
        self._apply_qss()

    def _apply_qss(self):
        qss = (project_root() / "app" / "styles.qss").read_text(encoding="utf-8")
        self.setStyleSheet(qss)

    def _build(self):
        central = QWidget()
        central.setObjectName("Central")
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        top = QFrame()
        top.setObjectName("TopBar")
        top_l = QHBoxLayout(top)
        top_l.setContentsMargins(22, 14, 22, 14)
        brand = QVBoxLayout()
        title = QLabel("公文排版助手")
        title.setObjectName("AppTitle")
        sub = QLabel(f"本地离线 · 识别器：{self.session.recognizer_name.upper()} · GB/T 9704-2012")
        sub.setObjectName("AppSub")
        brand.addWidget(title)
        brand.addWidget(sub)
        top_l.addLayout(brand, 1)
        badge = QLabel("纯本地")
        badge.setStyleSheet("background:#e7f5ee;color:#0f7a4c;border-radius:999px;padding:4px 10px;")
        top_l.addWidget(badge)
        layout.addWidget(top)

        step_bar = QFrame()
        step_bar.setStyleSheet("background:#fff;border-bottom:1px solid #d7dde8;")
        step_l = QHBoxLayout(step_bar)
        step_l.setContentsMargins(8, 0, 8, 0)
        self.step_btns: list[QPushButton] = []
        for i, name in enumerate(self.STEPS):
            btn = QPushButton(f"{i + 1}  {name}")
            btn.setObjectName("StepBtn")
            btn.clicked.connect(lambda checked=False, idx=i: self.goto_step(idx, from_nav=True))
            self.step_btns.append(btn)
            step_l.addWidget(btn)
        layout.addWidget(step_bar)

        self.stack = QStackedWidget()
        self.import_page = ImportPage()
        self.confirm_page = ConfirmPage(self.session)
        self.structure_page = StructurePage(self.session)
        self.export_page = ExportPage(self.session)
        for page in (self.import_page, self.confirm_page, self.structure_page, self.export_page):
            self.stack.addWidget(page)
        layout.addWidget(self.stack, 1)

        foot = QFrame()
        foot.setObjectName("FooterBar")
        foot_l = QHBoxLayout(foot)
        foot_l.setContentsMargins(18, 12, 18, 12)
        self.step_label = QLabel()
        foot_l.addWidget(self.step_label, 1)
        self.btn_back = QPushButton("上一步")
        self.btn_back.clicked.connect(self.back)
        self.btn_next = QPushButton("开始识别")
        self.btn_next.setObjectName("Primary")
        self.btn_next.clicked.connect(self.next)
        foot_l.addWidget(self.btn_back)
        foot_l.addWidget(self.btn_next)
        layout.addWidget(foot)

        self._sync_chrome()

    def _sync_chrome(self):
        for i, btn in enumerate(self.step_btns):
            btn.setProperty("active", "true" if i == self.step else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self.step_label.setText(f"步骤 {self.step + 1} / 4 · {self.STEPS[self.step]} · {self.session.recognizer_name}")
        self.btn_back.setEnabled(self.step > 0)
        self.btn_next.setText(["开始识别", "下一步", "下一步", "生成 docx"][self.step])
        self.stack.setCurrentIndex(self.step)

    def goto_step(self, idx: int, from_nav: bool = False):
        if from_nav and idx > self.step:
            # 禁止跳过未完成校验的步骤
            if not self._validate_before(idx):
                return
        self.step = max(0, min(3, idx))
        if self.step == 1:
            self.confirm_page.load_from_session()
        elif self.step == 2:
            self.confirm_page.collect_to_session()
            self.structure_page.load_from_session()
        self._sync_chrome()

    def _validate_before(self, target: int) -> bool:
        if target >= 1 and not self.import_page.current_text() and not self.session.raw_text:
            QMessageBox.information(self, "提示", "请先粘贴或导入文稿")
            return False
        if target >= 2:
            missing = self.confirm_page.collect_to_session()
            if not self.confirm_page.seal_ok():
                QMessageBox.warning(self, "提示", "请先选择有章 / 无章版式")
                return False
            # 允许进入结构页，即使其它必填仍缺——最终导出再拦
            _ = missing
        return True

    def back(self):
        self.goto_step(self.step - 1)

    def next(self):
        if self.step == 0:
            text = self.import_page.current_text()
            if not text:
                QMessageBox.information(self, "提示", "请先粘贴文本或载入样例")
                return
            try:
                model = self.recognizer.recognize(text)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "识别失败", str(exc))
                return
            self.session.apply_model(model, source_text=text)
            self.goto_step(1)
            return
        if self.step == 1:
            self.confirm_page.collect_to_session()
            if not self.confirm_page.seal_ok():
                QMessageBox.warning(self, "提示", "请先选择有章 / 无章版式")
                return
            self.goto_step(2)
            return
        if self.step == 2:
            self.structure_page.collect_to_session()
            self.goto_step(3)
            return
        if self.step == 3:
            self.structure_page.collect_to_session()
            self.confirm_page.collect_to_session()
            self.export_page.export()
