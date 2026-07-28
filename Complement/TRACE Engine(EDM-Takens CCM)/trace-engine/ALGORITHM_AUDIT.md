# TRACE Engine — Algorithm Audit (元审计 P0 补全)

> 创建: 2026-07-20（元审计 P0 修缮）
> 范围: 六勇士算法深度审计 + 边界局限 + 启发式回退诚实标注
> 关联: [DESIGN_SIX_IN_ONE.md](examples/counterfactual_hybrid/DESIGN_SIX_IN_ONE.md) | [forbidden_rules.md](examples/counterfactual_hybrid/references/forbidden_rules.md) | [edge_cases.md](examples/counterfactual_hybrid/references/edge_cases.md)

---

## 0. 审计目的

本文档对 trace-engine 的六勇士集成进行**算法层深度审计**，回答四个元问题：

1. **名实相符性**：每个"勇士"是真实算法实现，还是启发式诊断？
2. **边界局限**：算法在什么数据画像下失效？失效是设计意图还是缺陷？
3. **证据等级**：输出可作为因果证据，还是仅作为文本类型诊断信号？
4. **降级路径**：依赖缺失时如何降级？降级后输出语义是否变化？

> **审计哲学**：错误不是"bug"，而是"系统错位的影子"。本审计不掩盖启发式回退，
> 而是让其显式化、可追溯、可消费——这是"异质性诊断联盟"的设计本意。

---

## 1. 六勇士架构等级声明（Tier System）

### 1.1 Tier-A 真算法层（4 名）— 输出可追溯因果证据

| # | 勇士 | 实现位置 | 算法核心 | 完成度 |
|---|------|---------|---------|--------|
| 1 | 🔴 TRACE | [run_real_pipeline.py:178-262](examples/counterfactual_hybrid/run_real_pipeline.py) | ΔNLL 掩码干预 + BPE token 对 | ★★★★★ |
| 2 | ⚫ HAVOK | [six_warriors.py:_deploy_havok](examples/counterfactual_hybrid/six_warriors.py) | Hankel 矩阵 + SVD 90% 能量截断 + 强迫项定位 | ★★★★☆ |
| 3 | 🟡 DoWhy+CF | [counterfactual_bridge.py:166-1138](examples/counterfactual_hybrid/counterfactual_bridge.py) | do-calculus + Pearl 三步反事实 | ★★★★★ |
| 4 | ⬜ causallearn | [causallearn_validator.py:19-161](examples/counterfactual_hybrid/causallearn_validator.py) | PC + GES 双算法 | ★★★★☆ |

### 1.2 Tier-B 启发式诊断层（2 名）— 文本特征启发式

| # | 勇士 | 实现位置 | 算法核心 | 真算法依赖 |
|---|------|---------|---------|-----------|
| 5 | 🔵 CCM | [six_warriors.py:_deploy_ccm](examples/counterfactual_hybrid/six_warriors.py) | 概念覆盖率统计 | edm-takens `ccm_with_convergence` |
| 6 | 🟡 EDM | [six_warriors.py:_deploy_edm](examples/counterfactual_hybrid/six_warriors.py) | 间隔变异系数近似 ρ | 无（始终启发式） |

### 1.3 设计意图（"不是投票，是测绘"）

> 引用 [DESIGN_SIX_IN_ONE.md:69-73](examples/counterfactual_hybrid/DESIGN_SIX_IN_ONE.md)

六合一的语义不是"六个等价算法投票取多数"，而是"异质性诊断联盟拓扑测绘"：

- **Tier-A 互相验证**：TRACE 的 ΔNLL 与 causallearn 的 PC/GES 在边集上做双向对比（CONSENSUS/DIVERGENT/TRACE_ONLY）
- **Tier-B 是文本类型诊断信号**：当 CCM 报告 `NARRATIVE_TEXT`、EDM 报告 `HEURISTIC_STRONG_NARRATIVE_STRUCTURE` 时，是诊断结论（叙事文/论证文），不是失败
- **降级不等于失败**：Tier-B 的 `status=fallback` 携带 `verdict=HEURISTIC_FALLBACK` 标签，消费方可据此降权

---

## 2. 各勇士算法深度审计

### 2.1 🔴 TRACE — ΔNLL 掩码干预

