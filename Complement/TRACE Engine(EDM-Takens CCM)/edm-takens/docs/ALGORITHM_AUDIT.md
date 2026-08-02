# EDM-Takens 算法与工程审计报告

> 审计对象：`f:\攻略\研发测试\Skill\edm-takens`（原生项目，非 Web 版本）  
> 审计日期：2026-07-13  
> 审计范围：`src/pipeline.py`、`src/enhanced_cross_validate.py`、`src/ccm_causality.py`、`src/sovereign_havok.py`、`src/edm_auditor.py`、`src/final_interpretation.py`、`src/_edm_bridge.py`、`src/_numpy_edm.py`  
> 结论：核心算法实现正确，测试全部通过；本轮审计修复了 2 处真实隐患，另有若干已知限制已在下文明示。

---

## 1. 测试结果（精确记录）

| 测试项 | 命令 | 结果 | 耗时 |
|--------|------|------|------|
| 快速测试套件 | `python run_tests.py --quick` | **89 passed, 0 failed, 0 skipped** | ~196–235 s |
| 完整测试套件 | `python run_tests.py` | **96 passed, 0 failed, 0 skipped** | ~382 s |
| CCM 模块自测 | `python src/ccm_causality.py` | 全部通过 | ~180 s（已优化） |
| HAVOK 模块自测 | `python src/sovereign_havok.py` | 全部通过 | < 10 s |
| NumPy EDM 回退自测 | `python src/_numpy_edm.py` | 全部通过 | < 5 s |

> 注：快速/完整测试套件已包含 `src/ccm_causality.py` 与 `src/sovereign_havok.py` 的子进程自测（`Layer 7: Module Self-Tests`）。

---

## 2. 已修复问题

### 2.1 `_numpy_edm.CCM` 收敛判定与主路径不一致

**问题描述**

`src/_numpy_edm.py` 是纯 NumPy/SciPy 的 EDM 回退实现，当 `pyEDM` 不可用时通过 `src/_edm_bridge.py` 被调用。其 `CCM()` 函数的收敛判定仅检查：

```python
is_converging = total_rise > 0.05 and spear_rho > 0.7
```

而规范实现 `src/ccm_causality.py` 的 `ccm_causality_test()` 使用更严格的标准：

```python
total_rise > 0.05 and spear_rho > 0.7 and spear_p < 0.1 and abs(final_rho) > 0.2
```

这导致：
1. **判定不一致**：同一组数据在 pyEDM 路径与 numpy 回退路径可能得到不同的 `is_converging`。
2. **样本量伪显著**：库大小扫描点很多时（长序列），近零噪声曲线可能因 Spearman 样本量效应得到极高的 `spear_rho` 和极小的 `spear_p`，从而被误判为收敛。
3. **返回字段缺失**：`_numpy_edm.CCM()` 返回字典缺少 `spearman_p`，而下游调用者（如 `ccm_causality_test()` 在桥接层）期望该字段存在。

**修复内容**

在 `src/_numpy_edm.py` 的 `CCM()` 中：
- 将收敛判定与 `ccm_causality_test()` 对齐，加入 `spearman_p < 0.1` 与 `abs(final_rho) > 0.2` 门控。
- 在返回字典中显式加入 `spearman_p`。

**验证**

`python src/_numpy_edm.py` 自测仍通过，且耦合系统 X→Y 仍正确报告 `converging=True`。

---

### 2.2 `pipeline.py` 小样本 Hankel 自校正信息不完整

**问题描述**

`PipelineConfig.auto_correct()` 在 `p/q < 10` 时会推荐或自动将 `q` 降至 `max(2, (n+1)//11)`。然而：
1. 报告信息只显示**校正前**的 `p/q`，用户无法直观看到校正后的比例。
2. 当样本量过小时（如 `n < 22`），即使 `q=2` 也无法达到 `p/q >= 10`，但代码未明确告知用户这一数学极限，可能让用户误以为自动修正已解决数值稳定性问题。

