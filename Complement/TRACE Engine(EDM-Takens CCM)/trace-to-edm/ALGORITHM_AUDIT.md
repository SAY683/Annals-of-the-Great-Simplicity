# ALGORITHM_AUDIT — trace-to-edm 方法学审计

> ROUND28 P0-02 交付物。本文档记录三层元因果控制论桥接系统的方法学限制、
> 诠释属性边界与 EDM 触发阈值，作为 `layer3_sacred.py` / `edm_trigger.py` /
> `layer2_semantic.py` 内嵌 disclaimer 的权威参考。
>
> 目标：让"科学层"与"诠释层"的边界可被程序化识别、可被投资者审计，
> 避免将私域经书投影与 DoWhy 因果推断并列呈现而误导决策。

---

## §0 审计动机

trace-to-edm 将异质语义层（因果推断 / PCA / 神圣坐标轴）的输出写入同一张
`narrative_meta_trajectories.csv`，再交由 EDM-Takens 做动力学预测。这带来一个
核心风险：**下游（EDM / 前端 / 报告）无法仅凭列名区分哪些列有统计保证、
哪些列只是诠释投影**。若不做显式标注，投资者可能把 `z_福音` 的相变信号
与 `ate` 的因果效应等同对待，构成方法学越权。

本文档逐层声明各列的统计保证等级、退化行为与使用边界，并在 §4 给出
程序化契约（常量名 / 字段名），供 `portable_verify.py` 与前端读取校验。

---

## §1 Layer 1 — 元 SCM 参数（科学层，30 列）

### 1.1 统计保证等级：**有保证**（refutation / p-value / 置换检验）

L1 由 `layer1_meta_scm.py` 从 TRACE 引擎的 `result.json` 提取，来源是
DoWhy 因果推断 + 六战士验证流水线：

| 子组 | 列 | 保证来源 |
|------|----|----------|
| 因果效应 | `ate`, `ate_ci_lower/upper`, `ci_width` | DoWhy 双重机器学习 + 置信区间 |
| 反驳稳健性 | `refuted_count`, `refutations_attempted` | 3 种 refute（安慰剂 / 子集 / 随机共同原因） |
| 可识别性 | `identifiable` | DoWhy backdoor 图判定 |
| 图结构 | `edge_count`, `adj_density`, `max_delta_nll` | NLL 显著性 + 邻接矩阵 |
| 信号层级 | `signal_type`, `max_delta_nll_concept_level`, `concept_level_edge_count` | token-level vs concept-level 标注 |
| 数据诊断 | `concept_coverage`, `condition_number`, `unk_rate` | 分词 / 矩阵条件数 |
| CCM | `ccm_coverage_pct`, `ccm_verdict`, `ccm_algorithm_run` | 六战士 CCM 模块 |
| EDM 内嵌 | `edm_rho_high`, `edm_rho_mid` | TRACE 内部 EDM ρ 分箱 |
| HAVOK | `havok_status`, `havok_linear_pct` | 六战士 HAVOK（可能 `unavailable`） |
| causallearn | `causallearn_consensus` | 第三方因果发现共识 |
| 稳定性 | `edge_stability_mean`, `permutation_p_value` | bootstrap + 置换检验 |
| 共识 | `consensus_score`, `consensus_direction` | 三方算法共识度（计算列） |
| 剖面 | `total_ms` | 执行耗时 |

### 1.2 已知限制

- **`ccm_algorithm_run`**: 当前实现仅做启发式覆盖率，真实 `ccm_with_convergence`
  从未调用；`verdict=VERIFIABLE` 时置 1。下游不得将 `ccm_coverage_pct` 等同于
  Sugihara CCM ρ 收敛证据。
- **`refutations_attempted`**: LIGHT 模式为 0（未尝试），DEEP/SUPER 模式为 3。
  `refuted_count=0` 在 LIGHT 下含义为"未检验"而非"全通过"。
- **`havok_status=unavailable`**: HAVOK 在短序列 / 高噪声下不可用，
  `havok_linear_pct=-1.0` 为哨兵值，不得解读为"0% 线性能量"。
- **`consensus_score=-1.0`**: 计算异常时的哨兵值（ROUND28 P2-05 修缮），
  表示"不可用"，CSV 中应被识别为缺失值，**不得**解读为"完全无共识"。