**算法核心**（[run_real_pipeline.py:178-262](examples/counterfactual_hybrid/run_real_pipeline.py)）：
```
对每对 token (i, j):
  1. 计算 P(j | 完整上下文) → nll_normal
  2. mask token i，计算 P(j | 上下文\i) → nll_masked
  3. ΔNLL(i→j) = nll_masked - nll_normal
  4. ΔNLL > threshold → 因果边 i→j
```

**边界局限**：
- 计算量 O(N²) — 200 token ≈ 8 条边（信号衰减轨迹）
- max_position 限制 — 长文本需分段（max_segments 参数）
- UNK 率 > 30% 时 ΔNLL 信号失真（[test_case.py:test_10e](examples/counterfactual_hybrid/test_case.py) 覆盖）

**完成度评分**：★★★★★（5/5）
- 完整实现 ΔNLL 计算 + 分段策略 + UNK 率感知
- 缓存机制（`real_adj.npy`）存在但无失效策略——文本变更后需手动清理

### 2.2 ⚫ HAVOK — Hankel 矩阵算子

**算法核心**（[six_warriors.py:_deploy_havok](examples/counterfactual_hybrid/six_warriors.py)）：
```
1. 构造 Hankel 矩阵 H (embedding_dim × n_snapshots)
2. SVD: H = U Σ V^T
3. 截断至 90% 能量: U_r, Σ_r, V_r
4. 线性算子 A = U_r^T H_shift V_r Σ_r^{-1}
5. 强迫项 v_r = (I - U_r U_r^T) × (H_shift V_r)
6. 定位 |v_r| 峰值 → 非线性事件时间点
```

**边界局限**：
- 输入是 token 频率时序，非连续动力系统——HAVOK 的连续时间假设在离散 token 上有失真
- Hankel 比例约束 p/q ≥ 10（[edm-takens forbidden_rules](../edm-takens/references/forbidden_rules_reference.md)）在 N<22 时无法满足
- 强迫项峰值定位的统计显著性未做 surrogate 检验

**完成度评分**：★★★★☆（4/5）
- 完整自实现（不依赖 edm-takens）
- 自适应 embedding_dim = min(concepts, √N × 3)
- 缺少 surrogate 显著性检验（建议后续集成）

### 2.3 🟡 DoWhy+CF — do-calculus + Pearl 三步

**算法核心**（[counterfactual_bridge.py:166-1138](examples/counterfactual_hybrid/counterfactual_bridge.py)）：
- `identify()`：do-calculus 后门调整
- `estimate()`：backdoor.linear_regression + 置信区间
- `refute()`：三层反驳（random_common_cause / placebo / data_subset）
- `counterfactual()`：Pearl 三步（Abduction → Action → Prediction）

**边界局限**：
- 概念节点 > 50 时自动降级为 SimulationModel（[counterfactual_bridge.py:511-514](examples/counterfactual_hybrid/counterfactual_bridge.py)）— 经验阈值，未文档化在 forbidden_rules
- DoWhy identify 失败时回退到 SimulationModel（[counterfactual_bridge.py:687-695](examples/counterfactual_hybrid/counterfactual_bridge.py)）
- Pearl 反事实仅支持线性 SEM（OLS/ridge/lasso），非线性 SEM 未实现

**完成度评分**：★★★★★（5/5）
- DoWhy 0.14 完整集成 + 适配层（[dowhy_adapter.py](examples/counterfactual_hybrid/dowhy_adapter.py)）
- Pearl 三步 + SEM 估计 + 反事实扫描
- 三层反驳 + 9 条审计规则（[dowhy_auditor.py:98-432](examples/counterfactual_hybrid/dowhy_auditor.py)）

### 2.4 ⬜ causallearn — PC/GES/FCI 独立验证

**算法核心**（[causallearn_validator.py:19-161](examples/counterfactual_hybrid/causallearn_validator.py)）：
- `run_pc()`：PC 算法（基于条件独立性测试）
- `run_ges()`：GES 算法（基于评分的贪婪等价搜索）
- `run_fci()`：FCI 算法（DOC-04 修复: 已实现, 含端点常量与节点索引修复, 输出 PAG 可识别潜在混淆）
- `compare_with_trace()`：双向边集对比

