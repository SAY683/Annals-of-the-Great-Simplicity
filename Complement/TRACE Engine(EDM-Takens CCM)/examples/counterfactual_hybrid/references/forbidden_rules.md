# DoWhy + Counterfactual — Forbidden Rules & Enforcement

> 对标 edm-takens 的 14 条 Forbidden Rules。
> 每条规则有明确的 强制执行级别 (FAIL/WARN/ADVISORY) 和 数据要求。

---

## Rule Summary

| # | Rule | Enforcement | Data Requirement | Status |
|---|------|-------------|------------------|--------|
| 1 | Identifiability Gate | **FAIL** | Treatment→Outcome directed path | ✅ ADOPTED |
| 2 | Refutation Triangulation | **WARN** | N >= 30 | ✅ ADOPTED |
| 3 | SEM Coefficient Stability | **WARN** | N >= 50, V < N/5 | ⚠️ PARTIAL |
| 4 | Counterfactual Extrapolation Guard | **WARN** | treatment_value within observed range | 🔶 DEFERRED |
| 5 | Graph Completeness | **FAIL** | All nodes appear in DOT graph | ✅ ADOPTED |
| 6 | Placebo Vanishing | **WARN** | Placebo treatment → effect ≈ 0 | ✅ ADOPTED |
| 7 | CI Non-Degeneracy | **WARN** | CI must not be NaN/Inf | ✅ ADOPTED |
| 8 | Causal Direction Consistency | **WARN** | TRACE ΔNLL direction == DoWhy ATE direction | 🔶 DEFERRED |
| 9 | Sparse Graph Sanity | **ADVISORY** | Edge density < 0.5 | ✅ ADOPTED |

**Adoption rate**: 6/9 fully adopted, 1 partial, 2 deferred.

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
- If N < 5*V → WARN: "SEM coefficients may be unstable (N={n}, V={v}). Counterfactual ITE has wide error bars."
- If N < 2*V → FAIL: "Insufficient data for SEM estimation."

**Implementation**: `counterfactual_bridge.py` § `_estimate_sem_from_data()`

**Status**: ⚠️ PARTIAL — instability is detected but not formally enforced as FAIL/WARN with explicit messaging.

---

### Rule 4: Counterfactual Extrapolation Guard (WARN)

**Principle**: Pearl's counterfactual assumes the SEM is valid across the intervention range. If we query a treatment_value far outside the observed data range, we are extrapolating the linear model into uncharted territory — the CF result is speculative.

**Enforcement**:
- Compute observed treatment range [min(T), max(T)]
- If treatment_value or control_value outside [min, max] → WARN: "Counterfactual query extrapolates beyond observed range. Results are speculative."

**Status**: 🔶 DEFERRED — structural guard exists but not yet enforced with explicit WARN messaging.

---

### Rule 5: Graph Completeness (FAIL)

**Principle**: DoWhy's CausalModel builds an nx.DiGraph from the DOT string. If a node declared as treatment or outcome is not in the DOT graph, nx raises `NetworkXError` — the entire pipeline crashes.

**Enforcement**:
- When building DOT graph, declare ALL concept nodes (even isolated ones) before adding edges
- Verify: every concept in `concept_names` (except `<other>`) appears in DOT

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

**Status**: 🔶 DEFERRED — comparison calculated in test_case.py but not yet enforced as a firewall rule in the bridge.

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
| S1: Lyapunov Horizon | R4: Extrapolation Guard | 🔶 DEFERRED |
| S2: CCM Victim Mirror | R8: Causal Direction Consistency | 🔶 DEFERRED |
| S3: Hankel Golden Ratio | R3: SEM Coefficient Stability | ⚠️ PARTIAL |
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

> 完整参数预设见: `presets.yaml` (demo / standard / deep / archival)
