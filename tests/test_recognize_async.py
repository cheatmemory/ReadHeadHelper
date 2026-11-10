# -*- coding: utf-8 -*-
"""后台识别：startRecognize 不阻塞，结束后发出 recognizeFinished。"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402

from app.bridge import BackendBridge  # noqa: E402
from core.ir.schema import ModelOutput  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


def test_start_recognize_emits_finished(qapp):
    bridge = BackendBridge()
    fake = ModelOutput.from_dict(
        {
            "header": {"org_mark": "××市人民政府", "doc_number": "×政发〔2024〕1号"},
            "main": {
                "title": "关于测试的通知",
                "recipient": "各有关单位：",
                "body_blocks": ["现通知如下："],
            },
            "footer": {
                "org_signature": "××市人民政府",
                "date": "2024年1月1日",
                "print_org": "××市人民政府办公室",
                "print_date": "2024年1月2日",
            },
        }
    )

    class FakeRec:
        def recognize(self, text):
            return fake

    bridge.recognizer = FakeRec()
    bridge.session.recognizer_name = "mock"

    got: list[dict] = []

    def on_finished(raw: str):
        got.append(json.loads(raw))
        loop.quit()

    loop = QEventLoop()
    bridge.recognizeFinished.connect(on_finished)
    started = json.loads(bridge.startRecognize("关于测试的通知\n各有关单位：\n现通知如下："))
    assert started["ok"] is True
    assert started.get("started") is True

    QTimer.singleShot(8000, loop.quit)
    loop.exec()

    assert got, "应收到 recognizeFinished"
    assert got[0]["ok"] is True
    assert got[0]["fields"]["title"] == "关于测试的通知"