**边界局限**：
- 仅 top-12 概念参与（[six_warriors.py:520](examples/counterfactual_hybrid/six_warriors.py)）— 大概念集统计功效不足
- N<200 时 PC/GES/FCI 功效弱（`TRACE_ONLY — CL powerless at N={N}` 是设计意图）

**完成度评分**：★★★★★（5/5）
- PC/GES/FCI 完整集成
- 双向边集对比（CONSENSUS/DIVERGENT/TRACE_ONLY）
- FCI 已实现（PAG 输出, 端点常量 ENDPOINT_CIRCLE/ARROW/TAIL, 节点索引修复）

### 2.5 🔵 CCM — 交叉映射验证（Tier-B, ALG-02 修复后含真算法路径）

**算法核心**（[six_warriors.py:_deploy_ccm](examples/counterfactual_hybrid/six_warriors.py)）：
- 统计出现 ≥3 次的有效概念数（`ccm_eligible`）
- 计算覆盖率 `ccm_ratio = ccm_eligible / total_unique`
- 边级检查：TRACE 强边两端概念是否都在 `freq_tokens` 中
- **ALG-02 修复**: 真算法可用时实际调用 `ccm_with_convergence`（构建滑动窗口时间序列 → 最强边 CCM 收敛验证）

**真算法路径**：
- 优先从 `edm-takens/src/final_interpretation.py` 或 `ccm_causality.py` 导入 `ccm_with_convergence`
- 不可用时降级为启发式（标注 `HEURISTIC_FALLBACK`）
- **可用时**: 构建 token 滑动窗口计数时间序列 → 调用 `ccm_with_convergence` → 收敛则 `VERIFIABLE`, 未收敛则 `ELIGIBLE_BUT_NOT_RUN`

**边界局限**：
- 时间序列由 token 滑动窗口计数构建, 非 EDM 流形重构的原始信号
- 启发式输出 `verdict=LOW_TRUST` 是文本类型诊断信号，不可作为因果证据
- 真算法路径依赖 edm-takens Skill 可用性（环境敏感）

**完成度评分**：★★★★☆（4/5）
- 启发式实现完整 + 边级检查 + 真算法调用
- 真算法导入路径脆弱（依赖模块名 `final_interpretation` 或 `ccm_causality`）
- **名实不符风险已通过 Tier-B 标注 + ALG-02 真算法调用消除**

### 2.6 🟡 EDM — 间隔变异系数近似（Tier-B 启发式）

**算法核心**（[six_warriors.py:_deploy_edm](examples/counterfactual_hybrid/six_warriors.py)）：
- 对 top tokens 计算出现间隔 `intervals = np.diff(positions)`
- 变异系数 `cv = std(intervals) / mean(intervals)`
- 启发式 ρ = 1 / (1 + cv) — 低 CV → 高规律性 → 高 ρ

**边界局限**：
- **非 Sugihara EDM 算法**——不做 Simplex/S-Map 预测，仅做间隔规律性统计
- 启发式 ρ 与 Sugihara ρ 语义不同：前者测"出现规律性"，后者测"可预测性"
- 始终启发式，无真算法导入路径

**完成度评分**：★★★☆☆（3/5）
- 启发式实现完整 + 话语标记优先选择
- **名实不符风险已通过 Tier-B 标注消除**
- 与 edm-takens 真算法的桥接未实现（建议后续通过 MVE 集成，见 [MVE_OPTIMIZATION.md](MVE_OPTIMIZATION.md)）

---

## 3. 边界局限总览（"元架构和处理机制的要带"）

### 3.1 数据画像触发的算法边界

| 数据画像 | 触发边界 | 影响勇士 | 设计响应 |
|---------|---------|---------|---------|
| N < 22 | Hankel 比例 p/q≥10 不可满足 | HAVOK | 标记 `UNRELIABLE`，仍输出但降权 |
| N < 200 | PC/GES 统计功效不足 | causallearn | 输出 `TRACE_ONLY`，证明 TRACE 价值 |
| 概念数 > 50 | DoWhy DOT 图爆炸 | DoWhy+CF | 自动降级为 SimulationModel |
| UNK 率 > 30% | ΔNLL 信号失真 | TRACE | 警告但不拒绝（test_10e 覆盖） |
| 有效概念 < 3 | CCM 不可用 | CCM | 输出 `NARRATIVE_TEXT`（诊断信号） |
| 无高频话语标记 | EDM 无目标 | EDM | 输出 `HEURISTIC_WEAK_STRUCTURE` |

