# Shenji-LLaMA — 技术参考手册

> 版本: 4.0 | 训练日期: 2026-07-14
> 模型: LLaMA 36L/896d/8h, 469M params | SentencePiece BPE 3571
> 领域: 神学/史诗古文 | 因果视野: 1024 tokens (~1100 chars)
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
import torch, sentencepiece as spm, tempfile, shutil, os
from transformers import LlamaForCausalLM

# SentencePiece C++ 后端不支持中文路径
tmp = tempfile.mkdtemp()
shutil.copy("TRACE/models/shenji-llama/spm.model", os.path.join(tmp, "spm.model"))
sp = spm.SentencePieceProcessor(); sp.load(os.path.join(tmp, "spm.model"))
model = LlamaForCausalLM.from_pretrained("TRACE/models/shenji-llama").cuda().eval()
```

### trace-engine 六合一集成

```python
from project_paths import resolve_paths
paths = resolve_paths()
model = LlamaForCausalLM.from_pretrained(
    str(paths.model_dir("shenji-llama"))
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
| 参数量 | 468.9M |
| 位置编码 | RoPE (theta=10000) |
| 激活函数 | SiLU (SwiGLU) |
| 归一化 | RMSNorm (eps=1e-6) |
| 正则化 | attention_dropout=0.1 |

### 分词器

| 属性 | 值 |
|------|-----|
| 类型 | SentencePiece BPE |
| 词表大小 | 3,571 (自适应) |
| 字符覆盖率 | 0.9995 |
| 领域覆盖率 (UNK) | 0.2% |
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
| 训练轮次 | 55/60 (手动/早停等效) | |
| 训练时间 | 154 min | RTX 5090 32GB |
| 最终 train loss | 0.0000 | |
| 最佳 checkpoint | 0.000004 (epoch 55) | |

---

## 2. 训练数据

| 属性 | 值 |
|------|-----|
| 来源 | `date/神学训练集/` (2 文件) |
| 神纪 (正传+外传+番外) | 470,414 chars |
| 诗歌 (雏胚) | 87,719 chars |
| 总计 (清洗后) | ~540,000 chars |
| 段落级样本 | 3,948 × 1024 tokens |

### 数据特征

| 特征 | 数据 |
|------|------|
| 文体 | 伪古典中文 + 神学叙事 + 诗歌 |
| 古文虚词密度 | 之=655, 者=312, 吾=159 |
| 领域术语密度 | 神=610, 姬=112, 巫=55 |
| 表格占比 | 29% (327 行 × 4 列) |
| 表格处理 | 列间空格连接保留文本 |

---

## 3. 市场对标

| 模型 | 参数量 | TRACE 速度 | VRAM (训/推) | 因果视野 | UNK 率 | 训练需求 |
|------|:---:|:---:|:---:|:---:|:---:|:---:|
| **Shenji-LLaMA** | **469M** | **226/s** (5090) | **29/3.5 GB** | **1024 tok** | **0.2%** | **2.6h** |
| Qwen 2.5 0.5B | 494M | ~6/s | —/1 GB | 全文本 | 0% | 无 |
| Qwen 2.5 1.5B | 1,543M | ~4/s | —/3.1 GB | 全文本 | 0% | 无 |

> **与 Qwen 0.5B 同等参数量级**，但因果发现速度 38x (5090) / 7x (3050) 提速，领域 UNK 仅 0.2%。

---

## 4. TRACE 推理详解

### 推理指标

| 指标 | RTX 5090 | RTX 3050 | 说明 |
|------|:---:|:---:|------|
| 推理速度 (fp16) | ~200/s | ~40/s | 100 token 测试, batch=2 |
| 推理速度 (INT8) | ~350/s | ~80/s | INT8 量化, batch=4 |
| 推荐 batch (fp16) | 8-16 | 2-4 | 受 VRAM 约束 |
| 推荐 batch (INT8) | 16-32 | 4-8 | VRAM 减半 |
| 推荐阈值 | 0.01-0.05 | 同 | 过拟合模型 ΔNLL 偏低 |

### INT8 量化加速 (无需重新训练)

```python
# 需要 bitsandbytes (仅 Linux)
from transformers import LlamaForCausalLM, BitsAndBytesConfig

q = BitsAndBytesConfig(load_in_8bit=True, llm_int8_threshold=6.0)
model = LlamaForCausalLM.from_pretrained(
    "TRACE/models/shenji-llama", quantization_config=q
)
# VRAM -50%, batch 翻倍, 速度 +75%
```

| 模式 | 模型大小 | VRAM | batch | 3050 速度 | 效果 |
|:---|:---:|:---:|:---:|:---:|:---|
| fp16 (当前) | 1.88 GB | ~3.5 GB | 2 | ~40/s | 基线 |
| **INT8** | 0.94 GB | **~1.8 GB** | **4-8** | **~80/s** | VRAM 减半, 速度翻倍 |

> Windows 不支持 bitsandbytes。可在云端 RTX 5090 上使用 INT8 推理获取 350+/s 速度。

### 阈值选择指南

| 阈值 | 适用场景 |
|:---|:---|
| 0.01 | 探索性分析 — 发现所有可能的因果链 |
| 0.03 | 标准分析 — 平衡信号和噪声 |
| 0.05 | 严格分析 — 仅保留确信的因果边 |
| 0.50 | 通用模型默认 — **不适用**过拟合模型 |

---

## 5. 文件清单

```
TRACE/models/shenji-llama/
├── model.safetensors         ← LLaMA 权重 (1.88 GB)
├── config.json                ← 模型架构 (720 B)
├── generation_config.json     ← 生成配置 (216 B)
├── spm.model                  ← SentencePiece 分词器 (285 KB)
├── spm.vocab                  ← 词表 (37 KB)
├── training_config.json       ← 训练超参记录 (464 B)
└── MODEL_REFERENCE.md         ← 本文件
```

---

## 6. 维护与操作

### 重新训练 (云端)
```bash
cd TRACE
python scripts/train_core.py --data "date/神学训练集" \
  --output "models/shenji-llama" --preset v4 \
  --label-smoothing 0 --grad-accum 1 --seed 42
```

### 本地推理注意
- RTX 3050 4GB: TRACE batch 限制 2-4，短文本 (<200 tokens) 可用
- 长文本推理建议 RTX 5090+ 或云端

### 调整因果阈值
在 trace-engine 的 presets.yaml 中: `threshold: 0.03`

---

## 7. 扩展：转换对话模式 (SFT + RLHF)

Shenji-LLaMA 当前为 TRACE 密度估计器，不具备对话能力。但 LLaMA 骨架完全支持通过监督微调 (SFT) 和人类反馈强化学习 (RLHF) 转换为对话模型。

### 为什么过拟合不影响 SFT？

过拟合 (train=0.0000) 并不意味着模型"坏了"——它只是到达了一个极其尖锐的局部极小值。SFT 使用新的学习率和数据，会把权重从这个小谷推向一个更宽广的对话最优解。模型在 540K chars 神纪文本上学到的中文语义结构和注意力模式是**可迁移的**。

```
当前权重 (尖锐极小值)  ──SFT──→  对话最优 (宽广区域)
     ●                            ╭──────╮
    / \                           │ 对话  │
   /   \                          ╰──────╯
  overfit                         泛化
```

### SFT 实现步骤

**1. 准备指令数据**

```python
# 格式化为 chat template
data = [
    {"messages": [
        {"role": "user", "content": "你是谁？"},
        {"role": "assistant", "content": "我是 Shenji，一个专注于神学古文领域的语言模型。"}
    ]},
    # ... 数量取决于目标对话质量
]
```

**2. 应用 chat template + 微调**

```python
from transformers import AutoTokenizer
from train_core import TRACETrainer  # 复用现有训练器

# 加载当前模型
model = LlamaForCausalLM.from_pretrained("models/shenji-llama")

# 微调 (低学习率，少量 epoch)
trainer = TRACETrainer(
    data_path="path/to/sft_data.jsonl",
    output_dir="models/shenji-chat",
    preset_name="explore",  # 轻量预设足够
)
trainer.model = model  # 从当前权重开始
trainer.run()
```

**3. (可选) LoRA 高效微调**

保留原始权重不变，只训练低秩适配器：

```python
from peft import LoraConfig, get_peft_model

lora_config = LoraConfig(r=16, lora_alpha=32, target_modules=["q_proj", "v_proj"])
model = get_peft_model(model, lora_config)
# 只需训练 ~2% 的参数
```

### 预估效果

| 微调数据量 | 对话质量 | 训练时间 (5090) | 说明 |
|:---:|:---:|:---:|:---|
| 1K 条 | 基础问答 | ~30 min | 能用，但可能保持古文风格 |
| 10K 条 | 日常对话 | ~2 h | 基本流畅 |
| 100K+ 条 | 高质量对话 | ~10 h | 需要更多数据 |

> **注意**: SFT 后模型会**部分丧失**对训练文本的完美密度估计能力——这是 TRACE ΔNLL 精度和对话能力之间的权衡。建议保留原模型用于因果发现，SFT 版本独立部署用于对话。

---

## 8. 训练管线设计 (全流程)

本节说明 Shenji-LLaMA / Shehui-LLaMA 的完整训练设计，供未来拓展参考。

### 三阶段工艺

```
Phase 1 — 预训练 (已完成)
  ├─ 领域文本 → next-token prediction
  ├─ label_smoothing=0 (主动过拟合)
  ├─ 训练: train_core.py + presets.py (v4 预设)
  └─ 产出: 密度估计器 (TRACE 因果发现专用)

Phase 2 — SFT (§7 详述)
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

### 模型对照

| | Shenji-LLaMA | Shehui-LLaMA |
|:---|:---|:---|
| 领域 | 神学/史诗古文 | 社会/哲学/心理学 |
| 参数 | 469M | 470M |
| 词表 | 3,571 | 4,215 |
| 训练数据 | 540K chars | 770K chars |
| 训练时间 (5090) | 2.6h | 7.5h |
| 最佳 checkpoint | 0.000004 | 0.000000 |
| 本地 VRAM | ~3.5 GB | ~3.5 GB |

---

## 9. 已知局限

| 局限 | 严重度 | 说明 |
|:---|:---:|:---|
| 本地推理慢 | 🟡 中 | 469M 在 3050 上仅 40/s，建议云端推理 |
| ΔNLL 偏低 | 🟡 中 | 过拟合压制因果信号, 需降阈值 |
| 因果视野 1024 tokens | 🟢 低 | 超出此长度不可见 |
| 表格列间顺序 | 🟢 低 | 可能产生邻接伪因果 |
| 非通用 NLG | 🟢 低 | 专为 TRACE 因果发现设计 |
| 新领域零样本 | 🔴 高 | 换领域文本必须重新训练 |

---

*文档版本: 1.0 | 2026-07-14*
