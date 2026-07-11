# TRACE Engine Skill — Design Philosophy & Business Logic

## Architecture: Defense in Depth (Six Layers)

The Skill implements six concentric protection layers. Each layer catches
different classes of failure before they can produce garbage causal graphs.

```
┌─────────────────────────────────────────────────────────────┐
│  LAYER 1: Environment Validation                            │  ← check_env.py
│  "Can we even run?"                                         │
│  - PyTorch + CUDA version, VRAM availability                │
│  - transformers / sentencepiece / numpy deps                │
│  - Model files present and loadable                         │
├─────────────────────────────────────────────────────────────┤
│  LAYER 2: Configuration Audit (Firewall)                    │  ← trace_plus.py
│  "Is this TRACE request physically possible?"               │
│  - Sequence length vs model max_pos → auto-truncate          │
│  - VRAM budget (model + batch × seq_len × vocab)            │
│  - Threshold validity (0 < τ < 20)                          │
│  - AUTO-CORRECTS: max_batch reduced when VRAM low            │
├─────────────────────────────────────────────────────────────┤
│  LAYER 3: CCM Cross-Validation                              │  ← ccm_causality.py
│  "Do two independent methods agree?"                        │
│  - TRACE (ΔNLL via LLM) vs CCM (cross-map via dynamics)     │
│  - Both agree → HIGH CONFIDENCE                              │
│  - One agrees, one not → MEDIUM CONFIDENCE (inspect)         │
├─────────────────────────────────────────────────────────────┤
│  LAYER 4: DoWhy Formal Causal Inference  ★NEW (v5)          │  ← counterfactual_bridge.py
│  "Is the effect identifiable? Statistically robust?"       │
│  - Model (DAG+SCM) → Identify (do-calculus)                 │
│  - Estimate (ATE+95%CI) → Refute (3 refuters)               │
├─────────────────────────────────────────────────────────────┤
│  LAYER 5: Counterfactual Query Engine  ★NEW (v5)            │  ← PearlCounterfactual
│  "What if X were different?"                                │
│  - Abduction → Action → Prediction (Pearl 3-step)           │
│  - Independent of DoWhy-GCM (pure numpy implementation)     │
├─────────────────────────────────────────────────────────────┤
│  LAYER 6: causallearn Independent Validation  ★NEW (v5)     │  ← CausalLearnValidator
│  "Do constraint/score-based search algorithms agree?"       │
│  - PC (constraint-based), GES (score-based), FCI (latent)   │
│  - Cross-compare with TRACE edges                           │
└─────────────────────────────────────────────────────────────┘
```

## Design Note: Six Instruments, Six Dimensions

> **业务环节措辞说明**: 以下对六合一线六个算法组件的描述使用了物理测量仪器的
> 比喻语言（探照灯/测谎仪/节拍器/X光机/反事实镜/独立验证）。这不属于修辞膨胀——
> 每个比喻精确对应了该算法在文本诊断中测量的物理维度，是整个 Skill 设计哲学的核心隐喻。

The six-algorithm pipeline (TRACE + CCM + EDM + HAVOK + DoWhy/Counterfactual + causallearn)
is not a redundant ensemble — each component measures a **distinct physical dimension**
of the text, analogous to six independent scientific instruments:

| Algorithm | Instrument | Dimension Measured | Diagnostic Signal |
|-----------|-----------|-------------------|-------------------|
| **TRACE** | 探照灯 (Searchlight) | Causal edge discovery | ΔNLL strength; proves domain overfitting's absolute value for feature extraction |
| **CCM** | 测谎仪 (Lie Detector) | Nonlinear entanglement verification | Convergence slope; its *failure* is a critical signal: "no deep logic loops — do not search for nonlinear causality" |
| **EDM** | 节拍器 (Metronome) | Temporal rigidity / structural skeleton | ρ predictability of discourse markers (e.g. "但是" ρ=0.99 → strong narrative structure) |
| **HAVOK** | X光机 (X-ray) | Hidden singularities / forcing terms | Linear vs. nonlinear energy partition; identifies "mutation points" where the narrative trajectory bends |
| **DoWhy** | 法槌 (Gavel) | Formal identifiability + refutation | ATE + 95%CI; 3-layer refutation; do-calculus guarantees the effect is estimable from observational data |
| **Counterfactual** | 反事实镜 (Mirror) | What-if reasoning | ITE (Individual Treatment Effect); Pearl 3-step: Abduction → Action → Prediction |
| **causallearn** | 第三人 (Third Witness) | Independent graph search verification | PC/FCI/GES edges; cross-comparison with TRACE |

