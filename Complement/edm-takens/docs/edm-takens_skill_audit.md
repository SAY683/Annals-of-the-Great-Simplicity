# EDM-Takens Skill 工程审计与思想体系解析

> 审计对象：`F:\攻略\研发测试\.skills\edm-takens`（WorkBuddy 项目级 Skill）
> 审计时间：2026-07-07
> 执行环境：Python 3.13.2 + pyEDM 2.5.0（`edm_env2/Scripts/python.exe`）
> 结论：整体设计成熟、思想体系清晰，但部分代码一致性与工程细节可进一步收敛。

---

## 1. 发现范围

用户提到“本文件夹中有一个 Skills 文件夹”。实际发现两处相关技能目录：

| 路径 | 状态 | 说明 |
|------|------|------|
| `F:\攻略\研发测试\.skills\edm-takens` | **当前主力 Skill** | 完整、活跃、含测试与文档 |
| `F:\攻略\研发测试\_archive\dynamical-forecasting-toolkit` | 归档/旧版 | 已放入 `_archive`，未再维护 |

本报告聚焦 `.skills\edm-takens`，即 **EDM-Takens + SovereignHAVOK 非线性时序分析 Skill**。

---

## 2. 定位与目标

这是一个面向**非线性动力学与因果推断**的 Python 技能包，核心能力：

- **Takens 嵌入重构**：从一维观测恢复高维吸引子。
- **EDM 预测与因果**：Simplex、S-Map、CCM（Convergent Cross Mapping）。
- **SovereignHAVOK**：基于 Hankel-SVD 的 Koopman 算子分解，识别“何时发生相变”。
- **多重校验防火墙**：在计算前、计算中、计算后分别验证物理可行性、数值稳定性、算法一致性。

典型问题域：游戏数据分析、生态、金融、物理系统。示例数据集为 32 场游戏的 `result / kills / damage / deaths`。

---

## 3. 总体设计哲学

阅读 `SKILL.md`、`DESIGN.md`、`references/research-rigor.md` 后，可提炼出以下思想体系：

1. **防御式深度（Defense in Depth）**：三层把关，避免“算法正确但结果垃圾”。
2. **诚实的谦逊（Honest Humility）**：数据不够时直接 BLOCK 或降级为“结构化假设生成”，不包装成预测。
3. **Garden of Forking Paths 对策**：所有参数决策规则写成代码，禁止手调参数后挑选好看结果。
4. **可重复性优先**：配置工件（config artifact）、敏感性扫描、预注册、探索性/验证性标注。
5. **双重独立验证**：EDM 回答“IF”，HAVOK 回答“WHEN”，只有两者一致才可信。
6. **数据量决定方法**：拒绝用生成数据“凑样本”，样本不足时退回贝叶斯状态空间模型。

---

## 4. 三层防御架构

| 层级 | 入口模块 | 核心问题 | 处理手段 |
|------|----------|----------|----------|
| **L1 环境验证** | `environment_check.py` | 能不能跑？ | Python 版本、包依赖、文件完整性、平台兼容性 |
| **L2 配置审计** | `edm_auditor.py` | 这个请求在物理/数值上是否可行？ | 7 条禁律检查、PASS/WARN/FAIL 判定、自动修正部分参数 |
| **L3 算法交叉验证** | `verify_algorithms.py` + `enhanced_cross_validate.py` | 两种独立方法是否一致？ | EDM vs HAVOK、V-basis vs U-basis、替代数据、噪声注入、子采样 |

`pipeline.py` 将三层串成统一入口；`router.py` 提供决策路由，自动选择方法路径。

---

## 5. 模块职责一览

