# 公文排版助手

Windows 本地离线桌面程序：粘贴文本 / 上传 docx → 本地字段识别（Mock 或 ONNX）→ 确认要素 → 正文结构 → 按 **GB/T 9704-2012** 生成 docx。

## 环境

- Python 3.10–3.13（SDK 文档写 3.8–3.12；本机可用 3.13 时请先跑通 `verify`）
- 依赖见 `requirements.txt`（`numpy`、`onnxruntime`、`PySide6`、`python-docx`、`PyYAML`）

```bash
cd "E:\red head\Red Head Helper"
py -m pip install -r requirements.txt
```

## 运行界面

```bash
py main.py
```

界面就是原先定稿的 HTML（`app/web/index.html`），用 Qt WebEngine 全屏承载，经 QWebChannel 调 Python 识别/导出。  
不要再用那套原生 Qt 表单壳。

流程：导入文稿 → 确认要素（必选有章/无章）→ 正文结构 → 生成 docx。  
首次点「开始识别」才会加载 ONNX（约数秒）。

## 模型（govdoc-sdk）

已解压到 `third_party/govdoc-sdk/`（含 `model.onnx` + `vocab.txt` + 接入指南）。

- 配置：`config/default.yaml` → `model.enabled` / `onnx_path` / `vocab_path`
- `enabled: true` 且模型可读 → `OnnxFieldRecognizer`（调用 SDK + `postprocess`）
- 否则自动回退 `MockFieldRecognizer`（`fixtures/mock_json/`）

自检 SDK：

```bash
cd third_party/govdoc-sdk
py verify.py
```

字段名以 SDK 中文 schema 为准，程序内映射为提示词 §3 英文契约后再进 LayoutIR。抄送机关由 SDK 给出时可写入确认页；签发人若不在模型输出中，在确认页补填。

## 无界面生成示例

```bash
py scripts/generate_example.py
```

输出：`examples/out/下行文_无章_示例.docx`、`下行文_有章_示例.docx`

## 测试

```bash
py -m pytest tests -q
```

## 目录

```
app/                 桌面 UI（PySide6）
core/recognize/      FieldRecognizer / Mock / Onnx
core/ir/             ModelOutput + LayoutIR
core/body_structure/ 正文四层与重排编号
core/layout/         DocxEngine（模板+OOXML）
core/text_extract/   docx→纯文本
third_party/govdoc-sdk/  识别模型 SDK
fixtures/            Mock 与样例文本
config/default.yaml  配置
```

## WPS 验收要点

- 页边距上 37mm、左 28mm；版心约 156×225mm，网格 22×28
- 红头上边缘距版心顶约 35mm（不是「上边距 37 + 当第一行」）
- 发文字号下红线约 4mm、2pt、纯红
- 有章 / 无章落款位置分别核对
- 无模型文件时 Mock 全流程仍可导出

## 说明

- 不生成印章图形；不导出 PDF；不联网上传文稿
- 附件只做正文「附件说明」行，不做附件另面
- 排版精度会按里程碑继续加深；当前 DocxEngine 为可运行 v1
