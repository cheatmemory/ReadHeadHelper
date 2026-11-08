# govdoc-sdk — 公文字段识别模型（打包版）

微调后的 UIE 公文抽取模型 + 独立推理 SDK。
**依赖只有两个：numpy、onnxruntime。不需要 PaddlePaddle、不需要 paddlenlp。**

## 文件清单

| 文件 | 说明 |
|---|---|
| `model.onnx` | 微调模型（uie-medium 6 层，422MB，MD5 `48deed668f7191fe79e3fee92e317d02`） |
| `vocab.txt` | 分词词表（必须与 model.onnx 配套） |
| `sdk/govdoc_sdk.py` | 推理引擎（分词 + ONNX 前向 + 解码，纯 Python） |
| `postprocess.py` | 正则后处理（补"附件说明"字段） |
| `example.py` | 最小接入示例 |
| `verify.py` | 自检脚本（校验模型哈希 + 端到端结果） |
| `example_text.txt` | 测试公文样例 |
| `requirements.txt` | 依赖清单 |

## 接入方法（三步）

```bash
pip install numpy onnxruntime
```

```python
from sdk.govdoc_sdk import GovDocExtractor
from postprocess import fill_attachment_caption

ex = GovDocExtractor("model.onnx", "vocab.txt")
result = ex.extract(text, ["标题", "发文字号", "成文日期", ...])   # 15 字段任选
result = fill_attachment_caption(result, text)                     # 正则补附件说明
```

返回结构：`{字段名: [{"text":..., "start":..., "end":..., "probability":...}]}`；
字段不存在时为空列表。

## 模型能力（test 集 510 样本实测）

- 15 字段中 14 个 F1 ≥ 0.93（11 个 = 1.0）。
- 唯一短板：附件说明（模型侧 F1=0，已用 postprocess.py 正则兜底）。
- 支持长文（自动按 512 token 切块）、跨行断字（PDF 复制噪声）。

## 自检

```bash
python verify.py    # 输出 ALL CHECKS PASSED 即为完整可用
```

## 注意事项

1. `model.onnx` 与 `vocab.txt` 必须同包分发，不可单独替换其一。
2. 校验模型未被改动：`python -c "import hashlib;print(hashlib.md5(open('model.onnx','rb').read()).hexdigest())"`，应等于 `48deed668f7191fe79e3fee92e317d02`。
3. Python ≥ 3.8；CPU 推理，单份公文（约 800 字）约 1~3 秒。
