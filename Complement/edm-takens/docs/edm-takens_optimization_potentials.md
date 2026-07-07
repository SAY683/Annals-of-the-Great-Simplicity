# EDM-Takens Skill 优化潜能研究报告

> 前提：经七轮审计修复，Skill 已达健全基线（72/0 测试、80/100 验证、移植副本可运行、三态一致）。
> 本报告悬置创作者身份，作为独立研究员，识别在健全基线之上仍存在的优化/修复"潜能"。
> 原则：只列有据可查、与设计哲学一致的潜能；区分"应做"与"可做"；明确不建议改动项。

---

## 一、健全基线确认（前提保障已就位）

| 保障项 | 状态 |
|--------|------|
| 三层防御架构（环境/审计/交叉验证） | ✅ 闭环 |
| 桥接统一化（活跃模块全部走 `_edm_bridge`） | ✅ 完成 |
| 七条秘笈状态诚实标注（PARTIAL/DEFERRED 不伪装 ADOPTED） | ✅ 一致 |
| 核心算法与论文一致性（HAVOK/CCM/IAAFT/Rosenstein/AMI/Gavish-Donoho） | ✅ 核对通过 |
| 移植性（路径基于 `__file__`、无硬编码绝对路径、.skill 包标准化） | ✅ 验证 |
| 测试套件 | ✅ 72/0 通过 |

**结论**：基线已可信赖。以下潜能均为"增强"而非"缺陷修复"——不影响当前可用性，但能提升算法保真度、流程闭环度与工程健壮性。

---

## 二、优化潜能分级总览

| 编号 | 潜能 | 类别 | 影响 | 工程量 | 优先级 |
|------|------|------|------|--------|--------|
| P1 | `interpret_game_data` 域硬编码 | 流程/诚实 | 高 | 中 | **A** |
| P2 | `SovereignHAVOK.fit` 无输入校验 | 健壮性 | 高 | 低 | **A** |
| P3 | 无 `SovereignHAVOK` 单元测试 | 测试 | 高 | 中 | **A** |
| P4 | 无端到端测试覆盖主入口 | 测试 | 高 | 低 | **A** |
| P5 | pipeline ↔ cross-validate ↔ interpretation 三入口未串联 | 流程闭环 | 中 | 中 | **B** |
| P6 | 配置工件未含审计裁决 | 可追溯 | 中 | 低 | **B** |
| P7 | numpy Multiview 为近似（非 Sugihara-2016 完整候选扫描） | 算法保真 | 中 | 高 | **B** |
| P8 | FNN（伪近邻）E 选择未实现 | 算法互补 | 中 | 中 | **B** |
| P9 | CCM 收敛阈值 0.05 为魔法数 | 透明性 | 低 | 低 | **C** |
| P10 | SVDResidualMonitor 50% 丢弃启发式 | 诚实性 | 低 | 高 | **C** |
| P11 | 无 CHANGELOG | 治理 | 低 | 低 | **C** |
| P12 | requirements.txt 精确锁未来版本 | 移植性 | 低 | 低 | **C** |

---

## 三、A 级潜能详述（建议实施）

### P1. `interpret_game_data` 域硬编码——与"domain-agnostic"声明冲突

**现状**：`final_interpretation.interpret_game_data()` 无参数，内部硬编码：
```python
variables = ['result', 'kills', 'damage', 'deaths']
causality_pairs = [('kills','result'), ('damage','result'), ...]
```
而 SKILL.md 声称 "Domain-agnostic: game analytics, ecology, finance, physical systems"。

**问题**：算法层（EDM/HAVOK/CCM/审计器）确实是域无关的，但解释层是游戏专用的。这意味着非游戏用户无法直接用 `interpret_game_data`，只能用底层模块。这是一个"声明-实现"裂缝。

**潜能**：将 `interpret_game_data` 重构为 `interpret_data(df, target_col, columns, causality_pairs=None, ...)`，游戏特定文案移到 `examples/game_interpretation.py`。解释层变为域无关的"动力学诊断报告生成器"，与算法层一致。

**判断依据**：这直接落实"诚实算法"原则——不声称域无关却只在游戏域可运行。

