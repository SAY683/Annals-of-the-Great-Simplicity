# 算法审视报告 (ROUND 26)

> 审视日期: 2026-07-28
> 审视视角: 数学家 (数学正确性 / 统计推断 / 数值稳定性 / 优化升级)
> 审视范围: trace-engine + edm-takens 两个项目的算法实现层
> 审视方法: 静态代码审视 + 数学依据核对 + 与已有审计文档交叉验证

---

## 审视范围与方法

### 审视对象

| 项目 | 路径 | 核心算法文件 |
|------|------|-------------|
| trace-engine | `TRACE Engine(EDM-Takens CCM)/trace-engine/` | six_warriors.py, counterfactual_bridge.py, causallearn_validator.py, dowhy_auditor.py |
| edm-takens | `Skill/edm-takens/` | ccm_causality.py, _numpy_edm.py, sovereign_havok.py, surrogate_test.py, edm_auditor.py, edm_tau_optimization.py, final_interpretation.py, enhanced_cross_validate.py |
| (关联) trace-engine-web | `TRACE Engine(EDM-Takens CCM)/trace-engine-web/py_bridge.py` | permutation test + bootstrap CI (DEEP 路径) |

### 审视维度

1. **统计推断正确性**: permutation test +1修正、bootstrap CI方法、多重比较校正、p值方向性
2. **因果推断数学正确性**: DoWhy estimand可识别性、CCM收敛判定、lib_size选取依据、FCI PAG解读
3. **EDM流形重构数学正确性**: Takens嵌入条件、AMI选τ、FNN选E、CCM的ρ计算skem
4. **数值稳定性**: SVD正则化、矩阵求逆、log(0)/除零防护、eps一致性
5. **优化升级可能**: O(N²)循环、numpy向量化、Numba/Cython热点、GPU加速

### 严重度分级

- **P0** — 数学错误,影响结论 (必须修复)
- **P1** — 统计偏差,影响精度 (建议修复)
- **P2** — 数值问题,影响稳定性 (建议加固)
- **P3** — 优化机会 (可选提升)

---

## 发现清单 (按严重度排序)

### P0-1: Lyapunov 指数 log(0) 防护不一致导致系统性低估

**文件**: `f:\攻略\研发测试\Skill\edm-takens\src\enhanced_cross_validate.py`
**行号**: 138, 582
**问题描述**:

`enhanced_cross_validate.py:138` 在 Lyapunov 指数估计中使用:
```python
if div[0] > 1e-12:
    div_curves.append(np.log(div + 1e-12))
```

而 `final_interpretation.py:127` 已修复为正确的 NaN 掩码方式:
```python
log_div = np.log(div, where=div > 1e-12, out=np.full_like(div, np.nan))
div_curves.append(log_div)
# ...
div_mean = np.nanmean(div_arr, axis=0)
```

`enhanced_cross_validate.py:582` 的 batch 版本同样使用旧式 `np.log(np.sqrt(...) + 1e-12)`。

**数学依据**:

Rosenstein 算法 (Rosenstein et al., Physica D, 1993) 在计算平均发散率时,对每条发散曲线 `d(k) = ||x(i+k) - x(j+k)||` 取 log。当 `d(k) → 0` 时(两条轨迹在某个时刻重合或极近):

- 旧式 `log(d + 1e-12)` 会产生 `log(1e-12) ≈ -27.6` 的人为下陷
- 这个 -27.6 的伪值被 `np.mean()` 纳入平均,系统性拉低 `div_mean` 的尾部
- 线性拟合 `slope = λ_max` 因此偏小,Lyapunov 指数被低估
- 稳定系统可能被误判为更强稳定,混沌系统可能被误判为稳定

`final_interpretation.py` 已正确用 `where` 掩码 + `nanmean` 排除这些点,但 `enhanced_cross_validate.py` 的两条路径未同步修复。

**建议修复**:

将 `enhanced_cross_validate.py:137-138` 和 `:582` 与 `final_interpretation.py:127-137` 对齐,使用 `np.log(div, where=div > 1e-12, out=np.full_like(div, np.nan))` + `np.nanmean`。

---

### P1-1: Bootstrap 置信区间使用百分位法而非 BCa

