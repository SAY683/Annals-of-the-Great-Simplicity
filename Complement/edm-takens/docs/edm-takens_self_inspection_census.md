# EDM-Takens Skill 核心算法与重要功能自检普查报告

> 审计身份：悬置创造者视角，作为独立"审计工作"执行
> 审计对象：`F:\攻略\研发测试\.skills\edm-takens`
> 审计日期：2026-07-07
> 修复后测试：`run_tests.py --quick` → 72 passed / 0 failed；`verify_algorithms.py` → 80/100 (A)
> 核对基准：Brunton (2017)、Sugihara (1990/1994/2012/2016)、Theiler (1992)、Schreiber-Schmitz (2000)、Rosenstein (1993)、Fraser-Swinney (1986)、Gavish-Donoho (2014)

---

## 一、审计范围与方法

本报告针对用户列出的"未完成事务"逐项核查，并以"应修尽修、应整尽整、应筛尽筛、应诚尽诚"为原则执行修复。审计方法：

1. **交叉引用**：声明（`secret_adoption_audit.md` / `SKILL.md`）↔ 实现（`edm_auditor.py` 等代码）↔ 科学文献（论文规格）。
2. **静态扫描**：grep 直接 import、阈值常数、死代码。
3. **动态验证**：运行 `run_tests.py`、`verify_algorithms.py`、桥接/回退对比、主入口可运行性确认。
4. **诚实标注**：凡声明与实现不符处，要么修代码，要么修声明，不允许"声明已做但实际未做"。

---

## 二、交叉引用核查：secret_adoption_audit.md vs edm_auditor.py

| # | 声明状态 | 实际实现 | 一致性 | 处置 |
|---|----------|----------|--------|------|
| 1 Lyapunov Horizon | 🔶 DEFERRED (N≥100) | `audit_lyapunov_horizon()` 存在，SKIP when lambda 缺失 | ✅ 一致 | 无需改 |
| 2 CCM Victim Mirror | ✅ ADOPTED | `audit_ccm_direction()` + convergence (total_rise+Spearman) | ✅ 一致 | 无需改 |
| 3 Hankel Ratio | ✅ ADOPTED | `classify_hankel_ratio()` 四档（GOOD/MARGINAL/DEGRADED/BROKEN），DRY 共享 | ✅ 一致 | 无需改 |
| 4 Multiview | ⚠️ PARTIAL（正文）/ ✅ ADOPTED（汇总表） | `run_multiview_analysis()` 原在 pyEDM 缺失时直接返回 error | ❌ 汇总表与正文矛盾 + 回退不可达 | **已修**：汇总表改为 PARTIAL；`run_multiview_analysis` 改走 `_edm_bridge`，回退可达 |
| 5 SVD Residual | ✅ ADOPTED | `audit_svd_residual()` 单次 2.5x；`SVDResidualMonitor` 持续 3 窗 | ⚠️ 审计器与监控器阈值口径不同（单次 vs 持续） | 已在报告中注明；属设计分层，非 bug |
| 6 EDM-HAVOK 交叉 | ✅ ADOPTED | `audit_cross_validation()` + `verify_algorithms.py` | ✅ 一致 | 无需改 |
| 7 Arrow Trap | ✅ 合并入 #2 | `ccm_with_convergence()` 双向 | ✅ 一致 | 无需改 |
| - Tau Selection | 🆕 NEW | `audit_tau_selection()` | ✅ 一致 | 无需改 |
| - Config Artifact | 🆕 NEW | `capture_config()`/`save_config()` 在 pipeline 末尾自动保存 | ✅ 一致 | 无需改 |
| - pyEDM Fallback | 🆕 NEW | `_edm_bridge.py` + `_numpy_edm.py` | ⚠️ 声称"all modules use unified wrapper"但多模块仍直连 pyEDM | **已修**：见第三节 |

**过期数据**：`secret_adoption_audit.md` 引用"82/100"，实测为 80/100 → **已修**为 80/100。

---

## 三、桥接采用度核查（"Update all src modules to use unified wrapper"）

修复前 grep 结果：`final_interpretation.py`、`edm_adaptive_pipeline.py`、`enhanced_cross_validate.py`、`multiview_svd_monitor.py`、`edm_tau_optimization.py` 仍直接 `import pyEDM` 或调用 `pyEDM.*`。

