# Shenji-TRRACE — 技术参考手册

> 版本: v3.1 Bugfix | 训练日期: 2026-07-10
> 模型: GPT-2 8L/320d/8h, 11.2M params, SentencePiece BPE 4000
> Bugfix: per-epoch shuffle + attention_mask + label masking (-100)

---

## 0. 环境要求

### 最小依赖

```
Python >= 3.10
torch >= 2.0
transformers >= 4.40
sentencepiece >= 0.2
numpy
```

### 安装

```bash
pip install torch transformers sentencepiece numpy
```

### 硬件

| 模式 | 需求 |
|------|------|
| GPU 推理 (推荐) | NVIDIA GPU, >= 2GB VRAM |
| CPU 推理 (慢) | 任意 CPU, >= 2GB RAM |

本模型 11.2M 参数, RTX 3050 上仅用 ~1.2 GB VRAM。

### 独立使用

本目录完全自包含 — 不依赖 TRACE 项目文件夹:

```python
# 将此目录放在任意位置, 然后:
from shenji_trrace import ShenjiTRRACE
engine = ShenjiTRRACE()                     # 自动加载同目录模型
result = engine.trace("你的文本...")         # 运行 TRACE
print(engine.report(result))
```

```bash
# 命令行
python shenji_trrace.py "姬神蜕出皮，其皮钻入我灵"
python shenji_trrace.py --file article.txt --threshold 0.5
```

### 文件结构

```
Shenji-TRRACE/                  ← 可移植包 (任意位置)
├── shenji_trrace.py            ← 加载器 + TRACE 引擎 + CLI
├── model.safetensors           ← 权重 (44 MB)
├── config.json                 ← 模型架构
├── generation_config.json
├── spm.model                   ← SentencePiece BPE 分词器 (288 KB)
├── spm.vocab                   ← 词表 (48 KB)
└── MODEL_REFERENCE.md          ← 本文件
```

---

## 1. 模型档案

| 属性 | 值 |
|------|-----|
| 架构 | GPT-2 (transformers) |
| 层数 | 8 |
| 隐层维度 | 320 |
| 注意力头数 | 8 |
| 参数量 | 11.2M |
| 词表大小 | 4000 (SentencePiece BPE) |
| 位置编码 | 绝对位置 (max 256) |
| 激活函数 | GELU (new) |
| 训练 epochs | 50 |
| Batch size | 32 |
| Warmup | 100 steps → cosine decay |
| 优化器 | AdamW (lr=3e-4, wd=0.01) |
| 最佳 loss | 0.2517 |
| 训练时间 | 507s (RTX 3050 Laptop) |
| 模型大小 | ~44 MB (safetensors) |
| VRAM 需求 | ~1.5 GB (推理), ~2.0 GB (训练) |

## 2. 文件清单

```
F:/攻略/研发测试/TRACE/models/shenji-trrace/
├── model.safetensors    ← GPT-2 权重 (~44 MB)
├── config.json           ← 模型配置
├── generation_config.json
├── spm.model             ← SentencePiece BPE 分词器 (288 KB)
├── spm.vocab             ← 词表 (49 KB)
└── trace_results.json    ← 最近一次 TRACE 结果
```

## 3. 训练数据

| 属性 | 值 |
|------|-----|
| 源文件 | `神纪 - [一前传 + 二部曲 + 三公式 + 二外传 + 二番外].md` |
| 原始大小 | 240,757 字符 |
| 清洗后 | 37,794 字符 (1,546 行) |
| 编码后 | 26,072 tokens |
| 段落级样本 | 943 samples × 256 tokens |
| CJK 字符占比 | 75% |

## 4. 分词器

- **类型**: SentencePiece BPE (byte-pair encoding)
- **词表**: 4000 tokens, 其中 ~1575 个 CJK 多字词
- **Special tokens**: `<pad>=1, <bos>=2, <eos>=3, <mask>=4, <ghost>=5`
- **编码示例**:

```
输入: "姬神蜕出皮，其皮钻入我灵，我灵向姬神阐言"
输出: ['▁姬神', '蜕', '出', '皮', ',', '其皮', '钻', '入', '我', '灵', ',', '我', '灵', '向', '姬神', '阐', '言']
```

- **多字词示例**: 姬神, 吾神, 仁神, 意志, 巫女, 时空, 存在, 世界, 神官, 本质者, 现象者, 桔梗...

## 5. TRACE 性能

