# Shehui-LLaMA — 技术参考手册

> 版本: v1 | 训练日期: 2026-07-10
> 模型: LLaMA 8L/320d/8h + SwiGLU, 15.7M params
> 词表: SentencePiece BPE 4000 (社会/哲学领域)

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

本模型 15.7M 参数, RTX 3050 上仅用 ~1.0 GB VRAM。

### 独立使用

本目录完全自包含 — 不依赖 TRACE 项目文件夹:

```python
# 将此目录放在任意位置, 然后:
import sys; sys.path.insert(0, '..')
from trrace_loader import load_model, trace
model, sp, info = load_model("Shehui-LLaMA")
result = trace(model, sp, "你的文本...")
```

---

## 1. 模型档案

| 属性 | 值 |
|------|-----|
| 架构 | LLaMA (transformers) |
| 层数 | 8 |
| 隐层维度 | 320 |
| 注意力头数 | 8 |
| 中间层维度 | 1280 (SwiGLU) |
| 参数量 | 15.7M |
| 词表大小 | 4000 (SentencePiece BPE) |
| 位置编码 | RoPE (theta=10000, max 256) |
| 归一化 | RMSNorm |
| 激活函数 | SiLU (SwiGLU) |
| 训练 epochs | 40 |
| Batch size | 24 |
| Warmup | 80 steps -> cosine decay |
| 优化器 | AdamW (lr=3e-4, wd=0.01) |
| 最佳 loss | 0.0104 |
| 训练时间 | 506s (RTX 3050 Laptop) |
| 模型大小 | ~63 MB (safetensors) |

## 2. 文件清单

```
Shehui-LLaMA/
├── model.safetensors    ← LLaMA 权重 (~63 MB)
├── config.json           ← 模型配置
├── generation_config.json
├── spm.model             ← SentencePiece BPE 分词器 (288 KB)
├── spm.vocab             ← 词表 (49 KB)
└── MODEL_REFERENCE.md    ← 本文件
```

## 3. 训练数据

| 属性 | 值 |
|------|-----|
| 源文件 | `三皇部曲.md` + `太易 - 太伊原枢（纪录）.md` |
| 原始大小 | 39,566 字符 |
| 清洗后 | 38,897 字符 (102 行) |
| 编码后 | 23,352 tokens |
| 段落级样本 | 984 samples x 256 tokens |
| CJK 字符占比 | 86% |
| 文本类型 | 古典中文, 社会哲学, 易经, 太易原枢 |

## 4. 分词器

- **类型**: SentencePiece BPE
- **词表**: 4000 tokens, 其中 ~1500 个 CJK 多字词
- **Special tokens**: `<pad>=1, <bos>=2, <eos>=3, <unk>=0, <mask>=4`
- **编码示例**:

```
输入: "人类的社会的本质是联系"
输出: ['▁', '人类的', '社会的', '本质', '是', '联系']
```

- **多字词示例**: 人类的, 社会的, 必然, 自我, 因为, 一个人, 质量, 道路, 方法, 产生...

## 5. TRACE 性能

| 指标 | Shehui-LLaMA | Shehui-GPT2 | Qwen 1.5B |
|------|-------------|-------------|-----------|
| 速度 (pairs/s) | 358 | 401 | ~4 |
| 提速倍数 | **90x** | 100x | — |
| Loss | **0.010** | 0.100 | — |
| VRAM | 1.0 GB | 1.2 GB | 3.1 GB |
| 训练需求 | 506s (一次) | 582s (一次) | 无 |

## 6. 已知局限

1. **序列长度**: 训练窗口 256 tokens, 超出长度因果检测不到
2. **古典中文偏向**: 词表优先生成于古典文本, 现代词汇可能被拆分
3. **跨域泛化**: 非古典/社会哲学文本的因果信号会被削弱
4. **SentencePiece 中文路径**: C++ 后端不支持, 加载器自动用 ASCII 临时目录

---

*最后更新: 2026-07-10*
