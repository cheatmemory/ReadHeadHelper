# -*- coding: utf-8 -*-
"""公文排版助手入口 —— 使用已定稿的 HTML 界面 + WebEngine。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _enable_dpi():
    # 必须在创建 QApplication 之前
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )


def main():
    _enable_dpi()
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from app.web_window import WebMainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("公文排版助手")
    app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    # 系统 UI 字体，避免模糊光栅
    font = app.font()
    font.setFamily("Microsoft YaHei UI")
    font.setHintingPreference(font.HintingPreference.PreferFullHinting)
    app.setFont(font)

    win = WebMainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