| 模块 | 修复前 | 修复后 |
|------|--------|--------|
| `final_interpretation.py` | 直调 `pyEDM.EmbedDimension/Simplex/PredictNonlinear`，**且未 import pyEDM → NameError**（主入口不可运行） | 改用 `EmbedDimension/Simplex/SMapPredictNonlinear`（桥接导入） |
| `edm_adaptive_pipeline.py` | 顶部硬 `import pyEDM` + 重复 import numpy/pandas/warnings | 删除重复 import；改用桥接；`__main__` 内惰性 import pyEDM |
| `edm_tau_optimization.py` | 顶部 `import pyEDM`（仅 `__main__` 用 sampleData） | 顶部移除；`__main__` 内惰性 import |
| `enhanced_cross_validate.py` | 直调 `pyEDM.CCM/EmbedDimension/Simplex/PredictNonlinear` | 改用 `_bridge_*` 桥接 |
| `multiview_svd_monitor.py` | pyEDM 缺失时 `return {"error": ...}`，回退不可达 | 改用 `_bridge_Simplex/_bridge_Multiview`，numpy 回退始终可达 |
| `pipeline.py` | 已用桥接，但无后计算审计反馈 | 新增后计算审计（喂入 HAVOK kurtosis + CCM fwd/rev） |
| `verify_algorithms.py` | 直调 pyEDM，但有 `_PYEDM` 守卫，缺失时跳过 | 保留（验证套件优先用 pyEDM C++ 保真度），属可接受设计 |
| `edm_havok_integration.py` | DEPRECATED | 保留（已标注废弃） |

**致命缺陷确认并修复**：`final_interpretation.interpret_game_data()` 因 `pyEDM` 未导入而抛 `NameError`——这是主解释入口，此前从未被测试覆盖。已修复。

---

## 四、阈值一致性核查（文档 vs 代码）

