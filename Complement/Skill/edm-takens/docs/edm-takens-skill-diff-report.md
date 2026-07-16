> **⚠️ 历史文档。** 本报告记录 Skill 从 7 条规则演进到 14 条规则的迭代历程。当前算法实现、审计结论与最新修复请以 [`docs/ALGORITHM_AUDIT.md`](ALGORITHM_AUDIT.md) 和 [`CHANGELOG.md`](CHANGELOG.md) 为准。保留本文件仅作为演进历史参考。

# edm-takens.skill 演进对比报告

> 追踪 Skill 从最初 7 条规则到当前 14 条规则完整实现 + 双案例 + 文献溯源体系的全部变更。

---

## 1. 版本演变总览

| 阶段 | 规则 | 案例 | 文献 | 主要变化 |
|------|------|------|------|---------|
| **原始版** (7/7) | 7 条，无溯源 | 仅 `demo.py` | 核心 6 篇 | 基础 EDM/HAVOK/CCM 管线 |
| **Round 9** (7/8) | 7 条，代码修复 | 无变化 | +端点匹配文献 | CCM 唯一真源、tau 审计修复、IAAFT 端点匹配 |
| **工程审计** (7/8-9) | 7→14 条设计 | 无变化 | +33 篇论文 | `forbidden_rules_reference.md` 扩展至 14 条 + `[C][D][E]` 溯源标注 |
| **案例落地** (7/9-10) | 14 条设计 | 音神 + 游戏数据 | 已完备 | `examples/yinshen/` + `examples/game_analysis/` 自包含案例 |
| **AI 代码实现** (7/10) | 14 条实现 | 无变化 | 已完备 | S8-S14 代码落地、`ccm_batch_test`、`common_driver_disclaimer` |
| **第二轮 AI 精修** (7/11) | 14 条实现 | 无变化 | 已完备 | Inf/NaN 边界防御、`analysis_type` 参数、S11 输出集成 |
| **当前版本** (7/12) | **14 条设计+实现** | **双案例** | **39 篇** | + FDR 方向资格修复 (Round 13) |

---

## 2. 规则体系：7 → 14

```
原始 7 条:                              扩展为 14 条:
S1 Lyapunov Horizon                    S1 Lyapunov Horizon
S2 CCM Victim Mirror                   S2 CCM Victim Mirror
S3 Hankel Golden Ratio                 S3 Hankel Golden Ratio
S4 Multiview Embedding                 S4 Multiview Embedding
S5 SVD Residual Monitor               S5 SVD Residual Monitor
S6 EDM-HAVOK Cross-Validation          S6 EDM-HAVOK Cross-Validation
S7 CCM Arrow Trap                      S7 CCM Arrow Trap
                                       ─────────────────────
                                       S8 Stationarity Gate
                                       S9 Observation Genericity
                                       S10 Seasonality Confound
                                       S11 Common Driver Disclaimer
                                       S12 Prediction Decay Profile
                                       S13 Multiple Comparison Correction
                                       S14 Nonlinear Sampling Adequacy
```

每条规则现在标注了：
- `[G]`/`[D]`/`[I]` 三性质分类（关卡/诊断/解释）
- ★★★★/★★★/★★/★ 四档强度权重
- `[C]`/`[D]`/`[E]` 三类数值溯源（规范值/推导值/工程启发值）
- 按数据画像 (N, K, 二元, 分析目标) 的激活矩阵

---

## 3. 核心架构演进

| 维度 | 旧版 | 当前版 |
|------|------|--------|
| **防火墙层数** | 1 层 (auditor) | **3 层纵深防御** |
| **CCM 因果判定** | 2 处独立实现，规则不一致 | `ccm_causality.py` 唯一真源 |
| **HAVOK 稳定性** | 3 处硬编码阈值 | `classify_havok_stability()` 单一真源 |
| **Hankel 比** | 2 处硬编码阈值 | `classify_hankel_ratio()` 共享函数 |
| **规则激活** | 全部执行 | **按数据画像智能分流** |
| **多重比较** | 无 | `ccm_batch_test()` + FDR/Bonferroni |
| **公共驱动** | 无声明 | 所有 CCM 输出自动附带 (S11) |
| **分析类型** | 硬编码 "exploratory" | `analysis_type` 参数化 (驱动 S13) |

