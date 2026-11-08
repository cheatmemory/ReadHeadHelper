# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.ir.schema import ModelOutput


@runtime_checkable
class FieldRecognizer(Protocol):
    """字段识别可替换接口。"""

    def recognize(self, text: str) -> ModelOutput:
        ...