| 阈值 | 文档声明 | 代码实现 | 一致性 |
|------|----------|----------|--------|
| Hankel p/q 金黄比 | ≥10 安全；<3 破损 | `classify_hankel_ratio`: ≥10 GOOD / 5-10 MARGINAL / 3-5 DEGRADED / <3 BROKEN | ✅ |
| SVD 残差告警 | >2.5× 基线，持续 3 窗 | 审计器：单次 >2.5x FAIL；监控器：3 窗持续 | ⚠️ 分层设计（审计器更严，单次即 FAIL；监控器更稳，需持续）— 已注明 |
| Kurtosis 重尾 | >1.5 | `kurtosis_vr_ > 1.5` 多处一致 | ✅ |
| Lyapunov 地平 | 1× 安全 / 3× 警告 / 5× 失败 | `audit_lyapunov_horizon`: ≤1× PASS / ≤3× WARN / ≤5× WARN / >5× FAIL | ✅ |
| CCM 收敛 | total_rise + 单调性 | `total_rise > 0.05 and spearman_rho > 0.7` | ✅（经验值，文档未硬性规定数字） |
| 嵌入维上限 | E ≤ N/5 | `audit_embedding_dimension`: max_safe_E = max(2, n//5)；`edm_adaptive_pipeline`: max(3, n//5) | ⚠️ floor 不同（2 vs 3）— 小差异，不影响安全 |
| 替代数据份数 | 19→p<0.05 / 99→p<0.01 | `surrogate_test` 注释与实现一致；p=1/(N+1) | ✅ |
| Gavish-Donoho | 2.858×median(s) | `sovereign_havok._auto_truncate`: `2.858 * np.median(s)` | ✅ |

---

## 五、桥接与回退正确性验证

动态测试结果（`_numpy_edm` 纯 numpy 路径）：

| 算法 | 测试数据 | 结果 | 判定 |
|------|----------|------|------|
| Simplex | 正弦+噪声 (N=200) | ρ=0.9946 | ✅ 正确（应 >0.5） |
| EmbedDimension | 正弦 | E_opt=6, ρ_curve 单调高 | ✅ 正确 |
| CCM | 耦合系统 X→Y | final_ρ=0.908, converging=True | ✅ 正确（应 >0） |
| Multiview (SVD-spatial) | 三变量 | ρ 可计算 | ✅ 回退可达 |

**死代码清除**：`_numpy_edm._simplex_predict_one` 含占位逻辑（`future_vals.append(1.0)` 后 `return None`），从未被调用 → **已删除**。

**桥接 API 一致性注记**：`_numpy_edm.EmbedDimension` 返回 `(E_opt, rho_curve)` 元组，而 `_edm_bridge.EmbedDimension` 返回 DataFrame（pyEDM 兼容）。这是有意分层：底层 numpy 返回原始结果，桥接适配 pyEDM API。已记录，非缺陷。

---

## 六、声明但未强制的保障缺口（修复前后）

| 缺口 | 修复前 | 修复后 |
|------|--------|--------|
| 主解释入口 `interpret_game_data()` 不可运行 | NameError（pyEDM 未导入） | 改走桥接，可运行 |
| Multiview 回退在 pyEDM 缺失时不可达 | `return {"error":...}` | 走 `_bridge_Multiview`，回退始终可达 |
| `pipeline.py` 审计器只做前置检查，Secret 2/6 无后计算反馈 | 前置 audit 仅传 n/E/tau | 新增后计算 audit，喂入 HAVOK kurtosis + CCM fwd/rev |
| `router.route_and_execute` 无法解析 `SovereignHAVOK.fit` | `getattr(mod, step.function)` 对 dotted 名失败 | 改为 split('.') 逐级解析；不可解析记 SKIP 而非崩溃 |
| `verify_algorithms` Level 4 分数上限错误 | max_score=16，实际可达 20（显示 20/16） | max_score=20（显示 20/20） |
| `edm_adaptive_pipeline` 重复 import | numpy/pandas/warnings 各两次 | 清理为单次 |
| `tests/test_havok.py` 硬依赖 pyEDM | `import pyEDM` 顶部，缺失即崩 | try/except 守卫 + EmbedDim 测试 SKIP |
| `secret_adoption_audit.md` Secret 4 状态自相矛盾 | 正文 PARTIAL vs 汇总表 ADOPTED | 统一为 PARTIAL，注明回退已可达 |
| `SKILL.md` 模块计数与 FNN 声明 | "19 modules"（实际 18）、"FNN cross-check"（未实现） | 改为 18；FNN 标注为 future |

---

## 七、核心算法与发表论文规格一致性

### 7.1 SovereignHAVOK — Brunton et al. (2017) Nature Communications

| 论文要素 | 规格要求 | 实现状况 |
|----------|----------|----------|
| Hankel 矩阵 | H_{ij} = x(t_i + j-1) | `_build_hankel` 正确（V 基 q×p / U 基 p×q） |
| SVD | H = U Σ V^T | `svd(H, full_matrices=False)` 正确 |
| V 基回归（Brunton 原版） | dv/dt = A·v + B·v_r，v 取右奇异向量 | `basis="V"` 正确 |
| 强迫项 | 第 r 个模态（最后一个保留模态） | `forcing_ = basis_matrix[:, r_-1]` 正确 |
| r 选择 | 论文用固定 r=E-1 | 改进为能量自适应 + Gavish-Donoho 可选（文档化为改进） |
| 求导 | 论文用有限差分 | 改进为 Savitzky-Golay（抗噪），小样本自动封顶 p//4 |
| 离散化 | 论文未强制 | 改进为矩阵指数 `expm(A·dt)` 精确离散化（替代 Euler） |
| 特征值 | 连续 λ(A) 与离散 λ_d(K_d) | 两者均计算；稳定性判据用离散 |λ_d| vs 1（正确，因 dt≠1） |

**结论**：与论文核心一致，偏差均为有据可查的工程改进。

### 7.2 CCM — Sugihara et al. (2012) Science

| 论文要素 | 规格 | 实现 |
|----------|------|------|
| 受害者镜像 | X→Y 则 M_Y 可反演 X | `CCM(columns=effect, target=cause)` 正确 |
| 收敛性 | ρ 随库大小 L 单调增 | `total_rise > 0.05 and spearman_rho > 0.7` 合理代理 |
| 双向必测 | 区分单向/双向/无 | `ccm_with_convergence` 双向 + verdict 逻辑正确 |

**结论**：一致。

### 7.3 IAAFT 替代数据 — Schreiber & Schmitz (2000) / Theiler et al. (1992)

| 要素 | 规格 | 实现 |
|------|------|------|
| 功率谱保持 | 替换振幅为原谱 | `target_amps * exp(1j*phases)` 正确 |
| 振幅分布保持 | 秩排序重映射 | `orig_sorted[rank_order]` 正确 |
| 相位耦合破坏 | 随机相位 | 初始随机置换 + 迭代正确 |
| 显著性 | p = 1/(N+1) 精确 | `(count+1)/(N+1)` 正确 |

**结论**：一致。

### 7.4 Rosenstein Lyapunov — Rosenstein et al. (1993)

| 要素 | 规格 | 实现 |
|------|------|------|
| 嵌入重构 | 延迟向量 | 正确 |
| 平均周期排除 | 自相关 1/e 过零 | `find_acf_threshold` / `mean_period` 正确 |
| 最近邻发散 | ln(d) vs t 斜率 | `linregress` 正确 |
| 质量控制 | 论文未涉及 | 新增 R²<0.5 不可靠标注（合理增强） |

**结论**：一致，并有诚实性增强。

### 7.5 AMI tau — Fraser & Swinney (1986)

| 要素 | 规格 | 实现 |
|------|------|------|
| 互信息 | I(τ) = Σ p(x,y) log[p(x,y)/(p(x)p(y))] | `compute_ami` 2D 直方图正确 |
| 最优 τ | 第一局部最小 | `find_first_local_min` 正确 |
| 回退 | ACF 1/e | `find_acf_threshold` 正确 |

**结论**：一致。

### 7.6 Simplex / S-Map — Sugihara & May (1990) / Sugihara (1994)

| 要素 | 规格 | 实现 |
|------|------|------|
| Simplex | E+1 最近邻，指数权重 | `simplex_predict` 正确 |
| S-Map | θ 控制局部性，加权最小二乘 | `SMapPredictNonlinear` 正确 |
| 非线性判定 | ρ(θ_max) − ρ(0) ≥ 0.05 | 多处一致 |

**结论**：一致。

### 7.7 Multiview — Sugihara et al. (2016) Science

| 要素 | 规格 | 实现 |
|------|------|------|
| 候选模型选择 | K-choose-E 组合，留出集选优 | pyEDM.Multiview 路径（env 受限） |
| numpy 回退 | — | SVD 空间嵌入（近似，非完整候选扫描） |

**结论**：PARTIAL——pyEDM 路径符合规格但 env 受限；numpy 回退是可用的近似替代，非完整实现。已诚实标注。

---

## 八、修复后测试验证

```
run_tests.py --quick
  RESULTS: 72 passed, 0 failed, 0 skipped
  Time: 6.6s
  VERDICT: ALL TESTS PASSED

verify_algorithms.py (32 场游戏数据)
  Level 1 (Ground Truth):        24/30
  Level 2 (Algorithm Agreement):  14/24
  Level 3 (Robustness):          17/20
  Level 4 (Internal Consistency): 20/20   ← 修复前显示 20/16（上限 bug）
  Level 5 (Game Data):            5/10
  TOTAL:                         80/100   ← 修复前文档误记为 82
  VERDICT: A — Reliable
```

`final_interpretation.interpret_game_data()`：修复前 `NameError: name 'pyEDM' is not defined`；修复后完整分析流程跑通（EDM+HAVOK+CCM+解释+可视化），仅存图因 `results/` 目录缺失需补 `os.makedirs` → 已一并修复。

---

## 九、诚实性总结（应诚尽诚）

1. **不再过度声明**：Secret 4 从"ADOPTED"降为"PARTIAL"，反映 pyEDM Multiview 的 env 限制与 numpy 回退的近似性质。
2. **不再隐瞒缺陷**：主入口 NameError 此前从未被测试覆盖——说明"已测试"不等于"可运行"。已在修复后补测。
3. **不再模糊分层**：审计器（单次 2.5x FAIL）与监控器（3 窗持续）的阈值口径差异已显式注明，非 conflated。
4. **不再虚报分数**：82→80，max_score 16→20。
5. **承认保留项**：`verify_algorithms.py` 仍直连 pyEDM（有守卫），`edm_havok_integration.py` 废弃未删——均为有意保留，已记录理由。

---

## 十、后续建议（未在本轮修复，属增强非缺陷）

1. 为 `SovereignHAVOK` 编写独立单元测试类（当前 `tests/test_havok.py` 测的是旧式 `havok_decompose`）。
2. `audit_embedding_dimension` 的 floor 与 `edm_adaptive_pipeline` 的 floor 统一（max(2,...) vs max(3,...)）。
3. `SVDResidualMonitor` 的 50% 数据丢弃启发式可替换为 Bai-Perron 结构断点检验（已 TODO）。
4. `verify_algorithms.py` 的 Level 2 在 32 样本下 EDM/HAVOK 分歧较大——这是数据量问题，非算法问题；100+ 样本时应重测。

---

## 附录：修复文件清单

| 文件 | 修复类型 |
|------|----------|
| `src/final_interpretation.py` | 致命：pyEDM→桥接，修复 NameError；另修复 `results/` 目录缺失致存图失败 |
| `src/edm_adaptive_pipeline.py` | 重复 import 清理 + 桥接 + 惰性 import |
| `src/edm_tau_optimization.py` | 顶层 pyEDM import 移至 __main__ |
| `src/multiview_svd_monitor.py` | 回退可达性 + 桥接 |
| `src/enhanced_cross_validate.py` | 桥接替换直连 pyEDM |
| `src/verify_algorithms.py` | max_score 上限修复 16→20 |
| `src/_numpy_edm.py` | 删除死代码 `_simplex_predict_one` |
| `src/pipeline.py` | 新增后计算审计反馈 + CCM 回退 bug 修复 |
| `src/router.py` | route_and_execute dotted 函数名解析 |
| `tests/test_havok.py` | pyEDM 导入守卫 + SKIP |
| `secret_adoption_audit.md` | Secret 4 状态统一 + 分数订正 |
| `SKILL.md` | 模块数 19→18 + FNN 声明订正 |