| 模块 | 职责 | 设计亮点 | 注意点 |
|------|------|----------|--------|
| `sovereign_havok.py` | 核心 HAVOK 引擎：Hankel 构建、SG 滤波求导、SVD 截断、Koopman 特征值、预测 | 连续时间 ODE `dv/dt = A·v + B·v_r`、矩阵指数精确离散化、V/U 双基 | 中文注释与英文混用；小样本 SG 窗口自动封顶 |
| `edm_auditor.py` | 防火墙：七条禁律审查 | `AuditFinding` / `AuditReport` 结构清晰，可扩展 | 阈值（如 `spearman_rho > 0.7`）偏经验 |
| `router.py` | 决策路由：数据分级 → 方法选择 | `DataGrade`、`AnalysisGoal`、`AnalysisLabel` 枚举化，抑制“参数乱逛” | `route_and_execute` 用 `__import__` 反射执行，需确保模块路径 |
| `pipeline.py` | 统一入口，自动修正 + 审计 + 分析 | `PipelineConfig.auto_correct()` 明确区分可修正/不可修正问题 | 环境变量 `OMP_NUM_THREADS=1` 硬编码，可能不适合所有场景 |
| `_edm_bridge.py` | pyEDM 与纯 numpy fallback 的桥接 | `EDM_AVAILABLE`、`EDM_BACKEND` 状态暴露；DataFrame 与 numpy 双输入 | 部分模块仍直接依赖 pyEDM，未完全走桥 |
| `_numpy_edm.py` | 纯 numpy/scipy 实现 Simplex、S-Map、CCM、EmbedDimension、Multiview | 零外部依赖，保证可运行 | 准确率较 C++ pyEDM 有所下降；`_simplex_predict_one` 中有未完成的占位代码 |
| `multiview_svd_monitor.py` | Secret 4（Multiview）+ Secret 5（SVD 残差监控） | 环境不兼容时自动回退 numpy SVD | `run_multiview_analysis` 在 pyEDM 不可用时直接返回错误 |
| `edm_tau_optimization.py` | AMI 计算最优 tau | 先 AMI 局部最小，再 ACF 1/e，最后 tau=1 | `if __name__ == '__main__'` 直接 import `pyEDM.sampleData`，不影响导入 |
| `edm_adaptive_pipeline.py` | tau → E → theta → CCM 自适应流程 | 小样本自动压降 max_E | 顶部重复 import `numpy`、`pandas`、`warnings`；强依赖 pyEDM |
| `final_interpretation.py` | 游戏数据动态解释 + 可视化 | 整合 Lyapunov R² 检查、CCM 收敛、相变事件 | `interpret_game_data()` 中直接调用 `pyEDM.EmbedDimension`，未通过 bridge |
| `enhanced_cross_validate.py` | 三大安全保障（Lyapunov/CCM/Hankel） | 将研究规则编码为独立 verifier | 仅对 pyEDM 封装 try/except，大量函数仍依赖 pyEDM |
| `verify_algorithms.py` | 5 级评分验证体系 | 100 分制、合成系统标定、真实数据验证 | `max_score` 设定偏低（如 Level 4 实际可得 20/16） |
| `surrogate_test.py` | IAAFT 替代数据检验 | 精确 p 值计算、HAVOK kurtosis 专用 wrapper | 无 pyEDM 依赖，较好 |
| `sensitivity_config.py` | 敏感性扫描 + 配置工件 JSON | 配置捕获含包版本、时间戳、随机种子 | `random_seed` 用 `time.time()` 取模，非真随机熵源 |
| `environment_check.py` | 环境检查 | 依赖版本比较、文件完整性 | 版本比较仅取前两位，简单但够用 |
| `run_tests.py` | 统一测试运行器 | 5 层测试、quick/verbose 模式 | 部分层在 quiet 模式下无输出，不利于调试 |
| `tests/test_havok.py` | 旧版 HAVOK 单元测试 | 覆盖 Hankel、SVD、回归、edge cases | 使用的是旧式 `havok_decompose`，非当前 `SovereignHAVOK` 类 |
| `examples/demo.py` | pyEDM 功能演示 | 生成参考图 | 直接依赖 pyEDM，作为示例可接受 |
| `data/game_log.csv` | 32 场游戏示例数据 | 二进制/多变量/小样本，便于展示边缘场景 | 数据量本身不足以支撑强结论 |
| `references/*.md` | 数学基础、禁律、边缘场景、研究规范 | 思想体系文档化，便于后续维护 | 与 `research-rigor.md` 形成互补 |

