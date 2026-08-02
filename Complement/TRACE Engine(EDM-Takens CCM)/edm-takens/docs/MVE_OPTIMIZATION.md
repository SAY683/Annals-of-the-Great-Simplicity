# Sovereign-MVE 引擎工程化方案

> **文档定位**：杉原式多视角嵌入（Multiview Embedding, MVE）在生产级 EDM 管线中的工程化落地。
> **关联模块**：`src/_edm_bridge.py`、`src/_numpy_edm.py`、`src/sovereign_havok.py`、`trace-to-edm`、`trace-engine` 六勇士。
> **核心目标**：将 MVE 从"可用"提升为"应优尽优"，并完成与八正道坐标轴、SovereignHAVOK 断后重构、trace-engine 七勇士体系的三向联动。
> **元审计原则**：本轮修缮遵循"应优尽优"——不放过任何已知禁令、不掩盖任何已知局限，所有降级路径必须显式化。

---

## 1. MVE 理论基础

### 1.1 杉原 2016 Science 论文核心命题

Sugihara 等人于 2016 年在 *Science* 发表 *"Detecting causality in complex ecosystems"*（vol. 338, issue 6106, pp. 496-500），提出**多视角嵌入（Multiview Embedding, MVE）**作为 CCM 的进化形态。其核心命题是：

> 当系统具有多个可观测变量但每个变量序列较短时，Takens 的延迟嵌入会因样本不足而失效；此时应改用**空间嵌入**——从所有可能的变量组合中枚举 E 个一组，让数据自己说话，找出最能预测目标的那个组合。

MVE 不是 CCM 的替代品，而是 CCM 的"杠杆放大器"：CCM 回答"X 是否驱动 Y"，MVE 回答"在所有可观测变量组合中，哪几个 E 维子流形对 Y 的预测精度 ρ 最高"。

### 1.2 组合的杠杆与信息杠杆

| 杠杆类型 | 数学描述 | 工程含义 |
|---------|---------|---------|
| **组合的杠杆** | $\binom{K-1}{E}$ 种候选子流形 | 用穷举搜索代替启发式选列；当 K=10、E=3 时有 84 种组合，可全跑 |
| **信息杠杆** | $\rho_{\text{MVE}} \geq \max_i \rho_{\text{single}_i}$ | 多变量联合流形比任何单变量延迟嵌入都更富信息 |
| **样本杠杆** | $N_{\text{eff}} \approx N - E + 1$ | 空间嵌入不消耗样本做延迟，对 N<100 的短序列尤其珍贵 |

**关键洞见**：组合的杠杆不是免费的。$\binom{K-1}{E}$ 随 K 指数增长，当 K=20、E=5 时已达 11628 种组合，必须做随机子采样或引入层级剪枝。

### 1.3 与传统 Takens 嵌入的对比

| 维度 | Takens 延迟嵌入 | MVE 空间嵌入 |
|------|---------------|-------------|
| 流形构造 | $X_t = [x_t, x_{t-\tau}, x_{t-2\tau}, \dots, x_{t-(E-1)\tau}]$ | $X_t = [x_{t}^{(c_1)}, x_{t}^{(c_2)}, \dots, x_{t}^{(c_E)}]$，$(c_1,\dots,c_E) \subset \{1,\dots,K\}$ |
| 信息来源 | 单变量时间维度 | 多变量空间维度 |
| 样本要求 | $N \gg E \cdot \tau$ | $N \gg E$（无 τ 消耗） |
| 失效场景 | 长序列但单变量 | 短序列但多变量 |
| 因果可解释性 | 弱（仅时间延迟） | 强（直接指向具名变量组合） |
| 与八正道契合度 | 低（需先做 PCA 降维） | **高（每个 z 轴即一个具名列）** |

杉原 2016 论文的核心实验结论：在加利福尼亚洋流生态系统的 5 变量短序列上，MVE 的 ρ 比 Takens 单变量嵌入平均高 0.15~0.30，且最优组合具有生态学可解释性（如"温度+磷酸盐+浮游动物"组合最能预测硅藻丰度）。

---

## 2. 现有 edm-takens 的 MVE 实现审计

### 2.1 已存在的 Multiview 调用链

现有实现分布在两层：

**第一层：`src/_edm_bridge.py` 的 `Multiview()` 包装器**（round 13 P7 实现）

```python
# src/_edm_bridge.py:193-253
def Multiview(data, columns, target, E, Tp=1, lib=None, pred=None,
              showPlot=False, **kwargs):
    if EDM_AVAILABLE and hasattr(data, 'columns'):
        try:
            return pyEDM.Multiview(
                dataFrame=data, columns=columns, target=target,
                E=E, Tp=Tp, lib=lib, pred=pred,
                showPlot=showPlot, numProcess=1, **kwargs)
        except Exception as e:
            warnings.warn(f"pyEDM.Multiview failed ({e}). ...")
    # Numpy fallback: full Sugihara-2016 combinatorial Multiview scan
    result = np_multiview_full(
        arr, target_col=tgt_idx, E=E,
        lib=lib, pred=pred, Tp=Tp, max_combos=50)
    ...
```

