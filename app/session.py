# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field

from core.ir.schema import BodyBlock, LayoutIR, ModelOutput, SealMode


@dataclass
class AppSession:
    raw_text: str = ""
    model: ModelOutput = field(default_factory=ModelOutput)
    ir: LayoutIR = field(default_factory=LayoutIR)
    recognizer_name: str = "mock"
    last_export_path: str = ""

    def apply_model(self, model: ModelOutput, source_text: str = ""):
        from core.ir.builder import model_to_partial_ir

        self.model = model
        self.raw_text = source_text or self.raw_text
        self.ir = model_to_partial_ir(model, source_text=self.raw_text)
        # SDK 抄送
        cc = getattr(model, "_sdk_cc", "") or ""
        if cc:
            self.ir.cc_recipients = cc

    def set_body_tree(self, blocks: list[BodyBlock]):
        self.ir.body_tree = list(blocks)

    def set_seal_mode(self, mode: SealMode | None):
        self.ir.seal_mode = mode
