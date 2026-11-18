# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Any

from core.recognize.onnx_recognizer import OnnxFieldRecognizer


def create_recognizer(config: dict[str, Any] | None = None, project_root: str | Path | None = None):
    """创建 ONNX 识别器；模型缺失或加载失败时直接抛错（不再回退 Mock）。"""
    root = Path(project_root) if project_root else Path(__file__).resolve().parents[2]
    cfg = (config or {}).get("model") or {}
    if not bool(cfg.get("enabled", True)):
        raise RuntimeError(
            "模型未启用（config/default.yaml 中 model.enabled=false）。请改为 true 并放置 model.onnx。"
        )

    onnx = root / str(cfg.get("onnx_path") or "third_party/govdoc-sdk/model.onnx")
    vocab = root / str(cfg.get("vocab_path") or "third_party/govdoc-sdk/vocab.txt")
    if not onnx.is_file():
        raise FileNotFoundError(
            f"未找到 ONNX 模型：{onnx}\n"
            "请将 model.onnx 放到 third_party/govdoc-sdk/（与 vocab.txt 配套）后再识别。"
        )
    if not vocab.is_file():
        raise FileNotFoundError(
            f"未找到词表：{vocab}\n"
            "请将 vocab.txt 与 model.onnx 一并放到 third_party/govdoc-sdk/。"
        )

    try:
        rec = OnnxFieldRecognizer(
            onnx,
            vocab,
            position_prob=float(cfg.get("position_prob", 0.5)),
            sdk_root=onnx.parent,
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"ONNX 识别器加载失败：{exc}") from exc
    return rec, "onnx"