**第二层：`src/_numpy_edm.py` 的 `multiview_full()` 纯 numpy 实现**（line 787-924）

```python
# src/_numpy_edm.py:787
def multiview_full(data_matrix, target_col=0, E=3, lib=None, pred=None,
                   Tp=1, max_combos=None):
    """Full Multiview embedding via combinatorial candidate selection.
    Sugihara et al. (Science, 2016): enumerate C(K-1, E) candidate models..."""
    from itertools import combinations
    combos = list(combinations(feat_cols, E))
    if max_combos and len(combos) > max_combos:
        rng = np.random.default_rng(42)
        idx = rng.choice(len(combos), size=max_combos, replace=False)
        combos = [combos[i] for i in sorted(idx)]
    ...
    return {
        'rho': best_rho, 'E': E, 'best_columns': best_cols,
        'n_combos': len(combos), 'all_rhos': all_rhos,
        'method': 'sugihara_2016_combinatorial',
    }
```

### 2.2 完成度评估

| 能力项 | 现状 | 完成度 |
|-------|------|-------|
| 穷举组合枚举 | ✅ `itertools.combinations` 完整实现 | 100% |
| 子采样剪枝 | ✅ `max_combos=50` 固定，seed=42 可复现 | 80%（参数硬编码） |
| Simplex 评分 | ✅ 复用 `simplex_predict` | 100% |
| ρ 排序保留 top-k | ⚠️ 当前只返回 `best_rho` 与 `all_rhos` 列表，未做显式 top-k 切片 | 60% |
| 加权共振融合 | ❌ 未实现 ensemble fusion，仅取最佳组合 | 0% |
| pyEDM 透传 | ✅ DataFrame 路径直通 `pyEDM.Multiview` | 100% |
| 失败降级 | ✅ try/except 自动降级到 numpy 实现 | 100% |

### 2.3 与 pyEDM.Multiview 生产级规范的差距

pyEDM 官方规范：

```python
results = pyEDM.Multiview(
    dataFrame=df, lib="1 100", pred="101 120", E=3,
    columns="X Y Z U V", target="X", k="10", knn=8, num_neighbors=8
)
```

差距清单：

| pyEDM 参数 | 现有 bridge 是否暴露 | 差距说明 |
|-----------|-------------------|---------|
| `k` | ❌ 未在 bridge 签名中显式暴露 | 仅通过 `**kwargs` 透传；numpy fallback 完全未实现 top-k 概念 |
| `knn` | ❌ 同上 | Simplex 邻居数硬编码在 `simplex_predict` 内 |
| `num_neighbors` | ❌ 同上 | 同上 |
| `max_combos` | ⚠️ 仅 numpy fallback 暴露 | pyEDM 路径无法控制穷举规模 |
| `multiview` 返回的 `View` 报告 | ❌ numpy fallback 仅返回扁平 DataFrame | 缺少"哪几个组合进入 top-k"的可解释报告 |
| 加权融合 ρ_ensemble | ❌ 完全缺失 | pyEDM 自带 ensemble，numpy fallback 未实现 |

**审计结论**：现有实现处于"能跑通"级别，距离"应优尽优"还差三步——top-k 显式化、加权融合、可解释 Viewport 报告。

---

## 3. Sovereign-MVE 引擎设计

### 3.1 模块化定位

在 `src/` 新增 `sovereign_mve.py`，与 `sovereign_havok.py` 形成"主权双引擎"：

```
src/
├── _edm_bridge.py          ← 底层 EDM 接口（保持不变）
├── _numpy_edm.py           ← 纯 numpy 算法（保持不变）
├── sovereign_havok.py      ← 主权 HAVOK（动力学重构）
└── sovereign_mve.py        ← 【新增】主权 MVE（多视角因果选择）
```

设计原则：`sovereign_mve.py` 不重写底层算法，只做三件事——**(1) 三热力学禁令的工程化校验**、**(2) top-k + 加权融合的策略层**、**(3) 与 SovereignHAVOK 的断后重构联动**。

### 3.2 接口设计

