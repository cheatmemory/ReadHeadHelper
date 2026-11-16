# -*- coding: utf-8 -*-
"""测试公共夹具。

默认不强制关闭 Office 测宽（联合红头等用例依赖本机测宽口径）。
若设置环境变量 GOVDOC_TEST_NO_OFFICE=1，则跳过 Word/WPS COM，改走估算宽。
"""
from __future__ import annotations

import os

import core.layout.office_measure as om

if os.environ.get("GOVDOC_TEST_NO_OFFICE", "").strip() in {"1", "true", "TRUE", "yes"}:
    om._app_failed = True
    om._app = None