**Key design insight — composite diagnosis**: A single algorithm's output is
a measurement; the *pattern across all six* is the diagnosis. Example:

- CCM fails + EDM ρ>0.9 + HAVOK linear>80% + DoWhy refutes all → **tightly-structured linear
  narrative with identifiable turning points** (not an argumentative text)
- CCM converges + EDM ρ moderate + HAVOK nonlinear>30% + DoWhy passes refutation →
  **argumentative text with recursive logical entanglement**
- TRACE dense + CCM moderate + DoWhy identifies + Counterfactual ITE large →
  **high-stakes argument where rhetorical structure has measurable causal force**

The six-in-one system does not produce "wrong answers" — it produces a
**complete topological portrait** of the text. Each component's "failure"
is as informative as its success. See `examples/zhihu_consensus/README.md`
for the four-instrument demonstration, and `examples/counterfactual_hybrid/DESIGN_FIVE_IN_ONE.md`
for the full six-instrument architecture.

## Auto-Correction Philosophy

Not all problems should be auto-corrected. The guiding principle:

| Problem Class | Auto-Correct? | Rationale |
|--------------|---------------|-----------|
| Numerical suboptimality (batch too large) | YES | Reduce max_batch, notify user |
| Data insufficiency (seq_len < 5) | NO (block) | Can't create data from nothing |
| Domain mismatch (UNK rate > 20%) | NO (warn) | Model can't magically learn new vocabulary |
| Threshold extreme (τ > 10 or τ < 0) | NO (warn) | Requires domain knowledge |
| Model size > VRAM | YES | Suggest smaller model or CPU fallback |
| seq_len > max_pos | YES | Auto-truncate with warning |

### Auto-Correction Rules

1. **max_batch causes OOM**: AUTO-REDUCE to safe batch = floor(available_VRAM / estimated_per_sample)
   - Rationale: smaller batches with more forward passes > OOM failure
   - User notified: "max_batch reduced from X to Y for VRAM safety"

2. **seq_len > model.max_pos**: AUTO-TRUNCATE to max_pos
   - Rationale: the model literally cannot process longer sequences
   - User warned: "sequence truncated from X to Y tokens. Consider segment analysis."

3. **threshold ≤ 0**: WARN, use default 0.5
   - Rationale: threshold=0 accepts all edges including noise
   - User warned: "threshold=0 will produce near-complete graph. Recommended: 0.5-2.0"

4. **UNK rate > 20%**: WARN, recommend train-on-target
   - Rationale: high UNK rate → most tokens have no embedding → ΔNLL = noise
   - User notified: "UNK rate {r}%. Consider running instant_trrace.py to train a domain model."

5. **Data < 5K chars**: WARN, recommend Instant TRACE with data augmentation
   - Rationale: insufficient samples → model doesn't converge → ΔNLL too weak
   - See: Training Secrets §1 (stride=16 + paragraph-aligned + bidirectional)

## Design Assumptions & Tradeoffs

### Assumption 1: Small vocabulary is better for TRACE

```
TRACE's bottleneck is NOT model size — it's vocabulary size.

vocab=151936:  logits tensor eats VRAM, each forward pass slow
vocab=3000:     logits tensor negligible, forward pass 50x faster

Tradeoff: small vocab = domain-locked, can't handle OOV gracefully
Mitigation: train-on-target = 0% UNK rate for the text you care about
```

### Assumption 2: Domain overfitting is a feature

```
Traditional ML: overfitting = bad, model doesn't generalize
TRACE:          overfitting = good, model perfectly captures target text's patterns

Tradeoff: model useless outside its training domain
Mitigation: multi-model registry (Shenji-LLaMA, Shehui-LLaMA, per-text Instant)
```

### Assumption 3: Character-level BPE merges are the right granularity

```
Word-level:  "人类社会的反应其实就是" → unknown → UNK token
Char-level:  人|类|社|会|的|反|应|其|实|就|是 → 11 tokens, no context
BPE (ours):  人类|社会|的|反应|其实|就是 → 6 tokens, meaningful units

Tradeoff: BPE on small data creates "long phrase" tokens that appear once
Mitigation: check token frequency distribution; prune single-occurrence tokens
```

