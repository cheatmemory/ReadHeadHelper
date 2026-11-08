# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QMainWindow

from app.bridge import BackendBridge


class WebMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("公文排版助手")
        self.resize(1280, 860)

        self.view = QWebEngineView(self)
        self.setCentralWidget(self.view)

        settings = self.view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        # 清晰字体
        settings.setFontFamily(QWebEngineSettings.FontFamily.StandardFont, "Microsoft YaHei UI")
        settings.setFontFamily(QWebEngineSettings.FontFamily.SansSerifFont, "Microsoft YaHei UI")
        settings.setFontSize(QWebEngineSettings.FontSize.DefaultFontSize, 14)

        self.bridge = BackendBridge(self)
        self.channel = QWebChannel(self.view.page())
        self.channel.registerObject("backend", self.bridge)
        self.view.page().setWebChannel(self.channel)

        html = Path(__file__).resolve().parent / "web" / "index.html"
        self.view.load(QUrl.fromLocalFile(str(html)))
