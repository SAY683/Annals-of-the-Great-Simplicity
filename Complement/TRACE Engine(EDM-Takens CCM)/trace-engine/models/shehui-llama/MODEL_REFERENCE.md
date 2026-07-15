# Shehui-LLaMA — 技术参考手册

> 版本: 1.0 | 训练日期: 2026-07-14
> 模型: LLaMA 36L/896d/8h, 470M params | SentencePiece BPE 4215
> 领域: 社会/哲学/心理学 | 因果视野: 1024 tokens (~1100 chars)
> 平台: RTX 5090 32GB 云端训练 | RTX 3050 4GB 本地推理
> 定位: 专用因果发现模型 — 领域文本 → token 级因果图, 无需人工标注

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
| 层数 | 36 |
| 隐层维度 | 896 |
| 中间层 (SwiGLU) | 3,584 (4×) |
| 注意力头数 | 8 |
| 参数量 | 470.0M |
| 位置编码 | RoPE (theta=10000) |
| 激活函数 | SiLU (SwiGLU) |
| 归一化 | RMSNorm (eps=1e-6) |
| 正则化 | attention_dropout=0.1 |

### 分词器

| 属性 | 值 |
|------|-----|
| 类型 | SentencePiece BPE |
| 词表大小 | 4,215 (自适应) |
| 字符覆盖率 | 0.9995 |
| 领域覆盖率 (UNK) | 0.3% |
| 特殊 token | `<unk>=0, <pad>=1, <bos>=2, <eos>=3, <mask>=4, <ghost>=5` |

### 训练超参

| 参数 | 值 | 说明 |
|------|-----|------|
| 预设 | v4 (天穹) | 云端 RTX 5090 32GB |
| 优化器 | AdamW lr=8.45e-5 (自适应) | depth_factor × width_factor |
| 调度器 | Warmup 400 steps → Cosine Decay | |
| Batch (micro) | 8 | 无梯度累积 (32GB 够大) |
| AMP | fp32 master + fp16 fwd/bwd | |
| Label Smoothing | 0 | 主动过拟合 |
| 序列长度 | 1024 tokens | |
| 训练轮次 | 46/60 (手动停止) | |
| 训练时间 | ~7.5 小时 | RTX 5090 32GB |
| 最终 train loss | 0.0000 | |
| 最佳 checkpoint | 0.000000 (epoch 45) | |

---

## 2. 训练数据

| 属性 | 值 |
|------|-----|
| 来源 | `date/社会训练集/` (4 文件) |
| 推荐书籍 (现代心理学/商业) | 724,937 chars |
| 太易原枢 (古典社会哲学) | 33,546 chars |
| 特门拿书 (伪古典) | 10,051 chars |
| 三皇部曲 (古典格言) | 6,020 chars |
| 总计 (清洗后) | ~770,000 chars |
| 段落级样本 | 19,637 × 1024 tokens |

### 数据特征

| 特征 | 数据 |
|------|------|
| 文体 | 现代白话 + 伪古典格言 混合 |
| 跨域跨度 | 最大 — 从现代心理学到古典哲学 |
| 表格 | 0 行 (全为自然文本) |

---

## 3. 市场对标

| 模型 | 参数量 | TRACE 速度 | VRAM (训/推) | 因果视野 | UNK 率 | 训练需求 |
|------|:---:|:---:|:---:|:---:|:---:|:---:|
| **Shehui-LLaMA** | **470M** | **200/s** (5090) | **29/3.5 GB** | **1024 tok** | **0.3%** | **7.5h** |
| Shenji-LLaMA | 469M | 226/s (5090) | 29/3.5 GB | 1024 tok | 0.2% | 2.6h |
| Qwen 2.5 0.5B | 494M | ~6/s | —/1 GB | 全文本 | 0% | 无 |
| Qwen 2.5 1.5B | 1,543M | ~4/s | —/3.1 GB | 全文本 | 0% | 无 |

> **与 Qwen 0.5B 同等参数量级**，因果发现速度 33x (5090) / 5x (3050) 提速，领域 UNK 仅 0.3%。

---

## 4. TRACE 推理详解

### 推理指标

| 指标 | RTX 5090 | RTX 3050 | 说明 |
|------|:---:|:---:|------|
| 推理速度 (fp16) | ~200/s | ~27/s | 100 token 测试, batch=2 |
| 推理速度 (INT8) | ~350/s | ~80/s | INT8 量化, batch=4 |
| 推荐 batch (fp16) | 8-16 | 2 | 受 VRAM 约束 |
| 推荐 batch (INT8) | 16-32 | 4-8 | VRAM 减半 |
| 推荐阈值 | 0.01-0.05 | 同 | 过拟合模型 ΔNLL 偏低 |

### INT8 量化加速 (无需重新训练)

```python
# 需要 bitsandbytes (仅 Linux)
from transformers import LlamaForCausalLM, BitsAndBytesConfig

q = BitsAndBytesConfig(load_in_8bit=True, llm_int8_threshold=6.0)
model = LlamaForCausalLM.from_pretrained(
    "TRACE/models/shehui-llama", quantization_config=q
)
# VRAM -50%, batch 翻倍, 速度 +75%
```

| 模式 | 模型大小 | VRAM | batch | 3050 速度 | 效果 |
|:---|:---:|:---:|:---:|:---:|:---|
| fp16 (当前) | 1.88 GB | ~3.5 GB | 2 | ~27/s | 基线 |
| **INT8** | 0.94 GB | **~1.8 GB** | **4-8** | **~80/s** | VRAM 减半, 速度翻倍 |