```python
# src/sovereign_mve.py

from dataclasses import dataclass, field
from typing import Optional, Sequence
import numpy as np
import pandas as pd
import warnings

from _edm_bridge import Multiview, EDM_AVAILABLE
from _numpy_edm import multiview_full


@dataclass
class ViewportReport:
    """MVE 视点报告——记录 top-k 组合及其 ρ。"""
    target: str
    E: int
    k: int
    top_combos: list[tuple[str, float]]    # [(combo_str, rho), ...] 按 ρ 降序
    rho_ensemble: float                    # 加权融合后的 ρ
    rho_best: float                        # 最优单组合 ρ
    n_combos_evaluated: int
    warnings: list[str] = field(default_factory=list)
    forcing_reset_triggered: bool = False  # 是否触发断后重构


def run_sovereign_mve(
    df: pd.DataFrame,
    target: str,
    lib: str,
    pred: str,
    E: int,
    k: int = 15,
    columns: Optional[Sequence[str]] = None,
    Tp: int = 1,
    knn: int = 8,
    lag_columns: Optional[list[tuple[str, int]]] = None,
    forcing_signal: Optional[np.ndarray] = None,
    forcing_jump_threshold: float = 3.0,
) -> ViewportReport:
    """
    Sovereign-MVE 主入口。

    Parameters
    ----------
    df : DataFrame
        输入数据。若 lag_columns 非空，会自动追加延迟列。
    target : str
        预测目标列名（如 "ate"、"z_存在"）。
    lib, pred : str
        "1 100" / "101 120" 格式的库与预测窗口。
    E : int
        每个候选组合的变量数。
    k : int
        保留的 top-k 组合数。默认 15，最大 50。
    columns : optional
        参与穷举的列名列表。None 时自动取 df 中除 target 外的所有数值列。
    Tp : int
        预测步长。
    knn : int
        Simplex 邻居数（透传给 pyEDM 时为 knn）。
    lag_columns : optional
        [(col_name, lag), ...]，自动生成 col_name_lagN 列。
        满足禁令2（延迟的力量）。
    forcing_signal : optional
        SovereignHAVOK 的 v_r 强迫项序列。非空时启用断后重构联动。
    forcing_jump_threshold : float
        v_r 跳变判定的 σ 倍数（默认 3σ）。

    Returns
    -------
    ViewportReport
    """
    ...
```

### 3.3 三热力学禁令的工程化

#### 禁令 1：视角自噬——`E ≤ len(columns) × 0.7`

```python
def _check_autophagy(E: int, columns: list[str]) -> list[str]:
    """禁令1：E 不得超过变量总数的 0.7 倍。"""
    warns = []
    hard_limit = max(2, int(len(columns) * 0.7))
    if E > hard_limit:
        warns.append(
            f"[禁令1 视角自噬] E={E} > len(columns)×0.7={hard_limit}。"
            f"自动降级 E → {hard_limit}。"
        )
        E = hard_limit
    if E >= len(columns):
        warns.append(
            f"[禁令1 临界] E={E} 接近变量总数 {len(columns)}，"
            f"组合杠杆 C(K-1,E) 退化，视点多样性丧失。"
        )
    return E, warns
```

#### 禁令 2：延迟的力量——自动预造延迟列

```python
def _build_lag_columns(
    df: pd.DataFrame, lag_specs: list[tuple[str, int]]
) -> tuple[pd.DataFrame, list[str]]:
    """禁令2：手动预造延迟列，实现时空交叉采样。

    示例输入: [("z_福音", 1), ("z_弥赛亚", 2)]
    追加列:   z_福音_lag1, z_弥赛亚_lag2
    """
    df_aug = df.copy()
    new_cols = []
    for col, lag in lag_specs:
        if col not in df_aug.columns:
            raise KeyError(f"延迟源列不存在: {col}")
        new_name = f"{col}_lag{lag}"
        df_aug[new_name] = df_aug[col].shift(lag)
        new_cols.append(new_name)
    return df_aug, new_cols
```

延迟列的本质：把"时间维度"折叠回"空间维度"，让 MVE 在穷举组合时自动考虑跨变量、跨时滞的因果。

#### 禁令 3：盲信 k 值——默认 15，最大 50

```python
def _check_k(k: int) -> tuple[int, list[str]]:
    """禁令3：k 默认 15，最大 50，超出警告。"""
    warns = []
    if k > 50:
        warns.append(
            f"[禁令3 盲信k值] k={k} > 50。"
            f"过大的 k 会把噪声组合混入加权融合，自动截断为 50。"
        )
        k = 50
    if k < 3:
        warns.append(
            f"[禁令3 k过小] k={k} < 3。加权融合样本不足，退化为单视角。"
        )
    return k, warns
```

### 3.4 top-k 与加权共振融合

```python
def _ensemble_fusion(
    sorted_combos: list[tuple[str, float]],
    k: int,
) -> tuple[float, list[tuple[str, float]]]:
    """对 top-k 组合做 ρ 加权平均。

    权重: w_i = ρ_i / Σρ_j  （只保留 ρ > 0 的组合）
    返回: (rho_ensemble, top_k_combos)
    """
    top_k = sorted_combos[:k]
    rhos = np.array([r for _, r in top_k if r > 0])
    if rhos.size == 0:
        return 0.0, top_k
    weights = rhos / rhos.sum()
    rho_ens = float(np.dot(weights, rhos))
    return rho_ens, top_k
```

