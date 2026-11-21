# govdoc-sdk — 公文字段识别模型（打包版）

微调后的 UIE 公文抽取模型 + 独立推理 SDK + 文种判定。
**依赖只有两个：numpy、onnxruntime。不需要 PaddlePaddle、不需要 paddlenlp。**

支持四种文种：通用公文 16 字段、会议纪要 17 字段、命令（令）10 字段、信函 13 字段。

## 文件清单

| 文件 | 说明 |
|---|---|
| `model.onnx` | v5 微调模型（uie-medium 6 层，402.7MB，MD5 `0dbf791e0bf0e276621335b3410a4063`） |
| `vocab.txt` | 分词词表（必须与 model.onnx 配套） |
| `sdk/govdoc_sdk.py` | 推理引擎（分词 + ONNX 前向 + 解码，纯 Python） |
| `doc_kind.py` | 文种判定 + 四文种字段表 |
| `postprocess.py` | 正则后处理（校验 + 版式兜底 + 半截值修补） |
| `example.py` | 最小接入示例（三文种各跑一遍） |
| `verify.py` | 自检脚本（模型哈希 + 文种路由 + 端到端） |
| `example_text.txt` | 通用公文样例 |
| `example_order.txt` | 命令（令）样例 |
| `example_letter.txt` | 信函样例 |
| `requirements.txt` | 依赖清单 |

## 接入方法（四步）

```bash
pip install numpy onnxruntime
```

```python
from sdk.govdoc_sdk import GovDocExtractor
from postprocess import postprocess
import doc_kind

ex = GovDocExtractor("model.onnx", "vocab.txt")

kind = doc_kind.detect(text)          # 1) 判文种
schema = doc_kind.schema_for(kind)    # 2) 取该文种字段表
result = ex.extract(text, schema)     # 3) 只问该文种的字段
result = postprocess(result, text)    # 4) 校验 + 规则兜底
```

返回结构：`{字段名: [{"text":..., "start":..., "end":..., "probability":...}]}`；
字段不存在时为空列表。

判定不了文种时（例如文本残缺），直接用 `doc_kind.COMMON_FIELDS`。

## 四文种字段表

| 文种 | 字段数 | 字段 |
|---|---|---|
| 通用公文 | 16 | 份号、密级、保密期限、紧急程度、发文机关标志、发文字号、标题、主送机关、附件说明、发文机关署名、成文日期、附注、抄送机关、印发机关、印发日期、签发人 |
| 会议纪要 | 17 | 份号、密级、保密期限、紧急程度、发文机关标志、期号、标题、主送机关、附件说明、出席、请假、列席、成文日期、附注、抄送机关、印发机关、印发日期 |
| 命令（令） | 10 | 发文机关标志、令号、附件说明、签署职务、签署姓名、成文日期、附注、抄送机关、印发机关、印发日期 |
| 信函 | 13 | 份号、密级、保密期限、紧急程度、发文机关标志、发文字号、标题、主送机关、附件说明、发文机关署名、成文日期、附注、抄送机关 |

「正文」不是抽取字段。主送机关之后、附件说明/署名/落款之前的行区间就是正文，由你的程序按版式推导。

## 模型能力（v5 实测，模型 + postprocess）

| 测试集 | 份数 | 命中/漏/误 | F1 |
|---|---|---|---|
| 命令（令）300 份 | 300 | 2482 / 2 / 0 | 1.000 |
| 通用公文 + 纪要 + 信函混合 test200 | 200 | 2499 / 8 / 3 | 0.998 |
| — 其中通用公文 | 93 | 950 / 0 / 0 | 1.000 |
| — 其中会议纪要 | 100 | 1492 / 8 / 3 | 0.996 |
| — 其中信函 | 7 | 57 / 0 / 0 | 1.000 |
| 纪要独立留出集 | 61 | 871 / 12 / 5 | 0.990 |
| 信函存量冒烟集 | 11 | 87 / 2 / 3 | 0.972 |

命令集是训练集内文档，1.000 属拟合值。纪要的 8 漏 3 误全部在出席/列席/抄送，原因是长名单超过单次 512 token 被切块截断。

## 自检

```bash
python verify.py    # 输出 ALL CHECKS PASSED 即为完整可用
```

自检内容：模型 MD5、三个样例的文种判定、三个样例的端到端抽取（含命令的令号/签署职务/签署姓名）。
本机实测耗时 13.2 秒（39 个字段查询）。

## 注意事项

1. `model.onnx` 与 `vocab.txt` 必须同包分发，不可单独替换其一。
2. 校验模型未被改动：`python -c "import hashlib;print(hashlib.md5(open('model.onnx','rb').read()).hexdigest())"`，应等于 `0dbf791e0bf0e276621335b3410a4063`。
3. Python ≥ 3.8；CPU 推理。单次字段查询约 0.19 秒，耗时 ≈ 0.19 × 字段数 × 切块数。
4. 单次输入上限 505 汉字（`max_seq_len=512`）。超长文本自动切块，但字段值跨块时会被截断。