| 指标 | 当前 | Qwen 0.5B | Qwen 1.5B |
|------|------|-----------|-----------|
| 速度 (pairs/s) | 556 | 6 | ~4 |
| 提速倍数 | — | **93x** | **139x** |
| VRAM | 1.2 GB | 1.0 GB | 3.1 GB |
| 训练需求 | 507s (一次) | 无 | 无 |
| 因果粒度 | 子词 | 子词 | 子词 |

## 6. 优化迭代记录

| 版本 | 架构 | Tokenizer | 训练 | Loss | 速度 | 关键改进 |
|------|------|-----------|------|------|------|---------|
| v0 | 6L/288d | ByteLevel BPE | — | — | — | 起点 (乱码) |
| v1 | 6L/288d | CJK-split BPE | 15ep, bs16 | 0.44 | — | 字符级 (单字) |
| v2 | 6L/288d | SentencePiece | 20ep, bs16 | 2.20 | 924/s | 子词级 ✅ |
| v3 (P0+P1+P2) | 8L/320d | SentencePiece | 50ep+, bs32, warmup | 0.25* | 556/s | 更深+Ghost |
| **v3.1 (Bugfix)** | **8L/320d** | **SentencePiece** | **50ep, bs32, warmup, shuffle+mask** | **1.66** | **538/s** | **修正 loss (移除 PAD 虚低)** |

> *v3 loss=0.25 包含 PAD token 的虚低贡献。v3.1 loss=1.66 是仅计算真实文本预测的准确值。

### v3 新增 (P0+P1+P2)

- **P0**: batch 32, warmup 100 steps, cosine schedule → loss 降 8.7x
- **P1**: Ghost Token 基线减法, 段落级训练 → 过滤语法噪音
- **P2**: 8 层 / 320 维 → 更深的特征抽象

## 7. API 调用

### 7.1 加载模型

```python
import sentencepiece as spm
from transformers import GPT2LMHeadModel

sp = spm.SentencePieceProcessor()
sp.load("F:/攻略/研发测试/TRACE/models/shenji-trrace/spm.model")

model = GPT2LMHeadModel.from_pretrained(
    "F:/攻略/研发测试/TRACE/models/shenji-trrace"
).cuda().eval()
```

### 7.2 编码/解码

```python
ids = sp.encode("你的文本", out_type=int)
text = sp.decode(ids)
```

### 7.3 运行 TRACE

```bash
python TRACE/scripts/standalone_trrace.py "你的文本"
```

```python
from standalone_trrace import ShenjiTRRACE
engine = ShenjiTRRACE()
result = engine.trace("你的文本...", threshold=0.5)
```

### 7.4 全量分析

```bash
python TRACE/scripts/train_shenji.py
```
→ 训练 + TRACE + CCM + 报告, 一键执行。

## 8. 已知局限

1. **序列长度**: 训练窗口 256 tokens, 超出此长度的因果依赖检测不到
2. **稀有词**: 低频专有名词可能被拆分为单字
3. **Ghost 基线**: 当前在随机位置插入 ghost token, 统计功效有限
4. **跨段因果**: 段落间因果只能在全文分析中捕获
5. **SentencePiece 中文路径**: C++ 后端不支持, 需用 ASCII 临时目录

## 9. 维护指南

### 增量续训 (有新增文本时)

```python
# 加载已有模型
model = GPT2LMHeadModel.from_pretrained(MODEL_DIR).cuda()
model.train()
# 在新文本上 fine-tune (lr=1e-4, 5-10 epochs)
# ... 训练循环
model.save_pretrained(MODEL_DIR)
```

### 调整因果阈值

- **threshold=0.5** → 标准, 保留大部分语义因果
- **threshold=1.0** → 严格, 只保留强因果
- **threshold=2.0** → 极严, 仅最确信的边

### 扩展词表

如需增加新概念词, 修改 `VOCAB_SIZE` 到 6000-8000, 重新运行 `train_shenji.py`

## 10. 项目整合

```
TRACE/
├── models/shenji-trrace/        ← 本模型
│   ├── MODEL_REFERENCE.md       ← 本文件
│   ├── model.safetensors
│   ├── spm.model / spm.vocab
│   └── config.json
├── outputs/shenji/              ← 分析报告
├── scripts/
│   ├── train_shenji.py          ← 训练+分析 (一键)
│   ├── standalone_trrace.py     ← 独立调用
│   ├── trace.py                 ← TRACE 通用引擎
│   └── trace_plus.py            ← TRACE+ 融合管线
└── TRACE_MATH.md                ← 数学原理
```

---

*最后更新: 2026-07-10*