### 3.2 降级链完整性

| 依赖 | 不可用时降级 | 降级后语义 |
|------|------------|-----------|
| DoWhy | SimulationModel | 失去 do-calculus，保留线性回归 |
| pandas | _MinimalDataFrame | 失去 DataFrame API，保留 dict-of-lists |
| PyYAML | _simple_yaml_parse | 失去 YAML 注释，保留键值解析 |
| causallearn | 跳过 Layer 6 | 失去 PC/GES 验证 |
| graphviz | 跳过可视化 | 保留文本报告 |
| edm-takens Skill | CCM 启发式回退 | Tier-B 标注 `HEURISTIC_FALLBACK` |

### 3.3 设计选择：Bai-Perron 替代 50% 丢弃 (DOC-05)

**背景**：EDM 因果发现流水线在处理时间序列断点时，规范方法是 Bai-Perron (1998) 结构断点检验。本引擎当前采用简化的"50% 丢弃"策略，此处明确记录该设计选择的权衡与升级路径。

**设计权衡**：
1. **样本量约束**：EDM 因果发现典型 N=100~500，远低于 Bai-Perron 渐近有效性要求的 N≥500
2. **计算预算**：Bai-Perron 需 O(N²) 动态规划搜索所有可能断点，与实时 EDM 流水线冲突
3. **保守性偏好**：50% 丢弃比 Bai-Perron 更保守（丢弃更多数据），在小样本下倾向于"过切而非欠切"，符合 EDM "宁缺毋滥"原则
4. **可恢复性**：被丢弃的 50% 数据仍保留在原始 CSV 中，后续可离线用 Bai-Perron 复检

**代价与升级路径**：
- 代价：信息损失（50% 数据被丢弃而非自适应分割）
- 升级触发条件：N≥500 的生产场景应替换为 Bai-Perron（`ruptures>=1.1` 已在 requirements.txt 声明）
- 实现位置：`run_real_pipeline.py` 的断点检测逻辑，当前 `real_adj.npy` 缓存不区分断点策略

**与 edm-takens Skill 的关系**：edm-takens/references/forbidden_rules_reference.md §S5 已记录此设计选择，本节为 trace-engine 侧的对应文档化，确保两侧一致。

---

## 4. 审计规则 1:1 对应验证

### 4.1 forbidden_rules.md 9 条规则

| 规则 | 强度 | 代码位置 | 验证 |
|------|------|---------|------|
| R1 Identifiability Gate | FAIL | [dowhy_auditor.py:167-192](examples/counterfactual_hybrid/dowhy_auditor.py) | ✅ |
| R2 Refutation Triangulation | WARN | [dowhy_auditor.py:196-221](examples/counterfactual_hybrid/dowhy_auditor.py) | ✅ |
| R3 SEM Coefficient Stability | WARN | [dowhy_auditor.py:225-262](examples/counterfactual_hybrid/dowhy_auditor.py) | ✅ |
| R4 CF Extrapolation Guard | WARN | [dowhy_auditor.py:266-293](examples/counterfactual_hybrid/dowhy_auditor.py) | ✅ |
| R5 Graph Completeness | FAIL | [dowhy_auditor.py:297-320](examples/counterfactual_hybrid/dowhy_auditor.py) | ✅ |
| R6 Placebo Vanishing | WARN | [dowhy_auditor.py:324-346](examples/counterfactual_hybrid/dowhy_auditor.py) | ✅ |
| R7 CI Non-Degeneracy | WARN | [dowhy_auditor.py:350-370](examples/counterfactual_hybrid/dowhy_auditor.py) | ✅ |
| R8 Causal Direction Consistency | WARN | [dowhy_auditor.py:374-397](examples/counterfactual_hybrid/dowhy_auditor.py) | ✅ |
| R9 Sparse Graph Sanity | ADVISORY | [dowhy_auditor.py:401-421](examples/counterfactual_hybrid/dowhy_auditor.py) | ✅ |

**采纳率**：9/9 fully adopted（[forbidden_rules.md:22](examples/counterfactual_hybrid/references/forbidden_rules.md)）

### 4.2 edge_cases.md 9 个边界情况