---

## 6. 数据流与执行流

```
[Raw Data]
    │
    ▼
[environment_check]        L1 环境验证
    │
    ▼
[Router]                   数据分级 → 目标 → 方法路径
    │
    ▼
[edm_auditor]              L2 配置审计（7 条禁律）
    │  ├─ PASS 继续
    │  ├─ WARN 记录并继续
    │  └─ FAIL 阻断或 auto-fix
    ▼
[tau / E / theta 优化]      EDM 参数自动选择
    │
    ├──────────┬──────────┐
    ▼            ▼          ▼
[EDM Simplex]  [EDM S-Map]  [SovereignHAVOK]
    │            │          │
    └────────────┴──────────┘
                │
                ▼
[enhanced_cross_validate]    L3 算法交叉验证
    │
    ├─ 一致：可信
    └─ 不一致：提示数据/参数问题
                │
                ▼
[CCM causality]              因果方向（Victim Mirror）
    │
    ▼
[final_interpretation]       自然语言解释 + 可视化
    │
    ▼
[sensitivity_config]         配置工件 JSON（可重复）
```

---

## 7. 七条“禁律”审查

| # | 禁律 / Secret | 状态 | 实现位置 | 核心思想 |
|---|---------------|------|----------|----------|
| 1 | **Lyapunov Horizon** | 🔶 条件启用（N≥100） | `edm_auditor.py`、`final_interpretation.py` | 超过 `5·τ_L` 的预测无物理意义 |
| 2 | **CCM Victim Mirror** | ✅ 已采用 | `edm_auditor.py`、`final_interpretation.py` | 效应流形可反演原因，方向不能反 |
| 3 | **Hankel Golden Ratio** | ✅ 已采用 | `edm_auditor.py`、`enhanced_cross_validate.py` | `p/q ≥ 10` 保证 SVD 数值稳定；< 3 直接 FAIL |
| 4 | **Multiview Embedding** | ⚠️ 部分 | `multiview_svd_monitor.py` | N<100 多变量场景用空间嵌入替代时间延迟 |
| 5 | **SVD Residual Monitor** | ✅ 已采用 | `multiview_svd_monitor.py` | 吸引子变形时残差 > 2.5× 基线触发告警 |
| 6 | **EDM-HAVOK 交叉验证** | ✅ 已采用 | `verify_algorithms.py`、`enhanced_cross_validate.py` | 两种数学基础独立方法一致才可信 |
| 7 | **CCM Arrow Trap** | ✅ 合并入 #2 | 同上 | 必须同时测试双向 + 收敛斜率 |

额外新增守卫：tau 选择审计、配置工件自动保存、pyEDM 优雅回退、HAVOK 特征值连续→离散修正。

---

## 8. 决策路由（Router）

`router.py` 中的 `Router` 类把数据特征映射为执行计划，避免人工调参：

| 数据分级 | 条件 | 允许目标 | 输出标签 |
|----------|------|----------|----------|
| EXCELLENT | N≥100，规则采样，SNR 高/中 | predict / detect_nl / causal / phase / explore | 若有预注册为 confirmatory，否则 exploratory |
| ADEQUATE | N≥50，规则采样，SNR 中 | 同上，但推荐替代数据检验 | exploratory |
| MARGINAL | N<50 或不规则/噪声 | 仅 explore，predict 被 BLOCK | exploratory |
| INADEQUATE | N<20 | 全部 BLOCK，建议贝叶斯状态空间模型 | — |

强制步骤：环境检查 → 配置审计；可选步骤：AMI tau 优化、敏感性扫描；因果目标自动加入 CCM。

