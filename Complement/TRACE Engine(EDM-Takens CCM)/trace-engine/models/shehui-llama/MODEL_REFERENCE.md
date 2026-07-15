# Shehui-LLaMA — 技术参考手册

> 版本: 1.0 | 训练日期: 2026-07-15
> 模型: LLaMA 10L/384d/8h, 27M params | SentencePiece BPE 2264
> 领域: 社会哲学 (纯古典/伪古典文本) | 因果视野: 256 tokens (~280 chars)
> 定位: 专用因果发现模型 — 高密度因果文本 → token 级因果图

---

## 0. 快速开始

### 环境

```
Python >= 3.10  |  torch >= 2.0  |  transformers >= 4.40
sentencepiece >= 0.2  |  numpy  |  CUDA >= 11.8 (推荐)
```

### 加载模型

```python
import torch, sentencepiece as spm
from transformers import LlamaForCausalLM

sp = spm.SentencePieceProcessor()
sp.load("TRACE/models/shehui-llama/spm.model")
model = LlamaForCausalLM.from_pretrained("TRACE/models/shehui-llama").cuda().eval()
```

### trace-engine 六合一集成

```python
from project_paths import resolve_paths
paths = resolve_paths()
model = LlamaForCausalLM.from_pretrained(
    str(paths.model_dir("shehui-llama"))
).cuda().eval()
```

---

## 1. 模型档案

### 架构

| 属性 | 值 |
|------|-----|
| 基座架构 | LLaMA (HuggingFace transformers) |
| 层数 | 10 |
| 隐层维度 | 384 |
| 中间层 (SwiGLU) | 1,536 (4×) |
| 注意力头数 | 8 |
| 参数量 | ~27M |
| 位置编码 | RoPE (theta=10000, max 256) |
| 激活函数 | SiLU (SwiGLU) |
| 归一化 | RMSNorm (eps=1e-6) |
| 正则化 | attention_dropout=0.1 |

### 分词器

| 属性 | 值 |
|------|-----|
| 类型 | SentencePiece BPE |
| 词表大小 | ~2,264 (自适应, preset 上限 5000) |
| 字符覆盖率 | 0.9995 |
| 领域覆盖率 | < 2% UNK |
| 特殊 token | `<unk>=0, <pad>=1, <bos>=2, <eos>=3, <mask>=4, <ghost>=5` |

### 训练超参

| 参数 | 值 | 说明 |
|------|-----|------|
| 预设 | heavy (极量) | |
| 优化器 | AdamW lr=2.45e-4 (自适应) | depth_factor × width_factor |
| 调度器 | Warmup 100 steps → Cosine Decay | |
| Batch (micro) | 12 × 4 (梯度累积) = 48 有效 | |
| AMP | fp32 master + fp16 fwd/bwd | |
| Label Smoothing | 0 | 主动过拟合 |
| 序列长度 | 256 tokens | |
| 训练轮次 | ~36 epochs | max=40 |
| 训练时间 | ~20 min | RTX 3050 Laptop 4GB |
| 最终 train loss | ~0.003 | 主动过拟合模式 |

---

## 2. 训练数据

### 数据构成 (纯哲学版)

| 文件 | 字符数 | 文体 |
|------|:---:|------|
| 太易 - 太伊原枢（纪录） | 33,546 | 古典社会哲学 |
| 特门拿书 | 10,051 | 伪古典辩论 |
| 三皇部曲 | 6,020 | 古典格言 |
| **总计** | **~49,600** | **100% 高因果密度文本** |

### 数据策略

此模型**有意排除了推荐书籍 (725K chars)**。原因：
- 推荐书籍是现代白话叙事/说明文，因果密度极低
- 94% 的低因果密度数据会压制 6% 的高因果密度信号的 ΔNLL
- 专训高因果密度文本 → ΔNLL 信号更强 → 更多可检测的因果边

> 数据质量 > 数据数量。对 TRACE 因果发现而言，50K chars 的格言/辩论/哲学文本
> 比 725K chars 的现代白话书更有价值。

### 字符清洗

- ✅ Markdown 语法 (`# *`): 已清除
- ✅ 箭头 (→): 保留 (语义因果)
- ✅ 中文引号 (""): 保留 (标准标点)
- ✅ 零宽/不可见字符: 0 个

---

## 3. 市场对标

| 模型 | 参数量 | 因果视野 | VRAM | 速度 | UNK | 训练 |
|------|:---:|:---:|:---:|:---:|:---:|:---:|
| **Shehui-LLaMA** | **27M** | **256 tok** | **1.6 GB** | **~800/s** | **<2%** | **20 min** |
| Shenji-LLaMA V4 | 469M | 1024 tok | 3.5 GB | ~200/s | 0.2% | 2.6h (云端) |
| Qwen 2.5 0.5B | 494M | 全文本 | 1.0 GB | ~6/s | 0% | 无 |
| Qwen 2.5 1.5B | 1,543M | 全文本 | 3.1 GB | ~4/s | 0% | 无 |

> **提速倍数**: ~133x (Qwen 0.5B) / ~200x (Qwen 1.5B)
> 27M 参数是所有模型中最小的，推理速度和 VRAM 占用最低

### 设计取舍

| 维度 | Shehui-LLaMA | 通用大模型 |
|:---|:---|:---|
| 因果发现速度 | **~800/s** (极快) | 4-6/s |
| 领域适配 | **专属训练** + 数据精选 | 通用 |
| 模型大小 | **27M** (极轻) | 494M+ |
| ΔNLL 信号 | **强** (未极端过拟合) | 高噪音 |
| 训练成本 | **20 min** (极低) | 无 |
| 部署 | 消费级 (1.6 GB) | 需 1-3 GB |

---

## 4. TRACE 推理

### 阈值选择指南

| 阈值 | 适用场景 |
|:---|:---|
| 0.03 | 探索性分析 |
| 0.05 | 标准分析 |
| 0.10 | 严格分析 |
| 0.50 | 通用模型默认 |

> Shehui-LLaMA 未达到极端过拟合 (train≈0.003 vs V4 的 0.0000)，
> ΔNLL 值比 V4 高，可以使用更接近通用模型的阈值。

---

## 5. 文件清单

```
TRACE/models/shehui-llama/
├── model.safetensors         ← LLaMA 权重 (~108 MB)
├── config.json                ← 模型架构
├── spm.model / spm.vocab     ← SentencePiece BPE 分词器
├── training_config.json       ← 训练超参记录
└── MODEL_REFERENCE.md         ← 本文件
```

---

## 6. 维护与操作

### 重新训练
```bash
cd TRACE
python scripts/train_core.py --data "date/社会训练集_纯哲学" \
  --output "models/shehui-llama" --preset heavy \
  --label-smoothing 0 --grad-accum 4 --seed 42
```

### 扩展数据
将新高因果密度文本放入 `date/社会训练集_纯哲学/`，重新训练即可。20 分钟完成。

### 调整因果阈值
在 trace-engine 的 presets.yaml 中: `threshold: 0.05`

---

## 7. 已知局限

| 局限 | 严重度 | 说明 |
|:---|:---:|:---|
| 因果视野 256 tokens | 🟡 中 | 超出此长度的因果链不可见 |
| 数据量有限 | 🟡 中 | 50K chars，适合高密度因果文本 |
| 现代文本零样本 | 🔴 高 | 未训练现代白话，换领域需重新训练 |
| 非通用 NLG | 🟢 低 | 专为 TRACE 因果发现设计 |

---

*文档版本: 1.0 | 2026-07-15*