- **`signal_type`**: SUPER 模式用 `delta_nll`，LIGHT/DEEP 用 `co_occurrence`。
  EDM 不得将不同 `signal_type` 的 `max_delta_nll` 视为同质时间序列。

### 1.3 退化行为

| 退化场景 | 表现 | 处理 |
|----------|------|------|
| TRACE 失败 | `trace_status=FAILED`, `trace_error` 记录原因 | CSV 行仍写入，L1 列为默认值 |
| LIGHT 模式 | `refuted_count=0`, `ccm_verdict=N/A` | 前端应标注"LIGHT 模式，未运行反驳/CCM" |
| SUPER 模式 | `signal_type=delta_nll` | EDM 应按 signal_type 分组分析 |

---

## §2 Layer 2 — 世俗 PCA 投影（科学层，4 列）

### 2.1 统计保证等级：**有保证**（explained variance ratio）

L2 由 `layer2_semantic.py` 对 Qwen2.5-1.5B 最后一层隐藏状态做 PCA：

| 列 | 含义 |
|----|------|
| `z_pca_1/2/3` | 世俗语义流形的前 3 个主轴坐标 |
| `secular_entropy` | 投影分布的熵（话语多样性） |

### 2.2 已知限制 — 小样本 PCA 退化（P1-04 披露）

- **`LAYER2_MIN_SAMPLES_FOR_PCA = 10`**: 样本 <10 时，PCA 无法从项目自身
  协方差矩阵估计主轴。此时降级为**背景 PCA**：基于 8 个神圣向量的协方差
  构造主轴（非随机），确保第一条文本就有有意义的 `z_pca_1`。
- **退化披露**: 背景 PCA 的主轴与项目真实话语流形无关，`z_pca_*` 在
  样本 <10 时仅反映"相对神圣坐标轴的世俗投影"，不反映"项目内话语变异"。
  `edm_trigger.check_readiness()` 应在小样本时披露此退化。
- **`explained_variance_ratio`**: L2 在 ≥10 样本时记录各主轴的方差占比，
  背景 PCA 模式下方差占比无意义（主轴由神圣向量确定，非数据驱动）。

### 2.3 使用边界

- L2 是**数据驱动**的（PCA 由项目语料拟合），主轴语义随项目变化。
- `z_pca_1` 在项目 A 与项目 B 之间**不可直接比较**（主轴定义不同）。
- 跨项目比较需先对齐 PCA 基底（当前未实现）。

---

## §3 Layer 3 — 八正道神圣坐标轴（诠释层，48 列）

### 3.1 方法学属性声明（P0-01 核心）

> **Layer 3 是诠释性框架 (Interpretive Framework)，非统计推断。**
> z_* 值由八本私域经书的零样本余弦相似度确定，不具备 Layer 1 那样的
> refutation/p-value 统计保证。投资决策需与 L1 统计量交叉验证。

| 子组 | 列数 | 列前缀 | 含义 |
|------|------|--------|------|
| 绝对投影 | 8 | `z_{轴}` | 世俗文本与神圣坐标轴的余弦相似度 |
| 一阶差分 | 8 | `dz_{轴}` | Δz/Δt — 语义漂移速度 |
| 二阶差分 | 8 | `d2z_{轴}` | Δ²z/Δt² — 语义加速度 |
| z-score（Phase 2） | 8 | `z_{轴}_zscore` | per-project 滚动窗口归一化 |
| dz z-score | 8 | `dz_{轴}_zscore` | 一阶差分归一化 |
| d2z z-score | 8 | `d2z_{轴}_zscore` | 二阶差分归一化 |

`{轴}` ∈ {福音, 吉祥, 奥美, 存在, 自孕, 弥赛亚, Alice, 觉爱}（见 `config.SACRED_BOOKS`）。

### 3.2 为何标注为"诠释"而非"统计"

| 维度 | Layer 1（统计） | Layer 3（诠释） |
|------|-----------------|-----------------|
| 坐标轴来源 | 数据驱动（DoWhy 图 / NLL） | 本体论给定（8 本私域经书） |
| 有效性验证 | refutation / p-value / 置换 | 无数据驱动验证手段 |
| 可重复性 | 同数据 → 同结果（确定性） | 同数据 + 同经书 → 同结果（确定性） |
| 语义稳定性 | 跨项目可比 | 跨项目可比（坐标轴不变） |
| 投资决策 | 可直接作为因果证据 | 必须与 L1 交叉验证 |