### P2. `SovereignHAVOK.fit` 无 NaN/Inf 输入校验

**现状**：`fit()` 仅检查 `energy_threshold` 范围与 `n > q`，不检查数据中是否含 NaN/Inf。

**问题**：含 NaN 的数据会让 SVD 返回全 NaN，后续 kurtosis/eigenvalues 全部失真，但 `is_valid_` 仍被设为 True——产生"静默垃圾结果"。这正是 Skill 设计哲学最反对的失败模式。

**潜能**：在 `fit()` 开头加：
```python
if not np.all(np.isfinite(data)):
    raise ValueError("Data contains NaN/Inf. Clean before fit().")
if np.std(data) < 1e-12:
    warnings.warn("Constant data — SVD will be rank-1, diagnostics meaningless.")
```
低成本、高收益，符合"防火墙"精神。

### P3. 无 `SovereignHAVOK` 类的单元测试

**现状**：`tests/test_havok.py` 测的是旧式 `havok_decompose` 函数（离散 K=Xp·pinv(X)），不是当前的 `SovereignHAVOK` 类（连续 ODE + 矩阵指数 + 自适应截断）。

**问题**：核心引擎的 V/U 基等价、predict_next_state、eigenvalues_d_ 等关键路径无独立单元测试覆盖。这是第六轮 NameError 能潜伏的根本原因——测试与实现脱节。

**潜能**：新增 `tests/test_sovereign_havok.py`，覆盖：fit 基本路径、V/U 基 kurtosis 一致性、predict_next_state 形状、小样本 SG 窗口自动封顶、constant/NaN 输入拒绝。

### P4. 无端到端测试覆盖主解释入口

**现状**：`run_tests.py` Layer 5 只测 `ccm_with_convergence` 与 `estimate_lyapunov_robust`，不调用 `interpret_game_data()` 全流程。

**问题**：主入口在第六轮前一直 NameError 却未被任何测试发现。

**潜能**：在 `run_tests.py` 加 Layer 6：调用 `interpret_game_data()` 并断言其完成（不报错 + 生成 PNG + 打印关键诊断）。这是回归防护网。

---

## 四、B 级潜能详述（建议规划）

### P5. 三入口未串联——流程未完全闭环

**现状**：
- `pipeline.py`：环境→审计→HAVOK→CCM quick→后审计→config 保存
- `enhanced_cross_validate.py`：EDM-HAVOK 交叉验证 + 三安全保障
- `final_interpretation.py`：完整动力学解释 + 可视化

三者各自独立，无统一 `run_full_analysis()` 串联。

**问题**：SKILL.md 的流程图暗示一条完整链路，但实际需用户手动依次运行三个入口。对"高实用性 Skill"而言，这是体验缺口。

**潜能**：在 `pipeline.py` 加 `run_full_analysis(config)`，按 SKILL.md 流程图串联：pipeline → enhanced_cross_validate → final_interpretation，产出统一报告。保留各入口可独立调用。

### P6. 配置工件未含审计裁决

**现状**：`sensitivity_config.capture_config()` 记录参数、包版本、时间戳、随机种子，但不记录审计 verdict 与各 Secret 的 PASS/WARN/FAIL。

**问题**：配置工件能复现参数，但不能复现"当时审计是否通过"——可追溯性不完整。

**潜能**：在 `AnalysisConfig` 加 `audit_verdict`、`audit_findings_summary` 字段，pipeline 保存时写入。低成本，提升 provenance。

### P7. numpy Multiview 为近似

**现状**：`_numpy_edm.Multiview` 用 SVD 空间嵌入（PCA 风格），而 Sugihara 2016 的 Multiview 是 K-choose-E 候选组合 + 留出集选优。`secret_adoption_audit.md` 已诚实标 PARTIAL。

**潜能**：实现完整的 numpy Multiview 候选扫描（K 变量选 E 的组合，每个用 Simplex 评估，选最优）。工程量较大，但对"N<100 多变量"场景是最高 ROI 的算法增强（SKILL.md 自己说这是"highest feasibility"）。

**判断**：若 Skill 主要用于小样本多变量场景，值得做；否则保留 PARTIAL 标注即可。