---

## 4. 关键 Bug 修复历程

### Round 9 (独立重审计)
| Bug | 影响 | 修复 |
|-----|------|------|
| CCM 判定逻辑重复+不一致 | 同一数据可能得到不同因果结论 | `ccm_causality.py` 唯一真源 |
| tau 审计 FAIL 永远降级为 WARN | 超限嵌入窗口无法被拦截 | 显式 `critical` 布尔标志 |
| IAAFT 缺少端点匹配 | 代理数据 kurtosis 虚高 3-5x | Theiler & Prichard (1996) 端点匹配 |
| HAVOK 退化输入静默 NaN | `explained_var_` 成 NaN 传播 | 显式 0.0 + 警告 |
| Logistic 基准退化初始值 | 混沌检测自测永远失败 | x0 0.5 → 0.2 |

### Round 10 (14 规则扩展)
- `forbidden_rules_reference.md` 从 165 行 → 1128 行
- `fourteen_rules_bibliography.md` (39 篇论文, 按规则索引)
- 数值溯源体系 `[C][D][E]` 覆盖全部 63 个阈值

### Round 11 (纯噪声收敛防御)
| Bug | 影响 | 修复 |
|-----|------|------|
| CCM `is_converging` 被纯噪声满足 | 无信号的噪声对被标为"收敛" | `abs(final_rho) > strong_direction_rho` 加入收敛判定 |

### Round 12 (边界防御)
- Inf/NaN 过滤：S9 泛型性检查不再将 ±Inf 计为"合法唯一值"
- `pipeline.py` 早期 NaN/Inf 拦截：在 Layer 2 计算之前就拒绝坏数据

### Round 13 (FDR 方向资格 bug — 7/12 其它AI 来源)
| Bug | 影响 | 修复 |
|-----|------|------|
| `_benjamini_hochberg()` 只检查 `abs(final_rho)` 就接受 p 值，未检查方向是否真正收敛 | 发散方向的 p 值（负 Spearman 确认不收敛）被纳入 FDR 排名，挤占收敛方向的校正名额 | 准入门槛增加 `is_converging` 三条件：total_rise > 0.05、spearman_rho > 0.7、final_rho > strong_direction_rho。附带合成 fixture 回归测试 |

---

## 5. 案例体系

| 案例 | N | 数据类型 | 验证的关键规则 |
|------|---|---------|-------------|
| **游戏数据** | 32 | 连续+二元混合 | S3 Hankel 自动修正, S9 二元目标 |
| **音神序列** | 120 | 类别整数编码 | S2 CCM-E 一致性, S6 EDM-HAVOK 分歧 |

每个案例自包含：`run_analysis.py` + `README.md` + `data/` + `figures/`。

---

## 6. 文件结构变化

```
旧版:                                  当前版:
edm-takens/                            edm-takens/
├── data/game_log.csv                  ├── examples/
├── examples/demo.py                   │   ├── game_analysis/    ← 自包含案例
└── ...                                │   └── yinshen/          ← 自包含案例
                                       ├── references/
                                       │   ├── forbidden_rules_reference.md  (7→14条)
                                       │   └── fourteen_rules_bibliography.md ← 新增
                                       └── docs/
                                           ├── edm-takens-skill-intro.md      ← 新增
                                           └── edm-takens-skill-diff-report.md ← 本文件
```

核心源文件增量：
- `edm_auditor.py`: +S8/S9/S10 实现 + Inf/NaN 过滤
- `ccm_causality.py`: +S11/S13 + Round 11 纯噪声防御
- `sovereign_havok.py`: +S14 采样充分性 + `edm_guided_havok`
- `final_interpretation.py`: +HAVOK 集成 + S11 输出
- `pipeline.py`: +`analysis_type` 参数 + 早期 NaN/Inf 拦截

---

## 7. 使用建议

```bash
# 解包
python -m zipfile -e edm-takens.skill .

# 安装依赖
cd edm-takens
pip install -r requirements.txt

# 运行案例
python examples/game_analysis/run_analysis.py   # 32 场游戏
python examples/yinshen/run_analysis.py          # 120 音素序列

# 通用管线
python run_pipeline.py --data your_data.csv --target result --auto-fix

# 完整测试
python run_tests.py
```
