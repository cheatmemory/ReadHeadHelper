# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Any

from core.recognize.mock import MockFieldRecognizer
from core.recognize.onnx_recognizer import OnnxFieldRecognizer


def create_recognizer(config: dict[str, Any] | None = None, project_root: str | Path | None = None):
    """按配置创建识别器；ONNX 不可用时回退 Mock。"""
    root = Path(project_root) if project_root else Path(__file__).resolve().parents[2]
    cfg = (config or {}).get("model") or {}
    enabled = bool(cfg.get("enabled", True))
    if not enabled:
        return MockFieldRecognizer(), "mock"

    onnx = root / str(cfg.get("onnx_path") or "third_party/govdoc-sdk/model.onnx")
    vocab = root / str(cfg.get("vocab_path") or "third_party/govdoc-sdk/vocab.txt")
    try:
        rec = OnnxFieldRecognizer(
            onnx,
            vocab,
            position_prob=float(cfg.get("position_prob", 0.5)),
            sdk_root=onnx.parent,
        )
        return rec, "onnx"
    except Exception as exc:  # noqa: BLE001 — 启动期回退
        print(f"[recognize] ONNX 不可用，回退 Mock：{exc}")
        return MockFieldRecognizer(), "mock"
