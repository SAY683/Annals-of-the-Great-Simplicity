# Round 21 — 8 模块算法数学审查综合报告

> 创建: 2026-07-27
> 范围: edm-takens core (3模块) + EDM 三件套 (3模块) + trace-engine 反事实混合 (3模块)
> 视角: 数学家 + 统计家 + 因果推断专家
> 关联: ROUND21_ACTION_PLAN.md P0-B

---

## 0. 总体发现

| 严重度 | 数量 | 主要分布 |
|--------|------|---------|
| **P0** (阻断性) | 4 | Pearl 拓扑序缺失 / six_warriors 节点索引回归 / CV 独立性违反 / 模拟模式 ATE 伪装可识别 |
| **P1** (重要) | 17 | 数值稳定性 / R² 阈值 / 文档-代码不一致 / SEM 模拟模式局限 |
| **P2** (改进) | 15 | 命名混淆 / 死代码 / 阈值硬编码 |

**最严重发现**: `six_warriors.py:585-586` 的 causallearn 节点索引未做 `-1` 转换，与 `causallearn_validator.py:184-185` 的同名修复**直接矛盾**——同一 bug 在两个文件中，一个已修一个未修，说明代码复用断裂。

---

## 1. P0 级问题（必须立即修复）

### P0-1: Pearl 三步反事实缺失拓扑排序