**文件**: `f:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\trace-engine-web\py_bridge.py`
**行号**: 914-927
**问题描述**:

```python
ate_bootstrap_ci = [
    float(np.percentile(ate_bootstrap, 2.5)),
    float(np.percentile(ate_bootstrap, 97.5)),
]
# ...
"ate_bootstrap_method": "percentile" if ate_bootstrap_ci else None,
```

使用了最简单的百分位法 (percentile method) 构建 95% CI。

**数学依据**:

百分位法 bootstrap CI 在以下情况下有偏 (Efron & Tibshirani, 1993, Ch. 14):

1. **偏差 (bias)**: 当 bootstrap 分布的中心 ≠ 原始估计量时,百分位法不修正偏差
2. **偏度 (skewness)**: 当统计量的抽样分布偏斜时,百分位法不对称地覆盖
3. **小样本**: N < 50 时,偏差和偏度的影响被放大

BCa (Bias-Corrected and Accelerated) 方法通过两个校正系数修正:
- `z₀`: 偏差校正,基于 bootstrap 估计 < 原始估计的比例
- `a`: 加速系数,基于 jackknife 估计的影响函数

在 py_bridge.py 的场景中 (文本因果分析, N 通常 30-200),bootstrap ATE 分布常有偏度 (因 treatment 是计数变量),百分位法的覆盖率可能偏离名义 95%。

**建议修复**:

替换为 BCa bootstrap (scipy.stats.bootstrap 已内置 `method='BCa'`),或在现有百分位法基础上至少加入偏差校正 (bias-corrected, BC)。

---

### P1-2: _numpy_edm CCM 使用 in-sample cross-map 导致 ρ 高估

**文件**: `f:\攻略\研发测试\Skill\edm-takens\src\_numpy_edm.py`
**行号**: 540-541
**问题描述**:

```python
# Predict cause values for all library points (in-sample cross-map)
for i in range(lib_size):
    target = X_lib[i]
    k = min(E + 2, lib_size)
    dists, idxs = tree.query(target, k=k)
```

注释明确标注 "in-sample cross-map":用 library 内的点作为 query target,然后在同一个 library 中找最近邻。虽然 line 549-552 有 `good = dists > 1e-15` 排除自身,但:

1. 排除自身后的最近邻仍然来自同一 library,存在数据重用
2. pyEDM 的规范实现使用 train/test 分离的 cross-validation
3. in-sample 评估会系统性高估 ρ,因为 library 内的点天然有更近的邻居

**数学依据**:

Sugihara et al. (2012, Science) 的 CCM 框架要求 cross-map skill 在 **out-of-sample** 预测上评估。in-sample 评估违反了这一假设:

- ρ 的绝对值会被高估 (过拟合)
- 但收敛性 (ρ vs lib_size 的单调上升) 仍然成立,因为更大的 library → 更近的邻居 → 更高的 in-sample ρ
- 这意味着 `is_converging` 判定的 **方向** 是对的,但 `final_rho` 的 **绝对值** 偏高

由于 ccm_causality.py 的 `strong_direction_rho = 0.2` 阈值是针对 out-of-sample ρ 校准的,in-sample ρ 可能导致弱信号被误判为强信号。

**建议修复**:

将 in-sample cross-map 改为 leave-one-out 或 train/test split 评估。即:对每个 library 点 i,在 library \ {i} 中找最近邻,用邻居的 cause 值预测 i 的 cause 值。

---

### P1-3: BH-FDR 的 q 值默认 0.10 偏宽松

**文件**: `f:\攻略\研发测试\Skill\edm-takens\src\ccm_causality.py`
**行号**: 347, 556
**问题描述**:

```python
def _benjamini_hochberg(p_values: np.ndarray, q: float = 0.10):
    # ...
    alpha_or_q = fdr_q  # 默认 0.10
```

`ccm_batch_test` 的 `fdr_q` 默认值为 0.10,允许 10% 的假发现率。

**数学依据**:

Benjamini-Hochberg (1995) 原论文中 FDR 水平 q 的选择:

- `q = 0.05`: 标准探索性分析 (与 α=0.05 的 single-test 一致)
- `q = 0.10`: 更宽松,适合早期探索,但假发现率更高
- `q = 0.01`: 验证性分析