### Assumption 4: Shared embedding dimension for TRACE vs HAVOK

TRACE's causal matrix (T×T tokens) and HAVOK's Hankel matrix (p×q delays)
use fundamentally different "embedding dimensions" — TRACE uses the model's
hidden_dim (320), HAVOK uses the attractor embedding dimension (q). These are
NOT designed to coincide mathematically. The cross-validation is valid because
we compare the STRUCTURE of both outputs, not their dimensionalities.

### Assumption 5: CCM on token sequences is an approximation

Full CCM requires continuous numerical time series. We approximate by treating
token occurrence counts as a "presence timeseries" for each concept. This is a
simplifying assumption that loses amplitude information but preserves temporal
structure. For exploratory analysis this is correct; for publication-grade
results, consider converting tokens to embedding vectors and summing per concept.

## Business Scenarios & Decision Logic

### Scenario A: "I wrote a 2000-char philosophical essay. Find its causal structure."

```
Layer 1: env_check → PASS (CUDA available, model files present)
Layer 2: audit → WARN (data < 5K, recommend Instant TRACE)
         → Auto-detect: text is modern Chinese, not matching Shehui-LLaMA's classical domain
         → Decision A: YES → Instant TRACE
         → BPE trained on target text → vocab=3000, UNK=0.3%
         → Enhanced with all available data (5100 samples)
         → 60 epochs, batch=8, LLaMA 8L/320d
Layer 3: CCM → skipped (24 edges, below 100 threshold)
Output: "Found causal chains: 人性→社会根源 (9.77), 观念→社会运动 (18.42).
         Causal SNR: HIGH. Report saved."
```

### Scenario B: "Analyze a 50K-char classical Chinese text on society."

```
Layer 1: env_check → PASS
Layer 2: audit → PASS (data fits Shehui-LLaMA domain)
         → Decision A: NO → use existing Shehui-LLaMA
         → WARN: auto-truncate each segment to 256 tokens
         → 12 segments generated, TRACE each
Layer 3: CCM → invoked (312 edges > 100)
         → cross-validate top 50 edges by strength
         → 41/50 confirmed (82%), 9 flagged for inspection
Output: "TRACE found 312 edges. CCM confirms 82%. 9 potential false positives
         flagged. Consider HAVOK for hidden driver detection."
```

### Scenario C: "I have only 500 chars. Can TRACE work at all?"

```
Layer 1: env_check → PASS
Layer 2: audit → BLOCK
         → seq_len likely < 10 after splitting → insufficient for causal analysis
         → WARN: "500 chars provides insufficient statistical power.
                 Minimum: 30+ chars per paragraph, 3+ paragraphs.
                 Consider expanding the text or adding related material."
         → SUGGEST: combine this 500 chars with existing domain data,
                   train model, then TRACE this specific text
         → This is NOT auto-executed (requires human judgment)
```

### Scenario D: "Train a new model. How big should it be?"

```
Layer 1: env_check → PASS
Layer 2: audit → data audit
         → data_size = 78K chars (all combined)
         → RECOMMEND: 8L/320d LLaMA (15M) — sweet spot
         → NOT: 12L/448d (42M) — diminishing returns
         → NOT: GPT-2 (6L/288d) — LLaMA gives +15-25% lower loss at same size
         → WARN: "42M model will train 4x longer for < 0.1 loss improvement.
                 TRACE speed will drop from 350 to 17 pairs/s on 4GB GPU."
Output: "Recommended: Shehui-LLaMA architecture (8L/320d, 15.7M).
         For best results, train 50 epochs with paragraph-aligned samples."
```

## Known Failure Modes & Edge Cases

### Failure Mode 1: High UNK rate (> 20%)

```
Symptom:  ΔNLL values are unusually low or uniform
Cause:    Model has no learned representation for most tokens in the text
Fix:      Train BPE tokenizer on target text. Verify UNK rate < 2%.
Prevention: audit_trance_config() checks UNK rate before TRACE.
```

### Failure Mode 2: Positional encoding overflow

```
Symptom:  CUDA assert error: "index out of bounds" in embedding lookup
Cause:    seq_len > model.max_position_embeddings (256)
Fix:      Auto-truncate segments to max_pos before TRACE
Prevention: audit layer checks seq_len vs max_pos. Done in run_shehui_trrace.py.
```

### Failure Mode 3: Ghost token NaN contamination

