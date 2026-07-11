---
name: trace-engine
description: >
  TRACE causal discovery engine — train a miniature autoregressive model
  on target-domain text, then run masked-intervention ΔNLL to recover
  causal graphs from single token sequences. Includes LLaMA/GPT-2 training
  pipeline, CCM cross-validation bridge, auditor firewall, and portable
  model packaging. Domain-specific (not general-purpose). Integrates with
  EDM-Takens HAVOK for nonlinear forcing decomposition of causal matrices.
---

# TRACE Engine Skill

Token-level causal discovery via autoregressive density estimation,
with EDM-Takens CCM cross-validation and HAVOK decomposition.

## Quick Start

```python
# 1. Train a domain model (target text = training data)
#    Run: python TRACE/scripts/train_shenji_llama.py
#    Output: TRACE/models/<name>/  (portable, ~63-169 MB)

# 2. Run TRACE causal discovery
from trrace_loader import load_model, trace
model, sp, info = load_model("Shehui-LLaMA")
result = trace(model, sp, "你的文本...", threshold=0.5)

# 3. CCM cross-validate (from edm-takens)
#    See: src/ccm_causality.py for convergence-aware CCM test

# 4. HAVOK decomposition (from edm-takens)
#    Feed TRACE adjacency matrix → SovereignHAVOK for forcing term detection
```

## Architecture Decision Tree

```
Q: 你的文本是哪个领域?
   ├─ 史诗/神话/叙事 → Shenji-LLaMA (42M, 高精度, 17 对/s)
   ├─ 古典中文/社会哲学 → Shehui-LLaMA (16M, 极低 loss=0.01, 358 对/s)
   ├─ 现代白话/哲学 → 训练专属模型 (2-70 分钟)
   │    策略: BPE 在目标文本上训练 → 词表完美覆盖
   │          全作品编码为训练样本 → 充分过拟合
   │          60 epochs, batch=8-24
   └─ 任意文本/最高精度 → Qwen2.5-1.5B (4 对/s, 但通用)

Q: 数据量多少?
   ├─ < 2K chars → Instant TRACE: 训练即分析, 60 epochs, 需增强数据
   ├─ 30-70K chars → 标准训练: 50 epochs, 11-16M 模型
   └─ > 100K chars → 优质训练: 可用 25-40M 模型, 预期 loss < 0.1
```

## Train-on-Target Methodology

### When to train your own model

| Scenario | Train? | Reason |
|----------|--------|--------|
| 文本在已有模型领域内 | No | 直接 TRACE |
| 文本跨域/现代词汇多 | **Yes** | 词表不匹配 → ΔNLL 噪声 |
| 只有 2K chars 数据 | **Yes + 增强** | 用全作品当样本 |
| 追求极致因果精度 | **Yes** | 领域模型 SNR >> 通用模型 |

### Training scale guidelines

```
数据量    模型大小    架构         epochs    训练时间    TRACE速度
< 5K      8L/320d     LLaMA        60+       2-5 min    600+ 对/s
5-30K     8L/320d     LLaMA        50        5-10 min   500+ 对/s
30-70K    8-12L/320d  LLaMA        40-50     8-20 min   350-500 对/s
> 70K     12L/448d    LLaMA        40        20-40 min  100-200 对/s
```

### Architecture selection

```
Always LLaMA (not GPT-2):
  - RoPE: 更好的长距离位置感知 (对因果窗口内的位置敏感)
  - RMSNorm: 训练更稳, loss 更低
  - SwiGLU: 同参数下 loss 降 15-25%
  - 无 bias: 参数利用更高效

Vocab size: 3000-5000 (not 151936!)
  - 领域文本的独特 token < 5000
  - 小词表 = logits 不爆炸 = TRACE 速度快 100x+
  - Qwen 的 151K 词表是 TRACE 最大的性能杀手
```

## TRACE + EDM-Takens Integration

### CCM Cross-Validation Bridge

Two independent causal methods → agreement = high confidence:

```
TRACE: 掩码 x_i → ΔNLL(x_i → x_j) > τ → x_i causes x_j
CCM:  交叉映射 x_j 的历史预测 x_i 且收敛 → x_i causes x_j

Consistent:  both say yes → HIGH CONFIDENCE
Contradict:  one says yes, one no → inspect manually
Both No:     likely no causal relationship

Implementation: TRACE/scripts/trace_plus.py
  - ccm_cross_validate_trace() — heuristic CCM proxy for token sequences
  - Full CCM: edm-takens/src/ccm_causality.py (needs numerical timeseries)
```

### HAVOK Decomposition Pipeline

TRACE adjacency matrix → HAVOK forcing analysis:

```
1. TRACE →  causal matrix M (T×T) where M[i,j] = ΔNLL(x_i → x_j)
2. Extract key node timeseries from M's dominant eigenvector
3. Feed to SovereignHAVOK:
   - Hankel delay embedding (Takens theorem)
   - SVD truncation → linear dynamics + nonlinear forcing
4. v_r (forcing term) identifies external drivers in the causal system
5. If v_r is active at time t → unmodeled causal influence detected
   → suggests missing variable or concept drift
```

