# DoWhy + Counterfactual — Forbidden Rules & Enforcement

> 对标 edm-takens 的 14 条 Forbidden Rules。
> 每条规则有明确的 强制执行级别 (FAIL/WARN/ADVISORY) 和 数据要求。

---

## Rule Summary

| # | Rule | Enforcement | Data Requirement | Status |
|---|------|-------------|------------------|--------|
| 1 | Identifiability Gate | **FAIL** | Treatment→Outcome directed path | ✅ ADOPTED |
| 2 | Refutation Triangulation | **WARN** | N >= 30 | ✅ ADOPTED |
| 3 | SEM Coefficient Stability | **WARN** | N >= 50, V < N/5 | ✅ ADOPTED |
| 4 | Counterfactual Extrapolation Guard | **WARN** | treatment_value within observed range | ✅ ADOPTED |
| 5 | Graph Completeness | **FAIL** | All nodes appear in DOT graph | ✅ ADOPTED |
| 6 | Placebo Vanishing | **WARN** | Placebo treatment → effect ≈ 0 | ✅ ADOPTED |
| 7 | CI Non-Degeneracy | **WARN** | CI must not be NaN/Inf | ✅ ADOPTED |
| 8 | Causal Direction Consistency | **WARN** | TRACE ΔNLL direction == DoWhy ATE direction | ✅ ADOPTED |
| 9 | Sparse Graph Sanity | **ADVISORY** | Edge density < 0.5 | ✅ ADOPTED |

**Adoption rate**: 9/9 fully adopted.

---

## Rule Details

### Rule 1: Identifiability Gate (FAIL)

**Principle**: DoWhy's do-calculus cannot identify causal effects when treatment and outcome have no directed path. Running estimation on an unidentifiable estimand produces statistically meaningless results.

**Enforcement**: 
- `DoWhy14Adapter.is_identifiable()` returns `False` → BLOCK estimation
- Auto-suggest: use the strongest edge's source→target as treatment→outcome

**Implementation**: `counterfactual_bridge.py` § `identify()`

**Trigger**: `identify_effect()` returns `estimand_type=None`

**Mitigation**: Rebuild the CausalModel with a treatment→outcome pair that has a directed path. Use `bridge.significant_edges[0]` for the default.

---

### Rule 2: Refutation Triangulation (WARN)

**Principle**: A single refutation test can be gamed. Three independent refuters must be run, and at least 2/3 must pass (not refute) the estimate for it to be considered robust.

**Enforcement**:
- Run: random_common_cause, placebo_treatment_refuter, data_subset_refuter
- Count refuted: deviation > 30% → refuted
- If >= 2/3 refuted → WARN: "Causal estimate is not robust — 2+ refuters rejected it"

**Implementation**: `counterfactual_bridge.py` § `refute()`

**Data Requirement**: N >= 30 (subset refuter needs enough data to split)

---

### Rule 3: SEM Coefficient Stability (WARN)

**Principle**: The Pearl counterfactual query relies on SEM coefficients estimated via OLS. If N is small relative to the number of variables (V), the coefficient estimates are unstable — and the counterfactual query inherits that instability.

**Enforcement**:
- If N < 5*V_eff → WARN: "SEM coefficients may be unstable (N={n}, V_eff={v}). Counterfactual ITE has wide error bars."
- If N < 2*V_eff → FAIL: "Insufficient data for SEM estimation."

> **Note**: 此处 V_eff 指 DOT 图有效概念数（经概念过滤后实际参与 SEM 估计的节点数），而非原始变量总数 V。

**Implementation**: `counterfactual_bridge.py` § `estimate_sem_from_data()`

**Enforcement in `dowhy_auditor.py`**: `_check_sem_stability()` — N < 2V → FAIL，N < 5V → WARN，否则 PASS。

---

### Rule 4: Counterfactual Extrapolation Guard (WARN)

**Principle**: Pearl's counterfactual assumes the SEM is valid across the intervention range. If we query a treatment_value far outside the observed data range, we are extrapolating the linear model into uncharted territory — the CF result is speculative.

**Enforcement**:
- Compute observed treatment range [min(T), max(T)]
- If treatment_value or control_value outside [min, max] → WARN: "Counterfactual query extrapolates beyond observed range. Results are speculative."