在 CCM 因果发现场景,K=5 对时 q=0.10 意味着期望 0.5 个假发现。考虑到 CCM 的 Spearman p 值本身已有效应量门控 (line 524-532),q=0.10 可能过于宽松。

代码已有 `warn_pair_threshold = 5` 在 K≥5 时警告 (line 565),但警告不阻止,只是标注。

**建议修复**:

将默认 `fdr_q` 改为 0.05 (与 single-test α=0.05 一致),或在文档中明确说明 q=0.10 的选择理由。这不是 bug,但是统计严谨性的改进点。

---

### P1-4: AMI 计算使用 histogram-based 而非 KSG 估计器

**文件**: `f:\攻略\研发测试\Skill\edm-takens\src\edm_tau_optimization.py`
**行号**: 12-43
**问题描述**:

```python
def compute_ami(series, max_lag, bins=16):
    # ...
    joint, _, _ = np.histogram2d(x, y, bins=[edges, edges])
    joint_safe = joint + 1e-12
    joint_p = joint_safe / joint_safe.sum()
    # ...
    ami[lag] = np.sum(joint_p * np.log(joint_p / (outer + 1e-12)))
```

使用 2D histogram 估计联合分布,然后计算互信息。

**数学依据**:

互信息的估计方法 (按精度排序):

1. **KSG 估计器** (Kraskov, Stögbauer, Grassberger, 2004): 基于 k-NN 距离,无 bin 参数,渐近无偏,方差小
2. **Miller-Madow 修正**: histogram + 偏差修正项 `(K-1)(K-2)/(2N)`
3. **纯 histogram** (当前实现): 依赖 bins 参数,小样本下偏差大

当前实现的 `bins=16` 是硬编码:

- N=50 时,2D histogram 有 16×16=256 个 bin,平均每个 bin 0.2 个样本 → 严重稀疏
- 稀疏 bin 导致 `joint_p` 有大量零值,`+ 1e-12` 虽然防止 log(0),但引入系统性偏差
- AMI 曲线可能因此产生伪局部最小值,导致 τ 选择错误

**建议修复**:

集成 `sklearn.feature_selection.mutual_info_regression` (基于 KSG) 或 `npeet` (Greg Ver Steeg 的 KSG 实现)。如果保留 histogram,至少让 `bins` 自适应:`bins = max(3, int(np.sqrt(N/2)))` (Rice 规则的变体)。

---

### P2-1: eps 选择在不同模块间不一致

**文件**: 多处
**行号**: 见下表
**问题描述**:

| 文件 | 行号 | eps 值 | 用途 |
|------|------|--------|------|
| _numpy_edm.py | 118, 549, 558 | `1e-15` | 距离零值过滤 |
| _numpy_edm.py | 129 | `max(d_min, 1e-15)` | 权重归一化分母 |
| edm_tau_optimization.py | 35, 41 | `1e-12` | 概率平滑 + log 分母 |
| edm_auditor.py | 615, 979, 995 | `1e-12`, `1e-15` | 混用 |
| data_quality.py | 28, 82, 148, 222, 285, 302 | `1e-12` | 方差/相关防护 |
| sovereign_havok.py | 366, 395, 513 | `1e-12`, `1e-24` | 标准差/能量防护 |
| enhanced_cross_validate.py | 110, 137, 162 | `1e-12`, `1e-10` | 自相关/Lyapunov |

**数学依据**:

eps 的选择应基于数值计算的上下文:

- **距离比较**: `1e-15` 接近 float64 的机器精度 (≈2.2e-16),适合判断"严格为零"
- **概率平滑**: `1e-12` 对于 N≤1000 的样本足够,但对 N>1e6 的大样本可能不够 (累积误差)
- **方差防护**: `1e-12` 对于标准化数据合适,但对未标准化的原始数据可能太小

混用的风险:同一物理量在不同代码路径用不同 eps,可能在边界情况下产生不同判定。

**建议修复**:

定义模块级常量 (如 `EPS_DISTANCE = 1e-12`, `EPS_VARIANCE = 1e-12`, `EPS_PROB = 1e-12`),统一使用。这不是 bug,但能提高可维护性和一致性。

