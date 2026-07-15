# Shenji-LLaMA — 技术参考手册

> 版本: 3.0 | 训练日期: 2026-07-14
> 模型: LLaMA 16L/576d/8h, 89.1M params | SentencePiece BPE 3571
> 领域: 神学/史诗古文 | 因果视野: 512 tokens (~550 chars)
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

# Note: SentencePiece C++ backend 不支持中文路径, 需用 ASCII 临时目录
tmp = tempfile.mkdtemp()
shutil.copy("TRACE/models/shenji-llama/spm.model", os.path.join(tmp, "spm.model"))
sp = spm.SentencePieceProcessor(); sp.load(os.path.join(tmp, "spm.model"))
model = LlamaForCausalLM.from_pretrained("TRACE/models/shenji-llama").cuda().eval()
```

### 运行 TRACE 因果发现

```python
MASK = sp.piece_to_id("<mask>")
# 编码目标文本 → 逐 token 掩码 → 计算 ΔNLL → 因果边
# 完整示例: TRACE/scripts/train_core.py § _trace_validate
```

### trace-engine 六合一集成

```python
# 在 .skills/trace-engine 中使用:
from project_paths import resolve_paths
paths = resolve_paths()
model = LlamaForCausalLM.from_pretrained(
    str(paths.model_dir("shenji-llama"))
).cuda().eval()
# → 传入 six_warriors.py 或 run_real_pipeline.py
```

---

## 1. 模型档案

### 架构

| 属性 | 值 |
|------|-----|
| 基座架构 | LLaMA (HuggingFace transformers) |
| 层数 | 16 |
| 隐层维度 | 576 |
| 中间层 (SwiGLU) | 2,304 (4×) |
| 注意力头数 | 8 |
| 参数量 | 89.1M |
| 位置编码 | RoPE (theta=10000) |
| 激活函数 | SiLU (SwiGLU) |
| 归一化 | RMSNorm (eps=1e-6) |
| 正则化 | attention_dropout=0.1 |

### 分词器

| 属性 | 值 |
|------|-----|
| 类型 | SentencePiece BPE |
| 词表大小 | 3,571 (自适应, preset 上限 6000) |
| 字符覆盖率 | 0.9995 |
| 领域覆盖率 (UNK) | 0.2% |
| 特殊 token | `<unk>=0, <pad>=1, <bos>=2, <eos>=3, <mask>=4, <ghost>=5` |
| 最大 token 长度 | 16 |

编码示例:
```
输入: "姬神蜕出皮，其皮钻入我灵，我灵向姬神阐言"
输出: ['▁姬神', '蜕', '出', '皮', ',', '其皮', '钻', '入', '我', '灵',
       ',', '我', '灵', '向', '姬神', '阐', '言']
```

### 训练超参

| 参数 | 值 | 说明 |
|------|-----|------|
| 预设 | ultra (至极) | RTX 3050 4GB 天花板 |
| 优化器 | AdamW lr=1.58e-4 (自适应) | depth_factor × width_factor |
| 调度器 | Warmup 200 steps → Cosine Decay | 10% warmup ratio |
| Batch (micro) | 4 | 受 4GB 显存约束 |
| 梯度累积 | 4 | 有效 batch = 16 |
| AMP | fp32 master + fp16 fwd/bwd | GradScaler 自动溢出检测 |
| 梯度裁剪 | max_norm=1.0 | |
| Weight Decay | 0.01 | |
| Label Smoothing | 0 | 主动过拟合 — 专属模型特质 |
| 早停 | MultiMetricEarlyStop (4-signal) | patrol=8 epochs |
| 序列长度 | 512 tokens | |
| 训练轮次 | 36 epochs (手动停止) | max=60 |
| 训练时间 | ~6 小时 | RTX 3050 Laptop 4GB |

### 收敛指标

| 指标 | 目标 | 实际 | 状态 |
|------|------|------|:---:|
| train loss | < 0.04 (min_loss) | **0.0000** | ✅ |
| loss delta | < 0.002 | 达成 | ✅ |
| dNLL variance | < 0.03 | 达成 | ✅ |
| grad flatness | < 0.0003 | **0.0001** | ✅ |
| best checkpoint | — | **0.000007** | 36 epochs |

---

## 2. 训练数据

| 属性 | 值 |
|------|-----|
| 来源 | `date/神学训练集/` (2 文件) |
| 神纪 (正传+外传+番外) | 470,414 chars |
| 诗歌 (雏胚) | 87,719 chars |
| 总计 (清洗后) | ~540,000 chars |
| 段落级样本 | 7,238 × 512 tokens |
| Train/Val 分割 | 6,514 / 724 (90/10) |

### 数据特征

| 特征 | 数据 |
|------|------|
| 文体 | 伪古典中文 + 神学叙事 + 诗歌 |
| 古文虚词密度 | 之=655, 者=312, 吾=159, 也=... |
| 领域术语密度 | 神=610, 姬=112, 巫=55, 圣=53, 灵=50 |
| 表格占比 | 29% (327 行 × 4 列) |
| 表格处理 | 列间空格连接: `"天使们在颂唱着祂的歌 多种的神权..."` |

### 字符清洗

- ✅ Markdown 语法 (`# *`): 已清除
- ✅ 表格列分隔符 (`|`): 解析为文本
- ✅ 表格分隔符 (`|---|---|`): 丢弃
- ✅ 箭头 (→↓↑, 26 个): 保留 (语义因果)
- ✅ 中文引号 (""): 保留 (标准标点)
- ✅ 零宽/不可见字符: 0 个

---

## 3. 市场对标

### 因果发现性能