**Implementation**: `dowhy_auditor.py` § `_check_extrapolation_guard()` — 检查 scan_results 中 treatment_value 是否超出观测数据范围，超出则 WARN。

---

### Rule 5: Graph Completeness (FAIL)

**Principle**: DoWhy's CausalModel builds an nx.DiGraph from the DOT string. If a node declared as treatment or outcome is not in the DOT graph, nx raises `NetworkXError` — the entire pipeline crashes.

**Enforcement**:
- When building DOT graph, declare only the nodes that appear in valid (filtered) edges — not ALL concept nodes. Declaring all concept nodes on large graphs makes DoWhy extremely slow or causes it to crash.
- Verify: every treatment/outcome variable appears in DOT (i.e., is an endpoint of at least one significant edge)

**Implementation**: `counterfactual_bridge.py` § `build_model()` — FIXED in v2.

**Trigger**: `nx.exception.NetworkXError: The node X is not in the digraph.`

---

### Rule 6: Placebo Vanishing (WARN)

**Principle**: When treatment is replaced with a random placebo variable, the estimated causal effect should vanish (ATE ≈ 0). If the placebo still shows an effect, the original estimate is likely driven by confounding rather than genuine causation.

**Enforcement**:
- `placebo_treatment_refuter` → `deviation > 30%` → refuted
- If NOT refuted (i.e., placebo doesn't deviate enough from original): this is a BAD sign — the original effect might not be causal

**Implementation**: `counterfactual_bridge.py` § `refute()`, `DoWhy14Adapter.check_refuted()`

---

### Rule 7: CI Non-Degeneracy (WARN)

**Principle**: A 95% confidence interval of `[NaN, NaN]` indicates numerical degeneracy — typically from zero-variance predictors, singular design matrices, or insufficient data. An ATE without a valid CI is not scientifically reportable.

**Enforcement**:
- After estimation, check `DoWhy14Adapter.get_confidence_interval()`
- If CI contains NaN or Inf → WARN: "CI is degenerate. Increase sample size or check data variance."

**Implementation**: `counterfactual_bridge.py` § `estimate()`

---

### Rule 8: Causal Direction Consistency (WARN)

**Principle**: TRACE ΔNLL and DoWhy ATE should agree on the SIGN of the causal effect. If TRACE says A strongly causes B (ΔNLL >> 0) but DoWhy says the effect is negative (ATE < 0), this is a red flag — either the masking intervention or the SEM estimation is picking up a different signal.

**Enforcement**:
- For each edge: sign(ΔNLL) should match sign(ATE)
- If mismatch → WARN: "TRACE and DoWhy disagree on causal direction for {edge}"

**Implementation**: `dowhy_auditor.py` § `_check_causal_direction_consistency()` — 对 scan_results 中每条边检查 sign(ΔNLL) 与 sign(ITE) 是否一致，不一致则 WARN。

---

### Rule 9: Sparse Graph Sanity (ADVISORY)

**Principle**: If the causal DAG is near-fully-connected (edge density > 0.5), the TRACE threshold is likely too low — most edges are noise. The default τ=0.5 should produce interpretable graphs; if not, increase τ.

**Enforcement**:
- edge_density = n_edges / (V*(V-1))
- If density > 0.5 → ADVISORY: "Graph is near-fully-connected. Consider raising threshold."

**Implementation**: `counterfactual_bridge.py` § `build_model()`

---

## Comparison with EDM-Takens Forbidden Rules

| EDM-Takens Rule | DoWhy/Counterfactual Analog | Status |
|-----------------|---------------------------|--------|
| S1: Lyapunov Horizon | R4: Extrapolation Guard | ✅ ADOPTED |
| S2: CCM Victim Mirror | R8: Causal Direction Consistency | ✅ ADOPTED |
| S3: Hankel Golden Ratio | R3: SEM Coefficient Stability | ✅ ADOPTED |
| S5: SVD Residual Monitor | R7: CI Non-Degeneracy | ✅ ADOPTED |
| S6: EDM-HAVOK Cross-Validation | R2: Refutation Triangulation | ✅ ADOPTED |
| — | R1: Identifiability Gate (unique to DoWhy) | ✅ ADOPTED |
| — | R5: Graph Completeness (unique to DoWhy) | ✅ ADOPTED |
| — | R6: Placebo Vanishing (unique to DoWhy) | ✅ ADOPTED |

---

## Six-Layer Cross-Reference Index

### Layer → Forbidden Rules mapping

| Layer | Component | EDM-Takens Rules | DoWhy Rules |
|-------|-----------|:---:|:---:|
| 1 | Environment Check | environment_check.py | — |
| 2 | Configuration Firewall | S1-S7 (edm_auditor.py) | R1,R5,R9 (dowhy_auditor.py) |
| 3 | CCM Cross-Validation | S2,S7 (ccm_causality.py) | — |
| 4 | DoWhy do-calculus | — | R1,R2,R7 |
| 5 | Pearl Counterfactual | — | R3,R4,R6,R8 |
| 6 | causallearn PC/GES | — | R9 (cross-compare) |

### Diagnostic Dimension → Text Type sensitivity

| | 论证文 | 叙事文 | 描述文 | 样本需求 |
|---|:---:|:---:|:---:|:---:|
| TRACE (ΔNLL) | ★★★★★ | ★★★☆☆ | ★★★☆☆ | N ≥ 1 文本 |
| CCM (Convergence) | ★★★★☆ | ★★☆☆☆ | ★★★☆☆ | token freq ≥ 3 |
| EDM (ρ) | ★★★★☆ | ★★★★☆ | ★★★☆☆ | 有序 tokens |
| HAVOK (forcing) | ★★★★★ | ★★★★☆ | ★★★☆☆ | matrix > 50×50 |
| DoWhy (ATE+CI) | ★★★★★ | ★★★☆☆ | ★★☆☆☆ | N ≥ 30, 有向路径 |
| Counterfactual (ITE) | ★★★★★ | ★★★☆☆ | ★★☆☆☆ | SEM stable (N≥5V) |
| causallearn (PC/GES) | ★★★☆☆ | ★☆☆☆☆ | ★★☆☆☆ | N ≥ 200 |

### Parameter tuning by text type

| Parameter | 论证文 | 叙事文 | 说明 |
|-----------|--------|--------|------|
| `threshold` | 0.5-1.0 | 0.3-0.7 | 叙事文 ΔNLL 弱，降低阈值 |
| `concept_min_freq` | 3 | 2 | 叙事文 token 稀疏 |
| `max_edges_for_dowhy` | 8-15 | 5-8 | 论证文因果边密集 |
| `refutation_deviation_threshold` | 0.3 | 0.4 | 叙事文放宽反驳标准 |

> 完整参数预设见: `presets.yaml` (demo / standard / deep / archival / llama)

---

## LLaMA 预设说明

`llama` 预设专为过拟合训练的 TRACE LLaMA 模型设计（shehui-llama 27M 轻量 / shenji-llama 469M / shehui-llama-v4-archive 470M 归档）。这类模型 ΔNLL 信号偏低（典型范围 0.000-0.160），需要专属阈值才能捕获中等以上因果边。

### 关键参数

| Parameter | Value | 说明 |
|-----------|-------|------|
| `threshold` | 0.01 | V4 过拟合模型 ΔNLL 偏低，0.01 捕获中等以上因果 |
| `concept_min_freq` | 1 | 领域文本 token 频率低，放宽最小出现次数 |
| `window_size` | 128 | V4 seq=1024，使用更大滑动窗口 |
| `max_segments` | 3 | 469M 参数在 RTX 3050 上限制分段数 |
| `classical_mode` | false | 默认现代白话模式；Shenji 古文场景可切换为 true（保留之/乎/者/也等虚词） |

### 适用场景

- **模型**: Shehui-LLaMA (27M 轻量，古典社会领域) / Shenji-LLaMA (469M，史诗领域) / Shehui-LLaMA V4 Archive (470M 旧版归档)
- **特点**: 过拟合训练导致 ΔNLL 绝对值小，但因果区分度依然存在
- **古汉语分析**: 当分析先秦/文言文本时，将 `classical_mode` 切换为 `true`，保留文言虚词作为有效概念节点

### 调用方式

```python
from presets import load_presets
p = load_presets("llama")
bridge = TRACE2DoWhy(adj, tokens, **p.trace2dowhy)
```