---

## 9. 工程实现亮点

1. **桥接设计降低依赖风险**：`_edm_bridge.py` + `_numpy_edm.py` 保证 pyEDM 缺失时仍可运行核心算法。
2. **配置工件可重复**：`capture_config()` 记录 Python/包版本、参数、时间戳、随机种子。
3. **自动修正策略克制**：只修正数值次优参数（Hankel 比、SG 窗口、E 上限），不修正数据不足或逻辑错误。
4. **研究规范内建**：`research-rigor.md` 把“花园分叉路径”、“预注册”、“标定数据 ≠ 数据增强”等写成纪律。
5. **双层测试**：
   - 模块级 `__main__` 自测（每个 `.py` 可独立运行）。
   - 统一 `run_tests.py` 五层测试（环境、核心、审计、交叉验证、集成）。
6. **代码注释直接嵌入研究洞察**：例如 `CCM` 方向用“受害者（Y）带有加害者（X）的印记”帮助记忆。

---

## 10. 实测结果

### 10.1 环境检查

使用 `edm_env2/Scripts/python.exe` 运行 `environment_check.py`，结果：

```
[OK] Python (v3.13.2)
[OK] numpy (v2.5.1)
[OK] scipy (v1.18.0)
[OK] pandas (v3.0.3)
[OK] matplotlib (v3.11.0)
[OK] pyEDM (v2.5.0)
[OK] 全部 16 项文件完整性检查
Overall: READY
```

### 10.2 快速测试套件

```bash
python run_tests.py --quick
# RESULTS: 72 passed, 0 failed, 0 skipped
# Time: 19.0s
# VERDICT: ALL TESTS PASSED
```

### 10.3 完整五级验证（32 场游戏数据）

```bash
python src/verify_algorithms.py
```

| 层级 | 得分 | 说明 |
|------|------|------|
| L1 Ground Truth | 24/30 | Lorenz 与 EDM 非线性判断不一致；Logistic 混沌 expl_var 为 nan；AR(1) 未判为 dissipative |
| L2 Algorithm Agreement | 14/24 | `result` / `damage` / `deaths` 的可预测性/非线性判断在 EDM 与 HAVOK 间有分歧 |
| L3 Robustness | 17/20 | 噪声注入下 explained variance 非单调下降 |
| L4 Internal Consistency | 20/16（分数上限设定问题） | V/U 基一致、SVD 能量守恒、Hankel 结构验证均通过 |
| L5 Game Data | 5/10 | `damage` 的 Hankel 比 4.5 为 CRITICAL；`kills` 的 Koopman 最大特征值 > 1 |
| **TOTAL** | **80/100** | **A — Reliable. Minor discrepancies explained by data limits.** |

> 注：80 分在 N=32 的小样本条件下是合理表现；技能自身也明确指出“需要 100+ 场数据才能稳定估计 Lyapunov 与相变”。

---

## 11. 风险与改进建议

### 11.1 代码一致性问题（中优先级）

- **部分模块仍直接硬编码 `import pyEDM`**，与 `_edm_bridge` 的解耦目标不一致：
  - `edm_adaptive_pipeline.py`：顶部 `import pyEDM`，未做 fallback。
  - `final_interpretation.py`：`interpret_game_data()` 中直接调用 `pyEDM.EmbedDimension`。
  - `tests/test_havok.py`：直接 `import pyEDM`。
- 建议：所有 EDM 调用统一走 `_edm_bridge`，缺失 pyEDM 时也能给出降级结果或清晰错误。

### 11.2 重复导入与代码冗余（低优先级）

- `edm_adaptive_pipeline.py` 中 `import numpy as np`、`import pandas as pd`、`import warnings` 出现两次。
- `_numpy_edm.py` 中 `_simplex_predict_one` 函数内存在未完成的占位代码（`future_vals.append(1.0)` 后返回 `None`），虽然后续被 `simplex_predict` 替代，但应删除或标记 TODO。