### Auditor Firewall (ported from EDM-Takens Layer 1-2)

```
Layer 1: Environment   → PyTorch, VRAM, model files present?
Layer 2: Configuration → seq_len < context? threshold valid? batch safe?
Layer 3: CCM verify    → TRACE edges confirmed by independent CCM?

See: TRACE/scripts/trace_plus.py → audit_trance_config()
```

## Training Secrets (from 4 rounds of iteration)

### What matters most (ranked by impact)

```
1. Vocab size (小词表)         → 消除 logits 瓶颈, 100x+ speedup
2. BPE on target text         → UNK=0%, 词表完美覆盖
3. Training epochs (充分)     → 15ep→60ep: ΔNLL 从 0.6 涨到 18.4 (30x)
4. Per-epoch shuffle          → 防止过拟合样本顺序
5. Attention mask + label -100 → 消除 PAD 虚假 loss
6. Warmup + cosine schedule   → 稳定收敛
7. LLaMA over GPT-2           → loss 降 15-25%
8. Architecture scale         → 边际效益递减 (16M → 42M: loss 0.01→0.17)
```

### What doesn't work (tested and rejected)

```
Attention pruning (Qwen):    SDPA 不支持 output_attentions; Eager+fp16 = NaN
GPT-2 ByteLevel BPE (中文):   Mojibake — 字节级编码破坏中文字符
GPT-3 architecture:           与 GPT-2 同骨架, 不同之处仅在 scale
Qwen as small model:          151K 词表让 embedding 爆炸 (48M 起跳)
Train ONLY on target text:    数据不足 → ΔNLL 极弱 → 必须用全作品增强
```

## Model Registry

```
TRACE/models/
├── shenji-llama/     42.1M  LLaMA 12L/448d  loss=0.18  17 对/s  史诗
├── shehui-llama/     15.7M  LLaMA 8L/320d   loss=0.01  358 对/s 古典社会
├── shenji-trrace/    11.2M  GPT-2 8L/320d   loss=1.66  538 对/s 史诗(旧)
└── shehui-trrace/    11.2M  GPT-2 8L/320d   loss=0.10  401 对/s 社会(旧)

Portable: Complement/TRACE Engine(EDM-Takens CCM)/
          ├── Shehui-LLaMA/  + MODEL_REFERENCE.md
          └── Shenji-LLaMA/  + MODEL_REFERENCE.md
```

## Examples

### zhihu_consensus — TRACE+CCM+EDM+HAVOK Full Pipeline

Zhihu article (5,932 chars narrative text) analyzed through all four components.
Demonstrates text-type sensitivity of CCM and HAVOK's text-type-agnostic value.
This case is the canonical demonstration of the **four-instrument design metaphor**
(探照灯/测谎仪/节拍器/X光机) documented in `DESIGN.md` §Four Instruments, Four Dimensions.

See: `examples/zhihu_consensus/README.md`
Run: `python TRACE/scripts/pipeline_zhihu.py`

Key findings:
- Narrative texts produce sparse token frequencies → CCM trust drops below 10%
- HAVOK correctly identifies linear-dominant structure (83% linear) for timeline narratives
- "此时" discovered as hidden forcing driver (time-adverbial dominates narrative flow)
- UNK rate 0.1% with train-on-target vs 30% with cross-domain model

### Component Assessment by Text Type

| Component | Argumentative | Narrative | Optimization |
|-----------|--------------|-----------|-------------|
| TRACE | ★★★★★ | ★★★☆☆ | Lower threshold to 0.5-0.7 for narrative |
| CCM | ★★★★☆ | ★★☆☆☆ | Auto-detect token freq <3 → paragraph-level CCM |
| EDM | ★★★★☆ | ★★★★☆ | Mark rho>0.8 as "high-determinism concepts" |
| HAVOK | ★★★★★ | ★★★★☆ | Adaptive matrix sizing: min(unique_concepts, √N) |

## Training Speed Presets + Dynamic Early Stopping

Not minutes-based — **multi-metric convergence based**.

### Principle

```
Training stops when ALL of these converge:
  1. Loss delta < target    → improvement has stagnated
  2. ΔNLL variance < target → causal signal crystallized
  3. Gradient norm < target → optimizer settled
  4. Freq gap < target      → high/rare token loss equalized

Weighted verdict:
  dnl=35%, loss=30%, grad=20%, freq=15%
  Need required_signals indicators passing
  + min_loss safety guard (cannot stop above this loss)
```

### Five Presets

| Preset | Max Ep | Signals | Safety | Target Time | Use |
|--------|--------|---------|--------|-------------|-----|
| explore | 10 | 1/4 | loss<0.8 | 3-5 min | Sanity check |
| **light** | 15 | 2/4 | loss<0.5 | 10-15 min | Default |
| standard | 25 | 3/4 | loss<0.2 | 20-30 min | Production |
| heavy | 40 | 4/4 | loss<0.12 | 30-40 min | High precision |
| full | 60 | 4/4 | loss<0.06 | 50+ min | Archival |