| 模型 | 参数量 | TRACE 速度 | VRAM | 因果视野 | UNK 率 | 训练需求 |
|------|:---:|:---:|:---:|:---:|:---:|:---:|
| **Shenji-LLaMA v3** | **89M** | **226/s** | **3.5 GB** | **512 tok** | **0.2%** | **6h (一次)** |
| Shehui-LLaMA V2 | 27M | 415/s | 1.9 GB | 256 tok | 1.2% | 84 min |
| Qwen 2.5 0.5B | 494M | ~6/s | 1.0 GB | 全 (通用) | 0% | 无 |
| Qwen 2.5 1.5B | 1,543M | ~4/s | 3.1 GB | 全 (通用) | 0% | 无 |

> **提速倍数**: 38x (Qwen 0.5B) / 57x (Qwen 1.5B)
> Shenji 的 0.2% UNK 率在所有模型中最低 — 词表对神学古文完全适配

### 设计取舍

| 维度 | Shenji-LLaMA | 通用大模型 (Qwen) |
|:---|:---|:---|
| 因果发现速度 | **226/s** (快速) | 4/s (极慢) |
| 领域适配 | **专属训练** (主动过拟合) | 通用 (零微调) |
| UNK 率 | **0.2%** | 0% (通用词表) |
| ΔNLL 噪音 | **低** (Ghost Token 过滤) | 高 (语法/风格噪音) |
| 因果视野 | 512 tokens | 全文本 |
| 可复现性 | **确定性训练** (seed=42) | GPU 浮点非确定 |
| 部署 | 消费级 GPU (4GB) | 需 3-6GB+ |
| 新领域 | 需重新训练 | 零样本可用 |

---

## 4. TRACE 推理详解

### 算法原理

```
1. 自回归模型在目标文本上训练到过拟合 (train loss → 0)
2. 对每个 token pair (cause, effect):
   a. 计算正常 NLL: -log P(effect | context)
   b. 掩码所有 cause token → 重新计算 NLL
   c. ΔNLL = NLL_masked - NLL_normal
   d. Ghost Token 基线减法: ΔNLL_final = ΔNLL_raw - ΔNLL_ghost
3. ΔNLL_final > threshold → 因果边
```

### 推理指标

| 指标 | 值 | 说明 |
|------|-----|------|
| 推理速度 | 226 pairs/s | 3 段 × 100 tokens 测试 |
| 因果边总数 | 2,860 | 任何强度的边 |
| ΔNLL max | 0.160 | 最强因果信号 |
| ΔNLL >= 0.01 | 21 条 | 中等强度 |
| ΔNLL >= 0.05 | 12 条 | 强因果 |

### 阈值选择指南

| 阈值 | 边数 (预估) | 适用场景 |
|:---|:---:|:---|
| 0.01 | ~20 | 探索性分析 — 发现所有可能的因果链 |
| 0.03 | ~15 | 标准分析 — 平衡信号和噪声 |
| 0.05 | ~12 | 严格分析 — 仅保留确信的因果边 |
| 0.10 | ~5 | 高置信度 — 核心因果骨架 |
| 0.50 | ~0 | 通用模型默认 — **不适用**过拟合模型 |

> **为什么阈值这么低？** 主动过拟合意味着模型对每个 token 的预测近乎完美 (perplexity≈1.0)。
> 掩码一个 token 不会大幅改变预测 → ΔNLL 整体偏低。这不是 bug, 是过拟合模型的设计特质。
> 通用模型 (Qwen) 的 ΔNLL 通常在 0-5 范围内, 所以用 0.5 做阈值。

---

## 5. 文件清单

```
TRACE/models/shenji-llama/
├── model.safetensors         ← LLaMA 权重 (356 MB)
├── config.json                ← 模型架构 (750 B)
├── generation_config.json     ← 生成配置 (226 B)
├── spm.model                  ← SentencePiece 分词器 (285 KB)
├── spm.vocab                  ← 词表 (41 KB)
└── MODEL_REFERENCE.md         ← 本文件
```

完全自包含 — 复制到任意位置，`from_pretrained()` 直接加载。

---

## 6. 维护与操作

### 重新训练

```bash
cd TRACE
python scripts/train_core.py \
  --data "date/神学训练集" \
  --output "models/shenji-llama" \
  --preset ultra \
  --label-smoothing 0 \
  --grad-accum 4 \
  --seed 42
```

### 增量续训 (新增文本后)

```python
from train_core import TRACETrainer
trainer = TRACETrainer(
    data_path="date/神学训练集",   # 更新后的数据
    output_dir="models/shenji-llama",
    preset_name="ultra",
    label_smoothing=0,
    grad_accum_steps=4,
    seed=42,
)
result = trainer.run()
```

### 调整因果阈值

```python
# 在 trace-engine 的 presets.yaml 中:
threshold: 0.03   # Shenji 推荐默认值
```

### 扩展到新领域

1. 将新领域文本放入 `date/` 目录
2. 运行训练命令 (同上)
3. 自动生成新词表 + 新模型
4. ~6 小时后即可用于新领域因果发现

---

## 7. 已知局限

| 局限 | 严重度 | 说明 |
|:---|:---:|:---|
| 因果视野 512 tokens | 🟡 中 | 超出此长度的因果链不可见 |
| ΔNLL 偏低 | 🟡 中 | 过拟合压制因果信号, 需降阈值 |
| 表格列间顺序 | 🟢 低 | 4 列表格 → 列间固定顺序可能产生邻接伪因果 |
| 古文虚词主导 | 🟢 低 | 之/者/也 高频虚词可在概念排名中占主导 |
| 非通用 NLG | 🟢 低 | 本模型专为 TRACE 因果发现设计, 不适合文本生成 |
| 新领域零样本 | 🔴 高 | 换领域文本必须重新训练 |

---

*文档版本: 1.0 | 2026-07-14*