```
Symptom:  All ΔNLL values become NaN or Inf
Cause:    <mask> token not in vocabulary or fp16 underflow → log(0) = -inf
Fix:      Use fp32 for TRACE inference (model is small enough).
          Clamp softmax output to [1e-8, 1.0].
Prevention: trace() function in trrace_loader.py already clamps.
```

### Failure Mode 4: Cross-paragraph window contamination

```
Symptom:  Spurious causal edges between unrelated topics in adjacent paragraphs
Cause:    Training windows that span paragraph boundaries create false co-occurrence
Fix:      Use paragraph-aligned window sampling (DEFAULT in train_shenji_llama.py)
Prevention: Paragraph-level sample generation. Verified during training setup.
```

### Failure Mode 5: SentencePiece Chinese path error

```
Symptom:  OSError: "Not found: F:\攻略...\spm.model"
Cause:    SentencePiece C++ backend doesn't support CJK paths on Windows
Fix:      Copy spm.model to a temp directory with ASCII-only path
Prevention: trrace_loader.py and standalone_trrace.py handle this automatically.
```

### Failure Mode 6: ΔNLL signal too weak

```
Symptom:  All ΔNLL values < 1.0, no edges distinguishable from noise
Cause:    Undertrained model (too few epochs, too little data)
Fix:      Increase epochs to 60+, use all available data as training samples
          Optimal: stride=16 + paragraph-aligned + bidirectional sampling
Prevention: Monitor training loss. If best_loss > 0.5 after 30 epochs,
          data or architecture is insufficient.
```

## Verification Checklist

Before trusting TRACE results, verify:

```
□ Layer 1: env_check → PASS
□ Layer 2: audit → PASS or WARN (no BLOCK)
□ Model loss < 1.0 (lower = cleaner ΔNLL)
□ UNK rate < 5% (lower = better vocabulary coverage)
□ Top-5 ΔNLL edges are semantically interpretable (spot check)
□ CCM cross-validation rate > 60% (if CCM was run)
□ No NaN or Inf values in causal matrix
□ Edge density < 0.5 (too many edges = threshold too low)
□ Top causal concepts match expected themes from text
```

If ≥ 8/9 checks pass, results are reliable. If < 6, re-train or adjust parameters.

## File Map

```
trace-engine/
├── SKILL.md                          ← Master entry point (architecture, training, integration)
├── DESIGN.md                         ← This file (philosophy, scenarios, edge cases)
│
├── examples/
│   ├── zhihu_consensus/              ← 四合一线完整案例（叙事文）
│   └── counterfactual_hybrid/        ← ★ 五合一 + DoWhy + Counterfactual
│       ├── README.md                 ← DoWhy/反事实概念说明
│       ├── DESIGN_FIVE_IN_ONE.md     ← 五合一工程设计文档
│       ├── counterfactual_bridge.py  ← TRACE→DoWhy 桥接模块 (v2)
│       ├── test_case.py              ← 10 项测试套件
│       └── outputs/
│           ├── counterfactual_report.md
│           ├── causal_graph.png
│           └── causal_graph.svg
│
├── ../TRACE/                         ← Implementation (project root)
│   ├── README.md
│   ├── TRACE_MATH.md                 ← Mathematical foundations + engineering decisions
│   ├── scripts/
│   │   ├── trace.py                  ← Base TRACE engine (GPT-2/LLaMA, batch, long doc)
│   │   ├── trace_plus.py             ← TRACE+ (auditor, CCM cross-val, normalization)
│   │   ├── train_shenji_llama.py     ← Epic domain LLaMA training
│   │   ├── train_shehui_llama.py     ← Classical society LLaMA training
│   │   ├── instant_trrace.py         ← Train-on-target pipeline
│   │   ├── presets.py                ← Training preset system (v3)
│   │   └── ...
│   ├── models/                       ← Trained model registry
│   └── outputs/                      ← Analysis reports
│
│   Portable copy:
│   └── Complement/TRACE Engine(EDM-Takens CCM)/
│       ├── README.md
│       ├── trrace_loader.py          ← Unified loader (auto-detect LLaMA)
│       ├── Shehui-LLaMA/             ← Classical Chinese society model (16M)
│       └── Shenji-LLaMA/             ← Epic narrative model (42M)
└──
    Integration with:
    ├── edm-takens/                    ← CCM cross-validation + HAVOK decomposition
    │   ├── src/ccm_causality.py       ← Convergence-aware CCM test
    │   └── src/sovereign_havok.py     ← Koopman decomposition
    │
    └── counterfactual_hybrid/         ← DoWhy + Pearl CF + causallearn (v5 new)
        └── counterfactual_bridge.py   ← Six-layer bridge module
```

