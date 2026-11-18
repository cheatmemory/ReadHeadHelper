# -*- coding: utf-8 -*-
"""HTML 前端 ↔ Python 后端桥。"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
from pathlib import Path

from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QTimer, Slot, Signal
from PySide6.QtWidgets import QFileDialog

from app.session import AppSession
from core.body_structure.parser import renumber_blocks
from core.config_loader import load_config, project_root
from core.ir.builder import split_names
from core.ir.minutes import format_issue_no, normalize_name_list
from core.ir.schema import AttachmentDocx, BodyBlock, DocKind, LayoutIR, ModelOutput, SealMode
from core.layout import DocxEngine
from core.layout.office_preview import render_docx_preview
from core.recognize import create_recognizer
from core.text_extract import extract_text_from_docx


class BackendBridge(QObject):
    statusChanged = Signal(str)
    toast = Signal(str)
    recognizeFinished = Signal(str)  # JSON：识别结束（成功/失败），供前端异步接收
    previewFinished = Signal(str)  # JSON：Office 一比一预览页图

    def __init__(self, parent=None):
        super().__init__(parent)
        self.session = AppSession()
        self.config = load_config()
        self.recognizer = None
        self.session.recognizer_name = "pending"
        self._last_export = ""
        self._recog_busy = False
        self._recog_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="recognize")
        self._recog_future = None
        self._preview_busy = False
        self._preview_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="preview")
        self._preview_future = None
        self._preview_tmpdir: str | None = None

    def _field_trace_enabled(self) -> bool:
        return bool((self.config.get("debug") or {}).get("field_trace", False))

    def _ensure_recognizer(self):
        if self.recognizer is not None:
            return
        self.recognizer, self.session.recognizer_name = create_recognizer(self.config, project_root())

    def _build_recognize_payload(self) -> dict:
        ir = self.session.ir
        payload = {
            "ok": True,
            "recognizer": self.session.recognizer_name,
            "doc_kind": ir.doc_kind.value if ir.doc_kind else DocKind.GENERAL.value,
            "fields": {
                "copy_number": ir.copy_number,
                "secret_combo": (
                    f"{ir.secret_level}★{ir.secret_period}"
                    if ir.secret_level and ir.secret_period and "★" not in ir.secret_level
                    else (ir.secret_level or "")
                ),
                "urgency": ir.urgency,
                "issuer_sign": "、".join(ir.signers),
                "org_mark": "、".join(ir.org_marks),
                "doc_number": ir.doc_number,
                "issue_no": format_issue_no(ir.issue_no) or ir.issue_no,
                "title": ir.title,
                "recipient": ir.recipient,
                "attachment_caption": ir.attachment_caption,
                "org_signature": ir.org_signature,
                "date": ir.date,
                "note": ir.note,
                "cc_recipients": ir.cc_recipients,
                "print_org": ir.print_org,
                "print_date": ir.print_date,
                "attendance": ir.attendance,
                "leave": ir.leave,
                "liexi": ir.liexi,
                "attendance_absent_confirmed": bool(ir.attendance_absent_confirmed),
                "recipients_in_footer": bool(ir.recipients_in_footer),
            },
            "body_tree": [b.to_dict() for b in ir.body_tree],
        }
        if self._field_trace_enabled():
            payload["debug_field_trace"] = True
            payload["field_trace"] = self.session.field_trace or {"fields": {}}
            payload["body_trace"] = self.session.body_trace or {}
        return payload

    def _apply_recognizer_traces(self) -> None:
        rec = self.recognizer
        if not self._field_trace_enabled() or rec is None:
            self.session.field_trace = None
            self.session.body_trace = None
            return
        self.session.field_trace = getattr(rec, "_last_field_trace", None)
        self.session.body_trace = getattr(rec, "_last_body_trace", None)

    @Slot(result=str)
    def getAppInfo(self) -> str:
        # 启动时不立刻加载 422MB 模型，界面先出来
        name = self.session.recognizer_name
        if name == "pending":
            enabled = bool((self.config.get("model") or {}).get("enabled", True))
            name = "onnx(延迟加载)" if enabled else "mock"
        return json.dumps(
            {
                "name": "公文排版助手",
                "recognizer": name,
                "offline": True,
                "debug_field_trace": self._field_trace_enabled(),
            },
            ensure_ascii=False,
        )

    def _read_docx(self, path: str) -> str:
        return json.dumps(
            {"ok": True, "path": path, "text": extract_text_from_docx(path)},
            ensure_ascii=False,
        )

    @Slot(result=str)
    def pickDocx(self) -> str:
        path, _ = QFileDialog.getOpenFileName(None, "选择公文 docx", "", "Word (*.docx)")
        if not path:
            return json.dumps({"ok": False}, ensure_ascii=False)
        try:
            return self._read_docx(path)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(result=str)
    def pickAttachmentDocx(self) -> str:
        """选择一个或多个附件 docx，返回 base64（Qt WebEngine 无法可靠弹出隐藏 file input）。"""
        paths, _ = QFileDialog.getOpenFileNames(None, "选择附件 docx（可多选）", "", "Word (*.docx)")
        if not paths:
            return json.dumps({"ok": False, "cancelled": True}, ensure_ascii=False)
        items: list[dict] = []
        try:
            for path in paths:
                p = Path(path)
                if not p.is_file() or p.suffix.lower() != ".docx":
                    continue
                items.append(
                    {
                        "name": p.name,
                        "data_b64": base64.b64encode(p.read_bytes()).decode("ascii"),
                    }
                )
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
        if not items:
            return json.dumps({"ok": False, "error": "未选择有效的 .docx 文件"}, ensure_ascii=False)
        return json.dumps({"ok": True, "attachments": items}, ensure_ascii=False)

    @Slot(str, result=str)
    def importDocxPath(self, path: str) -> str:
        """拖拽等场景：按本机路径抽取 docx 文本。"""
        path = (path or "").strip().strip('"')
        if not path:
            return json.dumps({"ok": False, "error": "空路径"}, ensure_ascii=False)
        p = Path(path)
        if not p.is_file() or p.suffix.lower() != ".docx":
            return json.dumps({"ok": False, "error": "请选择 .docx 文件"}, ensure_ascii=False)
        try:
            return self._read_docx(str(p))
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(str, str, result=str)
    def importDocxBase64(self, name: str, b64: str) -> str:
        """浏览器 DnD 无路径时：用文件内容抽文本。"""
        name = (name or "drop.docx").strip() or "drop.docx"
        if not name.lower().endswith(".docx"):
            return json.dumps({"ok": False, "error": "请拖入 .docx 文件"}, ensure_ascii=False)
        try:
            raw = base64.b64decode(b64 or "", validate=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"ok": False, "error": f"解码失败：{exc}"}, ensure_ascii=False)
        if not raw:
            return json.dumps({"ok": False, "error": "空文件"}, ensure_ascii=False)
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(prefix="govdoc_", suffix=".docx")
            os.close(fd)
            Path(tmp_path).write_bytes(raw)
            return self._read_docx(tmp_path)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    @Slot(str, result=str)
    def recognize(self, text: str) -> str:
        """同步识别（兼容旧调用）；界面请用 startRecognize，避免主线程卡死。"""
        text = (text or "").strip()
        if not text:
            return json.dumps({"ok": False, "error": "请先粘贴或导入文稿"}, ensure_ascii=False)
        try:
            self._ensure_recognizer()
            trace_on = self._field_trace_enabled()
            model = self.recognizer.recognize(text, with_trace=trace_on)
            self.session.apply_model(model, source_text=text)
            self._apply_recognizer_traces()
            return json.dumps(self._build_recognize_payload(), ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    def _run_recognize_job(self, text: str):
        """线程池任务：返回 (recognizer, name, model, field_trace, body_trace) 或抛错。"""
        rec = self.recognizer
        name = self.session.recognizer_name
        if rec is None or name in ("pending", "onnx(延迟加载)"):
            rec, name = create_recognizer(self.config, project_root())
        trace_on = self._field_trace_enabled()
        # Mock 无 with_trace 参数时降级
        try:
            model = rec.recognize(text, with_trace=trace_on)
        except TypeError:
            model = rec.recognize(text)
        ft = getattr(rec, "_last_field_trace", None) if trace_on else None
        bt = getattr(rec, "_last_body_trace", None) if trace_on else None
        return rec, name, model, ft, bt

    @Slot(str, result=str)
    def startRecognize(self, text: str) -> str:
        """立即返回并在后台线程识别，完成后发 recognizeFinished(JSON)。"""
        if self._recog_busy:
            return json.dumps({"ok": False, "error": "正在识别，请稍候"}, ensure_ascii=False)
        text = (text or "").strip()
        if not text:
            return json.dumps({"ok": False, "error": "请先粘贴或导入文稿"}, ensure_ascii=False)

        self._recog_busy = True
        fut = self._recog_pool.submit(self._run_recognize_job, text)
        fut._source_text = text  # type: ignore[attr-defined]
        self._recog_future = fut
        QTimer.singleShot(40, self._poll_recognize_future)
        return json.dumps({"ok": True, "started": True}, ensure_ascii=False)

    @Slot()
    def _poll_recognize_future(self) -> None:
        fut = self._recog_future
        if fut is None:
            return
        if not fut.done():
            QTimer.singleShot(50, self._poll_recognize_future)
            return
        self._recog_future = None
        source = getattr(fut, "_source_text", "") or ""
        try:
            rec, name, model, ft, bt = fut.result()
            self.recognizer = rec
            self.session.recognizer_name = name
            self.session.apply_model(model, source_text=source)
            if self._field_trace_enabled():
                self.session.field_trace = ft
                self.session.body_trace = bt
            else:
                self.session.field_trace = None
                self.session.body_trace = None
            payload = self._build_recognize_payload()
        except Exception as exc:  # noqa: BLE001
            self._recog_busy = False
            self.recognizeFinished.emit(
                json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
            )
            return
        self._recog_busy = False
        self.recognizeFinished.emit(json.dumps(payload, ensure_ascii=False))

    @Slot(str, result=str)
    def renumberBody(self, body_json: str) -> str:
        try:
            items = json.loads(body_json or "[]")
            blocks = [BodyBlock.from_dict(x) for x in items]
            out = renumber_blocks(blocks)
            return json.dumps({"ok": True, "body_tree": [b.to_dict() for b in out]}, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot(str, result=str)
    def exportDocx(self, payload_json: str) -> str:
        try:
            data = json.loads(payload_json or "{}")
            self._apply_payload(data)
            missing = self.session.ir.missing_required()
            if missing:
                return json.dumps({"ok": False, "error": "缺少：" + "、".join(missing)}, ensure_ascii=False)

            ir = self.session.ir
            if ir.is_minutes():
                from core.ir.minutes import minutes_export_basename

                default_name = minutes_export_basename(ir)
            else:
                default_name = (ir.doc_number or "导出公文").replace("/", "-") + ".docx"
            out_dir = project_root() / "examples" / "out"
            out_dir.mkdir(parents=True, exist_ok=True)
            suggested = str(out_dir / default_name)
            path, _ = QFileDialog.getSaveFileName(None, "保存 docx", suggested, "Word (*.docx)")
            if not path:
                return json.dumps({"ok": False, "error": "已取消保存"}, ensure_ascii=False)
            if not path.lower().endswith(".docx"):
                path += ".docx"

            DocxEngine().render(self.session.ir, path)
            self._last_export = path
            self.session.last_export_path = path
            return json.dumps({"ok": True, "path": path}, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @staticmethod
    def _preview_job(ir_data: dict, tmp_dir: str) -> dict:
        """后台线程：写 docx + Office 渲页图（勿在主线程做）。"""
        seal = ir_data.get("seal_mode")
        kind = ir_data.get("doc_kind") or DocKind.GENERAL.value
        body = [BodyBlock.from_dict(x) for x in (ir_data.get("body_tree") or [])]
        atts = [
            AttachmentDocx.from_dict(x) if isinstance(x, dict) else AttachmentDocx(name=str(x))
            for x in (ir_data.get("attachments") or [])
        ]
        skip = {"seal_mode", "doc_kind", "body_tree", "attachments"}
        kwargs = {
            k: v
            for k, v in ir_data.items()
            if k in LayoutIR.__dataclass_fields__ and k not in skip
        }
        ir = LayoutIR(**kwargs)
        try:
            ir.doc_kind = DocKind(kind)
        except ValueError:
            ir.doc_kind = DocKind.GENERAL
        if ir.is_minutes():
            ir.seal_mode = None
        else:
            ir.seal_mode = SealMode(seal) if seal else None
        ir.body_tree = body
        ir.attachments = atts
        docx_path = Path(tmp_dir) / "preview.docx"
        DocxEngine().render(ir, docx_path)
        # 有附件时多渲几页，避免只看到正文
        max_pages = 3 + max(0, len(atts)) * 2
        return render_docx_preview(docx_path, max_pages=max_pages, zoom=1.6)

    @Slot(str, result=str)
    def startPreview(self, payload_json: str) -> str:
        """立即返回；docx 渲染与 WPS/Word 预览均在后台线程完成。"""
        if self._preview_busy:
            return json.dumps({"ok": False, "error": "预览生成中，请稍候"}, ensure_ascii=False)
        try:
            data = json.loads(payload_json or "{}")
            self._apply_payload(data)
            missing = self.session.ir.missing_required()
            if missing:
                return json.dumps(
                    {"ok": False, "error": "缺少：" + "、".join(missing)},
                    ensure_ascii=False,
                )

            tmp_dir = Path(tempfile.mkdtemp(prefix="govdoc_prev_"))
            self._preview_tmpdir = str(tmp_dir)
            ir_data = self.session.ir.to_dict()

            self._preview_busy = True
            fut = self._preview_pool.submit(self._preview_job, ir_data, str(tmp_dir))
            fut._cleanup_dir = str(tmp_dir)  # type: ignore[attr-defined]
            self._preview_future = fut
            QTimer.singleShot(40, self._poll_preview_future)
            return json.dumps({"ok": True, "started": True}, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            self._preview_busy = False
            return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)

    @Slot()
    def _poll_preview_future(self) -> None:
        fut = self._preview_future
        if fut is None:
            return
        if not fut.done():
            QTimer.singleShot(80, self._poll_preview_future)
            return
        self._preview_future = None
        cleanup = getattr(fut, "_cleanup_dir", None)
        try:
            result = fut.result()
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "error": str(exc)}
        self._preview_busy = False
        self.previewFinished.emit(json.dumps(result, ensure_ascii=False))
        if cleanup:
            try:
                p = Path(cleanup)
                for f in p.glob("*"):
                    try:
                        f.unlink()
                    except OSError:
                        pass
                p.rmdir()
            except OSError:
                pass
            if self._preview_tmpdir == cleanup:
                self._preview_tmpdir = None

    @Slot(result=str)
    def openLastExport(self) -> str:
        path = self._last_export or self.session.last_export_path
        if not path or not Path(path).exists():
            return json.dumps({"ok": False, "error": "请先生成 docx"}, ensure_ascii=False)
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except Exception:
            subprocess.Popen(["cmd", "/c", "start", "", path], shell=False)
        return json.dumps({"ok": True, "path": path}, ensure_ascii=False)

    def _apply_payload(self, data: dict):
        ir = self.session.ir
        fields = data.get("fields") or {}
        secret = str(fields.get("secret_combo") or "")
        if "★" in secret:
            a, b = secret.split("★", 1)
            ir.secret_level, ir.secret_period = a.strip(), b.strip()
        else:
            ir.secret_level, ir.secret_period = secret.strip(), ""

        kind_raw = data.get("doc_kind") or fields.get("doc_kind") or DocKind.GENERAL.value
        try:
            ir.doc_kind = DocKind(str(kind_raw))
        except ValueError:
            ir.doc_kind = DocKind.GENERAL

        ir.copy_number = str(fields.get("copy_number") or "").strip()
        ir.urgency = str(fields.get("urgency") or "").strip()
        ir.signers = split_names(str(fields.get("issuer_sign") or ""))
        org_raw = str(fields.get("org_mark") or "").strip()
        # 纪要标志通常整串含顿号机关名，勿按顿号拆成多标志
        if ir.is_minutes():
            ir.org_marks = [org_raw] if org_raw else []
        else:
            ir.org_marks = split_names(org_raw)
        ir.doc_number = str(fields.get("doc_number") or "").strip()
        ir.issue_no = format_issue_no(str(fields.get("issue_no") or ""))
        ir.title = str(fields.get("title") or "").strip()
        ir.recipient = str(fields.get("recipient") or "").strip()
        ir.attachment_caption = str(fields.get("attachment_caption") or "").strip()
        ir.org_signature = str(fields.get("org_signature") or "").strip()
        ir.date = str(fields.get("date") or "").strip()
        ir.note = str(fields.get("note") or "").strip()
        ir.cc_recipients = str(fields.get("cc_recipients") or "").strip()
        ir.print_org = str(fields.get("print_org") or "").strip()
        ir.print_date = str(fields.get("print_date") or "").strip()
        ir.attendance = normalize_name_list(str(fields.get("attendance") or ""))
        ir.leave = normalize_name_list(str(fields.get("leave") or ""))
        ir.liexi = normalize_name_list(str(fields.get("liexi") or ""))
        ir.attendance_absent_confirmed = bool(
            fields.get("attendance_absent_confirmed")
            or (data.get("absent_flags") or {}).get("f-attendance")
            or (data.get("absent_flags") or {}).get("attendance")
        )
        ir.recipients_in_footer = bool(fields.get("recipients_in_footer"))
        if ir.is_minutes() and ir.recipient.strip():
            ir.recipients_in_footer = True
        ir.absent_flags = dict(data.get("absent_flags") or {})

        seal = data.get("seal_mode")
        if ir.is_minutes():
            ir.seal_mode = None
        else:
            ir.seal_mode = SealMode(seal) if seal else None

        body = data.get("body_tree") or []
        ir.body_tree = [BodyBlock.from_dict(x) for x in body]

        atts = data.get("attachments") or []
        ir.attachments = [
            AttachmentDocx.from_dict(x) if isinstance(x, dict) else AttachmentDocx(name=str(x))
            for x in atts
        ]
