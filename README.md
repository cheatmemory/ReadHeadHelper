# 公文排版助手

**版本：V1.1**（界面优化 + 会议纪要公文支持）

Windows 本地离线桌面程序：粘贴文本 / 上传 docx → 本地 ONNX 字段识别 → 确认要素 → 正文结构 → 按 **GB/T 9704-2012** 生成 docx。确认与结构步骤可借助本机 WPS/Word 做接近一比一的页图预览。

## 版本说明

| 版本 | 说明 |
|------|------|
| **V1.1**（当前） | 优化 Web 界面；新增**会议纪要**文种（标志、期号、出席/请假/列席；无红线、不选有章/无章） |
| V1.0 | 通用公文识别与排版、有章/无章落款、正文四层结构、docx 导出 |

## 环境

- Python 3.10–3.13（SDK 文档写 3.8–3.12；本机用 3.13 时请先跑通 `third_party/govdoc-sdk/verify.py`）
- 依赖见 `requirements.txt`：`numpy`、`onnxruntime`、`PySide6`、`python-docx`、`PyYAML`、`pywin32`、`pymupdf`  
  （后两者仅用于 Office 页图预览；无 WPS/Word 时仍可识别与导出 docx）
- **识别依赖 `model.onnx`**：缺失或加载失败时直接报错，不会假装识别

```bash
cd "项目根目录"
py -m pip install -r requirements.txt
```

## 运行界面

```bash
py main.py
```

界面为定稿 HTML（`app/web/index.html`），由 Qt WebEngine 承载，经 QWebChannel 调用 Python 识别 / 预览 / 导出。  
入口是 `app/web_window.py`，不要再用 `app/main_window.py` 那套原生 Qt 表单壳。

**流程：** 导入文稿 → 确认要素 → 正文结构 → 生成 docx。

- **通用公文**：确认页须选择有章 / 无章落款版式。
- **会议纪要**：可自动识别或手动切换；须补全纪要标志、正文、出席名单（或确认「本件无」）；不选印章版式、不画红线。
- 首次点「开始识别」才会加载 ONNX（约数秒）。模型文件不存在、`model.enabled=false` 或加载失败时，识别会返回明确错误。

## 模型（govdoc-sdk）

SDK 与词表在 `third_party/govdoc-sdk/`（含 `vocab.txt`、接入指南与代码）。  
**`model.onnx`（约 400MB）不纳入 Git**，需自行放到该目录（与 `vocab.txt` 配套）。见仓库 `.gitignore`。

- 配置：`config/default.yaml` → `model.enabled` / `onnx_path` / `vocab_path`
- `enabled: true` 且 `model.onnx`、`vocab.txt` 可读 → `OnnxFieldRecognizer`（SDK + `postprocess`，非纪要另经 `review`）
- 否则 `create_recognizer` / 识别接口直接抛错（不再使用假识别器）

自检 SDK：

```bash
cd third_party/govdoc-sdk
py verify.py
```

字段名以 SDK 中文 schema 为准；程序内映射为英文契约 `ModelOutput` 后再进 `LayoutIR`。  
通用文约 16 字段；纪要约 17 字段（含期号、出席/请假/列席）。抄送可由 SDK 写入确认页；签发人若缺失，在确认页补填。

## 无界面生成示例

```bash
py scripts/generate_example.py
```

输出：`examples/out/下行文_无章_示例.docx`、`下行文_有章_示例.docx`。  
该脚本直接读取 `fixtures/mock_json/` 中的样例 JSON 做排版演示，**不调用识别器**，因此可不依赖 `model.onnx`。

## 测试

```bash
py -m pytest tests -q
```

依赖 ONNX 的端到端用例在缺少 `model.onnx` 时会自动 skip。

## 目录

```
main.py                 入口
app/                    桌面壳（WebEngine + bridge + session）
  web/index.html        定稿界面
  bridge.py             HTML ↔ Python
  session.py            会话中的 ModelOutput / LayoutIR
core/recognize/         Onnx 识别 / factory / review
core/ir/                ModelOutput、LayoutIR、纪要判定与字段
core/body_structure/    正文抽取与四层编号
core/layout/            DocxEngine、附件并入、Office 预览
core/text_extract/      docx → 纯文本
third_party/govdoc-sdk/ 识别 SDK（model.onnx 需自备）
fixtures/               排版/测试用样例 JSON 与原文（非识别器）
docs/baselines/         纪要等基线说明
config/default.yaml     配置
scripts/                无界面示例脚本
tests/                  pytest
```

## WPS 验收要点

- 页边距上 37mm、左 28mm；版心约 156×225mm，网格 22×28
- 红头上边缘距版心顶约 35mm（不是「上边距 37 + 当第一行」）
- 发文字号下红线约 4mm、2pt、纯红（**纪要不画红线**）
- 有章 / 无章落款位置分别核对（**纪要不选印章版式**）
- 正式识别必须有 `model.onnx`；缺模型时点「开始识别」应报错而非填入假数据

## 下一步更新方向

- **优化排版引擎**：加深 GB/T 9704 版式精度（版心、红头几何、落款与版记等）
- **扩展文种**：在现有通用公文与会议纪要之外，逐步支持**函、命令**及其他公文格式

## 说明

- 本地离线：不联网上传文稿；不生成印章图形；用户侧不导出 PDF（预览可能经本机 Office 临时转 PDF 再出页图）
- 附件说明行在正文排版；另可上传附件 docx，导出时另页接入原文（「附件N」+ 空行 + 正文，不做国标附件另面精细排版）
- 当前发布版本为 **V1.1**
