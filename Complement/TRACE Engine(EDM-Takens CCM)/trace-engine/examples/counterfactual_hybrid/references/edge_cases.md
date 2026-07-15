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

---

## EC-8: 跨域模型 UNK 率稀释 ΔNLL

**症状**: 使用领域 A 训练的模型分析领域 B 的文本时，ΔNLL 信号极弱，即使降低阈值也只能获得少量显著边。

**触发条件**:
- 跨域 TRACE（如 Shehui-LLaMA [古典中文] → 知乎文本 [现代白话]）
- UNK rate > 5%

**实测案例**: 知乎网友.txt (5932 chars, 叙事文)
- Shehui-LLaMA (古典): UNK=11.7%, τ=0.05 → 10 edges, max ΔNLL=1.12
- Instant TRACE (专域): UNK=0.1%,  τ=1.0  → 22 edges, max ΔNLL=6.24
- **差距**: 30x ΔNLL 差异，边数 2.2x

**机制**: UNK token 没有嵌入向量 → 自回归模型对 UNK 的预测是纯随机 → 掩码 UNK 对 NLL 几乎无影响 → ΔNLL 弱。

**缓解**:
- **首选**: 运行 Instant TRACE (`python TRACE/scripts/instant_trrace.py --data zhihu.txt`)
  - 自动训练 BPE tokenizer + 微型 LLaMA → UNK=0%
  - 时间: 5-10 min（轻量）或 80+ min（完整）
- **次选**: 降低 τ 到 0.05-0.1（本次测试方案）
  - 捕获弱信号，但噪声增加
  - 配合 concept_min_freq=3 过滤噪声
- **文本类型检测**: `aggregate_concepts()` 中已添加 UNK 率 + 叙事文自动检测，输出阈值建议

**当前状态**: v6 已在 `aggregate_concepts()` 中添加自动 WARN + 阈值建议。

---

## EC-9: LLaMA 过拟合模型的低 ΔNLL 体制 (llama 预设)

**症状**: 使用过拟合训练的 TRACE LLaMA 模型（Shehui-LLaMA 27M / Shenji-LLaMA 469M / Shehui-LLaMA V4 Archive 470M）时，ΔNLL 绝对值极低（典型范围 0.000-0.160），默认阈值（0.3-1.0）几乎捕获不到因果边。

**触发条件**:
- 使用过拟合训练的 TRACE LLaMA 模型（Shenji-LLaMA 469M / Shehui-LLaMA 27M / Shehui-LLaMA V4 Archive 470M）
- 模型在领域文本上 loss 极低（如 0.092），预测过于自信 → 掩码扰动带来的 ΔNLL 被压缩

**机制**: 过拟合模型对训练分布的预测概率接近 1.0，掩码一个 token 后 NLL 的变化被softmax 的平缓区压缩，导致 ΔNLL 绝对值小。但因果区分度依然存在 —— 真因果边的 ΔNLL 仍显著高于伪因果边。

**缓解**: 使用 `llama` 预设（见 `presets.yaml`）

| Parameter | Value | 说明 |
|-----------|-------|------|
| `threshold` | 0.01 | 捕获中等以上因果边 |
| `concept_min_freq` | 1 | 领域文本 token 频率低，放宽 |
| `window_size` | 128 | V4 seq=1024，更大窗口 |
| `max_segments` | 3 | 469M 参数在 RTX 3050 上限制分段数 |
| `classical_mode` | false | 默认现代白话；古汉语分析可切换为 true（保留之/乎/者/也等虚词） |

**适用场景**:
- **模型**: Shehui-LLaMA (27M 轻量，古典社会领域) / Shenji-LLaMA (469M，史诗领域) / Shehui-LLaMA V4 Archive (470M 旧版归档)
- **古汉语分析**: 当分析先秦/文言文本时，将 `classical_mode` 切换为 `true`，保留文言虚词作为有效概念节点

**调用方式**:
```python
from presets import load_presets
p = load_presets("llama")
bridge = TRACE2DoWhy(adj, tokens, **p.trace2dowhy)
```