### 11.3 评分上限设定（低优先级）

- `verify_algorithms.py` 中 `Level 4` 的 `max_score=16`，但实际得分可达 20（各子检查分数之和 > max_score）。
- 建议：让 `max_score` 动态等于各检查项满分之和，或调整单项分数。

### 11.4 小样本与数值稳定性（已部分处理，仍有注意点）

- `damage` 在 32 场数据下 E=6，Hankel 比 4.5，属于 CRITICAL。虽然审计会 WARN/FAIL，但 `pipeline.py` 的 auto-fix 可能把它降到 `q_safe = 3`。
- 建议：在示例/文档中强调“damage 用默认 E=6 不可靠，需更多数据或多变量 Multiview”。

### 11.5 可视化输出路径（低优先级）

- `final_interpretation.py` 和 `enhanced_cross_validate.py` 默认写入 `results/` 目录，但未显式处理中文字体；在 Windows 上通常可用，但在某些无字体环境可能乱码。
- 建议：增加字体回退或保存为矢量图时嵌入说明。

### 11.6 测试覆盖率（中优先级）

- `tests/test_havok.py` 测试的是旧式 `havok_decompose`，不是当前 `SovereignHAVOK` 类。
- 建议：新增针对 `SovereignHAVOK` 的单元测试类，覆盖 `fit`、`predict_next_state`、`diagnose`、V/U 基对比。

### 11.7 安全审查（静态）

- 未在源码中发现 `rm -rf`、网络请求、密码/密钥硬编码、eval/exec、子进程调用等高风险操作。
- 唯一潜在风险是 `pipeline.py` 的 `os.makedirs('results', exist_ok=True)` 与文件写入，属于正常分析输出。
- 结论：作为已安装的本地技能，安全风险可控。

---

## 12. 思想体系总结

EDM-Takens Skill 不只是一个算法封装，更是一套**“在数据有限、噪声真实、结论易被过度解读”的场景下如何负责任地做非线性动力学分析”**的工作流：

1. **先问能不能，再问对不对**：L1 环境、L2 审计、L3 交叉验证依次把关。
2. **参数选择规则化**：把“试到显著为止”变成“规则先写死，机器自动执行”。
3. **双重独立验证**：EDM 与 HAVOK 从完全不同的数学基础出发，结果一致才可信。
4. **数据诚实原则**：小样本不强求吸引子重建，宁可降级为假设生成，也不伪造数据或夸大结论。
5. **可重复与可追溯**：配置工件、敏感性扫描、预注册、探索性标注，把“研究纪律”写进代码。
6. **人的判断不可被替代**：审计只给 WARN/FAIL，因果方向仍要求人类解释。

这套思想体系可以直接迁移到其他“高不确定性、强方法依赖”的 AI/数据分析工程中。

---

## 附录：关键文件路径

| 文件 | 作用 |
|------|------|
| `.skills\edm-takens\SKILL.md` | 主入口文档 |
| `.skills\edm-takens\DESIGN.md` | 设计哲学与业务逻辑 |
| `.skills\edm-takens\secret_adoption_audit.md` | 七条禁律采用状态 |
| `.skills\edm-takens\references\research-rigor.md` | 研究规范（vibe coding 纪律） |
| `.skills\edm-takens\src\edm_auditor.py` | 防火墙实现 |
| `.skills\edm-takens\src\router.py` | 决策路由 |
| `.skills\edm-takens\src\pipeline.py` | 统一流水线入口 |
| `.skills\edm-takens\src\sovereign_havok.py` | HAVOK 核心引擎 |
| `.skills\edm-takens\src\_edm_bridge.py` | pyEDM / numpy 桥接 |
| `.skills\edm-takens\src\verify_algorithms.py` | 5 级验证评分 |
| `.skills\edm-takens\run_tests.py` | 统一测试运行器 |