**修复内容**

在 `src/pipeline.py` 的 `auto_correct()` Rule 1 中：
- 计算并报告校正后的 `p/q`。
- 当 `n` 小到无法使 `p/q >= 10` 时，追加明确提示：
  > "With N={n}, p/q>=10 is impossible while maintaining q>=2 (best achievable p/q={ratio_new:.1f}). Collect more data or treat results as exploratory."

**影响**

仅改变日志/提示文本，不改变实际参数选择，对现有通过用例保持行为一致。

---

### 2.3 跨项目同步修复记录（ROUND26-27 科研严谨性审查）

以下修复虽发生在 trace-engine 项目，但影响 edm-takens 的算法契约，
故在此记录以保证审计完整性（详见 ROUND26_ALGORITHM_REVIEW.md）：

| 修复 ID | 文件 | 问题描述 | 修复内容 |
|---------|------|----------|----------|
| P0-1 | enhanced_cross_validate.py:138, 587 | Lyapunov log(0) 防护不一致 (final_interpretation.py:127 已用 where 掩码 + nanmean, enhanced_cross_validate.py 仍用 log(div + 1e-12)) | 同步为 where 掩码 + nanmean，消除 -27.6 偏差导致的 λ_max 系统性低估 |
| P1-2 | _numpy_edm.py:540-541 | CCM 使用 in-sample cross-map 导致 ρ 高估 (Sugihara 2012 要求 out-of-sample) | 增加 out_of_sample 参数，lib_size >= 2*(E+2) 时拆分 train/test 评估 ρ |
| P1-4 | edm_tau_optimization.py:12-43 | AMI 使用 histogram-based 而非 KSG 估计器 (小样本严重偏差) | 新增 mi_estimator='ksg' 参数, 默认尝试 KSG (sklearn.feature_selection.mutual_info_regression), 失败回退 histogram + 自适应 bins |
| S2-1 | sovereign_havok.py:252 | _auto_truncate 引用未定义的 H 变量 (Gavish-Donoho 已知噪声路径会 NameError) | fit() 在调用 _auto_truncate 前存储 self._H_shape_ = H.shape |
| S2-2 | sovereign_havok.py:255-257 | Gavish-Donoho 已知噪声阈值维度公式错误 (用 sqrt(_q) 应为 sqrt(min(_p,_q))) | 改为 sqrt(min(_p, _q)) + 校准 lambda(beta) 表值 (Gavish & Donoho 2014 Table 1) |
| S2-3 | pipeline.py:781 | 全局 RNG 污染 (np.random.seed 影响同进程其他随机操作) | 在 PipelineConfig 加 reproducibility_seed 字段, 创建独立 Generator _pipeline_rng 供支持 rng 透传的子模块使用 |
| S1-1 | ccm_causality.py:612-613 | IAAFT surrogate silent failure (except: pass 静默吞错, 失败比例高时 p 值误导) | 记录异常到 stderr + 失败比例 > 50% 时设 surrogate_p_value=None |
| S1-2 | ccm_causality.py:752 | effect-size gating 默认路径破坏 BH uniform-null 假设 (未显式披露保证级别) | 添加 is_strict_confirmatory 布尔字段，True 当且仅当 use_surrogate_p=True + analysis_label in {'confirmatory', 'preregistered'} |
| S1-3 | _numpy_edm.py:665 | CCM out-of-sample 拆分改变有效库大小 (用户指定 lib_size=100 实际建树 50) | 添加 effective_lib_sizes + out_of_sample_used 字段，下游消费者可据此选择措辞 |

---

## 3. 已确认健康、无需修改的部分