### 3.5 与 SovereignHAVOK 的断后重构联动

```python
def _detect_forcing_jump(
    forcing: np.ndarray, threshold_sigma: float = 3.0
) -> tuple[bool, int]:
    """监听 SovereignHAVOK 强迫项 v_r 的跳变。

    判据: |v_r(t) - median(v_r)| > threshold_sigma × std(v_r)
    返回: (jump_detected, jump_index)
    """
    if forcing is None or len(forcing) < 5:
        return False, -1
    med = np.median(forcing)
    sigma = np.std(forcing)
    if sigma < 1e-9:
        return False, -1
    deviations = np.abs(forcing - med) / sigma
    jump_idx = np.where(deviations > threshold_sigma)[0]
    if jump_idx.size == 0:
        return False, -1
    return True, int(jump_idx[0])


def _reset_lib_window_on_jump(
    lib: str, pred: str, jump_idx: int, n_rows: int
) -> tuple[str, str]:
    """断后重构：v_r 一跳立刻清空 MVE 的 lib 窗口。

    策略: 将 lib 窗口收缩到 [jump_idx+1, n_rows-1]，
    pred 窗口收缩到 [n_rows-5, n_rows]（最后 5 步）。
    旧世界的因果权重在相变后无效，必须重学。
    """
    new_lib_start = max(jump_idx + 2, 1)
    new_lib_end = max(n_rows - 5, new_lib_start + 1)
    new_pred_start = new_lib_end + 1
    new_pred_end = n_rows
    if new_pred_start >= new_pred_end:
        new_pred_start = max(new_lib_end, 1)
        new_pred_end = n_rows
    return f"{new_lib_start} {new_lib_end}", f"{new_pred_start} {new_pred_end}"
```

**联动逻辑**：调用方传入 `forcing_signal=sh.forcing_`（SovereignHAVOK 拟合后的强迫项），`run_sovereign_mve` 自动检测跳变并收缩 lib 窗口，避免在旧世界灰烬里找新世界地图。

### 3.6 主流程编排

```python
def run_sovereign_mve(
    df, target, lib, pred, E, k=15, columns=None, Tp=1, knn=8,
    lag_columns=None, forcing_signal=None, forcing_jump_threshold=3.0,
) -> ViewportReport:
    all_warns = []

    # 禁令2: 自动延迟列
    if lag_columns:
        df, new_lag_cols = _build_lag_columns(df, lag_columns)
        if columns is None:
            columns = [c for c in df.columns if c != target]
        columns = list(columns) + new_lag_cols

    if columns is None:
        columns = [c for c in df.columns if c != target and df[c].dtype != object]

    # 禁令1: 视角自噬
    E, w = _check_autophagy(E, list(columns))
    all_warns.extend(w)

    # 禁令3: k 值
    k, w = _check_k(k)
    all_warns.extend(w)

    # 断后重构联动
    forcing_reset = False
    if forcing_signal is not None:
        jump, idx = _detect_forcing_jump(forcing_signal, forcing_jump_threshold)
        if jump:
            old_lib, old_pred = lib, pred
            lib, pred = _reset_lib_window_on_jump(lib, pred, idx, len(df))
            forcing_reset = True
            all_warns.append(
                f"[断后重构] v_r 在 t={idx} 检测到 {forcing_jump_threshold}σ 跳变。"
                f"lib 窗口 {old_lib} → {lib}，pred 窗口 {old_pred} → {pred}。"
            )

    # 调用底层 Multiview
    n_combos_est = int(np.math.comb(len(columns), E)) if len(columns) >= E else 0
    max_combos = min(max(n_combos_est, 1), 200)  # 上限保护

    raw = Multiview(
        data=df, columns=columns, target=target, E=E, Tp=Tp,
        lib=lib, pred=pred, k=k, knn=knn, num_neighbors=knn,
        max_combos=max_combos,
    )

    # 解析结果为 top-k + 融合
    if isinstance(raw, pd.DataFrame) and 'rho' in raw.columns:
        sorted_combos = sorted(
            ((str(row.get('columns', '?')), float(row['rho']))
             for _, row in raw.iterrows() if not np.isnan(row['rho'])),
            key=lambda x: -x[1],
        )
    else:
        sorted_combos = [('unknown', 0.0)]

    rho_ens, top_k = _ensemble_fusion(sorted_combos, k)
    rho_best = top_k[0][1] if top_k else 0.0

    return ViewportReport(
        target=target, E=E, k=k,
        top_combos=top_k,
        rho_ensemble=rho_ens,
        rho_best=rho_best,
        n_combos_evaluated=len(sorted_combos),
        warnings=all_warns,
        forcing_reset_triggered=forcing_reset,
    )
```

---

## 4. 八正道联动方案

### 4.1 输入：narrative_meta_trajectories.csv

