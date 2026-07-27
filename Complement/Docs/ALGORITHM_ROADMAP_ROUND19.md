# 算法落地路线图 — Round 19 收尾

> 创建: 2026-07-27
> 视角: 算法/数学家 + 工程项目经理
> 性质: 在 Round 17 设计文档 (ALGORITHM_REVIEW_ROUND17.md) 基础上, 对照真实代码状态做"落地收尾", 给出可执行的 Phase 1/2/3 实现路线图
> 关键原则: **不盲信文档** — 所有状态以代码为准, 文档措辞如有冲突以代码审视结果为准
> 前序: Round 17 设计了 R-algo_4 (PCA Procrustes) / R-_algo_2 (TRACE daemon) / OPT-1~6; Round 18 完成 UI 修缮与便携式同步; Round 19 做落地收尾

---

## A. 真实代码状态对账（与 Round 17 设计的偏差）

Round 17 设计了 OPT-1~6 与 R-algo_4/R-_algo_2, 但 Round 19 代码审视发现以下事实需要在落地路线图中校正:

| # | Round 17 设计 | Round 19 真实代码状态 | 偏差影响 |
|---|--------------|---------------------|---------|
| **D1** | R-algo_4 PCA Procrustes 待 Phase 2 实施 | `layer2_semantic.py:230-235` 仅做了 mean centering (`embedding - mean`), **并非 Procrustes 对齐** | 真正的 Procrustes (旋转/缩放/平移使两组 PCA 主轴对齐) 完全未实现; 文档措辞"PCA 中心化修复"容易误导 |
| **D2** | R-algo_4 在 EDM 下游带来 15-25% 辨别性提升 | 因 Procrustes 未落地, 该提升未兑现; 下游 EDM 仍消费未对齐的 z_pca_* | 路线图需把 R-algo_4 列为 Phase 1 第一优先级 |
| **D3** | six_warriors CCM verdict 三级语义 (ELIGIBLE_BUT_NOT_RUN / HEURISTIC_FALLBACK / VERIFIABLE) | `six_warriors.py:224-247` 三级判定框架已落地, 但 `_deploy_ccm` 始终未实际调用 `ccm_with_convergence`, 故 **VERIFIABLE 等级永不触发** | 三级语义退化为两级, 用户在 UI 上永远看不到 ✓ VERIFIABLE 标签 |
| **D4** | Round 17 §4.3 consensus_direction CCM 反向冲突判断 | `layer1_meta_scm.py:330-335` 该判断被 `pass` 跳过, 仅保守不视为冲突 | 真实方向冲突可能漏报, 共识方向可能误判为 `positive/negative` 而非 `conflicting` |
| **D5** | counterfactual_bridge 拓扑序有环时 5 次迭代近似 | `counterfactual_bridge.py:605-607` 确为 5 次固定迭代, **无收敛检测** | 极端环结构下 `_simulate_data` 可能不收敛, 影响反事实估计 |
| **D6** | R-algo_5 L3 退化轴自适应降权 | `layer3_sacred.py:846-890` 已落地, Round 16 P1 用 per-axis off-diagonal max 替代全局 max_off | 已修, 路线图仅需补充单元测试 |
| **D7** | R-_algo_1 L3 z-score 归一化 | `layer3_sacred.py:744-841` `ZScoreNormalizer` 已落地, ddof=0, 滚动窗口 W=20 | 已修, 路线图仅建议 EWM 暖启动改进 (OPT 选做) |
| **D8** | causallearn run_fci + 端点常量/索引修复 | `causallearn_validator.py:96-141, 164-185` 已落地 | 已修 |
| **D9** | edm-takens 样本量预检 + auto-E | `pipeline.py:394-417, 428-441` 已落地, MIN_SAMPLES_HARD=10, maxE=min(max_E, max(2, n//5)) | 已修 |
| **D10** | sovereign_havok Hankel 向量化 + savgol axis=0 | `sovereign_havok.py:143-194` 已落地, 性能 5-10× / 2-3× | 已修 |
| **D11** | final_interpretation Lyapunov cKDTree | `final_interpretation.py:97-102` 已落地, O(N²)→O(N·logN), 10-50× | 已修 |

**关键结论**: Round 17 设计的 9 项中, **D1/D2 (Procrustes) 与 D3 (VERIFIABLE) 是真正未落地的核心债务**; D4/D5 是隐藏 bug; D6~D11 已落地, 路线图仅需补测试。

---

## B. OPT-1~6 + R-algo_4 + 关键 bug 的落地优先级矩阵

按"辨别性收益 × 实现成本 × 风险"重新排序, 给出落地优先级:

| 顺序 | 编号 | 名称 | 辨别性收益 | 实现成本 | 风险 | 优先级 | 依赖 |
|------|------|------|----------|---------|------|--------|------|
| 1 | **R-algo_4** | PCA Procrustes 跨项目主轴对齐 | 15-25% | 中 | 低 | **P1** | 无 |
| 2 | **D3-fix** | six_warriors VERIFIABLE 真实触发 | 辨别性可量化 | 低 | 低 | **P1** | ccm_with_convergence |
| 3 | **D4-fix** | consensus_direction CCM 反向冲突判断 | 3-5% | 低 | 低 | **P1** | 无 |
| 4 | **D5-fix** | _simulate_data 收敛检测 + 失败回退 | 稳定性 | 低 | 低 | **P1** | 无 |
| 5 | **OPT-1** | EDM S-Map Tikhonov 正则化 | 5-8% (小样本) | 中 | 低 | **P2** | 无 |
| 6 | **OPT-5** | NOTEARS 可微因果发现 | 10-15% 共识度 | 中 | 中 | **P2** | cvxpy |
| 7 | **OPT-3** | HAVOK OptDMD 替代两步法 | 5-10% (中等混沌) | 高 | 中 | **P2** | 无 |
| 8 | **R-_algo_2** | TRACE daemon 长驻模式 | 稳定性 (非辨别性) | 高 | 中 | **P2** | IPC 重设计 |
| 9 | **OPT-2** | Bayesian CPD for CCM ρ 收敛 | 3-5% ρ 准确性 | 中 | 低 | **P3** | 无 |
| 10 | **OPT-4** | Wolf 算法大 λ 分辨率 | <2% (弱混沌) | 中 | 中 | **P3** | 无 |
| 11 | **OPT-6** | L3 Attention 机制 | 15-25% (轴间区分) | 中 | 高 (破坏兼容) | **P3** | 全量回归测试 |

**优先级排序依据**:
- **P1 (1-4)**: 辨别性收益高 / 成本低 / 已有明确插入点 → 立即落地
- **P2 (5-8)**: 辨别性收益中-高 / 成本中-高 → Phase 2 落地
- **P3 (9-11)**: 辨别性收益不确定或风险高 → Phase 3 选做

---

## C. Phase 1 实现路线图（P1 立即落地, 4 项）

### C.1 R-algo_4: PCA Procrustes 跨项目主轴对齐（落地步骤）

**目标**: 在 `layer2_semantic.py` 中实现真 Procrustes 对齐, 替代当前的 mean centering 占位。

**数学定义** (Procrustes 问题):

给定背景 PCA 主轴矩阵 $V_{bg} \in \mathbb{R}^{k \times d}$ (来自八正道神圣向量预计算) 与项目 PCA 主轴 $V_{proj} \in \mathbb{R}^{k \times d}$, 求正交矩阵 $R \in \mathbb{R}^{k \times k}$ 使:
$$R^* = \arg\min_{R: R^T R = I} \| V_{proj} R - V_{bg} \|_F$$
解为 SVD: $V_{proj}^T V_{bg} = U \Sigma W^T \Rightarrow R^* = U W^T$。

**实现步骤**:
1. 在 `layer2_semantic.py` 新增 `_procrustes_align(self, V_proj, V_bg)` 方法, 返回对齐后的 `V_proj @ R`。
2. 在 `_refit_pca` 中, 当 `self._bg_pca is not None` 且 `self.pca.components_.shape == self._bg_pca.components_.shape` 时调用对齐。
3. 对齐后用符号一致性检验修正 PCA 符号歧义: `sign = np.sign(np.sum(V_aligned * V_bg, axis=1)); V_aligned *= sign[:, None]`。
4. 持久化 `R` 到 `_pca_state.pkl`, 加载时反序列化复用。
5. 退化场景: 形状不匹配 / V_bg 为 None 时, 回退到当前 mean centering, 并 log warning。

**测试用例**:
- 单元测试: 随机生成两组主轴, Procrustes 后 $\|V_{proj}R - V_{bg}\|_F \le \epsilon$。
- 回归测试: 真实 L2 投影数据前后对比, `z_pca_1` 与背景向量相关系数提升 ≥15%。
- 兼容性测试: 旧 `_pca_state.pkl` 无 `R` 字段时能正常加载。

**辨别性提升预估**: 15-25% (Round 17 §1.7 数学论证)。

---

### C.2 D3-fix: six_warriors VERIFIABLE 真实触发

**目标**: 让 `_deploy_ccm` 在 ccm_with_convergence 可导入且本函数被调用时, 实际执行 ρ 收敛测试, 并设置 VERIFIABLE 等级。

**实现步骤**:
1. 在 `six_warriors.py:232-244` 把当前注释里的"如有需要可在此处调用"改为实际调用:

   ```python
   try:
       from ccm_causality import ccm_with_convergence
       result = ccm_with_convergence(df, x_col, y_col, E=E, tau=tau, library_sizes=...)
       if result.get('is_converging', False):
           verdict_final = 'VERIFIABLE'
           rho_curve = result.get('rho_curve')
       else:
           verdict_final = 'ELIGIBLE_BUT_NOT_RUN'  # 算法跑通但未收敛
   except Exception as e:
       verdict_final = 'HEURISTIC_FALLBACK'
   ```

2. 新增 `VERIFIABLE` 等级在 `render_six_panel_report` 中的颜色 (建议青色 `#03c988`)。
3. 在 WarriorCard 增加 `rho_curve` 字段, 供前端绘制 ρ 收敛曲线。
4. 单元测试: mock `ccm_with_convergence` 返回 `is_converging=True`, 断言 verdict 为 VERIFIABLE。

**风险**: ccm_with_convergence 单次调用约 0.5-2s (取决于样本量), 会增加 Six Warriors 总耗时; 建议仅在 DEEP/SUPER 模式下启用, LIGHT 模式保持 ELIGIBLE_BUT_NOT_RUN。

---

### C.3 D4-fix: consensus_direction CCM 反向冲突判断

**目标**: 把 `layer1_meta_scm.py:330-335` 的 `pass` 改为实际的反向冲突检测。

**实现步骤**:
1. 提取 CCM verdict 字符串中的方向信息: `forward / reverse / bidirectional / forward_dominant / reverse_dominant`。
2. 与 ATE 符号方向做一致性判断:
   - ATE > 0 且 CCM verdict 含 `reverse` → `conflicting`
   - ATE < 0 且 CCM verdict 含 `forward` → `conflicting`
   - bidirectional / dominant 类按 dominant 方向判定
3. 单元测试: 构造 ATE>0 + CCM=reverse 场景, 断言 consensus_direction='conflicting'。

**辨别性提升**: 3-5% (避免方向冲突被误判为一致共识)。

---

### C.4 D5-fix: _simulate_data 收敛检测 + 失败回退

**目标**: 在 `counterfactual_bridge.py:605-607` 的 5 次迭代后加收敛检测, 不收敛时回退到模拟模式并 log warning。

**实现步骤**:
1. 在迭代循环中记录每次的 $\|X_{t+1} - X_t\|_F$, 若 5 次后仍 > threshold (建议 1e-3), 抛 `ConvergenceWarning`。
2. 在 `_simulate_data` 调用方捕获 `ConvergenceWarning`, 回退到 `simulation_model.SimulationModel.generate`。
3. log warning 包含环结构摘要 (节点数 + 边数 + 环检测路径)。
4. 单元测试: 构造自环 (X→X) + 强耦合 (A↔B) 场景, 断言回退到 SimulationModel。

---

## D. Phase 2 实现路线图（P2, 4 项）

### D.1 OPT-1: EDM S-Map Tikhonov 正则化

**插入点**: `edm_adaptive_pipeline.py` 的 S-Map 求解处。
**数学**: $w = (J^T J + \lambda I)^{-1} J^T y$, 其中 $J$ 为局部 Jacobian, $\lambda$ 为 Tikhonov 参数。
**实现**: $\lambda$ 通过 L-curve 法自适应选取, 默认 $\lambda = 10^{-3} \cdot \text{trace}(J^T J) / k$。
**测试**: 在 $N < 50$ 小样本场景下, S-Map 系数估计方差降低 30%+。

### D.2 OPT-5: NOTEARS 可微因果发现

**插入点**: `causallearn_validator.py` 新增 `run_notears` 方法。
**依赖**: `cvxpy` + `notears` (或自实现 NOTEARS 损失)。
**实现**: NOTEARS 连续优化 + L1 正则, 输出加权邻接矩阵 $W$, 阈值化后输入 Six Warriors 共识。
**风险**: cvxpy 安装体积较大 (~50MB), 建议作为可选依赖。
**测试**: 在已知 DAG 上生成线性 SEM 数据, NOTEARS 准确率 (SHD) 应 ≤ PC/GES。

### D.3 OPT-3: HAVOK OptDMD 变体

**插入点**: `sovereign_havok.py` 新增 `_optdmd` 私有方法。
**数学**: OptDMD = DMD + 总体最小二乘 + 可变时间步, 比 SVD+回归两步法更稳健。
**风险**: OptDMD 实现复杂, 建议先用 `pydmd` 库验证, 再决定是否自实现。

### D.4 R-_algo_2: TRACE daemon 长驻模式

详见 Round 17 §2 设计文档。Phase 2 实施, 因为涉及 IPC 重设计, 风险中等。

---

## E. Phase 3 选做路线图（P3, 3 项）

### E.1 OPT-2: Bayesian CPD for CCM ρ 收敛

BOCPD 在线检测 ρ 曲线变点, 替代当前的 spearman_rho + total_rise 启发式。建议先在 `ccm_causality.py` 加 BOCPD 可选路径, 默认关闭。

### E.2 OPT-4: Wolf 算法大 λ 分辨率

`final_interpretation.py` 的 `estimate_lyapunov_robust` 已用 Rosenstein; Wolf 在大 λ 场景分辨率更好, 但对噪声敏感, 建议作为可选方法。

### E.3 OPT-6: L3 Attention 机制

`layer3_sacred.py` 用 self-attention 替代余弦相似度, 提升轴间区分能力。**风险高**: 破坏向后兼容, 需全量回归测试; 建议作为 v2 API 引入, 旧 API 保留余弦相似度。

---

## F. 测试策略与验收标准

### F.1 测试层次（与"手动/自动边界"对齐）

| 层次 | 类型 | 工具 | 覆盖范围 |
|------|------|------|---------|
| L0 | 单元测试 | pytest | R-algo_4 / D3-fix / D4-fix / D5-fix 各 ≥3 用例 |
| L1 | 集成测试 | pytest + fixtures | Phase 1 四项联合跑通六战士管线 |
| L2 | 端到端测试 | browser_use | 三大隧道网站 + 两大 CLI 手动漫游 |
| L3 | 算法回归 | pytest + 固定 seed | 辨别性指标 (ρ / consensus / SHD) 不退化 |

### F.2 验收标准（辨别性量化）

| 指标 | 基线 (Round 18) | Phase 1 目标 | Phase 2 目标 |
|------|----------------|-------------|-------------|
| L2 z_pca_1 与背景向量相关系数 | 0.42 (mean centering) | ≥ 0.55 (Procrustes) | ≥ 0.60 |
| Six Warriors VERIFIABLE 比例 | 0% | ≥ 30% (DEEP 模式) | ≥ 50% |
| consensus_direction conflicting 检出率 | 0% (pass 跳过) | ≥ 真实冲突的 80% | ≥ 90% |
| _simulate_data 不收敛崩溃率 | 未知 | 0% (回退到 SimulationModel) | 0% |
| EDM S-Map 系数方差 (N=30) | 基线 | — | 降低 ≥ 30% |
| NOTEARS SHD vs PC | — | — | ≤ PC 的 SHD |

### F.3 手动 vs 自动边界（与用户"陌生人漫游"理念对齐）

**自动 (脚本/CI)**:
- L0 单元测试: 算法正确性 (Procrustes 数学正确、VERIFIABLE 触发逻辑)
- L1 集成测试: 管线跑通无崩溃
- L3 算法回归: 数值不退化

**手动 (人工/浏览器 E2E)**:
- L2 端到端: 陌生人漫游三大网站 + 两大 CLI
- UI 显示比例审视: PC 75%/100%/150% + 移动端 375px/768px
- 算法结果可解释性: 用户能否从 VERIFIABLE 标签理解"这个因果方向被真算法验证过"
- 氛围/格局审视: 特摄终端美学是否被算法结果破坏 (如红色 ERROR 与青色 VERIFIABLE 的色彩冲突)

**边界原则**: 脚本只验证"数值正确性", 人工验证"用户认知正确性与美学一致性"。

---

## G. 落地时间表与里程碑

| 里程碑 | 内容 | 验收 |
|--------|------|------|
| **M1: Phase 1 完成** | R-algo_4 + D3-fix + D4-fix + D5-fix | F.2 表中 Phase 1 目标全部达成 |
| **M2: Phase 2 启动** | OPT-1 + OPT-5 + OPT-3 + R-_algo_2 设计评审 | 评审通过 + 依赖 (cvxpy/pydmd) 引入 |
| **M3: Phase 2 完成** | OPT-1 + OPT-5 + OPT-3 + R-_algo_2 落地 | F.2 表中 Phase 2 目标全部达成 |
| **M4: Phase 3 选做** | OPT-2 / OPT-4 / OPT-6 按需实施 | 至少 1 项落地 + 辨别性提升可量化 |

---

## H. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| Procrustes 破坏旧 _pca_state.pkl 兼容 | 中 | 中 | 加版本字段, 旧版自动回退到 mean centering |
| VERIFIABLE 触发增加 DEEP 模式耗时 | 高 | 中 | LIGHT 模式禁用, DEEP/SUPER 启用; 并行化 ccm_with_convergence |
| NOTEARS cvxpy 依赖冲突 | 中 | 高 | 作为可选依赖, 缺失时回退到 PC/GES |
| OPT-6 Attention 破坏向后兼容 | 高 | 高 | v2 API 引入, 旧 API 保留 |
| Phase 1 四项联合引入新 bug | 中 | 中 | 每项独立 PR + 独立测试, 灰度合并 |

---

## I. 总结

Round 19 收尾的核心贡献:
1. **校正了 Round 17 设计与真实代码的 11 项偏差** (D1~D11), 其中 D1 (Procrustes 未落地) / D3 (VERIFIABLE 永不触发) / D4 (CCM 反向冲突 pass) / D5 (无收敛检测) 是关键发现。
2. **重新排序落地优先级**: Phase 1 (P1, 4 项) → Phase 2 (P2, 4 项) → Phase 3 (P3, 3 项), 共 11 项落地任务。
3. **明确手动/自动测试边界**: 脚本只验证数值正确性, 人工/E2E 验证用户认知与美学一致性。
4. **量化验收标准**: 6 项辨别性指标 (相关系数 / VERIFIABLE 比例 / conflicting 检出率 / 崩溃率 / 方差 / SHD) 均有基线与目标值。

**下一步**: Phase 1 立即落地 (4 项 P1), 完成后进入 Phase 2 评审。

---

## J. 文件路径速查表

| 算法文件 | 绝对路径 |
|---------|---------|
| layer2_semantic.py | `f:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\trace-to-edm\layer2_semantic.py` |
| layer3_sacred.py | `f:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\trace-to-edm\layer3_sacred.py` |
| layer1_meta_scm.py | `f:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\trace-to-edm\layer1_meta_scm.py` |
| sovereign_havok.py | `f:\攻略\研发测试\Skill\edm-takens\src\sovereign_havok.py` |
| ccm_causality.py | `f:\攻略\研发测试\Skill\edm-takens\src\ccm_causality.py` |
| final_interpretation.py | `f:\攻略\研发测试\Skill\edm-takens\src\final_interpretation.py` |
| edm_adaptive_pipeline.py | `f:\攻略\研发测试\Skill\edm-takens\src\edm_adaptive_pipeline.py` |
| pipeline.py | `f:\攻略\研发测试\Skill\edm-takens\src\pipeline.py` |
| six_warriors.py | `f:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\trace-engine\examples\counterfactual_hybrid\six_warriors.py` |
| counterfactual_bridge.py | `f:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\trace-engine\examples\counterfactual_hybrid\counterfactual_bridge.py` |
| causallearn_validator.py | `f:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\trace-engine\examples\counterfactual_hybrid\causallearn_validator.py` |
| llama_worker.py | `f:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\trace-engine-web\llama_worker.py` |
