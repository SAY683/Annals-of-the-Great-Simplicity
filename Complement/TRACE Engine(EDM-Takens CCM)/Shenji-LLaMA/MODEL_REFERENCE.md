# Shenji-LLaMA — 技术参考手册

> 版本: v1 | 训练日期: 2026-07-10
> 模型: LLaMA 12L/448d/8h + SwiGLU, 42.1M params
> 词表: SentencePiece BPE 4000 (史诗/奇幻领域)

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
| CPU 推理 (慢) | 任意 CPU, >= 4GB RAM |

本模型 42.1M 参数, RTX 3050 上约用 ~2.0 GB VRAM。

### 独立使用

```python
import sys; sys.path.insert(0, '..')
from trrace_loader import load_model, trace
model, sp, info = load_model("Shenji-LLaMA")
result = trace(model, sp, "你的文本...")
```

---

## 1. 模型档案

| 属性 | 值 |
|------|-----|
| 架构 | LLaMA (transformers) |
| 层数 | 12 |
| 隐层维度 | 448 |
| 注意力头数 | 8 |
| 中间层维度 | 1792 (SwiGLU) |
| 参数量 | 42.1M |
| 词表大小 | 4000 (SentencePiece BPE) |
| 位置编码 | RoPE (theta=10000, max 256) |
| 归一化 | RMSNorm |
| 激活函数 | SiLU (SwiGLU) |
| 训练 epochs | 40 |
| Batch size | 16 |
| Warmup | 100 steps -> cosine decay |
| 优化器 | AdamW (lr=3e-4, wd=0.01) |
| 最佳 loss | 0.1765 |
| 训练时间 | 2950s (RTX 3050 Laptop) |
| 模型大小 | ~169 MB (safetensors) |

## 2. 文件清单

```
Shenji-LLaMA/
├── model.safetensors    ← LLaMA 权重 (~169 MB)
├── config.json           ← 模型配置
├── generation_config.json
├── spm.model             ← SentencePiece BPE 分词器 (288 KB)
├── spm.vocab             ← 词表 (49 KB)
└── MODEL_REFERENCE.md    ← 本文件
```

## 3. 训练数据

| 属性 | 值 |
|------|-----|
| 源文件 | `神纪 - [一前传 + 二部曲 + 三公式 + 二外传 + 二番外].md` |
| 原始大小 | 470,414 字符 |
| 清洗后 | ~37,500 字符 (1,548 行) |
| 编码后 | ~26,000 tokens |
| 段落级样本 | ~900 samples x 256 tokens |
| CJK 字符占比 | 85% |
| 文本类型 | 史诗, 奇幻叙事, 古典中文 |

## 4. 分词器

- **类型**: SentencePiece BPE
- **词表**: 4000 tokens, 其中 ~1550 个 CJK 多字词
- **Special tokens**: `<pad>=1, <bos>=2, <eos>=3, <unk>=0, <mask>=4`
- **编码示例**:

```
输入: "姬神蜕出皮，其皮钻入我灵，我灵向姬神阐言"
输出: ['▁姬神', '蜕', '出', '皮', ',', '其皮', '钻', '入', '我', '灵', ',', '我', '灵', '向', '姬神', '阐', '言']
```

- **多字词示例**: 姬神, 吾神, 仁神, 意志, 巫女, 时空, 存在, 世界, 神官, 本质者, 现象者, 桔梗...

## 5. TRACE 性能

| 指标 | Shenji-LLaMA | Shenji-GPT2 | Qwen 1.5B |
|------|-------------|-------------|-----------|
| 速度 (pairs/s) | 17 | 538 | ~4 |
| 提速倍数 | 4x | **134x** | — |
| Loss | **0.177** | 1.655 | — |
| VRAM | 2.0 GB | 1.2 GB | 3.1 GB |
| 训练需求 | 2950s (一次) | 548s (一次) | 无 |

### 速度说明

Shenji-LLaMA (42.1M) 在 4GB VRAM 的 RTX 3050 上速度受限。若需更高吞吐量,
推荐使用 Shehui-LLaMA (15.7M, 358 pairs/s) 或训练更小的神纪模型 (8L/320d, ~500 pairs/s)。

## 6. 已知局限

1. **速度**: 42.1M 参数在 4GB VRAM 上 batch size 受限, TRACE 慢 (~17 pairs/s)
2. **序列长度**: 训练窗口 256 tokens
3. **领域锁定**: 词表专属史诗/奇幻叙事, 跨域需重新训练
4. **SentencePiece 中文路径**: C++ 后端不支持

---

*最后更新: 2026-07-10*