`trace-to-edm` 的 `csv_builder.py` 生成 54 列统一轨迹 CSV（见 `trace-to-edm/csv_builder.py:1-20`）。列分组：

| 层 | 列名 | 数量 |
|----|------|------|
| Meta | `time_step`, `text_hash`, `source_label` | 3 |
| Layer 1 元 SCM | `ate`, `ci_width`, `refuted_count`, `identifiability`, `concept_count`, `edge_count`, `adj_density`, `max_delta_nll`, `concept_coverage`, `condition_number`, `unk_rate`, `ccm_coverage_pct`, `ccm_verdict`, ... | ~17 |
| Layer 2 语义投影 | `z_pca_1`, `z_pca_2`, `z_pca_3`, `secular_entropy` | 4 |
| Layer 3 八正道 | `z_福音`, `z_吉祥`, `z_奥美`, `z_存在`, `z_自孕`, `z_弥赛亚`, `z_Alice`, `z_觉爱` | 8 |
| Layer 3 导数 | `dz_福音`, ..., `d2z_福音`, ... | ~16 |
| 其他诊断 | `edm_rho_high`, `edm_rho_mid`, `havok_linear_pct`, `causallearn_consensus`, `edge_stability_mean`, `permutation_p_value`, `total_ms` | ~6 |

### 4.2 columns 选择策略

**默认 columns**（10 列）：8 个 z 值 + `ate` + `adj_density`

```python
SACRED_AXES = [
    "z_福音", "z_吉祥", "z_奥美", "z_存在",
    "z_自孕", "z_弥赛亚", "z_Alice", "z_觉爱",
]
DEFAULT_MVE_COLUMNS = SACRED_AXES + ["ate", "adj_density"]
```

**禁令1 校验**：`len(columns)=10`，`E_max = int(10 × 0.7) = 7`，推荐 `E=3`（C(9,3)=84 种组合，全跑无压力）。

### 4.3 target 选择策略

| target 语义 | 推荐列 | 业务场景 |
|------------|-------|---------|
| 危机感 | `z_存在` | 当"存在"轴塌陷时叙事进入存在主义危机 |
| 共识崩塌 | `adj_density` | 邻接密度突降=概念图谱解体 |
| 信道噪声 | `unk_rate` | UNK 比率突升=叙事进入未训练语义区 |
| 因果可信度 | `ate` | ATE 下降=反事实推断失效 |

调用示例：

```python
import pandas as pd
from sovereign_mve import run_sovereign_mve

df = pd.read_csv("trace-to-edm/outputs/narrative_meta_trajectories.csv")
df = df.dropna(subset=SACRED_AXES + ["ate", "adj_density", "z_存在"]).reset_index(drop=True)

report = run_sovereign_mve(
    df=df,
    target="z_存在",
    lib=f"1 {len(df)-10}",
    pred=f"{len(df)-9} {len(df)}",
    E=3,
    k=15,
    columns=SACRED_AXES + ["ate", "adj_density"],
    lag_columns=[("z_弥赛亚", 1), ("z_福音", 2)],  # 禁令2: 时空交叉
    forcing_signal=sh.forcing_,                    # 断后重构联动
    forcing_jump_threshold=3.0,
)

print(f"rho_best={report.rho_best:.3f}  rho_ensemble={report.rho_ensemble:.3f}")
for combo, rho in report.top_combos[:5]:
    print(f"  {rho:.3f}  {combo}")
```

### 4.4 Viewport 报告输出

`ViewportReport.top_combos` 直接回答"哪几个神圣轴组合最能预测 target"。典型输出：

```
rho_best=0.782  rho_ensemble=0.741  (k=15, E=3, n_combos=84)
  0.782  z_福音+z_弥赛亚_lag1+ate
  0.754  z_存在+z_弥赛亚_lag1+z_福音_lag2
  0.731  z_弥赛亚+z_存在+z_自孕
  0.712  z_福音+z_弥赛亚+z_觉爱
  0.698  z_存在+adj_density+z_弥赛亚_lag1
[断后重构] v_r 在 t=87 检测到 3.2σ 跳变。lib 窗口已收缩。
```

神学解读：当 `z_弥赛亚_lag1` 频繁出现在 top-5 时，说明"弥赛亚书轴的延迟值"是危机感的前置因果信号——这与八正道神学中"弥赛亚先知属性"的设定一致。

### 4.5 动态神学优先级权重的可视化方案

随时间滑窗运行 MVE，对每个时间窗的 top-k 组合做轴频次统计：