**数学实现本身是严谨的**（cosine + modified Gram-Schmidt 正交化 + z-score），
问题在于**输入语义**（私域经书的选取）与**输出语义**（"神圣坐标"的命名）
属于本体论诠释，不在算法本身。因此本审计将 L3 标注为"诠释"而非否定其
数学正确性。

### 3.3 已知限制 — 退化轴（P1-04 披露）

- **正交化退化**: 8 本经书的定义文本若语义高度重合，modified Gram-Schmidt
  正交化后某些轴会退化为近零向量。`get_orthogonality_report()` 报告
  Frobenius 距离，前端应在退化时标注。
- **零投影**: 大多数世俗文本的 `z_*` 接近 0（正交）——这不是失败，是测量。
  "零"意味着该文本在本体论上是空的。真正有动力学意义的是 `dz_*` / `d2z_*`。
- **经书选取主观性**: 更换经书集合会改变全部 `z_*` 值，且无法用数据驱动
  方式判定哪组经书"更正确"。

### 3.4 EDM 触发 L3 目标的边界

- EDM 可将 `z_*` / `dz_*` 作为预测目标，但其动力学预测的**可解释性远低于**
  对 `ate` / `adj_density` 等 L1 统计不变量的预测。
- 报告中 L3 目标的分析结果必须标注"(诠释)"，不得与 L1/L2 并列呈现。
- `edm_trigger.list_recommended_targets()` 已将 L3 目标单独分组并附 disclaimer。

---

## §4 EDM 触发阈值边界（P0-04）

### 4.1 分级 confidence_level

`edm_trigger.check_readiness()` 返回 `confidence_level` 字段，三级分类：

| 级别 | 行数条件 | 含义 | 投资决策许可 |
|------|----------|------|--------------|
| `insufficient` | `n < 15` | 数据不足，无法触发 EDM | 禁止 |
| `exploratory` | `15 ≤ n < 30` | 探索性 — 小样本下 EDM 动力学预测不稳定，可能产生伪相变信号 | 仅供探索，不得用于决策 |
| `formal` | `n ≥ 30` | 正式 — 可用于报告 | 许可，但仍受 IAAFT/BH 边界约束 |

### 4.2 阈值对齐依据

- `EDM_MIN_ROWS_FOR_ANALYSIS = 15`（config.py）— 触发下限。
- `EDM_FORMAL_THRESHOLD = 30`（edm_trigger.py）— 正式分析下限。
- EDM-TAKENS 自身测试明示 **32 样本仍不足以可靠估计 Lyapunov 时间**，
  故 15-30 行区间显式标注为"探索性"，避免投资者将小样本相变信号误读为
  正式结论。

### 4.3 EDM-TAKENS 统计保证边界（下游契约）

即便 `confidence_level=formal`，EDM-TAKENS 的统计保证仍受以下约束：
- **IAAFT 置换**: 非线性显著性需通过 IAAFT null 分布检验。
- **BH 多重检验校正**: 跨目标 ρ 显著性需 Benjamini-Hochberg 校正。
- **Takens 嵌入定理**: 要求系统具备确定性动力学结构；纯随机序列的
  ρ 显著性无意义。

trace-to-edm 仅负责触发与转译，统计保证由 EDM-TAKENS 流水线承担。
报告生成时必须保留 EDM-TAKENS 返回的 `p_value` / `iaaft_significant`
等字段，不得仅凭 ρ 值下结论。

---

## §5 程序化契约（供 portable_verify / 前端 / 报告读取）

### 5.1 方法学常量（已实装）

| 模块 | 常量 | 值 | 用途 |
|------|------|----|------|
| `layer3_sacred` | `METHODOLOGY_TAG` | `"interpretive_zero_shot"` | L3 诠释属性标识 |
| `layer3_sacred` | `METHODOLOGY_DISCLAIMER` | （中文长字符串） | L3 disclaimer 文本 |
| `edm_trigger` | `EDM_FORMAL_THRESHOLD` | `30` | 正式分析行数下限 |
| `edm_trigger` | `check_readiness()` → `confidence_level` | `insufficient`/`exploratory`/`formal` | 分级置信度 |
| `edm_trigger` | `check_readiness()` → `confidence_disclaimer` | （中文长字符串） | 分级 disclaimer |
| `csv_builder` | `COLUMN_COUNT` | `88` | 列总数契约（Meta 6 + L1 30 + L2 4 + L3 48） |