---

### P2-2: CCM 权重归一化在 d_min=0 时的退化路径

**文件**: `f:\攻略\研发测试\Skill\edm-takens\src\_numpy_edm.py`
**行号**: 118-130, 549-559
**问题描述**:

```python
# Line 118-130 (simplex_predict)
good = dists > 1e-15
if not good.any():
    good = np.ones(len(dists), dtype=bool)  # fallback: 全部保留
dists = dists[good][:E + 1]
# ...
d_min = dists[0]
w = np.exp(-dists / max(d_min, 1e-15))  # d_min=0 时 → exp(0)=1
w = w / w.sum()
```

当所有距离都 ≤ 1e-15 时 (退化数据:重复点或常数段):

1. `good.any()` 为 False → fallback 保留所有点
2. `dists[0]` 可能 = 0 → `d_min = 0`
3. `max(d_min, 1e-15) = 1e-15`
4. `w = np.exp(-dists / 1e-15)` → 当 `dists[0]=0` 时 `w[0]=1`,当 `dists[1]>0` 时 `w[1]≈0`
5. 结果:只用了第一个邻居,等价于 1-NN 而非 simplex 投影

这不会产生 NaN,但语义上退化为 1-NN 预测,失去了 simplex 投影的加权平均平滑效果。对于常数段数据,预测值就是该常数,ρ 仍为 1,不会报错但诊断意义丧失。

**数学依据**:

Simplex 投影 (Sugihara & May, 1990) 要求 E+1 个邻居形成单纯形,权重由距离决定。当所有距离为零时,加权平均退化为算术平均更合理 (`w = np.ones(len(dists)) / len(dists)`),而非当前的距离权重。

**建议修复**:

在 `d_min < 1e-15` 的退化情况下,显式使用均匀权重:
```python
if d_min < 1e-15:
    w = np.ones(len(dists)) / len(dists)
else:
    w = np.exp(-dists / d_min)
    w = w / w.sum()
```

---

### P2-3: SovereignHAVOK 的 lstsq 缺少显式正则化

**文件**: `f:\攻略\研发测试\Skill\edm-takens\src\sovereign_havok.py`
**行号**: 470
**问题描述**:

```python
Xi, residuals, rank, s_lstsq = lstsq(Theta, dv_dt, rcond=None)
```

默认使用 `rcond=None` (自动选择),但没有显式的 Tikhonov 正则化。`ridge_alpha` 参数存在但默认不启用 (`regression_method="lstsq"`)。

**数学依据**:

HAVOK 的回归矩阵 `Theta = [v | v_r]` (shape `p_steps × r`):

- 当 `r` 较大 (高 embedding) 而 `p_steps` 较小 (短序列) 时,`Theta` 可能病态
- `Theta.T @ Theta` 的条件数 = `cond(Theta)²`,可能极大
- `lstsq` 用 SVD 分解处理,但 `rcond=None` 的自动截断可能保留过小的奇异值,导致 `Xi` 的方差爆炸

`np.linalg.cond(self.A_)` 在 diagnose() 中报告 (line 678),但没有基于条件数的自动正则化切换。

**建议修复**:

在 `cond(Theta) > 1e10` 时自动切换到 ridge 回归,或在 `lstsq` 中设置显式 `rcond=1e-10` 截断小奇异值。这不是 bug,但能提升数值稳定性。

---

### P2-4: AMI 的 log 分母防护不足以防止数值溢出

**文件**: `f:\攻略\研发测试\Skill\edm-takens\src\edm_tau_optimization.py`
**行号**: 41
**问题描述**:

```python
outer = np.outer(px, py)
ami[lag] = np.sum(joint_p * np.log(joint_p / (outer + 1e-12)))
```

**数学依据**:

当 `px[i]` 或 `py[j]` 很小 (如 1/N) 而 `joint_p[i,j]` 也很小时:

- `outer[i,j] = px[i] * py[j]` 可能 ≈ 1/N² (如 N=1000 时 ≈ 1e-6)
- `outer + 1e-12` 的修正相对于 1e-6 可以忽略
- 但当 `joint_p[i,j] = 1e-12` (平滑后的零计数 bin) 而 `outer[i,j] = 1e-6` 时:
  - `log(1e-12 / 1e-6) = log(1e-6) ≈ -13.8`
  - 这个大负值被 `joint_p[i,j] = 1e-12` 加权后贡献 ≈ -1.4e-11,可忽略