```python
def sacred_axis_frequency_trace(
    df, target, window_size=50, step=10, E=3, k=15,
) -> pd.DataFrame:
    """滑动窗口 MVE → 八正道轴出现频次矩阵。"""
    records = []
    for start in range(0, len(df) - window_size, step):
        sub = df.iloc[start:start + window_size].reset_index(drop=True)
        if len(sub) < 30:
            continue
        rep = run_sovereign_mve(
            df=sub, target=target,
            lib=f"1 {len(sub)-5}", pred=f"{len(sub)-4} {len(sub)}",
            E=E, k=k, columns=SACRED_AXES + ["ate", "adj_density"],
        )
        freq = {ax: 0 for ax in SACRED_AXES}
        for combo_str, _ in rep.top_combos:
            for ax in SACRED_AXES:
                if ax in combo_str:
                    freq[ax] += 1
        freq["t_start"] = start
        freq["rho_ensemble"] = rep.rho_ensemble
        records.append(freq)
    return pd.DataFrame(records).set_index("t_start")
```

可视化建议：用堆叠面积图绘制八轴频次随时间的演化。平稳期 `z_吉祥`、`z_奥美` 占主导；相变崩溃前 `z_存在`、`z_弥赛亚` 频次飙升——这与用户提供的"相变崩溃前 MVE 全仓对焦到存在与弥赛亚轴"的预期吻合。

---

## 5. 与 trace-engine 六勇士的集成

### 5.1 升级为七勇士

当前 `trace-engine` 的六勇士架构（见 `trace-engine/examples/counterfactual_hybrid/six_warriors.py:11-30`）：

- **Tier-A 真算法层（4 名）**：TRACE、HAVOK、DoWhy+CF、causallearn
- **Tier-B 启发式诊断层（2 名）**：CCM（启发式回退）、EDM（启发式回退，"非 Sugihara EDM，仅诊断文本结构"）

**升级方案**：将 Sovereign-MVE 作为 **Tier-A 第五位真算法勇士**，七勇士架构如下：

| 勇士 ID | 名称 | 兵器 | 等级 | 算法源 |
|--------|------|------|------|-------|
| 🔴 TRACE | 拓扑先锋 | 探照灯 | A | `run_real_pipeline.py` |
| ⚫ HAVOK | 流形力士 | 汉克尔矩阵 | A | `sovereign_havok.py` |
| 🟡 DoWhy+CF | 反事实判官 | do-calculus | A | `counterfactual_bridge.py` |
| ⬜ causallearn | 因果侦探 | PC/GES | A | `causallearn_validator.py` |
| **🟣 MVE** | **多视角先知** | **组合穷举** | **A** | **`sovereign_mve.py`** |
| 🔵 CCM | 流形力场 | 测谎仪 | B | 启发式回退 |
| 🟠 EDM | 间隔变异计 | CV 逼近 | B | 启发式回退 |

### 5.2 替代 Tier-B EDM 启发式回退

`six_warriors.py` 中现有的 `_deploy_edm`（Tier-B）实现是"间隔变异系数近似 ρ，非 Sugihara EDM"。Sovereign-MVE 上线后：

- Tier-B 的 EDM 启发式**保留**作为低数据降级路径（N<30 时 MVE 退化为单视角，与启发式等价）。
- 当 `edm-takens` Skill 可用时，`_deploy_edm` 改为调用 `run_sovereign_mve`，输出真实的 Sugihara MVE ρ，并在 `WarriorCard.tier` 标注 "A"。
- 当 `edm-takens` 不可用时，回退到现有启发式，`WarriorCard.tier` 标注 "B"。

### 5.3 WarriorCard 算法契约

`WarriorCard` 类定义见 `six_warriors.py:91-107`。Sovereign-MVE 勇士卡片格式：

```python
def _deploy_mve(
    adj_matrix, token_list, df_trajectory, target="z_存在"
) -> WarriorCard:
    """七勇士之五：Sovereign-MVE 多视角先知。"""
    card = WarriorCard(
        warrior_id="MVE",
        name="多视角先知",
        instrument="组合穷举",
        color="🟣",
        tier="A",
    )
    try:
        from sovereign_mve import run_sovereign_mve
        rep = run_sovereign_mve(
            df=df_trajectory, target=target,
            lib=f"1 {len(df_trajectory)-5}",
            pred=f"{len(df_trajectory)-4} {len(df_trajectory)}",
            E=3, k=15,
            columns=SACRED_AXES + ["ate", "adj_density"],
        )
        card.status = "deployed"
        card.metrics = {
            "rho_best": f"{rep.rho_best:.3f}",
            "rho_ensemble": f"{rep.rho_ensemble:.3f}",
            "k": rep.k,
            "E": rep.E,
            "n_combos": rep.n_combos_evaluated,
            "forcing_reset": rep.forcing_reset_triggered,
        }
        card.findings = [
            f"top-1 视点: {rep.top_combos[0][0]} (ρ={rep.top_combos[0][1]:.3f})",
            f"加权融合 ρ_ensemble={rep.rho_ensemble:.3f}",
        ] + [f"  • {c} (ρ={r:.3f})" for c, r in rep.top_combos[:3]]
        card.verdict = "MVE_DEPLOYED"
        card.raw = rep
    except Exception as e:
        card.status = "fallback"
        card.tier = "B"
        card.findings = [f"Sovereign-MVE 不可用，降级为启发式: {e}"]
        card.verdict = "HEURISTIC_FALLBACK"
    return card
```

