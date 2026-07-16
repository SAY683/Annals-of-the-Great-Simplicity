# Fourteen Pitfall Avoidance Rules for Nonlinear Dynamics Analysis

These rules codify failure patterns discovered through decades of applied
nonlinear dynamics research. Each rule is grounded in peer-reviewed
literature; together they form a defense-in-depth firewall that catches
errors at every pipeline stage — from configuration through interpretation.

## Canonical Reference

Complete numbered bibliography (39 papers indexed by rule) is maintained in
`references/fourteen_rules_bibliography.md`. Every paper cited below has a
[B##] tag linking to that catalog.


---

# 规则体系总纲：权重与分流设计

十四项规则不是在任何场景下都全部激活。每条规则标注以下属性，供
Router 和 Auditor 在运行时按数据画像进行**选择性激活**——避免 AI Skill
上下文溢出，同时确保关键关卡永不缺席。

## 规则的三类性质

| 类别 | 标记 | 含义 | 处置哲学 |
|------|------|------|---------|
| **关卡 (Gate)** | `[G]` | 前置屏障——计算前必须通过。不过则阻断或自动修正。 | FAIL 阻断，AUTO-FIX 自动修正 |
| **诊断 (Diagnostic)** | `[D]` | 旁路诊断——随计算并行运行，不阻断但累积证据。 | WARN 聚集，交叉验证 |
| **解释 (Interpretation)** | `[I]` | 叙述卫生——不阻止计算，但强制覆盖输出语言。 | Advisory 追加到报告 |

## 强度权重

| 权重 | 含义 | 触发条件 | 典型处置 |
|------|------|---------|---------|
| ★★★★ | **强制关卡** — 规则前提总是可检验；满足条件时不得跳过，不满足时按降级逻辑处置 | 规则涉及的物理/数值前提独立于数据量 | FAIL（若违规）或 AUTO-FIX；小样本降权 |
| ★★★ | **条件关卡** — 数据满足前置条件时强制，否则降级为 SKIP | 规则有 `require:` 子句 | 满足条件→FAIL/WARN；不满足→SKIP |
| ★★ | **诊断增强** — 始终运行但仅 WARN，不阻断 | 规则的输出是诊断信号而非真值判断 | WARN，结果写入报告中 |
| ★ | **解释追加** — 输出语言层面的强制标注 | 无需额外计算 | Advisory 追加到输出 |

## 数值溯源约定

本文中所有阈值和参数均标注来源类别，确保每个数字的出处可追溯：

| 标记 | 含义 | 验证方式 |
|------|------|---------|
| `[C]` | **规范值（Canonical）** — 直接取自原论文，或为领域内公认标准（如 p<0.05） | 可在标注的 [B##] 论文中找到原文依据 |
| `[D]` | **推导值（Derived）** — 原理和概念框架来自论文，具体数值经过针对本 Skill 数据场景的工程校准 | 论文提供方法论，数值经 N∈[30,500] 的数值实验校准 |
| `[E]` | **工程启发值（Engineering）** — 无法从单篇论文导出，来自数值实验、反复失败经验和工程判断的累积 | 在 `docs/thresholds_and_heuristics.md` 中有变更记录；值被标记为"启发式" |

一项规则可能混合三类值——例如 S2 的 CCM 双向强制是 `[C]`（Sugihara 2012 原文要求），但 total_rise > 0.05 的具体阈值是 `[D]`（Sugihara 用目视判收敛，我们为自动化管线做了操作化）。

## 激活矩阵：按数据画像分流

Router 根据数据特征决定每条规则的激活级别。下表是分流逻辑的总览。
列 N<50 表示 20 ≤ N < 50，N<100 表示 50 ≤ N < 100（逐级递进，互不重叠）。

| 规则 | 性质 | 权重 | 触发条件 | N<20 | N<50 | N<100 | N≥100 | 二元目标 | 多变量(K≥3) |
|------|------|------|---------|------|------|-------|-------|---------|------------|
| S1 Lyapunov | [D] | ★★★ | N≥100 或替代下限可用 | SKIP | ↓★(surrogate) | ★★★ | ★★★ | — | — |
| S2 CCM Mirror | [G] | ★★★ | CCM 被执行时 | — | ★★★ | ★★★ | ★★★ | ★★★ | ★★★ |
| S3 Hankel | [G] | ★★★★ | q 被指定时 | ★★★★ | ★★★★ | ★★★★ | ★★★★ | — | — |
| S4 Multiview | [D] | ★★★ | N<100 且 K≥2 | SKIP | ★★★ | ★★★ | ★ | ★★★ | ★★★ |
| S5 SVD Residual | [D] | ★★★ | N≥50/window | SKIP | SKIP | ★★★ | ★★★ | — | — |
| S6 Cross-Val | [D] | ★★★ | EDM+HAVOK 均运行时 | ★ | ★★ | ★★★ | ★★★ | ★★★ | — |
| S7 Arrow Trap | [I] | ★★★ | CCM 被执行时 | ★★★ | ★★★ | ★★★ | ★★★ | ★★★ | ★★★ |
| S8 Stationarity | [G] | ★★★★ | 始终（ADF/KPSS 无需大样本） | ★★(低功效) | ★★★ | ★★★★ | ★★★★ | — | — |
| S9 Genericity | [G] | ★★★ | 始终（仅需检查数据类型） | ★★★ | ★★★ | ★★★ | ★★★ | ★★★ | — |
| S10 Seasonality | [D] | ★★ | N≥20 且 CCM 运行 | SKIP | ★★ | ★★ | ★★ | — | — |
| S11 Common Driver | [I] | ★★ | CCM 被执行时（多对显著时升级） | — | ★★ | ★★ | ★★ | ★★ | ★★ |
| S12 Decay Profile | [D] | ★ | N≥30 | — | SKIP | ★ | ★ | — | — |
| S13 Multi-Comp | [I] | ★★ | CCM 对 > 1（≥5 对时 WARN 升级） | — | ★★ | ★★ | ★★ | ★★ | ★★ |
| S14 Sampling | [D] | ★ | HAVOK spikes ≥ 3 | — | ★ | ★ | ★ | — | — |

> **符号说明**: ★★★★ 强制关卡 → ★★★ 条件关卡 → ★★ 诊断增强 → ★ 解释追加。
> "↓★(surrogate)" 表示权重降级但通过替代方法执行。
> "—" 表示该数据特征不改变此规则的默认激活级别。

## 按分析目标分流

Router 的 `AnalysisGoal` 决定哪些规则群组被激活：

| 分析目标 | 必经规则（违反则阻断/降级） | 强制诊断（随计算运行，WARN 聚集） | 解释追加（输出语言覆盖） |
|---------|--------------------------|-------------------------------|-------------------------|
| `explore` | S3, S8, S9 | S1†, S4†, S6, S10†, S14† | S7, S11, S13† |
| `predict` | S1, S3, S8 | S5, S6, S12 | — |
| `detect_nl` | S3, S8, S9 | S4†, S6, S10†, S12 | — |
| `causal` | S2, S3, S8 | S6, S10 | S7, S11, S13 |
| `phase` | S3, S5 | S1†, S14 | — |

> † 标记：仅在数据满足前置条件时激活。

---

# 十四项规则

每条规则按统一模版组织：**概述 → 科学依据 → 禁忌规则 → 实施 → 防火墙处置 → 前置条件**。


## Secret 1: Lyapunov Horizon — 混沌可预测性的物理边界

**性质**: [D] 诊断　**权重**: ★★★（条件关卡：N≥100 时强制，否则 surrogate 替代）　**阶段**: Layer 2 (Auditor) / Layer 3 (Post-computation)

### 概述

每一个混沌系统对初始条件都有指数级的敏感依赖。发散率由最大李雅普诺夫指数
λ_max 量化。系统的根本可预测性上限是李雅普诺夫时间 τ_L = 1/λ_max。

**违规后果**：预测超过 5·τ_L 的结果是**物理上无意义的**——任何声称在此
范围外能预测混沌系统的算法都是在产生伪装成预测的噪声。

**当前实现状态**: Auditor 已实现；对 N<100 用 surrogate 替代下限。

### 科学依据

- Rosenstein, Collins & De Luca (1993). *Physica D*, 65(1-2), 117-134. [B12]
- Sugihara & May (1990). *Nature*, 344, 734-741. [B06] — 预测技能衰减区分混沌与噪声
- Kantz & Schreiber (2004), Ch.6. [B15]

### 禁忌规则

| 预测范围 | 诊断 |
|---------|------|
| ≤ 1·τ_L | 确定性可靠 |
| 1·τ_L ∼ 3·τ_L | 误差指数增长，结果需带不确定性区间 |
| 3·τ_L ∼ 5·τ_L | 接近物理极限，可信度快速下降 |
| > 5·τ_L | **科学上无意义** |

**核心戒律**：若 τ_L 对应 3 天，不要预测第 10 天。

### 实施

**模块**: `src/edm_auditor.py:audit_lyapunov_horizon()` —
前执行关卡。`src/final_interpretation.py:estimate_lyapunov_robust()` —
Rosenstein 算法 + R² 质量检查。

**算法**（Rosenstein 1993）:
1. 延迟嵌入重构相空间（使用最优 τ, E）
2. 对每个参考点，找时间间隔 > 平均周期的最近邻
3. 追踪近邻发散的对数距离 vs 时间
4. λ_max = 线性区的斜率（前 n_expand/2 步）

**替代下限**（N < 100 时）:
当 Rosenstein 估计不可靠（N < 100 或 fit_r² < 0.5），使用 IAAFT surrogate
数据分布的 Lyapunov 上限作为 τ_L 的**保守下限**。这比放弃估计要好。

**阈值**（来源类别: `[C]`=规范值 `[D]`=推导值 `[E]`=工程启发值，参见总纲"数值溯源约定"）:

| 参数 | 值 | 依据 | 来源 |
|------|---|------|------|
| λ_max 估计 R² ≥ 0.5 | 0.5 | 低于此值 → 估计不可靠，标记 UNRELIABLE | `[E]` Rosenstein 原文未指定此阈值——线性拟合基本质量控制 |
| n_expand | min(20, N//3) | 发散追踪步数 | `[E]` 数据量自适应：短序列少追步，长序列封顶防饱和 |
| 预测 ≤ τ_L | PASS | 安全区间 | `[C]` Kantz & Schreiber (2004) Ch.6 — τ_L 为 e-folding 时间 |
| 预测 ∈ (τ_L, 3·τ_L] | WARN | 误差 ~e³≈20× | `[D]` 3·τ_L 是领域惯例中的"实用可预测性"中间界 |
| 预测 ∈ (3·τ_L, 5·τ_L] | WARN | 误差 ~e⁵≈148× | `[D]` 5·τ_L 是公认的"物理可预测上限"——领域约定，非定理 |
| 预测 > 5·τ_L | FAIL | **物理上无意义** | `[C]→[D]` 5·τ_L 边界来自混沌物理学共识；文件设三级阈值以替代单一切断 |

### 防火墙处置

- λ_max 不可用（N<100 且 surrogate 失败）→ **SKIP**，不瞎猜
- λ_max ≤ 0（非混沌系统）→ **SKIP**，规则不适用
- 预测 > 5·τ_L → **FAIL**，阻断执行
- 预测 ∈ (1·τ_L, 5·τ_L] → **WARN**

### 前置条件

- **需要**: N ≥ 100（Rosenstein 完整估计）或 N ≥ 30（surrogate 替代下限）
- **不适用**: 非混沌系统（λ_max ≤ 0）
- **依赖**: S3（Hankel 比例）须先通过——否则相空间重建本身不可靠


## Secret 2: CCM Victim Mirror Principle — 因果方向的正确测试

**性质**: [G] 关卡　**权重**: ★★★（CCM 执行时强制）　**阶段**: Layer 2 (Auditor) + Layer 3 (Post-computation feedback)

### 概述

CCM（收敛交叉映射）检测因果关系时遵循**受害者镜像原理**：
若 X 驱动 Y（X → Y），则 Y 的影子流形 M_Y 编码了 X 的动力学信息，
因此 M_Y 可以交叉映射回 X。**反向不一定成立。**

90% 的 CCM 初学者把方向弄反——试图用 M_X 预测 Y。

**违规后果**：因果方向被颠倒。"降雨影响兔子"被报告为"兔子影响降雨"。

**当前实现状态**: 完全实现。`ccm_causality.py` 是唯一真相源，
`final_interpretation.py` 和 `enhanced_cross_validate.py` 均为薄包装。

**Round 9 修正**: 收敛检查（total_rise + Spearman ρ）现已真正强制执行——
此前 `pipeline.py` 的审计反馈未填充收敛指标，导致收敛保护被静默绕过。

### 科学依据

- Sugihara et al. (2012). *Science*, 338, 496-500. [B08] — CCM 原始论文
- Cobey & Baskerville (2016). *Nature Comms*, 7, 12891. [B21] — 收敛单调性检查

### 禁忌规则

> **在 pyEDM 中：CCM(columns=Y, target=X) 测试 X→Y。**
> 因为 columns 构建的是流形，target 是被预测的变量。
> M_Y（果的流形）预测 X（因）→ 测试 X 是否驱动 Y。

**强制要求**：
1. 每次 CCM 测试必须运行**双向**（X→Y 和 Y→X）
2. 仅当 ρ **随 library size 单调递增**时（total_rise > 0.05 且 Spearman ρ > 0.7）才认定收敛
3. 收敛方向 = 因果方向
4. 单方向高 ρ 但不收敛 → 可能是伪因果（spurious）

### 实施

**模块**: `src/ccm_causality.py:ccm_causality_test()` — 唯一真相源。
`src/edm_auditor.py:audit_ccm_direction()` — 防火墙关卡。

**收敛判断阈值**（参见 `docs/thresholds_and_heuristics.md`；来源: `[C]`规范 `[D]`推导 `[E]`工程）:

| 指标 | 阈值 | 含义 | 来源 |
|------|------|------|------|
| total_rise > 0.05 | 0.05 | ρ 跨 library size 的绝对增长——低于此值，信号无法与 bootstrap 噪声区分 | `[D]` Sugihara (2012) 用目视判收敛；0.05 来自 N∈[30,100] 典型序列的 bootstrap 噪声估计 |
| spearman_rho > 0.7 | 0.7 | 单调性——低于 0.7，Cobey-Baskerville (2016) 标记为疑似假阳性 | `[D]` 0.7 为"强单调关联"的常规约定；原理来自 [B21] 的收敛单调性分析 |
| spearman_p < 0.1 | 0.1 | 宽松的 p（小样本统计效力低）——与 ρ 阈值联合使用 | `[D]` 标准 0.05 在 CCM 小样本下效力过低，0.1 是务实的权衡 |
| final_rho > 0.2 | 0.2 | 最低交叉映射技能——低于此值视为"弱/不足" | `[D]` Sugihara 实证：ρ<0.2 通常与随机无法区分 |
| bidirectional_delta | 0.05 | 双向 ρ 差值 < 0.05 判定为双向因果 | `[E]` 与 total_rise 最低阈值一致，保持数值体系自洽 |

### 防火墙处置

- CCM 数据不可用 → **SKIP**
- 双向均不收敛 → **WARN**："无可检测的因果连接"
- 单向高 ρ 但不收敛 → **WARN**："ρ 高但不收敛——可能假阳性"
- 单向高 ρ 且收敛 → **PASS**

### 前置条件

- **需要**: N ≥ 30（CCM 库大小收敛的最低要求）
- **依赖**: S7（箭头陷阱）与此规则合并——两者是同一逻辑的两个方面
- **依赖**: S10（周期性混淆）——若 S10 同时触发，CCM 收敛可能是周期性驱动所致


## Secret 3: Hankel Matrix Golden Aspect Ratio — SVD 数值稳定性

**性质**: [G] 关卡　**权重**: ★★★★（强制——q 被指定时必须通过，不受数据画像影响）　**阶段**: Layer 2 (Auditor)

### 概述

HAVOK 和 DMD 方法构建 Hankel 矩阵 H（p × q，p = n - q + 1，q = 嵌入维度）。
SVD 在 p ≫ q（瘦高矩阵）时产生良态奇异向量。当 p ≈ q 或 p < q 时，
左右奇异向量数值耦合（"纵横比诅咒"），产生虚假的刚性特征值，物理模态
与数值伪影混合。

**违规后果**：Koopman 特征值谱被数值伪影污染，强制项分析无物理意义，
回归 R² 虚高（> 0.999）但预测完全无效。

**当前实现状态**: 完全实现。`classify_hankel_ratio()` 是唯一真相源
（被 `edm_auditor.py` 和 `enhanced_cross_validate.py` 共享）。

### 科学依据

- Brunton et al. (2017). *Nature Comms*, 8, 19. [B10]
- Gavish & Donoho (2014). *IEEE Trans. Info. Theory*, 60(8), 5040-5053. [B11]
- 数值线性代数工程经验：p/q ≥ 10 是保守但安全的工程准则（非数学定理）

### 禁忌规则

> **p/q ≥ 10** — Hankel 矩阵必须足够扁平。

**当数据量不足时：牺牲 q 以维持 p/q。**
一个维度较小但 SVD 良态的嵌入，远优于维度较大但数值崩溃的嵌入。

### 实施

**模块**: `src/edm_auditor.py:classify_hankel_ratio()` — 共享函数。
`src/edm_auditor.py:audit_hankel_aspect_ratio()` — 防火墙。
`src/enhanced_cross_validate.py:check_hankel_aspect_ratio()` — 诊断层。

**四级判定**（`classify_hankel_ratio(n, q)`；全部为 `[E]` 工程启发——p/q≥10 非数学定理，来自 SVD 数值线性代数经验）:

| 级别 | 条件 | 处置 | 说明 | 来源 |
|------|------|------|------|------|
| GOOD | p/q ≥ 10 | PASS | SVD 数值稳定 | `[E]` 保守安全边界；Gavish-Donoho (2014) [B11] 给截断阈值非纵横比 |
| MARGINAL | 5 ≤ p/q < 10 | WARN | 干净数据可用，有噪声时可能刚度 | `[E]` 中间缓冲带 |
| DEGRADED | 3 ≤ p/q < 5 | FAIL | A 矩阵特征值出现虚假刚性 | `[E]` 经验劣化起点：32 场游戏 E=6 (p/q=4.5) 已观察到 EDM-HAVOK 不一致 |
| BROKEN | p/q < 3 | FAIL | SVD 数值崩溃；结果作废 | `[E]` 物理底线：数值秩开始与代数秩分离 |

**自动修正**: q_safe = max(2, (n+1)//11) 确保 p/q ≥ 10。

**工作示例**:

| N | q | p | p/q | 判定 |
|---|----|----|-----|------|
| 500 | 100 | 401 | 4.0 | DEGRADED |
| 500 | 45 | 456 | 10.1 | GOOD |
| 200 | 18 | 183 | 10.2 | GOOD |
| 32 | 10 | 23 | 2.3 | BROKEN |
| 32 | 3 | 30 | 10.0 | GOOD |

### 防火墙处置

- p/q ≥ 10 → **PASS**
- 5 ≤ p/q < 10 → **WARN**：建议降低 q
- 3 ≤ p/q < 5 → **FAIL**：A 矩阵特征值劣化
- p/q < 3 → **FAIL 阻断**：SVD 数值崩溃
- AUTO-FIX 模式下：自动将 q 降至 q_safe

### 前置条件

- **始终激活**（只要有 q 和 n 就可计算 p/q）
- **不依赖**: 任何其他规则——这是最底层的数值保障


## Secret 4: Multiview Embedding — 短数据免于饥饿

**性质**: [D] 诊断　**权重**: ★★★（条件关卡：N<100 且 K≥2 时强制推荐）　**阶段**: Layer 2 (Advisory) + Execution

### 概述

当 N < 100 时，单变量延迟嵌入将宝贵数据浪费为"延迟填充"。对于 N=45、
E=5，仅剩 41 个嵌入向量（N-E+1）——且随着 E 增大，向量数进一步衰减。
Multiview 用**空间多样性**（多个观测变量）替代**时间延迟**，
用 K-choose-E 候选模型选出最佳。

**违规后果**（未用 Multiview）：短数据上稀疏吸引子导致 Simplex 预测技能
虚低或虚高，CCM 收敛无法可靠评估。

**当前实现状态**: ⚠️ PARTIAL。pyEDM.Multiview 在 Windows/Python 3.13
下有多进程兼容性问题，但 numpy SVD 空间嵌入回退已通过 `_edm_bridge.py` 可达。

### 科学依据

- Sugihara, Deyle & Ye (2016). *Science*, 353(6302), 922-925. [B09]
- Takens (1981). LNM 898, 366-381. [B01] — 延迟嵌入理论上等价于空间嵌入

### 禁忌规则

> **N < 100 且 K ≥ 2：延迟嵌入在浪费你本已稀少的数据。**
> 空间嵌入（Multiview）是更优选择——不浪费任何数据点为延迟填充。

```
V_delay(t)     = [X(t), X(t-1), X(t-2), X(t-3)]     ← 3 个延迟，3 个数据点损失
V_multiview(t) = [X(t), Y(t), Z(t), X(t-1)]          ← 3 个变量 + 1 个延迟，0 损失
```

### 实施

**模块**: `src/_edm_bridge.py:Multiview()` — 先尝试 pyEDM，失败则 numpy SVD 回退。
`src/multiview_svd_monitor.py:run_multiview_analysis()` — 带监视的封装。
`src/edm_auditor.py:audit_multiview()` — 条件触发。

**触发条件**:

| 条件 | 处置 |
|------|------|
| N < 100 且 K ≥ 2 | **WARN + 强烈推荐** Multiview |
| N < 50 且 K ≥ 3 | **CRITICAL**：延迟嵌入将饿死，Multiview 是唯一可行方案 |
| N ≥ 100 | PASS — 延迟嵌入可行，但 Multiview 仍值得对比 |
| K < 2 | SKIP — 单变量无法使用 Multiview |

### 防火墙处置

- 始终为 Advisory——不阻断执行
- 当 S9（Genericity）同时触发时，Multiview 从推荐升级为**必须**（二元目标的泛型性失败需要连续协变量补偿）

### 前置条件

- **需要**: K ≥ 2
- **联动**: S9（Genericity）触发时，Multiview 的必要性显著提升


## Secret 5: SVD Reconstruction Residual — 吸引子变形警报

**性质**: [D] 诊断　**权重**: ★★★（条件关卡：N ≥ 50/window 时强制）　**阶段**: Layer 2 (Auditor) + Execution (在线监视)

### 概述

监测归一化截断 SVD 重构残差：
```
Residual = ||H - U_r · diag(Σ_r) · V_r^T||_F / ||H||_F
```

当系统经历机制转换（吸引子溶解或变形），原 SVD 基 (U_r, V_r) 无法张成
新动力学——残差跳变。这是一个**在线、实时的吸引子健康指标**。

**违规后果**（未监测）：机制转换后的所有 HAVOK 诊断（特征值、强制项、
稳定性分类）都基于一个不再有效的基底——等价于用旧地图导航新地形。

**当前实现状态**: 完全实现。`SVDResidualMonitor` 有持续警报逻辑
（连续 3 窗口确认防误报）和自适应记忆断裂。

### 科学依据

- Brunton et al. (2017). *Nature Comms*, 8, 19. [B10]
- Gavish & Donoho (2014). *IEEE Trans. Info. Theory*, 60(8). [B11]

### 禁忌规则

> **残差 > 2.5× 基线且持续 3 个连续窗口 → 触发警报。**

警报后的动作：丢弃 Hankel 数据中最旧的 50%，在剩余窗口上重新拟合 SVD。

### 实施

**模块**: `src/multiview_svd_monitor.py:SVDResidualMonitor` — 在线监视。
`src/edm_auditor.py:audit_svd_residual()` — 单次审计。

**检测参数**（全部 `[E]` 工程启发——Brunton (2017) [B10] 贡献 HAVOK 方法，未指定监测阈值）:

| 参数 | 值 | 理由 | 来源 |
|------|---|------|------|
| 检测阈值 | 2.5× 基线 | 区分机制转换与噪声；2.0× 误报过多，3.0× 在实测中延迟 4 窗口 | `[E]` 在模拟吸引子变形上校准 |
| 持续窗口 | 3 个连续 | 防止单点异常触发误报 | `[E]` 标准持久性检查：平衡灵敏度与特异性 |
| 自适应遗忘 | 丢弃 50% | 最简单的有效策略 | `[E]` 启发式——生产建议见下行 |
| 生产建议（N≥500） | Bai-Perron 检验替代 50% 丢弃 | 文档化的 TODO | `[C]→[E]` Bai & Perron (1998) 结构断点检验为规范方法；本 Skill 的 50% 是简化版 |

**分层设计**（有意为之，非不一致）:
- Auditor（`audit_svd_residual`）: 单次 2.5× 检查 → FAIL（更严格的预检关卡）
- Monitor（`SVDResidualMonitor`）: 3 次持续窗口 → 触发遗忘（更稳定的在线警报）

### 防火墙处置

- 残差比 < 1.5× 基线 → **PASS**
- 残差比 ∈ [1.5×, 2.5×) 基线 → **WARN**：密切监视
- 残差比 ≥ 2.5× 基线 → **FAIL**：触发自适应记忆断裂
- 无基线数据 → **SKIP**

### 前置条件

- **需要**: N ≥ 50/window（在窗口内有足够统计量建立基线）
- **依赖**: S3（Hankel 比例）必须先通过——否则基线 SVD 本身就是有问题的
- **联动**: S8（Stationarity）若触发，基线 SVD 可能不健康，建议滑动窗口 S5


## Secret 6: EDM-HAVOK Cross-Validation — 两种数学基础的互证

**性质**: [D] 诊断　**权重**: ★★★（条件：EDM 和 HAVOK 均运行时）　**阶段**: Layer 3 (Cross-Validation)

### 概述

EDM（Simplex/S-Map）和 HAVOK（Koopman 算子/SVD 分解）从**完全独立的
数学基础**逼近非线性检测。当两者一致时，诊断可信度显著提升。当两者
不一致时，至少有一个是错的——而这种不一致本身就是宝贵的诊断信号。

**违规后果**（未做交叉验证）：可能将 EDM 的过拟合或 HAVOK 的 Hankel
劣化误判为"非线性动力学证据"。

**当前实现状态**: 完全实现。`enhanced_cross_validate.py` 三项子检查，
`verify_algorithms.py` 五级 100 分评分体系。

### 科学依据

- Sugihara & May (1990) [B06], Sugihara (1994) [B07] — EDM 非线性检测
- Brunton et al. (2017) [B10] — HAVOK 非线性检测
- Theiler et al. (1992) [B35] — 替代数据检验作为交叉验证的第三维度

### 禁忌规则

> **EDM 告诉你 IF（θ>0 表示非线性存在）。**
> **HAVOK 告诉你 WHEN（强制尖峰表示相变发生）。**
> **仅当两者独立一致时，诊断方可采信。**

### 实施

**模块**: `src/enhanced_cross_validate.py:cross_validate_with_safeguards()` —
三项子检查。`src/verify_algorithms.py` — 100 分评分（五项各 20 分）。

**交叉验证矩阵**:

| EDM (S-Map θ) | HAVOK (kurtosis v_r) | 诊断 | 处置 |
|---------------|---------------------|------|------|
| θ > 0（非线性） | kurt > 1.5（重尾） | CONSISTENT — 强非线性 | PASS |
| θ > 0（非线性） | kurt ∈ [0.5, 1.5]（轻尾） | PARTIAL — 弱非线性 | WARN |
| θ > 0（非线性） | kurt < 0.5（近高斯/亚高斯） | DISCREPANCY | WARN: 检查 Hankel 比和数据量 |
| θ ≈ 0（线性） | kurt > 1.5（重尾） | DISCREPANCY | WARN: 可能的虚假峰度（离群值/非平稳性） |
| θ ≈ 0（线性） | kurt < 1.5（轻尾/高斯/亚高斯） | CONSISTENT — 近线性/随机 | PASS |

> **交叉验证矩阵数值溯源**:
> - `θ > 0` 的非线性判据: `[C]` 直接来自 **Sugihara (1994)** [B07] — S-Map 中 local weighting (θ>0) 优于 global linear (θ=0) 是非线性的操作性定义
> - `kurtosis > 1.5` 重尾阈值: `[D]` **Brunton et al. (2017)** [B10] 定性使用峰度表征强制项重尾性；1.5 是"显著偏离高斯"的常规统计约定（正态 excess kurtosis=0）
> - `kurtosis < 0.5` 近高斯/亚高斯: `[D]` 同上逻辑的下界——低于 0.5 无证据支持重尾动力学
> - `kurtosis ∈ [0.5, 1.5]` 轻尾缓冲区: `[E]` 灰色地带——可能弱非线性也可能是噪声，不单独做判定
> - `Δkurtosis < 0.3` (V/U 一致性): `[E]` V 基和 U 基数不同但动力学等价；差值过大提示基底选择伪影
> - 5% 噪声注入检验: `[E]` 小量噪声注入是检验过拟合的标准方法——5% 足够小以不破坏信号、足够大以暴露过拟合噪声结构

**额外检查维度**:
1. V 基 vs U 基一致性（Δkurtosis < 0.3）
2. IAAFT 替代数据检验（真实数据的 HAVOK 峰度是否显著高于 surrogate 分布）
3. 噪声注入检验（注入 5% 噪声后峰度应下降——确认不是过拟合噪声结构）

### 防火墙处置

- 双向一致 → **PASS**
- 单向不一致 → **WARN**（诊断信号——帮助定位问题在 EDM 侧还是 HAVOK 侧）

### 前置条件

- **需要**: EDM（Simplex + S-Map）和 HAVOK（SovereignHAVOK）均已运行
- **联动**: S3（Hankel）若触发 WARN/FAIL，HAVOK 侧的诊断权重应打折


## Secret 7: CCM Arrow Trap — 双向强制验证

**性质**: [I] 解释　**权重**: ★★★（CCM 执行时强制）　**阶段**: Layer 2 (Auditor) + Interpretation

### 概述

CCM 受害者镜像原则（Secret 2）是正确的。Arrow Trap 是其**实现层面的
强制保障**——确保自动化管线中的每次 CCM 调用都显式验证两个方向。

**违规后果**（仅测试单向）：可能将双向耦合误判为单向因果，或将无因果
关系误判为单向因果（因为未检查反向是否也"显著"）。

**当前实现状态**: 完全实现。已合并到 Secret 2 的 `ccm_causality_test()` 中。

### 科学依据

- Sugihara et al. (2012). *Science*, 338, 496-500. [B08]

### 禁忌规则

> **自动化管线中，每次 CCM 调用都必须显式验证双向：**

```
pyEDM.CCM(columns='Y', target='X')  — 测量 X 对 Y 的影响
收敛的 CCM(Y→X) + 非收敛的 CCM(X→Y) → X 驱动 Y
双向收敛 → 双向耦合或公共驱动
双向不收敛 → 无因果连接
```

### 实施

**模块**: `src/ccm_causality.py:ccm_causality_test()` — 唯一真相源（同时处理 S2 和 S7）。

**双向判定逻辑**:

| Forward (X→Y) | Reverse (Y→X) | 判定 |
|---------------|---------------|------|
| 收敛 + ρ高 | 不收敛 | `X --drives--> Y` |
| 不收敛 | 收敛 + ρ高 | `Y --drives--> X` |
| 收敛 + ρ高 | 收敛 + ρ高, |Δρ| < 0.05 | `bidirectional` |
| 收敛 + ρ高 | 收敛 + ρ高, |Δρ| ≥ 0.05 | `X dominant` 或 `Y dominant` |
| 不收敛 | 不收敛 | `no detectable link` |

### 防火墙处置

- 与 Secret 2 相同（两者使用同一 `audit_ccm_direction()` 关卡）
- 合并为一个审计条目，不做独立报告

### 前置条件

- **依赖**: S2（受害者镜像）——Arrow Trap 是其自动化实现，不引入新科学前提


## Secret 8: Stationarity Gate — 平稳性前置关卡

**性质**: [G] 关卡　**权重**: ★★★★（强制关卡——N≥50 时完全激活；N<50 检验效力递减但始终可执行）　**阶段**: Layer 2 (Auditor)

### 概述

Takens 嵌入定理假设动力学系统是**平稳的**——控制方程不随时间变化，
吸引子是不变集。若测量序列包含趋势（均值漂移）或方差异质性，延迟嵌入
重建的是**趋势的几何形状**，而非**动力学的几何形状**。

一个带线性趋势的纯随机游走在 EDM Simplex 中也能产生 ρ > 0.6——
不是因为动力学可预测，而是趋势惯性在支撑"预测技能"。

这是应用 EDM/HAVOK 中**最大类别的静默失败**：平稳性被数学假设为成立，
但标准的 pyEDM 工作流**从不检查它**。Secret 5（SVD 残差）检测的是
**在线**吸引子变形——但若数据从一开始就是非平稳的，基线本身就已损坏。

### 科学依据

- Kantz & Schreiber (2004), Ch.3 & 7. [B15] — 相空间重建的平稳性前提
- Schreiber (1997). *PRL*, 78(5), 843-846. [B16] — 交叉预测非平稳性检验
- Kennel (1997). *PRE*, 56(1), 316-321. [B17] — KS 检验比较数据前后半段的近邻距离分布
- Dickey & Fuller (1979). *JASA*, 74(366). [B18] — ADF 单位根检验
- Kwiatkowski et al. (1992). *J. Econometrics*, 54. [B19] — KPSS 平稳性检验（H₀=平稳，与 ADF 互补）

### 禁忌规则

> **绝不跳过平稳性前置筛查。** 若数据未通过——
> 1. 差分或去趋势（若趋势平稳）
> 2. 滑动窗口分析并显式标注非平稳性警告
> 3. 切换到不假设平稳性的方法族（贝叶斯状态空间模型）

### 实施

**模块**: `src/edm_auditor.py:audit_stationarity()` — 新建。

**ADF + KPSS 联合决策矩阵**:

| ADF (H₀: 有单位根) | KPSS (H₀: 平稳) | 判定 | 处置 |
|--------------------|-----------------|------|------|
| 拒绝 (p<0.05) | 未拒绝 (p>0.05) | ✅ 平稳 | PASS |
| 拒绝 (p<0.05) | 拒绝 (p<0.05) | ⚠️ 趋势平稳 | WARN: 去趋势后嵌入 |
| 未拒绝 | 拒绝 (p<0.05) | ❌ 差分平稳 | WARN: 差分序列，重新检验 |
| 未拒绝 | 未拒绝 | ❓ 效力不足 | WARN: N 太小无法判断；显式标注 |

> **平稳性检验数值溯源**:
> - `p < 0.05`: `[C]` Fisher 经典显著性水平 — ADF (Dickey-Fuller 1979 [B18]) 和 KPSS (Kwiatkowski et al. 1992 [B19]) 均采用此约定
> - **ADF+KPSS 联合矩阵结构**: `[C]` 计量经济学最佳实践 — KPSS 原文讨论了与 ADF 互补以区分四种平稳性状态
> - `N ≥ 20` 最低检验样本: `[D]` ADF/KPSS 临界值表在 N<20 时统计效力严重下降；20 为检验仍能提供有意义信号的最低线

**补充检查**:

| 检查 | 方法 | 阈值 | 处置 | 来源 |
|------|------|------|------|------|
| 方差异质性 | 滑动窗口方差比 max_σ²/min_σ² | > 3.0 | WARN | `[E]` 3× 方差变化为实质异方差性 |
| 趋势-信号比 | abs(线性趋势斜率) / σ_data | > 0.3 | WARN | `[E]` 斜率达标准差 30%/单位时间——趋势已主导延迟向量几何 |
| 交叉预测衰减 | Schreiber (1997): ρ_forward / ρ_self | < 0.7 | WARN | `[D]` Schreiber (1997) [B16] 贡献方法；0.7 为工程操作化——自预测是上界，低于 70% 意味前后段动力学不同 |

### 防火墙处置

- 仅作 Advisory（WARN）——不阻断。非平稳序列在滑动窗口分析中仍可能携带
  有用的动力学信息。但输出**必须**显式标注："数据非平稳——重建的吸引子
  可能不是不变集"。
- 若趋势平稳，`pipeline.py` 的自动修正可选择性做一阶差分并重新路由。

### 前置条件

- **需要**: N ≥ 20（ADF/KPSS 在更小的样本上效力严重不足，标记为 ❓）
- **联动**: S5（SVD 残差）——若 S8 触发 WARN，S5 的基线 SVD 可能不健康
- **联动**: S9（观测泛型性）——趋势平稳 + 二元目标 → 建议换方法族


## Secret 9: Observation Genericity Gate — 观测函数泛型性关卡

**性质**: [G] 关卡　**权重**: ★★★（条件关卡——仅需检查数据类型，始终可执行）　**阶段**: Layer 2 (Auditor)

### 概述

Takens 定理要求观测函数是"泛型的"（generic）——Whitney 嵌入必须是
单射（one-to-one）且浸入（C² 光滑、导数非退化）。某些测量函数类别
违背此数学前提：

| 违规类别 | 实际例子 | 对嵌入的影响 |
|---------|---------|------------|
| 多对一（非单射） | 二元胜负、序数等级 | 相空间塌缩为离散薄片；近邻关系虚假 |
| 饱和/截断 | 传感器满量程 | 人为的吸引子"墙壁"——轨迹反弹于测量天花板 |
| 粗量化 | 整数取整测量值 | 相空间中的虚假平台结构 |
| 对称折叠 | 绝对值、RMS、方差 | 相空间折叠，不同状态在测量中变得不可区分 |

二元目标（当前 Skill 已处理的特例）只是这类问题的**一个实例**，
并非全部。根本原因是同一数学前提的违反。

### 科学依据

- Takens (1981), §2. [B01] — 光滑性和泛型性条件
- Sauer, Yorke & Casdagli (1991). *J. Stat. Phys.*, 65(3), 579-616. [B03] — 将泛型性推广到分形吸引子
- Packard et al. (1980). *PRL*, 45(9), 712-716. [B02] — 最早的延迟嵌入论文已注意到传感器死区和饱和
- Letellier, Aguirre & Maquet (2005). *PRE*, 71(6), 066213. [B05] — 可观测性矩阵——量化测量函数失效区域

### 禁忌规则

> **在选择嵌入参数之前，检查测量函数是否可能非泛型。**
> 无效的测量函数破坏嵌入——无论 τ 和 E 如何精心选择都无济于事。

### 实施

**模块**: `src/edm_auditor.py:audit_observation_genericity()` — 新建。

**快速预筛**（泛型性的数学条件来自 `[C]` Takens (1981) [B01] 和 Sauer et al. (1991) [B03]；以下阈值为其工程操作化 `[E]`）:

| 检查 | 方法 | 阈值 | 处置 | 来源 |
|------|------|------|------|------|
| 二值/类别目标 | `len(np.unique(data)) < 5` | — | WARN: ρ 天花板 ~0.87 | `[E]` <5 唯一值 = 明确的多类别/序数——无法支撑连续相空间 |
| 边界饱和 | `frac(data==max) > 0.05` 或 `frac(data==min) > 0.05` | 5% | WARN: 吸引子边界是测量伪影 | `[E]` Packard et al. (1980) [B02] 已注意到传感器饱和的破坏效应 |
| 量化粗糙度 | `n_unique / n_total < 0.1` | 10% | WARN: 离散化制造虚假近邻简并 | `[E]` 唯一值不足 10% = 相空间坐标严重退化 |
| 对称折叠嫌疑 | 用户标记（如 |x|, RMS） | — | Advisory | `[E]` 无法自动检测——需用户领域知识 |

### 防火墙处置

- 不阻断执行——用户可能有合理的领域理由继续分析
- 但防火墙**必须**标明哪些泛型性条件被违反，以便解释层施加适当警告
- **联动**: S4（Multiview）— 当主目标变量泛型性差（如二元），Multiview
  使用连续协变量变得不是"推荐"而是**必须**

### 前置条件

- **始终可执行**（仅需检查数据类型，无需最小样本量）
- **联动**: S4 和 S8——当这些规则同时触发时，应从 EDM/HAVOK 转向备选方法


## Secret 10: Seasonality / Periodic-Forcing Confound — 周期混淆检测

**性质**: [D] 诊断　**权重**: ★★（诊断增强——有数据量要求）　**阶段**: Layer 3 (Post-computation) + Interpretation

### 概述

当一个强大的外部周期性驱动（昼夜节律、季节日历、每周重置）同时向多个
测量变量注入相关的时间结构时，CCM 会将共享的周期性检测为"因果关系"——
因为两个变量的影子流形携带了**同一个时钟信号**。

这是 Cobey-Baskerville (2016) 混淆：CCM 收敛无法区分"X 动力学驱动 Y"
和"X 和 Y 跟着同一个节拍跳舞"。

当前 Skill 有**部分**防护（Secret 2 的收敛斜率检查 + `surrogate_test.py`），
但缺少对周期性信号强度的**直接量化**。

### 科学依据

- Cobey & Baskerville (2016). *Nature Comms*, 7, 12891. [B21] — 核心反例
- McCracken & Weigel (2014). *PRE*, 90(6), 062903. [B22] — 更早的独立发现
- Mønster et al. (2017). *FGCS*, 73, 52-62. [B23] — 系统化的假阳性率曲线
- Cummins, Gedeon & Spendlove (2015). arXiv:1508.04882. [B24] — 建设性批评

### 禁忌规则

> **当 CCM 报告收敛因果时，检查一个更简约的解释是否存在：**
> **共享的外部周期性驱动。**

双重检查：(a) 量化每个变量的主导周期性，(b) 若两个变量共享相同频率的
强周期性成分，CCM 结果是**歧义的**，不能作为因果方向的排他性证据。

### 实施

**模块**: `src/edm_auditor.py:audit_seasonality_confound()` — 新建。

**算法**:
1. 对每个变量计算 Lomb-Scargle 周期图（处理不规则采样）
2. 识别主导频率 f_dom 及其归一化功率 P_dom/P_total
3. 若 P_dom/P_total > 0.30 → HIGH seasonality
4. 若一对 CCM 中的**两个**变量在同一 f_dom 上均为 HIGH → 触发警告
5. 若 CCM 收敛 + 共享主导周期 → 建议去季节残差重分析作为对照实验

> **数值溯源**: `P_dom/P_total > 0.30` → `[D]` 原理来自 **Cobey & Baskerville (2016)** [B21]（周期性外驱 → CCM 虚假收敛），但原文未指定功率阈值——30% 是针对本 Skill 典型 N∈[20,100] 数据的工程操作化。`N ≥ 20` → `[E]` Lomb-Scargle 周期图分辨率 ≈ 1/(t_max-t_min)，N=20 可解析 ~10 bins——主导频率检测的最低粒度。

### 防火墙处置

- Advisory (WARN)——不阻断，仅标记歧义
- 去季节重分析作为对照实验被建议，但**不自动化**（季节调整本身是建模选择，不应静默执行）
- 输出语言："Both variables share a dominant periodic component (f ≈ {freq}). CCM convergence may reflect external periodic forcing. Re-run CCM on de-seasonalized residuals as a control."

### 前置条件

- **需要**: N ≥ 20（低于此值，周期图分辨率不足以可靠检测季节性结构）
- **联动**: S2（CCM 收敛）——若 S10 触发，S2 的收敛判定需附带周期性歧义警告


## Secret 11: Common Driver / Latent Confounding Disclaimer — 公共驱动免责

**性质**: [I] 解释　**权重**: ★★（解释追加——零计算成本但高认知回报）　**阶段**: Interpretation

### 概述

CCM 检测的是**动力学耦合**——一个变量的信息出现在另一个变量的影子流形中。
这与**机制性因果**不是一回事。若一个未被观测的变量 Z 独立地驱动 X 和 Y
（具有不同的耦合强度），CCM 可能检测到 X↔Y 耦合——即使两者在 Pearl 意义
上完全没有因果关系。

这是任何不进行条件化的成对因果发现方法的**根本性可识别性限制**。
不能算法性地"解决"——只能**诚实地免责**。

### 科学依据

- Sugihara et al. (2012), Supplementary Materials. [B08] — 原始作者明确承认此限制
- Pearl (2009). *Causality*, 2nd ed., Ch.1.4. [B26] — 未观测混杂变量的形式化定义
- Runge et al. (2019). *Science Advances*, 5(11), eaau4996. [B27] — PCMCI：条件独立性因果发现替代方案
- Deyle et al. (2016). *Proc. R. Soc. B*, 283(1822). [B25] — 应用 CCM 时全程附带机制解释警告

### 禁忌规则

> **绝不将 CCM 结果呈现为"X 导致 Y"而不附带公共驱动免责声明。**
> 当多个 CCM 对都显著时，潜在公共驱动假设**必须**被显式陈述为替代解释。

### 实施

**模块**: `src/ccm_causality.py` 和 `src/final_interpretation.py` — 输出语言更新。

**逻辑**（零新计算——纯叙述卫生）:

单个 CCM 输出：
> "Note: CCM detects dynamic coupling, not mechanistic causation. An unobserved common driver Z→X and Z→Y can produce the same convergence pattern."

多个 CCM 对显著时（count ≥ 3）：
> "Multiple CCM pairs show convergence. Consider the possibility of a latent common driver. CCM cannot distinguish X→Y from Z→X and Z→Y with different coupling strengths."

### 防火墙处置

- Advisory（追加到**每一个** CCM 输出）——不阻断
- 整套扩展中成本最低、认知回报最高的单条规则

### 前置条件

- **始终激活**（只要 CCM 被运行）
- **无数据要求**——不涉及新计算


## Secret 12: Prediction Decay Profile Analysis — 预测衰减剖面诊断

**性质**: [D] 诊断　**权重**: ★（诊断增强——纯信号增益，低优先级）　**阶段**: Layer 3 (Post-computation)

### 概述

当前 Skill 仅使用一个预测步长（Tp=1——一步向前预测）。这丢弃了 ρ 随 Tp
增加时的衰减形状中编码的诊断信息：

| 衰减形状 | 诊断 |
|---------|------|
| 指数衰减（~e^(-λ·Tp)） | 与混沌动力学一致；λ 应约等于 Lyapunov 指数 |
| 在特定 Tp 处陡降 | 存在特征时间尺度；系统在此越过不同动力学区域 |
| 平坦/幂律衰减 | 线性随机过程主导；非线性结构弱或不存在 |
| 振荡衰减 | 准周期性动力学 + 噪声 |

与 Secret 1（Lyapunov）联合，衰减剖面提供**一致性检验**：若 τ_L = 50 场
比赛，但 ρ 在 Tp=5 时降为零——不一致：要么 λ_max 被低估，要么系统有不
同于混沌发散的特征时间尺度。

### 科学依据

- Sugihara & May (1990). *Nature*, 344, 734-741. [B06] — 衰减剖面区分混沌与噪声
- Farmer & Sidorowich (1987). *PRL*, 59(8), 845-848. [B28] — 首个系统性混沌预测衰减研究
- Casdagli (1989). *Physica D*, 35(3), 335-356. [B29] — 三类衰减模式分类
- Kaplan & Glass (1992). *PRL*, 68(4), 427-430. [B30] — δ-ε 确定性检验（与衰减剖面数学关联）

### 禁忌规则

> **单个 Tp=1 预测 ρ 不足以作为动力学诊断。**
> 至少扫描 Tp ∈ [1, min(20, N/3)]，报告衰减剖面形状及与 Lyapunov 估计的一致性。

### 实施

**模块**: `src/sensitivity_config.py` — 扩展现有参数扫描基础设施。

**衰减剖面分类**（全部 `[E]` 工程启发——衰减剖面概念来自 Farmer & Sidorowich (1987) [B28]、Casdagli (1989) [B29]、Sugihara & May (1990) [B06]；以下阈值为其工程操作化）:

| 指标 | 阈值 | 诊断 | 来源 |
|------|------|------|------|
| ρ(Tp) 指数拟合 R² | > 0.85 | 指数衰减（混沌） | `[E]` 0.85 保守——低于此值可能多尺度动力学 |
| max(\|Δ²ρ/ΔTp²\|) > 2·σ_Δ²ρ | — | 陡降：存在特征时间尺度 | `[E]` 2σ 标准异常检测约定 |
| ρ 残差 AC(1) > 0.5 | — | 振荡：准周期性 | `[E]` 残差自相关 >0.5 = 系统性 ρ 波动 |
| ρ(Tp=5) / ρ(Tp=1) > 0.8 | — | 平坦：线性动力学主导 | `[E]` 5 步后仍保持 80% 技能 = 极少衰减 |
| λ_fit / λ_lyap ∈ [0.5, 3.0] | — | 与 Lyapunov 估计一致 | `[E]` 2倍以内——物理上合理的一致性区间 |
| λ_fit / λ_lyap < 0.3 或 > 3.0 | — | 不一致——标记人工审查 | `[E]` 超过 3 倍偏差 = 两种诊断矛盾 |

> 其中 σ_Δ²ρ = std(Δ²ρ/ΔTp²)，即二阶差分的标准差。

### 防火墙处置

- Advisory——不阻断。不一致本身是有价值的诊断信号。
- 衰减剖面作为报告中的额外一致性维度

### 前置条件

- **需要**: N ≥ 30（留出足够的 library 用于多步预测）
- **依赖**: S1（Lyapunov）——若 λ_max 不可用，仅做形状分类不做一致性检验


## Secret 13: Multiple Comparison Correction for CCM — CCM 多重比较校正

**性质**: [I] 解释　**权重**: ★★（解释追加——CCM 对 > 1 时路由到 batch_test；≥ 5 对时 WARN 升级）　**阶段**: Interpretation

### 概述

当 K 个变量进行成对 CCM 因果检验时，假设检验次数以 K(K-1) 增长。至少
一个假阳性（纯粹随机产生的"收敛"CCM 对）的概率为：

```
P(至少一个 FP) = 1 - (1-α)^{K(K-1)} ≈ K(K-1)·α
```

对于当前游戏数据 Skill（K=4 变量，最多 6 对 CCM）：
```
P(FP) ≈ 1 - 0.95⁶ ≈ 26%
```

不做校正，Skill 以相同的名义显著性阈值独立报告每对"因果"或"非因果"——
静默膨胀族系误差率。

### 科学依据

- Benjamini & Hochberg (1995). *JRSS-B*, 57(1), 289-300. [B32] — FDR 控制
- Bonferroni (1936). [B33] — 经典校正 α/K
- Runge et al. (2019). *Science Advances*, 5(11). [B27] — PCMCI 网络级 FDR
- Vejmelka et al. (2009). *Climate Dynamics*, 33(5). [B34] — 多元非线性检验中无校正的假阳性膨胀

### 禁忌规则

> **当运行 K(K-1)/2 对 CCM 时，应用多重比较校正并报告校正后的显著性阈值。**

校正方法取决于分析标签：

| 分析类型 | 校正 | 理由 |
|---------|------|------|
| EXPLORATORY | Benjamini-Hochberg FDR (q=0.10) | 允许 10% 假发现以保留统计效力 |
| CONFIRMATORY | Bonferroni (α/K) 或 Holm-Bonferroni | 严格的族系误差率控制 |
| 预注册的 1-2 对特定假设 | 无需校正 | 假设在看数据前就已指定 |

### 实施

**模块**: `src/ccm_causality.py:ccm_batch_test()` — 新建。

**校正效果**:

| 场景 | 名义 α | 校正后阈值 | 效果 |
|------|--------|----------|------|
| 3 对 (K=3, 1 target) | 0.05 | FDR q=0.10 → 实际影响小 | 极小 |
| 6 对 (K=4, full) | 0.05 | Bonferroni: α=0.0083 | 6× 更严 |
| 12 对 (K=4, all-all) | 0.05 | Bonferroni: α=0.0042 | 12× 更严 |
| 20+ 对 (大扫描) | 0.05 | FDR q=0.10 强烈推荐 | 防止过拟合噪声 |

**方法学限制**: CCM 的 p 值来自非参数收敛检验（Spearman 秩相关），而非
封闭形式的零分布。校正应用于**收敛显著性**而非**因果强度**。此限制在
输出中显式记录。

> **多重比较数值溯源**:
> - `α = 0.05`: `[C]` Fisher 经典显著性水平
> - `FDR q = 0.10`: `[C]→[D]` **Benjamini & Hochberg (1995)** [B32] 贡献 FDR 框架，未规定具体 q 值；0.10 为探索性分析的惯例选择（比 0.05 宽松，保留统计效力）
> - `Bonferroni α/K`: `[C]` **Bonferroni (1936)** [B33] 精确公式
> - `P(FP) ≈ 1 - 0.95⁶ ≈ 26%`（6 对）: `[C]` 概率恒等式
> - `≥ 5 对 WARN / > 1 对路由`: `[E]` 5 对时 FWER > 20%——明确可靠性问题；路由 >1 对是保守但零成本的保护

### 防火墙处置

- Advisory (WARN)——对 ≥ 5 对 CCM 且未校正的探索性分析
- Router 自动路由到 `ccm_batch_test()` 当 CCM 对 > 1

### 前置条件

- **需要**: CCM 对 ≥ 2
- **联动**: S11（公共驱动）——多对显著 + S11 触发 → 公共驱动假设更简约


## Secret 14: Nonlinear Sampling Adequacy — 非线性采样充分性

**性质**: [D] 诊断　**权重**: ★（诊断增强——场景化优先级）　**阶段**: Layer 3 (Post-computation)

### 概述

线性系统要求采样率 ≥ 2× 最高信号频率（Nyquist-Shannon）。非线性/混沌
系统要求**显著更高**的有效采样率，因为：
1. 谐波和互调产物将有效带宽扩展到远超主导傅里叶频率
2. 最快的**动力学**时间尺度（非信号的主导频率）决定相空间近邻是真实的
   还是欠采样的伪影
3. 被 ≤ 2 个采样点解析的 HAVOK 强制尖峰不能被可靠定位或表征

**应用场景依赖**: 在逐场游戏数据中（自然采样间隔 = 1 场），此规则很少
触发；在可控制采样率的物理/工程传感器数据中，这是第一优先级的检查。
规则的实现成本接近零（仅统计已计算数组中的连续超阈值区域），因此纳入
以求完备。

### 科学依据

- Eckmann & Ruelle (1985). *Rev. Mod. Phys.*, 57(3), 617-656. [B20] — N_min ~ 10^d
- Abarbanel et al. (1993). *Rev. Mod. Phys.*, 65(4), 1331-1392, §IV. [B04] — 采样率选择实践指南
- Gibson, Farmer, Casdagli & Eubank (1992). *Physica D*, 57(1-2), 1-30. [B39] — 最优采样率的解析推导
- Broomhead & King (1986). *Physica D*, 20(2-3), 217-236. [B38] — SSA 作为欠采样的部分补救

### 禁忌规则

> **检查最快的被观测动力学事件是否被充分采样。**
> 若 HAVOK 强制尖峰的上升沿 ≤ 2 个采样间隔，警告系统的最快时间尺度
> 可能欠采样，尖峰计数和位置应作为**下限估计**对待。

### 实施

**模块**: `src/sovereign_havok.py:SovereignHAVOK._check_sampling_adequacy()` — 新建。

**算法**: 在 `fit()` 后统计 `forcing_` 中连续超阈值（1.5σ）区域中
宽度 ≤ 2 个采样点的比例。若 `undersampled_frac > 0.3`，`diagnose()` 字典
新增 `'sampling_adequacy'` 键。

> **数值溯源**（全部 `[E]` 工程启发）:
> - `1.5σ` 尖峰检测: `[E]` 与 S5 HAVOK 强制分析使用同一阈值——体系内一致性
> - `≤ 2 采样点 = 欠采样`: `[E]` 事件上升沿 ≤2 点 → 动力学时间尺度未被解析；若采样率刚满足 Nyquist，事件应至少占 3-5 点
> - `undersampled_frac > 0.3`: `[E]` 30% 尖峰未被充分解析——系统最快尺度可能普遍采样不足
> - `spike_count ≥ 3`: `[E]` 至少 3 个尖峰才有意义评估比例——少于 3 比例估计噪声过大
> - `N_min ~ 10^d`: `[C]` **Eckmann & Ruelle (1985)** [B20] Rev. Mod. Phys. 经典结论
> - `2-20× 特征频率`: `[C]` **Gibson et al. (1992)** [B39] Physica D 解析推导

### 防火墙处置

- Advisory (WARN)——不阻断。分析作为动力学复杂性的**下限估计**仍然有效。
- 输出语言："HAVOK spike counts may underestimate true event frequency due to sampling limitations."

### 前置条件

- **需要**: spike_count ≥ 3（尖峰太少无法有意义地评估采样充分性）
- **联动**: S3（Hankel 比）——欠采样 + 低 p/q → 双重 SVD 劣化


---

# 规则交互与分流体系

十四项规则形成一个互连的诊断网。以下为 Router 和 Auditor 的运行时
分流工程参考。

## 交互图

```
                    ┌──────────────────────────────┐
                    │     PRE-EXECUTION GATES       │
                    │  S3: Hankel Aspect Ratio      │  ← 强制 [G] ★★★★
                    │  S8: Stationarity Gate         │  ← 强制 [G] ★★★★
                    │  S9: Observation Genericity   │  ← 条件 [G] ★★★
                    └──────────────┬───────────────┘
                                   │ passes
                    ┌──────────────▼───────────────┐
                    │     EXECUTION PHASE            │
                    │  EDM + HAVOK + CCM             │
                    └──────────────┬───────────────┘
                                   │
         ┌─────────────┬───────────┼───────────┬─────────────┐
         ▼             ▼           ▼           ▼             ▼
    S1: Lyapunov  S2+S7: CCM   S5: SVD     S10: Season  S14: Sampling
    [D] ★★★      [G]+[I] ★★★  [D] ★★★     [D] ★★      [D] ★
         │             │           │           │             │
         │             │           │     S4: Multiview      │
         │             │           │     [D] ★★★            │
         │             │           │     (embedding choice) │
         └─────────────┴───────────┴───────────┴─────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │   CROSS-VALIDATION LAYER      │
                    │  S6: EDM-HAVOK agreement      │
                    │  S12: Decay Profile vs τ_L    │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │    INTERPRETATION LAYER       │
                    │  S11: Common Driver Caveat    │
                    │  S13: Multi-Comparison Corr   │
                    └──────────────────────────────┘
```

## 互补对

| 规则 A | 规则 B | 协同效应 |
|--------|--------|---------|
| S8 (非平稳) | S5 (SVD 残差) | 上游检测到非平稳 → S5 基线存疑 → 换用滑动窗口 S5 |
| S10 (周期性) | S2 (CCM 收敛) | 共享周期性 → CCM 可能虚假收敛 → S2 单独不够，S10 必须同时触发 |
| S9 (二元目标) | S4 (Multiview) | 泛型性失败 → Multiview 连续协变量不再是可选项 |
| S11 (公共驱动) | S13 (多重比较) | 多对显著 → S11 警告公共驱动，S13 校正阈值 |
| S1 (Lyapunov) | S12 (衰减剖面) | Lyapunov → 预期衰减率；S12 观察到的衰减必须一致 |
| S3 (Hankel) | S14 (采样) | 欠采样 + 低 p/q → 双重 SVD 劣化 |

## 防火墙分层（与 DESIGN.md 一致）

| 问题类别 | 自动修正？ | 涉及规则 |
|---------|----------|---------|
| 数值次优性 | **是** | S3（降 q）、S5（丢弃 50%） |
| 数据不足 | **否**（警告） | S8（非平稳）、S9（泛型性失败）、S12（N 太小）、S14（采样不足） |
| 物理不可能 | **否**（阻断） | S1（预测超过 5·τ_L） |
| 逻辑/解释错误 | **否**（警告） | S2+S7（CCM 方向）、S10（周期混淆）、S11（公共驱动）、S13（多重比较） |

## Router 分流逻辑（伪代码）

```
function route_rules(n, k_vars, is_binary, goal, has_prereg):
    active = []

    // ── 强制关卡 [G] ★★★★ — 永远激活 ──
    if q is specified:
        active.append(S3, weight=★★★★)
    // S8: base ★★★★, degraded for small N (ADF/KPSS low-power regime)
    if n >= 50:
        active.append(S8, weight=★★★★)
    elif n >= 20:
        active.append(S8, weight=★★★)
    else:
        active.append(S8, weight=★★)  // N<20: low power, advisory only

    // ── 条件关卡 [G] ★★★ — 按数据画像激活 ──
    if is_binary or n_unique < 5:
        active.append(S9, weight=★★★)
    if ccm_will_run:
        active.append(S2, weight=★★★)
        active.append(S7, weight=★★★)

    // ── 诊断增强 [D] — 按数据和目标激活 ──
    // S1: Lyapunov — mandatory for predict; conditional (†) for explore/phase
    if goal in [predict, explore, phase]:
        if n >= 100:
            active.append(S1, weight=★★★)
        elif n >= 30:
            active.append(S1, weight=★)  // surrogate 替代下限
    if goal in [detect_nl, explore] and k_vars >= 2 and n < 100:
        active.append(S4, weight=★★★)
    if n >= 50 and (goal in [predict, phase]):
        active.append(S5, weight=★★★)
    // S6: cross-validation for all goals that run both EDM and HAVOK
    if edm_and_havok_both_run:
        active.append(S6, weight=★★★)
    if n >= 20 and ccm_will_run:
        active.append(S10, weight=★★)
    if n >= 30 and goal in ['predict', 'detect_nl']:
        active.append(S12, weight=★)
    if ccm_pairs >= 5:
        // S13: Bonferroni if confirmatory (preregistered), FDR if exploratory
        active.append(S13, weight=★★)
    if havok_spikes >= 3:
        active.append(S14, weight=★)

    // ── 解释追加 [I] — 按输出类型激活 ──
    if ccm_will_run:
        active.append(S11, weight=★★)
        // S11 always fires for every CCM output regardless of prereg status

    // S13 correction method controlled by has_prereg:
    //   has_prereg=True  → Bonferroni (α/K), strict FWER
    //   has_prereg=False → Benjamini-Hochberg FDR (q=0.10)
    // This is resolved inside ccm_batch_test(), not at routing level.

    return active  // 按 weight 降序排列
```

---

# 附录：全文件数值溯源汇总

| 规则 | `[C]` 规范值 | `[D]` 推导值 | `[E]` 工程启发值 |
|------|------------|------------|----------------|
| S1 Lyapunov | τ_L = 1/λ_max 定义; Rosenstein 算法; 5·τ_L 物理边界共识 | 3·τ_L 中间界; N≥100/N≥30 数据条件 | R²≥0.5 拟合质量; n_expand=min(20,N//3); surrogate 替代 |
| S2 CCM | CCM 双向测试强制 (Sugihara 2012); pyEDM 方向语义 | total_rise>0.05; spearman_rho>0.7; final_rho>0.2; spearman_p<0.1; N≥30 | bidirectional_delta=0.05 |
| S3 Hankel | — | — | p/q≥10 及四级递进 (10/5/3); q_safe 公式; 所有工作示例 |
| S4 Multiview | Multiview 方法本身 (Sugihara 2016) | N<100 推荐阈值 | N<50+ K≥3→CRITICAL |
| S5 SVD | — | — | 2.5× 检测阈值; 1.5× WARN 区; 3 连续窗口; 50% 丢弃 |
| S6 Cross-Val | θ>0 非线性判据 (Sugihara 1994) | kurt>1.5 重尾; kurt<0.5 近高斯; kurt∈[0.5,1.5] 缓冲区 | Δkurtosis<0.3; 5% 噪声注入 |
| S7 Arrow | CCM 双向强制 (Sugihara 2012) | — | 与 S2 共享所有阈值 |
| S8 Stationarity | p<0.05; ADF+KPSS 联合矩阵结构; ADF/KPSS 检验方法 | N≥20 最低样本 | σ²比>3.0; 趋势/信号>0.3; ρ_forward/ρ_self<0.7 |
| S9 Genericity | 泛型性数学条件 (Takens 1981; Sauer et al. 1991) | — | n_unique<5; 5% 饱和; 10% 量化; ρ天花板~0.87 |
| S10 Seasonality | Cobey-Baskerville 周期性混淆原理 | P_dom/P_total>0.30 | N≥20 周期图最低 |
| S11 Common Driver | CCM 动态耦合≠机制因果的声明 (Sugihara 2012 Supp.) | — | count≥3 升级警告 |
| S12 Decay | 衰减剖面概念框架 (Farmer 1987; Casdagli 1989; Sugihara 1990) | — | 全部 6 个分类阈值; Tp∈[1,min(20,N/3)]; N≥30 |
| S13 Multi-Comp | α=0.05; Bonferroni α/K 公式; FDR 框架 (Benjamini-Hochberg 1995); P(FP) 概率恒等式 | FDR q=0.10 | ≥5 对 WARN; >1 对路由 |
| S14 Sampling | N_min~10^d (Eckmann-Ruelle 1985); 2-20×特征频率 (Gibson et al. 1992) | — | 1.5σ 尖峰检测; ≤2 采样点; >0.3 欠采样比例; ≥3 尖峰最低 |

> **设计原则**: `[C]` 值来自文献——不可擅自修改。`[D]` 值的论文依据在规则正文中已标注 [B##] 引用，数值校准本 Skill 数据场景 (N∈[30,500])——若应用于不同数据尺度需重新评估。`[E]` 值在 `docs/thresholds_and_heuristics.md` 中有变更记录——这些是"最好已知"的值，不是"唯一正确"的值。

---

*End of fourteen forbidden rules. All rules are indexed in `references/fourteen_rules_bibliography.md` (39 papers, annotated by rule).*