主要问题在于 `joint_p * log(joint_p / outer)` 当 `joint_p → 0` 时应该 → 0 (信息论极限),但数值上可能产生 `0 * (-inf) = NaN`。当前的 `+ 1e-12` 在 `joint_p` 真正为零时 (未经平滑) 才是必要的,但 line 35 的 `joint_safe = joint + 1e-12` 已经保证了 `joint_p > 0`。

**建议修复**:

用 `np.log(joint_p / outer, where=joint_p > 0, out=np.zeros_like(joint_p))` 替代,显式处理 `joint_p=0` 的情况 (虽然当前已被 `+ 1e-12` 覆盖,但更清晰的实现有助于审计)。

---

### P3-1: _numpy_edm CCM 的 Python 循环可用 Numba 加速

**文件**: `f:\攻略\研发测试\Skill\edm-takens\src\_numpy_edm.py`
**行号**: 523-590
**问题描述**:

CCM 的 bootstrap 循环:
```python
for lib_size in lib_sizes:          # ~10-100 个 library size
    for _ in range(sample):          # 默认 50 次 bootstrap
        for i in range(lib_size):    # 每个 library 点
            # KDTree query + 邻居权重 + 预测
```

总迭代次数 ≈ `n_lib_sizes × sample × lib_size` ≈ 100 × 50 × 200 = 1,000,000 次 Python 循环。

**建议修复**:

- **Numba JIT**: 将内层循环 (邻居搜索 + 权重计算 + 预测) 用 `@numba.njit` 装饰,KDTree 替换为 brute-force 距离矩阵 (Numba 不支持 scipy.KDTree),在 lib_size < 500 时 brute-force 反而更快
- **向量化**: 对 `for i in range(lib_size)` 循环,可以批量查询 `tree.query(X_lib, k=k)` (scipy KDTree 支持 batch query)
- 预计 5-10× 加速

---

### P3-2: EDM Simplex 预测的邻居搜索可批量化

**文件**: `f:\攻略\研发测试\Skill\edm-takens\src\_numpy_edm.py`
**行号**: 110-167
**问题描述**:

```python
for i in range(pred_vec_start, pred_vec_end):
    target = X[i]
    dists, idxs = tree.query(target, k=k_neighbors)  # 单点查询
```

逐点 KDTree 查询,可以用 `tree.query(X[pred_vec_start:pred_vec_end], k=k_neighbors)` 一次性批量查询。

**建议修复**:

scipy.spatial.KDTree 支持批量查询 (`tree.query(points_array, k=k)`),返回 `(dists_array, idxs_array)`。预计 2-3× 加速 (减少 Python 循环开销 + C 级批量处理)。

---

### P3-3: HAVOK 的 SVD 可使用 truncated SVD

**文件**: `f:\攻略\研发测试\Skill\edm-takens\src\sovereign_havok.py`
**行号**: 405
**问题描述**:

```python
U, s, Vt = svd(H, full_matrices=False)  # 完整 SVD
```

当 Hankel 矩阵 H 很大 (p_steps × q, p_steps 可能 > 1000) 时,完整 SVD 的复杂度 O(min(p,q)² × max(p,q))。

**建议修复**:

如果只需要前 r 个奇异值/向量 (r << min(p,q)),用 `scipy.sparse.linalg.svds` 或 `sklearn.utils.extmath.randomized_svd`:

- `randomized_svd`: 复杂度 O(p × q × r),当 r < min(p,q)/10 时显著加速
- 适用于长时序 (N > 5000) 的 HAVOK 分析

---

### P3-4: Multiview 的组合枚举可用 GPU 加速

**文件**: `f:\攻略\研发测试\Skill\edm-takens\src\_numpy_edm.py`
**行号**: 845-916
**问题描述**:

`multiview_full` 枚举 `C(K-1, E)` 个候选模型,每个模型独立做 Simplex 预测。当 K=10, E=3 时有 `C(9,3)=84` 个组合,每个组合的 Simplex 预测是独立的。