## Speed-Quality Tradeoff: Training Presets

TRACE training converges quickly because the model only needs to learn
token co-occurrence patterns, not general language understanding.

### Convergence analysis (5K char text, 6K augmentation samples)

```
epoch  1: loss=3.44  ← random, useless
epoch  6: loss=0.45  ← already producing valid Delta-NLL
epoch 11: loss=0.22  ← ★ sweet spot for most use cases
epoch 21: loss=0.13  ← marginal improvement
epoch 31: loss=0.11  ← tiny delta
epoch 50: loss=0.09  ← last 19 epochs only 0.02 improvement

Key insight: epochs 12-50 spend 55 extra minutes for < 0.13 loss reduction,
which translates to < 5% Delta-NLL improvement for top causal pairs.
```

### Three presets

| Preset | Epochs | Time | Loss | Use Case |
|--------|--------|------|------|----------|
| fast | 12 | 10-12 min | 0.20-0.25 | Quick exploration, first-pass |
| standard | 25 | 25-30 min | 0.12-0.15 | Production analysis, reports |
| quality | 50 | 60-90 min | 0.08-0.10 | Publication-grade, final |

### Decision logic

```
Q: First-pass exploration? → fast (10 min). Iterate if needed.
Q: Definitive analysis for report? → standard (25 min).
Q: Publication or archival? → full (50+ min).
Q: Text has critical rare tokens? → standard or above.
```

### Dynamic Early Stopping

**Principle**: Training stops when the model has converged, not when a fixed epoch count is reached.

```
Convergence criterion:
  loss_delta = (loss[t-patrol] - loss[t]) / loss[t-patrol]
  if loss_delta < delta for patrol consecutive epochs → CONVERGED → stop

Safety cap: max_epochs (preset upper bound)
```

### Why dynamic beats fixed

```
Fixed 15 epochs on different texts:
  2K char low-quality text:   loss=0.45 at epoch 15  ← SHOULD stop at epoch 6
  5K char narrative text:    loss=0.10 at epoch 15  ← correctly runs to cap
  10K char dense argument:   loss=0.05 at epoch 15  ← could keep going

Dynamic early stopping adapts:
  Low quality data:    stops early (epoch 6-8) → saves time
  High quality data:   runs to cap → maximizes quality
  Exceptional data:    could signal "keep going" to user
```

### Five presets

| Preset | Target | Max Ep | Patrol | Delta | Description |
|--------|--------|--------|--------|-------|-------------|
| explore | 3-5 min | 8 | 3 | 0.05 | Quick sanity check. Stops when loss stalls at coarse level. |
| **light** | 10-15 min | 15 | 3 | 0.02 | Default for first-pass. 15 epochs with early exit. |
| standard | 20-30 min | 25 | 5 | 0.01 | Production analysis. Tougher convergence bar. |
| heavy | 30-40 min | 40 | 5 | 0.005 | Near-publication. Requires very flat loss to stop. |
| full | 50+ min | 60 | 8 | 0.003 | Complete convergence. For archival/verification. |

**Minutes are estimates** — actual time depends on data size, GPU, and whether
early stopping triggers. The presets set the convergence bar, not the clock.

### Verified convergence behavior (5K char text)

```
light preset (max=15, patrol=3, delta=0.02):
  epoch  1: 3.53  [Δ=N/A]
  epoch  6: 1.18  [Δ=0.46 > 0.02]  ← still learning fast
  epoch 11: 0.13  [Δ=0.45 > 0.02]  ← still improving
  epoch 15: 0.10  [Δ=0.07 > 0.02]  ← reached cap, NOT early-stopped
  Verdict: model correctly ran to max because data quality was good
  
explore preset would have: epoch 8 cap, loss ~0.80 — enough for rough causal sketch
standard preset would have: epoch 25 cap, loss ~0.07 — near-optimal
```

### Why fast works

TRACE needs the model to know that token A predicts token B — it does
NOT need exact probabilities. A model at loss=0.22 has already learned
the major predictive relationships. The remaining 0.13 loss improvement
mostly comes from infrequent tokens that rarely appear in core causal structure.