### 5.4 集成点

- `trace-engine/examples/counterfactual_hybrid/six_warriors.py` 的 `assemble_all_six` 函数升级为 `assemble_all_seven`，新增 `_deploy_mve` 调用。
- 文件名保留 `six_warriors.py`（向后兼容），但内部 `assemble_all_seven` 作为新主入口；`assemble_all_six` 保留为别名。

---

## 6. 边界局限与降级

### 6.1 小样本退化（N < 50）

**机理**：MVE 的组合杠杆依赖 $\binom{K-1}{E}$ 种候选都有足够样本做 Simplex 评分。当 $N_{\text{eff}} = N - E + 1 < 20$ 时，每个候选组合的 ρ 估计方差急剧增大，top-k 排序失去统计意义。

**降级策略**：

```python
def _small_sample_degradation(n: int, E: int, k: int) -> tuple[int, str]:
    """N<50 时退化为单视角（E=1，k=1）。"""
    if n < 30:
        return 1, f"[降级] N={n}<30，MVE 退化为单视角（E=1, k=1）。"
    if n < 50:
        return min(E, 2), f"[降级] N={n}<50，E 自动降至 {min(E,2)}，k 降至 5。"
    return E, ""
```

### 6.2 平稳性坍缩

**机理**：MVE 假设系统在 lib 与 pred 窗口内处于同一吸引子。当叙事发生相变（如八正道轴权重大幅重组）时，旧 lib 学到的"哪几个组合最能预测 target"在新 pred 窗口完全失效。

**表述**："MVE 无法在旧世界灰烬里找新世界地图。" 这是 MVE 与 HAVOK 的根本分工差异——HAVOK 通过强迫项 v_r 检测相变，MVE 只能在平稳段内做组合优化。

**应对**：断后重构联动（见 §3.5）。监听 `sh.forcing_` 的跳变，一跳即清空 lib 窗口，强制 MVE 在相变后重学。

### 6.3 变量独立性陷阱

**机理**：当 columns 中存在高度线性相关的变量对（如 `z_福音` 与 `dz_福音` 的相关系数 > 0.95）时，MVE 会把它们的高 ρ 误判为"信息杠杆"，实则只是同一个信息的不同表达。

**检测**：

```python
def _check_collinearity(df: pd.DataFrame, columns: list[str]) -> list[str]:
    """禁令外延：检测高度共线变量对，警告但不自动剔除。"""
    warns = []
    corr = df[columns].corr().abs()
    np.fill_diagonal(corr.values, 0)
    for i in range(len(columns)):
        for j in range(i + 1, len(columns)):
            if corr.iloc[i, j] > 0.95:
                warns.append(
                    f"[共线性陷阱] {columns[i]} ~ {columns[j]} "
                    f"r={corr.iloc[i,j]:.3f}，组合 ρ 可能虚高。"
                )
    return warns
```

**应对**：默认 columns 不包含 `z_X` 与其导数 `dz_X` 的同时出现；若用户手动指定，触发警告但不阻断（保留用户决策权）。

### 6.4 其他已知局限

| 局限 | 表现 | 缓解 |
|------|------|------|
| 计算成本 | K=20、E=5 时 C(19,5)=11628 组合，单组合 Simplex ~10ms，总 ~120s | `max_combos=200` 子采样 |
| ρ 饱和 | 当 target 与某 column 同时序高度自相关时，ρ 易达 0.95+ | 配合 surrogate test 验证 |
| 延迟列膨胀 | lag_columns 过多会触发禁令1 | 限制 lag_columns 总数 ≤ len(columns) × 0.3 |
| 强迫项缺失 | `forcing_signal=None` 时断后重构失效 | 在 ViewportReport.warnings 显式标注 |

---

## 7. 实施路线图

### Phase 1：`sovereign_mve.py` 核心实现（1~2 天）

- [ ] 创建 `src/sovereign_mve.py`，实现 §3.2~§3.6 全部接口
- [ ] 实现 `ViewportReport` dataclass
- [ ] 实现三热力学禁令校验函数
- [ ] 实现 `_ensemble_fusion` 加权融合
- [ ] 实现 `_detect_forcing_jump` + `_reset_lib_window_on_jump` 断后重构
- [ ] 单元测试：在 `tests/test_sovereign_mve.py` 中覆盖三条禁令、断后重构、小样本退化

**验收标准**：`python src/sovereign_mve.py` 自测通过；与 `pyEDM.Multiview` 在玩具数据集上 ρ 差异 < 0.02。

### Phase 2：八正道联动 + Viewport 报告（1 天）