- **位置**: [pearl_counterfactual.py](file:///f:/攻略/研发测试/TRACE%20Engine(EDM-Takens%20CCM)/trace-engine/examples/counterfactual_hybrid/pearl_counterfactual.py#L100-L110)
- **问题**: `predict_cf` 按 `range(n_vars)` 遍历，未做拓扑排序。当父节点索引 > 子节点索引时，`cf_values.get(p, observed[p])` 回退到观测值，中介变量未取反事实值。
- **数学证明**: 设 SEM 为 $X_3 \to X_2 \to X_1$（索引 3→2→1），查询 do(X_3=t'):
  - v=0: cf_values[0] = observed[0]（错误，X_1 是 X_3 后代应取反事实值）
  - v=1: pred = β_{01} * cf_values[0]（用了错误的 cf_values[0]）
  - v=2: cf_values[2] = t' ✓
- **后果**: ITE 计算错误，但注释 (L78-80) 自称"完整 Pearl 三步反事实"——属于"半吊子实现"。
- **修复**: 调用前计算拓扑序 `topo_order = self._topological_sort()`，按拓扑序遍历。

### P0-2: six_warriors causallearn 节点索引回归

- **位置**: [six_warriors.py](file:///f:/攻略/研发测试/TRACE%20Engine(EDM-Takens%20CCM)/trace-engine/examples/counterfactual_hybrid/six_warriors.py#L585-L586) (PC) 和 L595-596 (GES)
- **问题**:
  ```python
  # six_warriors.py:585-586 (BUG - 未修复)
  ni = _node_index(e.get_node1())
  nj = _node_index(e.get_node2())
  ```
  对比 [causallearn_validator.py:184-185](file:///f:/攻略/研发测试/TRACE%20Engine(EDM-Takens%20CCM)/trace-engine/examples/counterfactual_hybrid/causallearn_validator.py#L184-L185) (已修复):
  ```python
  i = _node_index(edge.get_node1()) - 1  # 1-based → 0-based
  j = _node_index(edge.get_node2()) - 1
  ```
- **后果**: 所有 PC/GES 边节点映射偏移1位；最后一个节点 X_N 越界被静默丢弃；`agree` 集合比较结果全错。
- **修复**: 立即在 six_warriors.py 中应用相同 `-1` 修复 + `0 <= ni` 越界检查。

### P0-3: enhanced_cross_validate "交叉验证"违反时间序列独立性

- **位置**: [enhanced_cross_validate.py:692-693](file:///f:/攻略/研发测试/Skill/edm-takens/src/enhanced_cross_validate.py#L692-L693)
- **问题**: `lib = '1 {n-7}'`, `pred = '{n-6} {n}'` 是单次时间相邻 hold-out，不是交叉验证。对 AR(1) φ=0.9，相邻样本互信息 ≈ 0.83 nats，测试集 ρ 被系统性高估。
- **缓解**: 文件名/函数名误导（`cross_validate_with_safeguards` 实为启发式 if-else），应重命名为 `heuristic_validation`。

### P0-4: 模拟模式 ATE 不可识别性被隐藏

- **位置**: [simulation_model.py:69-74](file:///f:/攻略/研发测试/TRACE%20Engine(EDM-Takens%20CCM)/trace-engine/examples/counterfactual_hybrid/simulation_model.py#L69-L74)
- **问题**: `SimulationEstimand` 硬编码 `identifiable=True`，但 ATE = `rng.uniform(0.1, 0.5)` 是随机数。`DoWhy14Adapter.is_identifiable` 通过 `hasattr` 检查直接返回 True。
- **后果**: 模拟模式报告显示"可识别: True"，用户无法区分真实 do-calculus 与合成值。
- **修复**: `SimulationEstimand` 增加 `synthetic=True` 标记，`is_identifiable` 对 synthetic 返回 False 或 "SYNTHETIC"。

---

## 2. P1 级关键问题

### 2.1 数值稳定性

| ID | 文件 | 问题 | 行号 |
|----|------|------|------|
| P1-1 | _numpy_edm.py | S-Map `d_avg=0` 时 `np.exp(-θ*0/0)=NaN` 传播到 lstsq | L364-370 |
| P1-2 | _numpy_edm.py | S-Map `lstsq` 用 `rcond=None` 对秩亏静默返回最小范数解，`except LinAlgError` 对 SVD 失效 | L413-416 |
| P1-3 | final_interpretation.py | `log(div + 1e-12)` 当 div→0 时引入 -27.6 偏差，拉低 λ_max | L125 |
| P1-4 | final_interpretation.py | `_divergence_rate_metric` 中 `N_local - 10` 可能为负，`np.random.choice` 抛 ValueError | L235-237 |
| P1-5 | enhanced_cross_validate.py | 自相关归一化 `autocorr / autocorr[0]` 对常量序列产生 NaN | L107 |

### 2.2 统计严谨性

| ID | 文件 | 问题 | 行号 |
|----|------|------|------|
| P1-6 | ccm_causality.py | Spearman 独立性假设违反（library size 嵌套抽样），p 值系统性偏低 | L187 |
| P1-7 | ccm_causality.py | `total_rise = 0.05` 是绝对差值，对 ρ ∈ [0.9, 0.95] 和 [0.05, 0.10] 等同对待 | L186 |
| P1-8 | final_interpretation.py | `fit_r2 >= 0.5` 阈值偏松（学术标准 0.9），且 `reliable` 语义不一致 | L147, L436 |
| P1-9 | enhanced_cross_validate.py | Lyapunov 时间用 `abs(lambda_max)`，稳定系统被误报为有限预测 horizon | L155 |
| P1-10 | counterfactual_bridge.py | `warnings.filterwarnings("ignore")` 静默过滤 condition_number=5.5×10¹² 的奇异矩阵警告 | L696-703 |
| P1-11 | counterfactual_bridge.py | report() 不输出 condition_number 诊断，用户看到 ATE/CI 但不知其不可信 | L1034-1039 |

### 2.3 SEM 模拟模式局限

| ID | 文件 | 问题 | 行号 |
|----|------|------|------|
| P1-12 | simulation_model.py | ATE = `_coeff[ti, oi]` 仅取直接效应，忽略所有间接路径 | L81-82 |
| P1-13 | simulation_model.py | 反驳结果 `rng.normal(0, estimate.value * 0.05)` 完全随机，与数据无关 | L90-103 |
| P1-14 | six_warriors.py | DoWhy+CF 卡片模拟模式下 verdict "ROBUST — 0/3 反驳" 不披露反驳无意义 | L524-529 |

### 2.4 文档-代码不一致

| ID | 文件 | 问题 | 行号 |
|----|------|------|------|
| P1-15 | pearl_counterfactual.py | 文档公式 (L8-11) 是 CDE，代码 (L100-110) 是 Y(t')，未更新文档 | L8-11 |
| P1-16 | sovereign_havok.py | 注释 (L200-203) 说 `r-1`，代码 (L237) 实际是 `r`，差一个索引 | L200-203 |
| P1-17 | pearl_counterfactual.py | SEM 估计失败静默吞异常 (`except LinAlgError`)，coeff 保持 0，ITE=0 | L183-185 |

---

## 3. 模块评估汇总

| 模块 | 数学正确性 | 边界处理 | 概念版省略 | 主要风险 |
|------|-----------|---------|-----------|---------|
| ccm_causality.py | ✓ 4条件实现与文档一致 | A | 否 | Spearman 独立性违反致 p 值低估 |
| sovereign_havok.py | ✓ Hankel/SVD/回归/增广矩阵指数均正确 | A+ | 否 | 0.999 能量阈值过严；K_d_ legacy 误导 |
| final_interpretation.py | ✓ Rosenstein 核心正确 | B+ | estimate_lyapunov_lower_bound 半概念版 | R²≥0.5 偏松；N_local<10 未防护 |
| edm_adaptive_pipeline.py | ✓ 公式正确 | C | **是** — docstring 承诺 ccm_results 但未实现 | NaN 处理弱，无 p 值 |
| enhanced_cross_validate.py | ⚠ Lyapunov tau_L 用 abs | B | **部分是** — "CV" 名实不符 | 时间相邻 hold-out 违反独立性 |
| _numpy_edm.py | ✓ Simplex/S-Map/CCM 公式正确 | C | Multiview 是死代码 | S-Map NaN 传播、秩亏无警告 |
| counterfactual_bridge.py | ⚠ SEM 环迭代无收敛判断 | B | estimate() 静默掩盖奇异矩阵 | condition_number 未披露 |
| pearl_counterfactual.py | **✗ 缺失拓扑排序** | C | **是** — 注释自称"完整"但缺核心要件 | ITE 计算错误 |
| six_warriors.py | ⚠ causallearn 节点索引回归 | B | CCM/EDM 是诚实启发式 | causallearn 结果全错 |

---

## 4. 4 角色互审结论

### 数学家视角
- HAVOK 的 Van Loan 增广矩阵指数技巧是教科书级正确实现 ✓
- Pearl 三步反事实缺失拓扑排序是**数学错误**，不是工程妥协
- `log(div + 1e-12)` 的偏差可用 `np.log(div, where=div>eps)` 优雅修复

### 统计家视角
- CCM 的 Spearman p 值在嵌套抽样下不成立，BH-FDR 的统计保证随之失效
- `fit_r2 >= 0.5` 作为可靠度阈值过松，应分级 (reliable/marginal/unreliable)
- 模拟模式的反驳结果与数据无关，"0/3 反驳"无统计意义

### 算法工程师视角
- six_warriors 的 causallearn 节点索引回归是**代码复用断裂**的典型症状
- _numpy_edm.py 的 S-Map 数值稳定性三连缺（NaN/秩亏/无 outlier 检查）
- 三份 Lyapunov 实现并存（enhanced_cross_validate L59+L546, final_interpretation L69）是反模式

### PM 视角
- 论文中 ATE=1.0183, CI=[0.9515, 1.0851] 在 condition_number=5.5×10¹² 下不可信，必须重设计
- 用户无法区分"可识别: True"是真实 do-calculus 还是合成值
- Pearl 注释自称"完整"但实际错误，属于"诚实性债务"

---

## 5. 修复优先级

### 立即修复（Round 21 内）

| 优先级 | 问题 | 修复复杂度 | 影响范围 |
|--------|------|-----------|---------|
| P0-2 | six_warriors 节点索引 `-1` | 4 行 | 单函数 |
| P1-3 | `log(div + 1e-12)` → `np.log(div, where=div>eps)` | 3 行 | 单函数 |
| P1-4 | `N_local - 10 < 0` 防护 | 2 行 | 单函数 |
| P1-5 | 自相关归一化 NaN 防护 | 2 行 | 单函数 |

### 待规划（Round 22+）

- P0-1: Pearl 拓扑排序（需设计 `_topological_sort` + 环检测）
- P0-3: enhanced_cross_validate 重命名 + 文档修正
- P0-4: SimulationEstimand 增加 synthetic 标记
- P1-1~P1-2: _numpy_edm S-Map 数值稳定性全面加固
- P1-10~P1-11: counterfactual_bridge condition_number 披露
- P1-15: pearl_counterfactual 文档公式更新

---

## 6. 验收清单

- [x] 8 模块全部审查（ccm/havok/lyapunov/edm_adaptive/cross_validate/numpy_edm/counterfactual_bridge/pearl/six_warriors）
- [x] 每模块含数值示例验证或数学证明
- [x] 发现问题按 P0/P1/P2 分级
- [x] 4 角色互审完成
- [x] 概念版/半吊子实现明确标注
- [ ] P0-2 立即修复（下一步）
- [ ] P1-3/P1-4/P1-5 立即修复（下一步）
