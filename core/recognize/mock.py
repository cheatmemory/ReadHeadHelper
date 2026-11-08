# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from core.ir.schema import ModelOutput


class MockFieldRecognizer:
    """读取 fixture JSON；也可按关键字选择样例。"""

    def __init__(self, fixture_path: str | Path | None = None, fixtures_dir: str | Path | None = None):
        root = Path(__file__).resolve().parents[2]
        self.fixtures_dir = Path(fixtures_dir) if fixtures_dir else root / "fixtures" / "mock_json"
        self.fixture_path = Path(fixture_path) if fixture_path else self.fixtures_dir / "downlink_stamp.json"

    def recognize(self, text: str) -> ModelOutput:
        path = self._pick_fixture(text)
        data = json.loads(path.read_text(encoding="utf-8"))
        return ModelOutput.from_dict(data)

    def _pick_fixture(self, text: str) -> Path:
        t = text or ""
        if "签发人" in t or "请示" in t:
            cand = self.fixtures_dir / "uplink_signer.json"
            if cand.exists():
                return cand
        if "联合" in t or t.count("人民政府") >= 2 and "文件" in t:
            cand = self.fixtures_dir / "joint_full.json"
            if cand.exists():
                return cand
        return self.fixture_path