> Windows 不支持 bitsandbytes。可在云端 RTX 5090 上使用 INT8 推理获取 350+/s 速度。

### 阈值选择指南

| 阈值 | 适用场景 |
|:---|:---|
| 0.01 | 探索性分析 |
| 0.03 | 标准分析 |
| 0.05 | 严格分析 |
| 0.50 | 通用模型默认 — **不适用**过拟合模型 |

---

## 5. 文件清单

```
TRACE/models/shehui-llama/
├── model.safetensors         ← LLaMA 权重 (1.88 GB)
├── config.json                ← 模型架构 (720 B)
├── generation_config.json     ← 生成配置 (216 B)
├── spm.model                  ← SentencePiece 分词器 (295 KB)
├── spm.vocab                  ← 词表 (45 KB)
└── MODEL_REFERENCE.md         ← 本文件
```

---

## 6. 维护与操作

### 重新训练 (云端)
```bash
cd TRACE
python scripts/train_core.py --data "date/社会训练集" \
  --output "models/shehui-llama" --preset v4 \
  --label-smoothing 0 --grad-accum 1 --seed 42
```

### 本地推理注意
- RTX 3050 4GB: TRACE batch 限制 2，短文本 (<150 tokens) 可用
- 长文本推理建议云端

### 调整因果阈值
在 trace-engine 的 presets.yaml 中: `threshold: 0.03`

---

## 7. 扩展：转换对话模式 (SFT + RLHF)

Shehui-LLaMA 当前为 TRACE 密度估计器，不具备对话能力。但 LLaMA 骨架完全支持通过监督微调 (SFT) 和人类反馈强化学习 (RLHF) 转换为对话模型。

### 为什么过拟合不影响 SFT？

过拟合 (train=0.0000) 是权重到达尖锐局部极小值。SFT 使用新学习率和数据，将权重推向更宽广的对话最优解。模型在 770K chars 社会文本上学到的中文语义结构和注意力模式是**可迁移的**。

### SFT 实现步骤

**1. 准备指令数据**

```python
data = [
    {"messages": [
        {"role": "user", "content": "什么是社会共识？"},
        {"role": "assistant", "content": "社会共识是群体成员在特定议题上达成的共同理解和认同..."}
    ]},
]
```

**2. 微调**

```python
from transformers import LlamaForCausalLM

model = LlamaForCausalLM.from_pretrained("models/shehui-llama")
# 用低学习率 (1e-5 ~ 5e-5) 训练 1-3 epochs
```

**3. (可选) LoRA 高效微调** — 只训练 ~2% 参数，保留原始权重。

### 预估效果

| 微调数据量 | 对话质量 | 训练时间 (5090) |
|:---:|:---:|:---:|
| 1K 条 | 基础问答 | ~30 min |
| 10K 条 | 日常对话 | ~2 h |
| 100K+ 条 | 高质量对话 | ~10 h |

> SFT 后模型会部分丧失对训练文本的完美密度估计能力。建议保留原模型用于因果发现，SFT 版本独立部署。

---

## 8. 训练管线设计 (全流程)

本节说明 Shehui-LLaMA / Shenji-LLaMA 的完整训练设计，供未来拓展参考。

### 三阶段工艺

```
Phase 1 — 预训练 (已完成)
  ├─ 领域文本 → next-token prediction
  ├─ label_smoothing=0 (主动过拟合)
  ├─ 训练: train_core.py + presets.py (v4 预设)
  └─ 产出: 密度估计器 (TRACE 因果发现专用)

Phase 2 — SFT (本指南 §7)
  ├─ 指令-回复数据 (1K-10K 条)
  ├─ 教模型理解"问答格式"
  ├─ 从当前权重开始，低 lr 微调
  └─ 产出: 能对话的模型

Phase 3 — RLHF/DPO (可选)
  ├─ 人类偏好排序数据
  ├─ 对齐价值观和回复质量
  └─ 产出: 高质量对话助手
```

### 对照表

| | Phase 1 (当前) | Phase 2 (SFT) | Phase 3 (RLHF/DPO) |
|:---|:---|:---|:---|
| 训练目标 | next-token prediction | 问答格式模仿 | 人类偏好对齐 |
| 数据 | 领域文本 (540K-770K) | 指令-回复 (1K-100K) | 偏好排序 |
| 学习率 | 8.45e-5 | 1e-5 ~ 5e-5 | 1e-6 ~ 1e-5 |
| 轮次 | 40-60 | 1-3 | 1-2 |
| 产出 | 密度估计器 | 对话模型 | 对齐模型 |
| 部署 | TRACE 因果发现 | 聊天/问答 | 生产对话 |
| 工具 | train_core.py | TRACETrainer 复用 | DPO/RLHF 库 |

---

## 9. 已知局限

| 局限 | 严重度 | 说明 |
|:---|:---:|:---|
| 本地推理慢 | 🟡 中 | 470M 在 3050 上仅 27/s，建议云端推理 |
| ΔNLL 偏低 | 🟡 中 | 过拟合压制因果信号, 需降阈值 |
| 因果视野 1024 tokens | 🟢 低 | 超出此长度不可见 |
| 非通用 NLG | 🟢 低 | 专为 TRACE 因果发现设计 |
| 新领域零样本 | 🔴 高 | 换领域文本必须重新训练 |

---

*文档版本: 1.0 | 2026-07-14*