- [ ] 在 `sovereign_mve.py` 中实现 `sacred_axis_frequency_trace` 滑窗函数
- [ ] 编写 `examples/eightfold_path_mve.py` 示例：读取 `narrative_meta_trajectories.csv`，跑 MVE，输出 Viewport 报告
- [ ] 编写可视化脚本：八轴频次堆叠面积图（matplotlib）

**验收标准**：在真实 `narrative_meta_trajectories.csv` 上跑通；Viewport 报告 top-5 组合具有神学可解释性。

### Phase 3：trace-engine 七勇士集成（1 天）

- [ ] 在 `trace-engine/examples/counterfactual_hybrid/six_warriors.py` 新增 `_deploy_mve` 函数
- [ ] 升级 `assemble_all_six` → `assemble_all_seven`（保留旧名为别名）
- [ ] 更新 `DESIGN_SIX_IN_ONE.md` 为 `DESIGN_SEVEN_IN_ONE.md`（或在原文档追加第七勇士章节）
- [ ] 集成测试：在 `trace-engine/tests/test_skill.py` 中新增 `test_seven_warriors_mve_deployed`

**验收标准**：七勇士全部 `deployed`（无 `fallback`）；`WarriorCard.tier="A"` 标注正确。

### Phase 4：断后重构 + 动态权重可视化（1~2 天）

- [ ] 在 `examples/eightfold_path_mve.py` 中接入 `SovereignHAVOK.forcing_` 作为 `forcing_signal`
- [ ] 实现"v_r 跳变 → lib 窗口收缩 → MVE 重学"的端到端演示
- [ ] 动态权重可视化：生成 `mve_sacred_axis_evolution.png`，展示八轴频次随时间的演化
- [ ] 在 `docs/CHANGELOG.md` 追加 "Sovereign-MVE 引擎上线" 条目

**验收标准**：在含相变点的数据集上，断后重构后 MVE 的 ρ_ensemble 高于不重构的对照组；可视化能直观识别"相变前存在/弥赛亚轴频次飙升"的预警信号。

### 路线图总览

```
Phase 1 (1-2d)          Phase 2 (1d)            Phase 3 (1d)            Phase 4 (1-2d)
─────────────           ─────────────           ─────────────           ─────────────
sovereign_mve.py   →    八正道联动         →    七勇士集成         →    断后重构+可视化
核心接口实现             Viewport 报告          WarriorCard 契约        v_r 跳变 → lib 重置
三禁令 + 融合            滑窗频次矩阵           _deploy_mve             动态权重 PNG
单元测试                神学可解释性           assemble_all_seven      CHANGELOG 追加
```

总工期：**4~6 个工作日**。完成后 Sovereign-MVE 与 SovereignHAVOK 形成完整的主权双引擎，覆盖"组合因果选择 + 动力学相变检测"两条主线。

---

## 附录 A：与现有文件的引用关系

| 现有文件 | 引用方式 | 关系 |
|---------|---------|------|
| `src/_edm_bridge.py` | 相对路径 `../src/_edm_bridge.py` | 底层 Multiview 包装器，sovereign_mve 调用其 `Multiview()` |
| `src/_numpy_edm.py` | 相对路径 `../src/_numpy_edm.py` | 纯 numpy 回退实现，`multiview_full()` 被 bridge 透传 |
| `src/sovereign_havok.py` | 相对路径 `../src/sovereign_havok.py` | 强迫项 `sh.forcing_` 作为断后重构的输入信号 |
| `trace-to-edm/csv_builder.py` | 跨 Skill 引用 | 生成 54 列 `narrative_meta_trajectories.csv` 作为 MVE 输入 |
| `trace-to-edm/config.py` | 跨 Skill 引用 | 定义 `SACRED_BOOKS` 八正道神圣书卷（line 112-121） |
| `trace-engine/examples/counterfactual_hybrid/six_warriors.py` | 跨 Skill 引用 | `WarriorCard` 类定义（line 91-107）与 `assemble_all_six` 升级点 |

## 附录 B：术语对照

| 术语 | 英文 | 出处 |
|------|------|------|
| 多视角嵌入 | Multiview Embedding (MVE) | Sugihara et al., Science 2016 |
| 组合杠杆 | Combinatorial Leverage | 本文档 §1.2 |
| 信息杠杆 | Information Leverage | 本文档 §1.2 |
| 视角自噬 | Viewport Autophagy | 用户提供的禁令1 |
| 断后重构 | Post-Rupture Re-embedding | 本文档 §3.5 |
| 八正道 | Eightfold Sacred Axes | `trace-to-edm/config.py:111` |
| 七勇士 | Seven Warriors | `trace-engine/.../six_warriors.py` 升级 |
| Viewport 报告 | Viewport Report | 本文档 §3.2 `ViewportReport` |

---

> **元审计 P4 修缮 (2026-07-20)**