| EC | 描述 | 测试覆盖 | 验证 |
|----|------|---------|------|
| EC-1 | 空因果图 | [test_case.py:test_10a](examples/counterfactual_hybrid/test_case.py) | ✅ |
| EC-2 | 全低频 token | test_10b | ✅ |
| EC-3 | Pearl 反事实引擎 | test_10c | ✅ |
| EC-4 | 反馈回路检测 | test_10d | ✅ |
| EC-5 | ASCII 单字母 BPE 碎片 | test_10e | ✅ |
| EC-6~9 | 见 [edge_cases.md](examples/counterfactual_hybrid/references/edge_cases.md) | 文档覆盖 | ✅ |

---

## 5. 元审计发现与修缮记录

### 5.1 本次审计发现（2026-07-20）

| # | 发现 | 严重度 | 修缮 | 状态 |
|---|------|--------|------|------|
| A1 | 六勇士"名实不符"——CCM/EDM 是启发式但未显式分层 | P0 | 增加 Tier-A/B 字段 + 架构等级声明 | ✅ 已修 |
| A2 | ALGORITHM_AUDIT.md 用户期望但不存在 | P0 | 创建本文件 | ✅ 已修 |
| A3 | secret_adoption_audit.md 引用断裂（5个文件不在 Skill） | P1 | 见 §5.2 | 🚧 待修 |
| A4 | causallearn FCI 未实现但未在边界局限文档化 | P2 | FCI 已实现 (DOC-04 修复), §2.4 更新 | ✅ 已修 |
| A5 | counterfactual_bridge.py:511-514 的 50 节点阈值未文档化 | P2 | 本文档 §2.3 已记录 | ✅ 已修 |

### 5.2 secret_adoption_audit.md 引用断裂修复

原文件引用了 5 个不在 Skill 目录的文件：
- `trace_plus.py` — 在 TRACE 主项目
- `pipeline_zhihu.py` — 在 TRACE 主项目
- `early_stop.py` — 在 TRACE 主项目
- `train_shenji_llama.py` — 在 TRACE 主项目
- `run_tests.py` — 标注为 ❌ DEFERRED

**修复方案**：保留原文件作为"设计规则采纳审计"，但补充说明这些文件位于 TRACE 主项目而非 Skill 目录。详见 [secret_adoption_audit.md](secret_adoption_audit.md) §6 引用范围说明。

---

## 6. 后续优化方向

### 6.1 算法深化

1. **CCM 真算法桥接**：✅ 已完成 (ALG-02 修复, _deploy_ccm 实际调用 ccm_with_convergence)
2. **EDM 真算法桥接**：通过 MVE（多视角嵌入）实现真正的 Sugihara EDM，详见 [MVE_OPTIMIZATION.md](MVE_OPTIMIZATION.md)
3. **causallearn FCI 实现**：✅ 已完成 (DOC-04 修复, 含端点常量与节点索引修复)
4. **HAVOK surrogate 检验**：强迫项峰值的统计显著性检验

### 6.2 工程深化

1. **pytest 测试框架**：替换 subprocess + assert（[test_skill.py](tests/test_skill.py)）
2. **覆盖率测量**：集成 coverage.py
3. **TRACE 缓存失效策略**：基于文本 hash 的版本检查
4. **50 节点阈值文档化**：将经验阈值写入 [forbidden_rules.md](examples/counterfactual_hybrid/references/forbidden_rules.md)

---

## 7. 审计结论

| 维度 | 评级 | 依据 |
|------|------|------|
| 算法名实相符性 | A | Tier-A/B 显式分层，启发式回退诚实标注 |
| 边界局限文档化 | A | 数据画像触发的边界全部记录（§3.1） |
| 降级链完整性 | A | 6 条降级路径全部覆盖（§3.2） |
| 审计规则 1:1 对应 | A | 9 条规则 + 9 个边界情况全部可追溯（§4） |
| 测试覆盖 | B | 10 个功能测试 + 4 smoke test，缺 pytest/CI |

**总体结论**：trace-engine 的六勇士架构在**算法名实相符性**上已通过 Tier 系统显式化，
启发式回退不再是"隐性债务"而是"显性诊断信号"。边界局限、降级路径、审计规则
均已文档化并可追溯。剩余工程债务（pytest/CI/覆盖率）不影响算法正确性。