### 5.2 前端披露契约（P1-04/05 + app.js）

`/api/status` 必须返回：
- `trajectory.confidence_level` — 当前置信度级别
- `trajectory.confidence_disclaimer` — 分级 disclaimer 文本
- `trajectory.edm_targets[].interpretive` — L3 目标置 `true`，L1/L2 置 `false`
- `trajectory.edm_targets[].methodology_tag` — 目标的方法学标签

前端 `app.js` 必须：
- EDM 目标下拉中 L3 选项标注"(诠释)"前缀；
- 小样本（`exploratory`）时显示警告条幅；
- L3 列在轨迹表格中以不同色块标注诠释属性。

### 5.3 审计项（portable_verify.py 扩展）

`portable_verify.py` 新增三项审计：
1. `ALGORITHM_AUDIT.md` 存在性；
2. `layer3_sacred.METHODOLOGY_TAG` / `METHODOLOGY_DISCLAIMER` 可导入；
3. `csv_builder.COLUMN_COUNT` 与 `_EXPECTED_COLUMN_COUNT` 一致（=88）。

---

## §6 ROUND48 三层算法数学验证（2026-08-04）

> 本章节记录 ROUND48 对 trace-to-edm 三层算法的数学正确性验证结果。
> 验证方法：数学家+算法工程师+架构师三视角并行审计，逐函数检查数学实现。

### 6.1 Layer 1 验证结果

| 函数 | 数学实现 | 验证状态 |
|------|---------|---------|
| `_deep_get` | 嵌套字典点号路径取值，处理 None/非 dict/数组越界 | ✓ 鲁棒 |
| `_safe_percent` | 值域守卫 [0,100]，小数比例自动转百分比 | ✓ 正确（启发式） |
| `_safe_float` | 百分比字符串→float 转换 | ✓ 正确 |
| `consensus_score` | `1 - std/max_std`，`max_std=√(2/9)≈0.471` | ✓ 数学正确 |
| `consensus_direction` | ATE 符号 + CCM verdict + causallearn 共识 | ✓ 保守策略正确 |

**consensus_score 数学验证**:
- 3 个 [0,1] 值的理论最大标准差：当 values={0,0,1} 时，mean=1/3，var=2/9，std=√(2/9)≈0.471
- 归一化：`consensus = 1 - std_v / max_std`，值域 [0,1]
- {x,x,x} → std=0 → consensus=1（完全一致）✓
- {0,0,1} → std=0.471 → consensus=0（完全背离）✓

**consensus_direction 保守策略说明**:
- CCM verdict 的 forward/reverse 表示因果方向（X→Y vs Y→X）
- ATE 符号表示因果效应正负（X增加→Y增加/减少）
- 两者语义维度正交，不应直接比较
- 代码中的 `pass` 是有意保守策略，非缺陷

### 6.2 Layer 2 验证结果

| 函数 | 数学实现 | 验证状态 |
|------|---------|---------|
| `project` | PCA 投影：`z_pca_i = (x - mean) · components[i]` | ✓ 正确（含中心化） |
| `secular_entropy` | z²能量→概率→Shannon熵→归一化 | ✓ 数学正确 |
| `_refit_pca` | sklearn PCA 拟合，n_components=min(3,n,d) | ✓ 正确 |
| `_get_active_mean` | 优先项目PCA，回退背景PCA | ✓ 正确 |

**PCA 投影中心化验证** (Q9 P1-17 修复):
- 原实现：`z_pca_i = np.dot(embedding, components[i])`（未中心化）
- 修复后：`centered = embedding - mean; z_pca_i = np.dot(centered, components[i])`
- 数学正确性：PCA 投影必须减去训练时均值，否则 z_pca 包含常数偏移 mean·components[i] ✓

**世俗熵验证**:
- 能量定义：`energy_i = z_pca_i²`（等价于各主轴方差贡献）✓
- 概率归一化：`prob_i = energy_i / total_energy` ✓
- Shannon 熵：`entropy = -Σ prob_i · log(prob_i)` ✓
- 归一化：`secular_entropy = entropy / log(n_axes)`，值域 [0,1] ✓

### 6.3 Layer 3 验证结果

