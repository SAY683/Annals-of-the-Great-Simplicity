# TRACE Engine — 便携因果发现工具包

> 基于自回归密度估计 (ΔNLL) + EDM-Takens CCM 交叉验证的因果发现引擎
>
> **领域专用 · 无需联网 · 即插即用**

---

## 环境配置

### 最低要求

| 组件 | 版本 | 说明 |
|------|------|------|
| Python | >= 3.10 | |
| PyTorch | >= 2.0 | CUDA 可选, CPU 可降级运行 |
| Transformers | >= 4.40 | 自动检测 LLaMA/GPT-2 架构 |
| SentencePiece | >= 0.2 | BPE 分词器 |
| NumPy | >= 2.0 | |

### 安装

```bash
pip install torch transformers sentencepiece numpy
```

GPU 推荐 (CUDA 12.x):
```bash
pip install torch --index-url https://download.pytorch.org/whl/cu121
```

### 硬件

| 模式 | 最低 | 推荐 |
|------|------|------|
| GPU 推理 | 2GB VRAM | 4GB+ (RTX 3050+) |
| CPU 推理 | 4GB RAM | 8GB+ |

---

## 模型清单

```
TRACE Engine(EDM-Takens CCM)/
│
├── README.md                  ← 本文件
├── trrace_loader.py           ← 统一加载器 (自动适配 LLaMA)
│
├── Shehui-LLaMA/              ← 社会/哲学因果模型
│   ├── MODEL_REFERENCE.md
│   ├── model.safetensors      (63 MB)
│   ├── config.json
│   ├── spm.model / spm.vocab
│   └── ...
│
└── Shenji-LLaMA/              ← 神纪史诗因果模型
    ├── MODEL_REFERENCE.md
    ├── model.safetensors      (169 MB)
    ├── config.json
    ├── spm.model / spm.vocab
    └── ...
```

---

## 快速使用

### 代码调用

```python
from trrace_loader import load_model, trace

# 加载模型 (自动检测 LLaMA 架构)
model, sp, info = load_model("Shehui-LLaMA")
print(f"Loaded: {info['params']/1e6:.0f}M params, {info['vocab']} vocab")

# 运行 TRACE
result = trace(model, sp, "你的文本内容...", threshold=0.5)
print(f"Found {len(result['edges'])} causal edges in {result['elapsed']:.1f}s")

# 查看因果对
for (i,j), s in sorted(result['edges'].items(), key=lambda x: x[1], reverse=True)[:10]:
    c = result['tokens'][i].replace('▁','')
    e = result['tokens'][j].replace('▁','')
    print(f"  [{c}] -> [{e}]  ({s:.3f})")
```

### 命令行

```bash
python trrace_loader.py                    # 列出可用模型
python -c "
from trrace_loader import *
model, sp, _ = load_model('Shehui-LLaMA')
r = trace(model, sp, '你的文本')
for (i,j),s in r['edges'].items(): print(r['tokens'][i],'->',r['tokens'][j],s)
"
```

---

## 模型选择指南

| 场景 | 推荐模型 | 原因 |
|------|---------|------|
| 古典中文/社会哲学/易经 | **Shehui-LLaMA** | 训练数据匹配, 15.7M, 极低 loss=0.01 |
| 神纪史诗/神话/叙事 | **Shenji-LLaMA** | 专属领域, 42.1M, 更高精度 |
| 通用现代文本 | **专区模型** | 用目标文本训练 2 分钟即可获得完美词表 |
| 最高精度 (任意文本) | **Qwen2.5-1.5B** | 通用, 但速度仅 4 pairs/s |

---

## 算法原理

```
TRACE (Temporal Reconstruction via Autoregressive Causal Estimation)

1. 自回归模型 = 条件密度估计器 P(x_t | x_{<t})
2. 掩码干预: 将 history 中的 xi 替换为 <mask>
3. 因果强度 = NLL_masked - NLL_normal

ΔNLL > 0 → xi 是 xj 的原因 (掩码后预测变差)
ΔNLL ≈ 0 → 无关
```

详见项目 `TRACE/TRACE_MATH.md`

---

## 已知局限

1. **领域锁定**: 模型只在训练数据领域有效, 跨域需重新训练
2. **序列长度**: 训练窗口 256 tokens, 长文本需分段分析
3. **训练数据**: 11-42M 模型需要 30K+ chars 训练数据才能充分收敛
4. **即时应变**: 对陌生文本可 2 分钟训练临时模型, 但 ΔNLL 信号弱 (需 50+ epochs)

## 维护

- 训练脚本: `TRACE/scripts/train_shenji_llama.py` (史诗) / `train_shehui_llama.py` (社会)
- 即时训练: `TRACE/scripts/instant_trrace.py` (训练即分析)
- 批量分析: `TRACE/scripts/analyze_truth.py`

---

*最后更新: 2026-07-10*
