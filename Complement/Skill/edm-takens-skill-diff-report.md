# edm-takens.skill 修正性对比报告

## 1. 文件形态变化

| 旧版本 | 新版本 | 说明 |
|--------|--------|------|
| `F:\攻略\研发测试\.skills\edm-takens\`（展开目录） | `F:\攻略\研发测试\edm-takens.skill`（单个二进制包） | 新版本是 ZIP 打包的 skill 分发包，文件大小约 177 KB，可用 `python -m zipfile -e edm-takens.skill .` 解压。 |

新版本本质上是旧目录的 **打包 + Round 9 独立审计修复** 后的产物。

---

## 2. 总体修正定位：Round 9 独立重审计

CHANGELOG 把这次更新命名为 **"Round 9 (independent audit + fix)"**，核心特点是：

- 没有从之前的审计报告出发找问题，而是**直接执行每个模块的 `__main__` 自测**，现场发现 bug。
- 其中两个 bug（tau 审计状态、Lorenz 代理数据检验）是模块自带自测本来就失败/边缘化的，但 `run_tests.py` 之前根本不跑这些自测，所以一直没暴露。

---

## 3. 关键修正项（按重要性排序）

### 3.1 CCM 因果判定逻辑统一（最重要）

**问题性质**：同一套 CCM 因果测试在 `final_interpretation.py` 和 `enhanced_cross_validate.py` 里各自实现了一次，且规则不一致：

- `ccm_with_convergence()`：要求 cross-map skill 必须收敛（total_rise > 0.05、Spearman rho > 0.7、p < 0.1）才给出因果结论。
- `verify_ccm_direction()`：只看最大 library size 处的 rho，**不做收敛检查**，而且两者用的 library-size 范围不同（`'5 {n-2} 3'` vs `'5 25 5'`）。
- 更糟的是 `pipeline.py` 事后审计只传了裸 rho，没传收敛指标；`edm_auditor` 默认把缺失收敛数据当成“已收敛”，导致高但非收敛的虚假 rho 能直接过防火墙。

**修正**：
- 新增 `src/ccm_causality.py`，作为**唯一的规范化收敛感知 CCM 测试实现**。
- `final_interpretation.ccm_with_convergence()` 和 `enhanced_cross_validate.verify_ccm_direction()` 都变成它的薄包装。
- `pipeline.py` 的事后审计现在显式传递 `total_rise`、`spearman_rho` 等收敛指标，防火墙真正生效。
- 默认 library-size 范围统一为数据长度自适应的 `'5 {n-2} 3'`。

**实际效果**：在示例 game_log.csv 上重新跑 `python src/pipeline.py`，现在会正确输出：

```
[!!] Secret 2: CCM Victim Mirror: ... Reverse rho high (rev=0.558) but NOT converging. Possible false positive
```

而旧版本会把这条警告**静默吞掉**。

---

### 3.2 tau 审计 FAIL/WARN 状态判定 bug

**问题性质**：`edm_auditor.audit_tau_selection()` 用 `any("0.5" in i for i in issues)` 来判定是否该 FAIL。但实际渲染消息时用的是百分比（如 `"75%"`），永远不会出现 `"0.5"` 这个子串，所以超 50% 窗口的情况**永远被降级成 WARN**。

**修正**：引入显式 `critical` 布尔标志，超 50% 窗口直接置 `critical=True`，再据此返回 FAIL。

**暴露方式**：该模块自带的 `__main__` 自测本来就在断言 FAIL，但旧版本返回 WARN，自测失败——只是 `run_tests.py` 以前不跑这个自测。

---

### 3.3 IAAFT 代理数据缺少端点匹配（endpoint matching）

**问题性质**：`surrogate_test.iaaft_surrogates()` 在 FFT 相位随机化前没有端点匹配。FFT 默认信号周期性，真实非周期时间序列的首尾值差异会被当作“跳变”，相位随机化后变成宽带高频能量，污染 HAVOK 强迫项峰度。

**影响**：在 1000 点 Lorenz-x 段上，代理数据的 HAVOK kurtosis 达到真实值的 3–5 倍（最高 16.5 vs 真实 3.4），导致本应是混沌的序列反而无法通过代理检验。

**修正**：按 Theiler & Prichard (1996) 做端点匹配：先减去首尾连线的线性斜坡，FFT/IAAFT 后再加回斜坡。

**附加修正**：
- 显著性边界从 `p_value < 0.05` 改为 `p_value <= 0.05`，因为 n_surrogates=19 时最小可达 p 值恰好是 0.05，严格小于永远无法显著。
- 自测的 n_surrogates 从 19 提升到 99，让检验有真实余量而非坐在边界上。

---

### 3.4 HAVOK 退化输入导致 explained_var_ 静默 NaN

**问题性质**：输入几乎恒定时，归一化 Hankel 矩阵总能量接近 0，累积解释方差变成 `0/0 = NaN`，并静默传入下游报告和审计，导致 `explained_var_ > 0.7` 这类比较无意义失败。

**修正**：在 `sovereign_havok.fit()` 和 `_auto_truncate()` 中检测总能量 < 1e-24 的退化情况，显式返回 `explained_var_ = 0.0`，配合已有的“近恒定输入”警告保持失败可诊断。

---

### 3.5 Logistic 映射基准测试使用退化初始值

**问题性质**：`verify_algorithms._test_logistic()` 在 r=4.0 混沌分支用 `x0=0.5`。0.5 是 logistic 映射在 r=4 时的精确临界点：x₁=1.0，x₂=0.0，之后永远为 0。由于 0.5 和 1.0 在 float64 中可精确表示，这个“测度为零”的退化轨道被确定性地命中，整个序列变成常数 0。

**修正**：改用 `x0=0.2`，这是混沌理论教材中避免此退化点的标准做法。

---

### 3.6 HAVOK 稳定性分级在 3 处重复实现

**问题性质**：`sovereign_havok.diagnose()`、`pipeline.py`、`enhanced_cross_validate.py` 都各自实现了 `|λ_d| > 1.05` / `< 0.90` 的分级逻辑。虽然当前一致，但未来改一个就会漂移。

**修正**：在 `sovereign_havok.py` 新增 `classify_havok_stability()`，三处统一调用这个单一真源（和之前 `classify_hankel_ratio` 的 DRY 修复一致）。

---

## 4. 新增文件

| 文件 | 作用 |
|------|------|
| `src/ccm_causality.py` | 规范化收敛感知 CCM 测试，统一 `final_interpretation` 和 `enhanced_cross_validate` 的因果判定逻辑。 |
| 隐式新增 | `sovereign_havok.classify_havok_stability()` 函数（虽然仍在同名模块内，但属于新增单一真源）。 |

---

## 5. 测试与质量流程改进

### 5.1 `run_tests.py` 新增 Layer 7：模块自测子进程执行

旧版本 `run_tests.py` 只跑自己实现的 Layers 1–6，从不执行各模块底部的 `if __name__ == '__main__':` 自测块。Round 9 发现的多个 bug 正是这些自测本来会抓到的：

- `edm_auditor.py` 自测断言 tau FAIL 但得 WARN；
- `surrogate_test.py` Lorenz 自测在 n=19 时无法达到 p<0.05；
- `verify_algorithms.py` logistic 自测命中退化轨道。

**修正**：`run_tests.py` 新增 `test_module_self_tests()`，用 subprocess 逐一运行每个模块的自测，并检查退出码。快速模式跑 11 个模块，完整模式再加 2 个慢模块。

---

## 6. 文档与元数据更新

- `SKILL.md` 在 "Reviewer Improvements" 表中新增条目 #10–#16，逐项说明上述修复。
- `CHANGELOG.md` 新增 "2026-07-08 — Round 9" 章节，详细记录每个 bug 的发现路径、修复方式和验证结果。
- `secret_adoption_audit.md` 和 `docs/thresholds_and_heuristics.md` 也有同步更新。

---

## 7. 对使用者的实际影响

| 场景 | 旧版本 | 新版本 |
|------|--------|--------|
| 运行 `python run_tests.py` | 可能通过，但隐藏了多个自测失败 | 会暴露各模块自测失败 |
| 跑 sample game_log 的 CCM | 高反向 rho 可能直接过审 | 会提示“反向 rho 高但不收敛，可能是假阳性” |
| 对非周期序列做 IAAFT 代理检验 | 代理 kurtosis 虚高，可能把真混沌判为不显著 | 端点匹配后更可靠 |
| 输入近恒定数据 | explained_var_ 静默 NaN | 显式 0.0 + 警告 |
| 引用 HAVOK 稳定性标签 | 三处可能漂移 | 统一调用，不会漂移 |

---

## 8. 建议后续操作

1. 解压新版本并替换 `.skills\edm-takens\` 目录：
   ```bash
   python -m zipfile -e "F:\攻略\研发测试\edm-takens.skill" "F:\攻略\研发测试\.skills"
   ```
2. 运行完整测试验证：
   ```bash
   python run_tests.py
   ```
3. 如需保留旧版本，先重命名 `.skills\edm-takens` 为 `.skills\edm-takens-old` 再解压。