**建议修复**:

- **并行化**: 候选模型之间完全独立,可用 `joblib.Parallel` 或 `multiprocessing.Pool` 并行
- **GPU**: 如果安装了 CuPy,可以将 KDTree 替换为 GPU brute-force + 加权预测
- 预计 4-8× 加速 (取决于核心数)

---

## 已有审计文档评估

### trace-engine/ALGORITHM_AUDIT.md (2026-07-20)

**准确性**: ★★★★☆ (4/5)

**准确反映的部分**:
- ✅ 六勇士 Tier-A/Tier-B 分层正确,CCM/EDM 的启发式回退已诚实标注
- ✅ FCI 实现状态 (DOC-04 修复) 记录准确,端点常量与节点索引修复已文档化
- ✅ 50 节点阈值 (counterfactual_bridge.py:511-514) 已记录
- ✅ 9 条 forbidden_rules 的 1:1 对应验证完整

**未准确反映的部分**:
- ❌ **未记录**: `six_warriors.py:_deploy_ccm` 调用 `ccm_with_convergence` 时,检查的字段是 `ccm_result.get('converging')` (line 304),但 `ccm_causality_test()` 返回的字段名是 `is_converging` (在 `forward`/`reverse` 子字典中),不是顶层的 `converging`。这可能导致 CCM 真算法路径始终判定为"未收敛"。
- ❌ **未记录**: `six_warriors.py:_deploy_edm` 的 ρ 计算 `1/(1+cv)` 与 Sugihara EDM 的 ρ 语义不同 (文档已标注,但未在 ALGORITHM_AUDIT 中记录数学依据)
- ❌ **未记录**: `six_warriors.py:_deploy_havok` 的 SVD 90% 能量截断是工程启发式,非 Gavish-Donoho 最优阈值 (sovereign_havok.py 支持但 six_warriors 未用)

### edm-takens/docs/ALGORITHM_AUDIT.md (2026-07-13)

**准确性**: ★★★★★ (5/5)

**准确反映的部分**:
- ✅ `_numpy_edm.CCM` 收敛判定与 `ccm_causality_test` 对齐的修复记录准确
- ✅ `pipeline.py` 小样本 Hankel 自校正的修复记录准确
- ✅ 剩余风险 (小样本 ρ 天花板、Hankel 比例极限、Lyapunov 不可靠) 均正确标注

**未准确反映的部分**:
- ❌ **未记录**: `enhanced_cross_validate.py:138` 的 Lyapunov log(0) 防护未同步 `final_interpretation.py` 的修复 (本报告 P0-1)
- ❌ **未记录**: `_numpy_edm.CCM` 的 in-sample cross-map 问题 (本报告 P1-2)
- ❌ **未记录**: `edm_tau_optimization.py` 的 AMI 使用 histogram-based 而非 KSG (本报告 P1-4)

---

## 优化升级建议

### 优先级 1: 修复 P0 (影响结论正确性)

1. **同步 Lyapunov log(0) 修复**: 将 `enhanced_cross_validate.py:138, 582` 与 `final_interpretation.py:127` 对齐
2. **修复 six_warriors.py 的 CCM 字段名**: `ccm_result.get('converging')` → `ccm_result.get('forward', {}).get('is_converging')`

### 优先级 2: 提升统计精度 (P1)

1. **Bootstrap CI 升级**: 百分位法 → BCa (scipy.stats.bootstrap 已内置)
2. **CCM cross-map 改为 leave-one-out**: `_numpy_edm.py:540-541` 的 in-sample → LOO
3. **AMI 估计器升级**: histogram → KSG (sklearn.feature_selection.mutual_info_regression)
4. **BH q 值收紧**: 0.10 → 0.05 (或文档说明选择理由)

### 优先级 3: 数值稳定性加固 (P2)

1. **统一 eps 常量**: 定义 `EPS_DISTANCE`, `EPS_VARIANCE`, `EPS_PROB` 模块级常量
2. **退化数据权重处理**: `d_min < eps` 时使用均匀权重
3. **HAVOK 条件数自动正则化**: `cond(Theta) > 1e10` 时切换 ridge

