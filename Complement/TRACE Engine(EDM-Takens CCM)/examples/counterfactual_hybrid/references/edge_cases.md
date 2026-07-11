# DoWhy + Counterfactual — Edge Cases & Mitigations

> 对标 edm-takens/references/edge_cases_reference.md。
> 记录 DoWhy/反事实管线在各数据体制下的已知边界情况和缓解策略。

---

## EC-1: BPE Token Fragment Contamination

**症状**: DOT 图包含 `",`、`▁`、`?` 等 BPE 碎片节点，导致 DoWhy identify 崩溃。

**触发条件**: 
- 使用 SentencePiece BPE tokenizer（TRACE 的默认 tokenizer）
- Token 列表包含标点、部分字符、空格前缀 `▁`

**机制**: BPE 分词可能将标点与文字合并（如 `",`）。这些 token 出现在因果边中时，DoWhy 的 DOT 解析器无法处理节点名中的特殊字符。

**缓解** (已在 v2 中实现):
```python
# build_model() 中的 _is_valid_concept() 过滤器
def _is_valid_concept(name):
    if len(name) <= 1: return False
    if any(c in name for c in ['"', "'", ',', '.', ':', ';', '(', ')']): return False
    if name.startswith('▁'): return False
    return True
```

**残留风险**: 极低 — 自然语义概念很少包含这些字符。

---

## EC-2: DOT 图规模爆炸

**症状**: DoWhy 的 identify_effect() 在超过 50 个节点的 DOT 图上极慢（>60秒）或内存溢出。

**触发条件**: 
- concept_min_freq 太低（< 3）
- 文本长（> 5000 chars）且概念多样
- threshold 太低（< 0.2）

**机制**: DoWhy 的 do-calculus 需要枚举后门路径，复杂度随节点数指数增长。

**缓解** (已在 v2 中实现):
- `max_edges_for_dowhy=8`（默认 top-8 最强边）
- DOT 图只包含在有效边中出现的节点（而非全部概念）
- 自动回退到 SimulationModel（当 DoWhy 超时/崩溃时）

**建议**: 生产环境中保持 `max_edges_for_dowhy <= 15`。

---

## EC-3: 零方差模拟数据导致 CI 退化

**症状**: ATE 的 95% CI 为 `[NaN, NaN]`。

**触发条件**:
- 模拟数据噪声太低（`noise_std < 0.01`）
- OLS 设计矩阵奇异

**机制**: 模拟数据用 `rng.normal(0, 0.1)` 生成，方差极低时 OLS 的 `Var(β)` 估计溢出。

**缓解**: 在真实 TRACE 数据中不会出现 — token 出现模式有自然方差（有些 token 出现 10 次，有些 1 次）。

**监控**: R7 (CI Non-Degeneracy) 规则自动检测并 WARN。

---

## EC-4: 反事实查询超出观测范围

**症状**: 反事实查询的 treatment_value 超出训练数据的 treatment 范围，结果具有推测性。

**触发条件**:
- Pearl CF 的 `treatment_value=1.0` 而观测数据中 treatment 的 max 值为 0.2

**机制**: SEM 系数是从观测范围估计的线性近似。外推到范围外时，线性近似可能失效。

**缓解**:
- R4 (CF Extrapolation Guard) 自动 WARN
- 建议: 使用观测数据的分位数作为 treatment_value 的范围

---

## EC-5: 小样本 SEM 系数不稳定

**症状**: Pearl CF 查询的 ITE 在不同 random_state 下波动大。

**触发条件**:
- N < 5 × V（样本量 < 5倍变量数）
- 概念数多（> 20）

**机制**: OLS 估计量在 N/V 比值低时方差异大。

**缓解**:
- R3 (SEM Coefficient Stability) 自动 WARN (N < 5V) 或 FAIL (N < 2V)
- 建议: 增加段落数（用更多文本段做样本）或减少 concept_min_freq

---

## EC-6: causallearn 在小样本上返回 0 边

**症状**: PC 和 GES 算法在真实 TRACE 数据上找不到任何边。

**触发条件**:
- N < 200（样本量不足）
- V > 8（变量太多）

**机制**: PC 的条件独立性检验和 GES 的 BIC 分数需要足够的统计功效。小样本下无法拒绝条件独立的零假设。

**缓解**: 这不是 bug — 恰恰证明了 TRACE 在 sparse-data 体制下的不可替代性。TRACE 可以在只有一段文本（单一观测序列）时工作。

**建议**: 对于大样本文本（> 50 段），causallearn 可以作为高价值的独立验证。

---

## EC-7: 语法 token 伪装成概念

**症状**: 高频语法 token（如"的"、"了"、"是"）被当作独立概念节点，污染因果图。

**触发条件**:
- concept_min_freq 太低
- 文本包含高频虚词

**缓解**:
- 提高 concept_min_freq 到 3+
- 添加 stopword 列表（中文虚词："的", "了", "是", "在", "和", "也", "就"）
- 单字 token 自动排除

**当前状态**: v2 已将单字 token（`len(name) <= 1`）过滤，但虚词过滤依赖于 concept_min_freq。

---

## 数据体制速查表

| 数据体制 | N (样本) | V (概念) | TRACE | DoWhy | causallearn | CF |
|---------|---------|---------|:---:|:---:|:---:|:---:|
| 微型 (<500 chars) | <10 | <10 | ✓ | △ 模拟 | ✗ | △ |
| 小型 (500-2K) | 10-30 | 5-15 | ✓ | △ 模拟 | ✗ | ✓ |
| 中型 (2K-10K) | 30-100 | 10-30 | ✓ | ✓ (top-8) | △ | ✓ |
| 大型 (>10K) | >100 | >30 | ✓ | ✓ (top-15) | ✓ | ✓ |