### P8. FNN（伪近邻）E 选择未实现

**现状**：E 选择仅靠 Simplex ρ 峰值。SKILL.md 已把"FNN cross-check"降级为"future"。但 FNN（Kennel 1992）是与 ρ 峰值互补的标准方法——ρ 峰值可能因过拟合虚高，FNN 从几何角度独立验证。

**潜能**：在 `edm_adaptive_pipeline` 或 `_numpy_edm` 加 `false_nearest_neighbors(series, E, tau)`，作为 E 选择的第二意见。两者一致时置信度更高（呼应 Secret 6 的双重验证精神）。

---

## 五、C 级潜能（可选，低优先）

### P9. CCM 收敛阈值 0.05 为魔法数

`ccm_with_convergence` 用 `total_rise > 0.05 and spearman_rho > 0.7`。这两个数有实践依据但无文档化推导。可在 `references/` 加一段说明：0.05 对应"库大小翻倍 ρ 至少升 0.05"的经验下限，0.7 对应"强单调"。低成本文档增强。

### P10. SVDResidualMonitor 50% 丢弃启发式

已在代码 TODO 与 audit 文档中标注为启发式。真正修复需 Bai-Perron 结构断点检验，工程量大。**建议保留现状 + 文档标注**，不强行升级——因为 N<500 时 Bai-Perron 本身也不可靠，启发式可能反而更稳健。

### P11. 无 CHANGELOG

经七轮迭代，无 CHANGELOG 记录演化。建议加 `CHANGELOG.md`，记录关键修复（NameError、桥接统一、max_score、废弃模块移除）。低成本治理增强。

### P12. requirements.txt 精确锁未来版本

`numpy==2.5.1`、`pandas==3.0.3` 是较新版本。对其他环境可能过严。建议改为 `numpy>=1.22` 的下限约束 + 单独 `requirements-lock.txt` 记录当前环境精确版本（PEP 621 风格）。

---

## 六、不建议改动项（判断力体现）

| 项 | 不改理由 |
|----|----------|
| HAVOK 矩阵指数精确离散化 | 已是 Euler 的正确升级，无需回退或再改 |
| Gavish-Donoho 2.858×median 阈值 | 直接来自论文，无需调参 |
| IAAFT 迭代次数 max_iter=50 | Schreiber-Schmitz 原版经验值，收敛足够 |
| 审计器单次 2.5x vs 监控器 3 窗持续 的分层 | 有意设计——审计器更严（单次即 FAIL），监控器更稳（防误报），不应统一 |
| `verify_algorithms.py` 仍直连 pyEDM | 验证套件优先 C++ 保真度，有 `_PYEDM` 守卫，缺失时跳过——可接受 |
| Lyapunov R²<0.5 不可靠标注 | 合理增强，无需改阈值 |

---

## 七、实施优先级建议

**第一批（A 级，立即）**：P2（输入校验）→ P4（端到端测试）→ P3（SovereignHAVOK 单元测试）→ P1（域解耦）。
理由：P2/P4 工程量极低且堵住"静默垃圾"与"回归漏网"两个最大风险；P3 补测试债；P1 落实诚实性。

**第二批（B 级，规划）**：P6（审计裁决入 config）→ P5（统一入口）→ P8（FNN）。
理由：P6 低成本；P5 提升实用性；P8 增强算法互补性。

**第三批（C 级，按需）**：P7（完整 Multiview）仅在确定主用小样本多变量场景时做；P9/P11/P12 为治理打磨。

---

## 八、总结

当前 Skill 的"前提保障"已健全——算法一致、流程可运行、移植性验证、诚实标注到位。在此之上，**最高价值的潜能不是新算法，而是堵住"静默失败"与"测试-实现脱节"**（P2/P3/P4），以及**消除"声明域无关却游戏专用"的裂缝**（P1）。这四项一旦完成，Skill 将从"可信赖的原型"升级为"可信赖的产品"。其余潜能均为边际增强，可视使用场景按需推进。

研究报告至此。所有潜能均有据可查，且与"诚实算法 + 高实用性 Skill"的设计哲学一致。