### 优先级 4: 性能优化 (P3)

1. **Numba 加速 CCM**: `_numpy_edm.py` 的 bootstrap 循环
2. **批量 KDTree 查询**: simplex_predict 和 CCM 的邻居搜索
3. **truncated SVD**: HAVOK 的长时序分析
4. **Multiview 并行化**: 候选模型独立,可 joblib 并行

---

## 数学正确性总结

### 核心算法正确性评级

| 算法 | 文件 | 评级 | 关键依据 |
|------|------|------|----------|
| CCM 收敛判定 | ccm_causality.py | A | 4 条件门控 (rise/spearman_rho/spearman_p/effect_size) 在所有路径一致 |
| BH-FDR 多重比较 | ccm_causality.py | A | 手工实现正确,通过单元测试验证 |
| Permutation +1 修正 | py_bridge.py, surrogate_test.py | A | Phipson & Smyth (2010) 公式正确 |
| FCI PAG 端点语义 | causallearn_validator.py | A | 9 种边类型映射正确,1-based→0-based 修复 |
| HAVOK Koopman 特征值 | sovereign_havok.py | A | 使用矩阵指数 expm(A·dt) 而非 Euler 近似 |
| Lyapunov 估计 (主路径) | final_interpretation.py | A | log(0) 用 where 掩码 + nanmean |
| Lyapunov 估计 (交叉验证路径) | enhanced_cross_validate.py | C | log(div + 1e-12) 未同步修复 (P0-1) |
| AMI 选 τ | edm_tau_optimization.py | B | histogram-based, bins=16 硬编码 (P1-4) |
| FNN 选 E | _numpy_edm.py | A | Kennel 1992 公式正确,rtol=15/atol=2 标准值 |
| Bootstrap CI | py_bridge.py | B | 百分位法,小样本有偏 (P1-1) |
| CCM ρ 计算 (主路径) | ccm_causality.py | A | 调用 pyEDM, out-of-sample |
| CCM ρ 计算 (回退路径) | _numpy_edm.py | B | in-sample cross-map (P1-2) |

### 总体结论

**trace-engine**: 数学正确性 **A-**
- 六勇士架构的 Tier 分层诚实标注了启发式回退
- DoWhy/causallearn 集成的算法正确性高
- 主要缺陷在 six_warriors.py 的 CCM 字段名不匹配 (可能导致真算法路径失效)

**edm-takens**: 数学正确性 **A-**
- CCM 收敛判定、BH-FDR、permutation test 的实现均为教科书级正确
- 主要缺陷在 enhanced_cross_validate.py 的 Lyapunov log(0) 未同步修复 (P0)
- _numpy_edm 的 in-sample cross-map 和 AMI 的 histogram 估计是精度改进点

**已有审计文档**: 整体准确,但有两处遗漏 (enhanced_cross_validate 的 Lyapunov 不一致、_numpy_edm 的 in-sample 问题),建议在下一轮审计中补充。

### 数学正确性的核心观察

1. **收敛判定的四条件门控** (total_rise + spearman_rho + spearman_p + effect_size) 是本项目最亮点的设计 — 它正确识别了"样本量伪显著"问题 (大 library sweep 产生小 p 值但无真实信号),并通过 effect_size floor 阻止了这类假阳性。这一设计在 ccm_causality.py、_numpy_edm.py、edm_auditor.py 三处一致实现,是统计推断正确性的标杆。

2. **Takens 嵌入定理的应用条件** 未显式验证 (微分同胚、E ≥ 2d+1 的 Whitney 嵌入下界)。这是 EDM 领域的普遍实践 — 理论条件通常假设满足,通过 Simplex 预测 skill 的实证表现间接验证。本项目在 EmbedDimension 中用 leave-one-out ρ 选择 E,是合理的实证替代。

3. **Sugihara CCM 的 lib_size 选取** 缺乏理论依据 (Takens 定理的推论建议 E+1 ≤ lib_size,但上界无明确指导)。当前默认 `{E+2} {n-2} 3` 是工程选择,步长 3 的精度有限。这不是 bug,但可在文档中说明选择理由。

---

*审视结束。本报告未修改任何代码文件,仅做审视和记录。*