| 模块/功能 | 审计结论 |
|-----------|----------|
| `src/ccm_causality.py` | 收敛判定、双向 CCM、Secret 11 免责声明、Benjamini-Hochberg/Bonferroni 多重比较校正、效应量门控均已实现且自测通过。 |
| `src/_edm_bridge.py` | Windows 下强制 `legacy='ccm_24'` 以避免并行死锁；pyEDM 不可用时回退 `_numpy_edm` 路径正确。 |
| `src/final_interpretation.py` | `ccm_with_convergence()` 已透传 `lib_sizes` 到规范 `ccm_causality_test()`；`final_rho` 为空时格式字符串已做保护。 |
| `src/edm_auditor.py` | CCM 收敛防火墙已包含 `spearman_p < 0.1` 与 `abs(final_rho) > 0.2`；NaN/Inf 在数据质量、平稳性、观测泛化性、周期性检查中均被过滤；Hankel 比例阈值由 `classify_hankel_ratio()` 单点维护。 |
| `src/pipeline.py` | 非有限目标值前置拦截、后计算审计反馈已完整传入 CCM 收敛指标与 HAVOK 峰度。 |
| `src/sovereign_havok.py` | 小样本 SG 窗口自适应封顶、V/U 双基一致、稳定性分类函数 `classify_havok_stability()` 单点维护。 |
| `src/enhanced_cross_validate.py` | CCM 方向验证已统一走 `ccm_causality_test()`；Hankel 比例检查复用 `classify_hankel_ratio()`。 |

---

## 4. 剩余风险与建议

以下并非代码缺陷，而是方法学/小样本固有约束，需在解释与报告中持续披露：

1. **小样本 CCM 的 ρ 天花板**
   - 二值目标（如 `result`）的理论上限约为 0.87；样本量 N≈30 时，即使存在真实耦合，CCM 也可能因库大小不足而报 `converging=False`。建议始终结合 Secret 11 免责声明，并将结论表述为“动态耦合”而非“机械因果”。

2. **Hankel 比例在小样本下的数学极限**
   - 当 `n < 22` 时，即使 `q=2` 也无法满足 `p/q >= 10`。自动修正会给出最佳可行 `q` 并提示该极限，但无法从算法上消除数值刚度。此时应视 HAVOK 稳定性分类为探索性。

3. **Lyapunov 时间估计不可靠**
   - 当前实现（Rosenstein 算法 + R² 门控）在 N<100 时主动标记为 `UNRELIABLE`。这是预期行为，不要降低阈值来“制造”显著性。

4. **numpy 回退的精度边界**
   - `_numpy_edm` 保证功能可用，但近邻搜索与 bootstrap 行为与 C++ pyEDM 存在实现差异。在科研级分析中建议优先安装 pyEDM。

5. **CCM 多重比较**
   - `ccm_batch_test()` 已按探索性/验证性/预注册三种场景分别使用 BH-FDR / Bonferroni / 无校正。当 `K >= 5` 对时，即使经 BH 校正仍会提示族错误率膨胀风险，这是设计意图。

---

## 5. 变更文件清单

| 文件 | 变更类型 | 变更理由 |
|------|----------|----------|
| `f:\攻略\研发测试\Skill\edm-takens\src\_numpy_edm.py` | 修改 | 统一 numpy 回退 CCM 收敛判定与 `ccm_causality_test()`，补全 `spearman_p` 返回字段。 |
| `f:\攻略\研发测试\Skill\edm-takens\src\pipeline.py` | 修改 | 小样本 Hankel 自校正报告校正后比例，并在不可达 `p/q>=10` 时显式提示用户。 |
| `f:\攻略\研发测试\Skill\edm-takens\docs\ALGORITHM_AUDIT.md` | 新建 | 汇总本轮审计发现、修复与剩余风险，作为当前权威审计文档。 |

---

## 6. 历史审计文档说明

`docs/edm-takens_skill_audit.md` 与 `docs/edm-takens_self_inspection_census.md` 为 2026-07-07 的历史审计记录，其中部分测试计数（72/80 等）与当前版本不一致。为精简文档并避免过期信息误导，这两个文件已在本轮整理中删除。本文档 `docs/ALGORITHM_AUDIT.md`（2026-07-13）为当前权威审计结论；早期修复细节亦可在 `CHANGELOG.md` 中按轮次追溯。