### Verified behavior

```
light preset on 5K narrative text:
  epoch  1: loss=3.57
  epoch  4: signals=2/4 but [HOLD] loss=2.23 > 0.5
  epoch  9: signals=2/4 but [HOLD] loss=0.75 > 0.5
  epoch 15: ran to cap, loss=0.10 ← correctly ran full 15 epochs
  
  min_loss safety: prevented false-early-stop 2 times
  Verdict: MIXED — identical to quality mode results
```

## File Map

```
TRACE/
├── README.md                      ← 项目说明书
├── TRACE_MATH.md                  ← 数学原理 + 工程决策记录
├── scripts/
│   ├── trace.py                   ← 基础 TRACE (GPT-2 引擎)
│   ├── trace_plus.py              ← TRACE+ (审计+CCM+归一化)
│   ├── train_shenji_llama.py      ← 史诗 LLaMA 训练 (主脚本)
│   ├── train_shehui_llama.py      ← 社会 LLaMA 训练
│   ├── instant_trrace.py          ← 训练即分析 (目标文本→模型→TRACE)
│   ├── standalone_trrace.py       ← Shenji 独立加载器 (已废弃, 用 trrace_loader)
│   ├── analyze_truth.py           ← 全文本分段分析
│   └── ...
├── models/                        ← 训练产出
├── outputs/                       ← 分析报告
└── date/                          ← 训练数据
    ├── 哲学训练集/                  ← 神纪史诗 (470KB)
    ├── 社会训练集/                  ← 三皇部曲+太易原枢 (117KB)
    └── 测试(什么是？？的真相).txt    ← 2KB 测试文本
```

## References

- TRACE: Math & Lienhart, "Scalable Sample-Level Causal Discovery via Autoregressive Density Estimation", arXiv:2602.01135
- CCM: Sugihara et al., "Detecting Causality in Complex Ecosystems", Science 2012
- HAVOK: Brunton et al., "Chaos as an Intermittently Forced Linear System", Nature Comms 2017
- EDM-Takens skill: `.skills/edm-takens/SKILL.md`

## Sampling Optimization for TRACE Training

For TRACE, sampling strategy directly affects model quality and ΔNLL signal strength.

### Strategies ranked by impact

| Strategy | Sample Multiplier | ΔNLL Gain | When to Use |
|----------|------------------|-----------|-------------|
| Reduce stride (64→16) | 4x | +30% | Data < 10K chars |
| Paragraph-aligned windows | 0 | +15% | Always (default) |
| Bidirectional (fwd+bwd) | 2x | +10% | Ultimate enhancement |
| Token dropout (10%) | 0 | +5% | Regularization |
| Short para repeat (×2) | 1.5x | +5% | Very short texts |

### Why paragraph-aligned matters

Cross-paragraph window mixing introduces spurious token transitions:
```
Bad:  [paraA tail...paraB head] → model learns noise
Good: [paraA sliding windows]   → intra-paragraph causality preserved
```

### Optimal for data-scarce (< 5K chars)

stride=16 + paragraph-aligned + bidirectional → 28 → 200+ samples, 3x faster convergence.

## EDM-Takens Decision Flowchart

```
TEXT INPUT
  │
  ▼
[AUDITOR] ←── ALWAYS (built into trace_plus.py)
  │
  ▼
[MODEL] ←── Decision A: Instant TRACE?
  │   Text < 2K or domain mismatch → train on target
  │   Otherwise → use existing domain model
  ▼
[TRACE] ←── Main ΔNLL computation
  │
  ▼
[CCM] ←── Decision B: Invoke EDM-Takens CCM?
  │   Edges > 100 or need high confidence → ccm_causality_test()
  │   Exploratory → SKIP
  ▼
[HAVOK] ←── Decision C: Invoke EDM-Takens HAVOK?
  │   Matrix > 50x50 or seeking hidden drivers → SovereignHAVOK
  │   Routine analysis → SKIP
  ▼
[REPORT]
```

Mnemonic: Audit always, CCM for big graphs, HAVOK for hidden drivers.

## Full Parameter Presets (v3)

Each preset controls: model architecture + training hyperparams + TRACE params.

| Preset | Model | Vocab | Train | TRACE | Window | Ghost |
|--------|-------|-------|-------|-------|--------|-------|
| explore | 6L/256d (6M) | 2K | 8ep, B=24 | 1066/s | 32 | No |
| light | 8L/320d (12M) | 3K | 15ep, B=16 | 640/s | 64 | Yes |
| standard | 8L/384d (17M) | 4K | 25ep, B=14 | 711/s | 96 | Yes |
| heavy | 10L/384d (22M) | 5K | 40ep, B=12 | 682/s | 128 | Yes |
| full | 12L/448d (34M) | 6K | 60ep, B=8 | 609/s | 256 | Yes |

As tier increases: deeper model, larger vocab, wider causal window,
stricter convergence, Ghost from light+, full target from heavy+.

Auto-recommend: `from presets import TRACEPreset; TRACEPreset.recommend()`

Implementation: `TRACE/scripts/presets.py`