| 函数 | 数学实现 | 验证状态 |
|------|---------|---------|
| `_project_with_vector` | 余弦相似度：`sim = w·h_x`（均已 L2 归一化） | ✓ 正确 |
| `encode_text` | SVD 聚合：第一右奇异向量 > mean-pooling | ✓ 正确 |
| `_gram_schmidt` | 经典 GS 正交化 | ✓ 正确 |
| `_modified_gram_schmidt` | 修正 GS 正交化 | ✓ 正确 |
| `project_with_orthogonalization` | `new_coords = Q.T @ h_x` | ✓ 正确 |
| `ZScoreNormalizer` | `(z - μ) / (σ + ε)`，滚动窗口 W=20 | ✓ 正确 |
| `compute_axis_weights` | per-axis off-diagonal 自适应降权 | ✓ 正确 |

**余弦相似度验证**:
- 两个 L2 归一化向量的点积 = 余弦相似度 ✓
- 值域 [-1, 1]，0 表示完全正交 ✓

**SVD 聚合验证**:
- 多 chunk 嵌入矩阵 M [n_chunks, hidden_size]
- SVD: M = U Σ V^T
- 第一右奇异向量 V^T[0] 是数据最大方差方向 ✓
- 比 mean-pooling 更优：找到最佳 1 维表示 ✓

**Gram-Schmidt 正交化验证**:
- 经典 GS: `Q[:,i] -= (Q[:,j]·Q[:,i]) * Q[:,j]` 然后 `Q[:,i] /= ||Q[:,i]||` ✓
- 修正 GS: 先归一化 `Q[:,i]`，再从后续列减去投影 ✓
- 正交化后重投影: `new_coords = Q.T @ h_x`（Q 列张成与 W 相同子空间但彼此正交）✓

**Z-Score 归一化验证**:
- 公式: `z_score = (z - μ_rolling) / (σ_rolling + ε)` ✓
- 窗口 W=20，per-axis 独立 ✓
- 样本不足（<5）返回 0.0（中性）✓
- ddof=0（总体标准差），滚动窗口下无偏性不必要 ✓

### 6.4 csv_builder.py 88 列契约验证

| 列组 | 列数 | 来源 |
|------|------|------|
| Meta | 3 | time_step, text_hash, source_label |
| 诊断标记 | 3 | trace_status, trace_error, trace_mode |
| Layer 1 | 30 | config.LAYER1_COLUMNS 动态构建 |
| Layer 2 | 4 | z_pca_1/2/3, secular_entropy |
| Layer 3 绝对投影 | 8 | f"z_{short}" for short in SACRED_BOOKS |
| Layer 3 一阶差分 | 8 | f"dz_{short}" |
| Layer 3 二阶差分 | 8 | f"d2z_{short}" |
| z-score 归一化 | 24 | z/dz/d2z × 8 轴 |
| **总计** | **88** | ✓ 契约完整 |

### 6.5 审计结论

**三层算法数学实现全部正确，未发现需要修复的数学错误。**

- Layer 1: consensus_score 归一化数学正确，consensus_direction 保守策略合理
- Layer 2: PCA 投影中心化正确，世俗熵计算正确
- Layer 3: 余弦相似度、SVD 聚合、Gram-Schmidt 正交化、Z-Score 归一化全部正确
- csv_builder: 88 列契约完整，列顺序动态构建，列错位检测守卫到位

---

## §7 修订记录

| 轮次 | 项 | 摘要 |
|------|----|------|
| ROUND28 | P0-01 | L3 诠释属性声明（layer3_sacred.py disclaimer + 常量） |
| ROUND28 | P0-02 | 本文档创建 |
| ROUND28 | P0-03 | README 列数契约修正（54→88, L1 23→30） |
| ROUND28 | P0-04 | EDM 触发阈值分级（exploratory / formal） |
| ROUND28 | P1-04/05 | L3 退化轴 + 小样本 PCA 在前端/状态 API 披露 |
| ROUND28 | P2-03 | csv_builder 列总数断言守卫 |
| ROUND28 | P2-05 | consensus_score 哨兵值 -1.0 |
| ROUND28 | P2-06 | bridge L2/L3 失败标记 PARTIAL |
| ROUND48 | §6 | 三层算法数学验证：L1 consensus_score归一化、L2 PCA中心化、L3 Gram-Schmidt正交化全部正确 |
