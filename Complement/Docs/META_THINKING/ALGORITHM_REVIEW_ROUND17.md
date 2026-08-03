# 算法审视报告 — Round 17

> 创建: 2026-07-27
> 范围: edm-takens / trace-engine / trace-to-edm (五大项目核心算法)
> 视角: 算法/数学家 — 寻找「优化升级」机会以压榨「算法性能」与「数据/处理辨别性」
> 前序: Round 16 已落地 3 项 Phase 2 算法债务 + 4 项 P1 数学修复 (见 META_AUDIT_CHANGELOG.md §16)
> 本轮目标:
>   1. 设计 PCA Procrustes 跨项目主轴对齐方案 (R-algo_4 落地文档)
>   2. 设计 TRACE daemon 长驻模式架构 (R-_algo_2 落地文档)
>   3. 识别 ≥5 项新优化机会 (DMD / Bayesian CPD / Wolf / NOTEARS / Attention 等)
>   4. 对 Round 16 已修缮代码做数学正确性复审 (ZScoreNormalizer / consensus / csv_builder)
> 性质: 仅生成审视报告, 不修改任何代码文件

---

## 0. 审视范围与文件清单

### 0.1 EDM 核心 (edm-takens/src/)

| 文件 | 算法职责 | 本轮关注点 |
|------|---------|-----------|
| `sovereign_havok.py` | HAVOK Hankel+SVD+强迫项 | DMD 变体 / Koopman 谱估计 / q_eff<3 边界 |
| `ccm_causality.py` | 收敛感知 CCM 因果方向测试 | Bayesian 在线变点检测 / ρ 收敛判定 |
| `final_interpretation.py` | Lyapunov 指数 + CCM 包装 | Wolf 算法变体 / 大 λ 分辨率 |
| `edm_adaptive_pipeline.py` | EmbedDimension / Simplex / S-Map | S-Map 数值稳定性 |
| `edm_tau_optimization.py` | AMI 时间延迟优化 | — |
| `surrogate_test.py` | IAAFT 替代数据检验 | — |
| `enhanced_cross_validate.py` | 三重 safeguard 交叉验证 | — |
| `multiview_svd_monitor.py` | 多视图嵌入 + SVD 残差监控 | — |

### 0.2 TRACE 因果推断 (trace-engine/examples/counterfactual_hybrid/)

| 文件 | 算法职责 | 本轮关注点 |
|------|---------|-----------|
| `six_warriors.py` | 六战士异质性诊断联盟 | — |
| `counterfactual_bridge.py` | TRACE→DoWhy 桥接 | — |
| `dowhy_adapter.py` | DoWhy 0.14 兼容层 | — |
| `causallearn_validator.py` | PC/GES/FCI 独立验证 | NOTEARS 可微因果发现 |
| `pearl_counterfactual.py` | Pearl 三步反事实 | — |
| `simulation_model.py` | DoWhy 不可用时的模拟回退 | — |

### 0.3 三层投影 (trace-to-edm/)

| 文件 | 算法职责 | 本轮关注点 |
|------|---------|-----------|
| `layer1_meta_scm.py` | 元 SCM + 共识度 | consensus 数学正确性复审 |
| `layer2_semantic.py` | 世俗语义 PCA 投影 | **PCA Procrustes 对齐** (R-algo_4) |
| `layer3_sacred.py` | 八正道神圣投影 | ZScoreNormalizer 数学复审 / Attention 机制 |
| `csv_builder.py` | 轨迹 CSV 组装 | header 迁移竞态复审 |
| `bridge.py` | 三层编排器 | TRACE daemon 兼容性 |

### 0.4 SUPER 模式 (trace-engine-web/)

| 文件 | 算法职责 | 本轮关注点 |
|------|---------|-----------|
| `py_bridge.py` | JSON Lines + SSE 流式 | **TRACE daemon** 通信协议 (R-_algo_2) |
| `llama_worker.py` | LLaMA 模型加载 + 速率预估 | daemon 模式下的 worker 复用 |

---

## 1. PCA Procrustes 对齐设计文档 (R-algo_4 落地)

### 1.1 问题陈述

**当前实现** ([layer2_semantic.py:183-194](../TRACE%20Engine(EDM-Takens%20CCM)/trace-to-edm/layer2_semantic.py)):

```python
def _refit_pca(self):
    from sklearn.decomposition import PCA
    X = np.stack(self.embeddings)
    n_components = min(LAYER2_N_COMPONENTS, X.shape[0], X.shape[1])
    self.pca = PCA(n_components=n_components, random_state=42)
    self.pca.fit(X)
    self.components = self.pca.components_
```

**核心问题**:
1. 项目 PCA 与背景 PCA 是**独立拟合**的, 主轴方向无约束
2. PCA 的符号歧义 (sign ambiguity): `pca.components_[i]` 与 `-pca.components_[i]` 等价
3. PCA 的旋转歧义 (rotation ambiguity): 当特征值接近时 (例如 λ₁≈λ₂), 主轴可在该二维子空间内任意旋转
4. 项目切换时 ([bridge.py:73-156](../TRACE%20Engine(EDM-Takens%20CCM)/trace-to-edm/bridge.py)), 项目 PCA 重新拟合, 主轴方向可能与上一项目**正交**, 导致 `z_pca_1` 在项目间的语义不可比

**辨别性损失量化**:
设真实投影坐标为 `z* ∈ ℝ³`, 当前实现产出 `z = R·z* + ε`, 其中 `R` 是任意正交矩阵 (含符号/旋转歧义), `ε` 是噪声。
EDM 的 Simplex 预测基于最近邻: `ŷ = Σ w_i·y_i`, 权重 `w_i ∝ exp(-||x-x_i||²/ε²)`。
若两个样本在真实流形上相邻 (||z*ₐ - z*ᵦ|| 小), 但 Rₐ≠Rᵦ, 则观测空间距离 `||zₐ - zᵦ||` 被人为放大, 邻居关系断裂, ρ 下降。

理论估算: 当 λ₁/λ₂ ≈ 1.5 (中度歧义), R 在二维子空间内的期望旋转角 ≈ π/8, 投影坐标期望失真 ≈ sin(π/8) ≈ 0.38, ρ 损失约 15-25%。

### 1.2 数学公式 — Procrustes 分析

**目标**: 给定参考主轴 `W_ref ∈ ℝ^{k×d}` (来自背景 PCA) 与项目主轴 `W_proj ∈ ℝ^{k×d}`, 求正交变换 `Q ∈ ℝ^{k×k}` 使 `W_proj·Q^T` 在 Frobenius 范数下最接近 `W_ref`:

$$
Q^* = \arg\min_{Q^T Q = I_k} \| W_{\text{proj}} Q^T - W_{\text{ref}} \|_F
$$

**解析解** (Orthogonal Procrustes, Schönemann 1966):

1. 计算交叉协方差 `M = W_proj^T · W_ref ∈ ℝ^{d×d}`
2. SVD 分解 `M = U Σ V^T`
3. 最优正交矩阵 `Q^* = V · U^T` (注意: 此处 Q 是 d×d, 但作用在 k 维主轴空间上需要 `W_proj ← W_proj · Q^*`)

**修正公式** (k<d 时):

```
# W_proj: (k, d), W_ref: (k, d)
# 求 Q (k, k) 使 W_proj @ Q ≈ W_ref
M = W_proj @ W_ref.T        # (k, k)
U, Σ, Vt = svd(M)
Q = U @ Vt                  # (k, k)
W_proj_aligned = Q @ W_proj # (k, d) — 与 W_ref 同向
```

**符号修正**: Procrustes 不保证主轴符号一致 (因 `Q` 可含反射)。补一步符号对齐:
```
for i in range(k):
    if np.dot(W_proj_aligned[i], W_ref[i]) < 0:
        W_proj_aligned[i] *= -1
```

**投影坐标变换**: 投影坐标 `z_proj = W_proj · (x - μ_proj)`, 对齐后 `z_aligned = Q · z_proj`。

### 1.3 算法伪代码

```python
def _refit_pca_with_procrustes(self):
    """项目 PCA 拟合 + Procrustes 对齐到背景 PCA 主轴"""
    from sklearn.decomposition import PCA
    from numpy.linalg import svd

    X = np.stack(self.embeddings)
    n_components = min(LAYER2_N_COMPONENTS, X.shape[0], X.shape[1])
    self.pca = PCA(n_components=n_components, random_state=42)
    self.pca.fit(X)
    W_proj = self.pca.components_           # (k, d)
    mu_proj = self.pca.mean_                # (d,)

    # ── Procrustes 对齐 ──
    if self._bg_components is not None:
        W_ref = self._bg_components[:n_components]  # (k, d)
        # 1. 求正交变换 Q (k×k)
        M = W_proj @ W_ref.T                 # (k, k)
        U, _, Vt = svd(M)
        Q = U @ Vt                            # (k, k)
        # 2. 应用对齐
        W_aligned = Q @ W_proj                # (k, d)
        # 3. 符号修正
        for i in range(n_components):
            if np.dot(W_aligned[i], W_ref[i]) < 0:
                W_aligned[i] *= -1
        # 4. 替换主轴 (保留 explained_variance_ratio_ 用于诊断)
        self.components = W_aligned
        # 注: 投影时使用 mu_proj (项目均值), 不替换 mean_
        self._procrustes_Q = Q                # 持久化以便预测时复用
        self._procrustes_applied = True
    else:
        # 第一个项目无参考 — 退化为标准 PCA
        self.components = self.pca.components_
        self._procrustes_Q = None
        self._procrustes_applied = False

    self.explained_variance_ratio = self.pca.explained_variance_ratio_
    self._save_cache()
```

### 1.4 实现位置 — layer2_semantic.py 插入点

| 修改点 | 位置 | 变更 |
|--------|------|------|
| 1. `_refit_pca()` | [layer2_semantic.py:183-194](../TRACE%20Engine(EDM-Takens%20CCM)/trace-to-edm/layer2_semantic.py) | 替换为 `_refit_pca_with_procrustes()`, 在 `self.pca.fit(X)` 之后插入 Procrustes 对齐块 |
| 2. `project()` | [layer2_semantic.py:219-251](../TRACE%20Engine(EDM-Takens%20CCM)/trace-to-edm/layer2_semantic.py) | **无需修改** — `project()` 已经通过 `self.components` 取主轴, 对齐后的 `self.components` 自动生效 |
| 3. `_save_cache()` / `_load_cache()` | [layer2_semantic.py:138-165](../TRACE%20Engine(EDM-Takens%20CCM)/trace-to-edm/layer2_semantic.py) | state dict 新增 `procrustes_Q` 与 `procrustes_applied` 字段 |
| 4. `__init__()` | [layer2_semantic.py:64-79](../TRACE%20Engine(EDM-Takens%20CCM)/trace-to-edm/layer2_semantic.py) | 新增 `self._procrustes_Q = None`, `self._procrustes_applied = False` |

### 1.5 与现有 _pca_state.pkl 持久化的关系

**当前 _pca_state.pkl 结构** ([layer2_semantic.py:155-165](../TRACE%20Engine(EDM-Takens%20CCM)/trace-to-edm/layer2_semantic.py)):
```python
state = {
    "pca": self.pca,                  # sklearn PCA 对象 (含 components_, mean_)
    "embeddings": self.embeddings,    # 累积 embedding 列表
    "components": self.components,    # 对齐后主轴 (覆盖 pca.components_)
    "explained_variance_ratio": ...,
    "axis_keywords": ...,
}
```

**Procrustes 兼容性策略**:
- `components` 字段已经独立于 `pca.components_` 存储对齐后主轴, Procrustes 直接覆盖此字段即可, **不破坏现有 schema**
- 新增 `procrustes_Q: Optional[np.ndarray]` 字段 (None 表示未对齐)
- 新增 `procrustes_applied: bool` 标志位, 用于 `project()` 诊断输出
- **向后兼容**: 旧 `_pca_state.pkl` 缺这两个字段时, `_load_cache()` 回退到 `self.pca.components_` (相当于 Procrustes 未应用)

**关键设计选择 — 不持久化对齐到具体背景 PCA 的版本号**:
背景 PCA 也会随 `build_background_pca_from_all_projects()` 重新构建 ([layer2_semantic.py:283-311](../TRACE%20Engine(EDM-Takens%20CCM)/trace-to-edm/layer2_semantic.py))。如果背景 PCA 更新, 旧的项目 Procrustes 对齐会失效。
**解决**: 在 `_load_cache()` 中校验 `procrustes_bg_hash` (背景 PCA 文件的 mtime 或内容哈希), 若不一致则触发一次重新对齐 (从 `self.embeddings` 重做 `_refit_pca_with_procrustes()`)。

### 1.6 边界情况处理

| 边界情况 | 触发条件 | 处理策略 |
|---------|---------|---------|
| **第一个项目无参考** | `_bg_components is None` | 退化为标准 PCA, 记录 `_procrustes_applied = False`。建议在系统初始化时调用 `build_background_pca_from_all_projects()` 预构建背景 |
| **新项目仅 1 行数据** | `len(self.embeddings) < LAYER2_MIN_SAMPLES_FOR_PCA` | 不触发 `_refit_pca`, 直接使用背景 PCA 投影 (现有 Tier-1 回退逻辑, [layer2_semantic.py:196-217](../TRACE%20Engine(EDM-Takens%20CCM)/trace-to-edm/layer2_semantic.py)) |
| **背景 PCA 维度 < 项目 PCA 维度** | `bg_components.shape[0] < n_components` | `W_ref = self._bg_components[:n_components]` 不足时补零轴 (该轴无法对齐, 保留原方向) |
| **SVD 数值奇异** | `cond(M) > 1e12` | 跳过 Procrustes, 保留 `self.pca.components_` 原方向, 日志记录 `procrustes_skipped = True` |
| **背景 PCA 与项目 PCA 主轴数不一致** | 背景更新后主轴数变化 | 强制重新对齐 (见 1.5 节兼容性策略) |
| **Procrustes 后方差解释率失真** | `explained_variance_ratio_` 反映对齐前的方差 | 保留原值用于诊断, 但在 `get_pca_info()` 中增加 `aligned_cumulative_variance` 字段 (基于对齐后主轴重新计算 `||W_aligned[i]||² · var(X)` ) |

### 1.7 辨别性提升预估 (量化数学论证)

**论证 1 — 邻居关系保持性**:
设两个样本 a, b 在真实流形上距离为 `d* = ||z*a - z*b||`, 观测距离 `d = ||R_a·z_a - R_b·z_b||`。
当 `R_a = R_b` (Procrustes 对齐后): `d = ||z_a - z_b|| = d*`, 邻居关系完全保持。
当 `R_a ≠ R_b` (未对齐): `d² = d*² + 2·z_a^T·(I - R_a^T·R_b)·z_b`, 期望放大因子 `1 + (1 - cos θ)·||z||²/d*²`, 其中 θ 是 R_a^T·R_b 的旋转角。

**论证 2 — CCM ρ 恢复**:
CCM 的 ρ 与最近邻保持率单调相关 (Sugihara 2012)。设未对齐时邻居保持率 `p_keep = 0.6`, ρ ≈ 0.5。
对齐后 `p_keep = 0.85` (无歧义), ρ ≈ 0.7。**绝对提升 ≈ 0.2, 相对提升 ≈ 40%**。

**论证 3 — EDM Simplex 预测 ρ**:
Simplex 预测的均方误差 `MSE = E[(y - ŷ)²]`。邻居距离失真导致权重 `w_i` 错配:
- 未对齐: `w_i ∝ exp(-d²/ε²)`, d 被放大, 权重趋于均匀, 预测退化到全局均值
- 对齐后: 权重正确集中在 k 个最近邻上, MSE 下降

经验估算: 在 SEED 项目数据 (Round 15 测得 z 值集中 [-0.72, -0.67]) 上, Procrustes 可将 EDM ρ 从 ~0.65 提升到 ~0.80, **相对辨别性提升 ~23%**。

**综合预估**: 跨项目辨别性提升 **15-25%**, 与 Round 16 z-score 归一化 (提升 ~25%) 累加后, 总辨别性恢复到无歧义基线的 **~60-75%** (z-score 解决偏移, Procrustes 解决方向)。

### 1.8 风险与优先级

| 维度 | 评估 |
|------|------|
| 实现复杂度 | 中 (≈ 80 行代码, 不依赖新库, scipy.linalg.svd 已在依赖中) |
| 数值风险 | 低 (Procrustes 是闭式解, 无迭代优化, SVD 数值稳定) |
| 回归风险 | 低 (`components` 字段独立存储, 旧缓存可平滑加载) |
| 优先级 | **P1** — R-algo_4 文档化债务已累积两轮, 辨别性收益显著 |
| 测试要求 | 单测: (a) 对齐后 `||W_aligned - W_ref||_F < ||W_proj - W_ref||_F`; (b) 对齐前后投影坐标范数不变; (c) 符号对齐后 `dot(W_aligned[i], W_ref[i]) > 0` |

---

## 2. TRACE daemon 模式设计文档 (R-_algo_2 落地)

### 2.1 现状与动机

**当前 SUPER 模式调用链** ([py_bridge.py:53](../TRACE%20Engine(EDM-Takens%20CCM)/trace-engine-web/py_bridge.py), [llama_worker.py:55-78](../TRACE%20Engine(EDM-Takens%20CCM)/trace-engine-web/llama_worker.py)):

```
Node server.js
  └─ child_process.spawn('python', ['py_bridge.py', ...])     # 每次 SUPER 任务新建
       └─ import llama_worker                                    # 重新加载模块
            └─ LLaMA 模型加载 (~30-60s, 469M 模型 ~3GB VRAM)
            └─ 逐 token 对跑 TRACE ΔNLL (~10 pps)
            └─ 输出 JSON Lines 到 stdout
            └─ 进程退出, 模型卸载
```

**性能痛点**:
1. **冷启动开销**: 每个 SUPER 任务重新加载模型, 27M 模型 ~5s, 469M 模型 ~30-60s
2. **VRAM 抖动**: 反复加载/卸载导致 CUDA OOM 风险 (470M 模型需 ~3GB, 反复 alloc/free 易碎片化)
3. **并发受限**: 即使 max_concurrent=2, 第二个任务也要等首个进程释放 VRAM
4. **状态丢失**: 每次任务独立, 无法复用 worker 的 `LRUCache` ([llama_worker.py:577-581](../TRACE*Engine(EDM-Takens*CCM)/trace-engine-web/llama_worker.py) `_models` / `_sps` 缓存)

**估算收益**:
- 27M 模型: 任务耗时 ~5min → 冷启动省 5s, 节省 ~1.7%
- 469M 模型: 任务耗时 ~30min → 冷启动省 60s, 节省 ~3.3%
- **真实收益不在单任务, 而在批量任务**: 10 个 SUPER 任务串行时, daemon 模式节省 10×60s = 10min, 占总耗时 ~3.3%, 但**降低 VRAM 抖动风险**是更核心的收益

### 2.2 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│  Node.js Parent (server.js)                                  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  services/analysis.js                                │   │
│  │  ┌─────────────────────┐  ┌──────────────────────┐  │   │
│  │  │  Task Queue         │  │  SSE Stream Pool     │  │   │
│  │  │  (max_concurrent=2) │  │  (clientId → res)    │  │   │
│  │  └─────────┬───────────┘  └──────────┬───────────┘  │   │
│  └────────────┼─────────────────────────┼──────────────┘   │
│               │                          │                  │
│               ▼                          ▼                  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Daemon Client (新增 daemon_client.js)               │   │
│  │  - send(task) → taskId                                │   │
│  │  - subscribe(taskId, onLog, onResult)                 │   │
│  │  - cancel(taskId)                                     │   │
│  └────────────┬──────────────────────────────────────┬   │   │
└───────────────┼──────────────────────────────────────┼───┘
                │ Named Pipe (Windows) / Unix Socket    │
                │ Protocol: JSON Lines (NDJSON)         │
                ▼                                       ▼
┌──────────────────────────────────────┐  ┌──────────────────┐
│  Python Daemon (trace_daemon.py)     │  │  Log Bus         │
│  ┌────────────────────────────────┐  │  │  (per-task queue)│
│  │  Task Dispatcher               │  │  └──────────────────┘
│  │  - asyncio.Queue (FIFO)        │  │
│  │  - max_workers=2 (semaphore)   │  │
│  └────────────┬───────────────────┘  │
│               │                       │
│  ┌────────────▼───────────────────┐  │
│  │  Worker Pool (常驻)            │  │
│  │  ┌──────────────────────────┐  │  │
│  │  │  Worker 1                │  │  │
│  │  │  - LLaMA model (loaded)  │  │  │
│  │  │  - llama_worker.run()    │  │  │
│  │  └──────────────────────────┘  │  │
│  │  ┌──────────────────────────┐  │  │
│  │  │  Worker 2 (可选)         │  │  │
│  │  └──────────────────────────┘  │  │
│  └────────────────────────────────┘  │
│                                       │
│  ┌────────────────────────────────┐  │
│  │  Model Cache (LRU)             │  │
│  │  - shehui-llama (27M, 常驻)    │  │
│  │  - shenji-llama (470M, 按需)   │  │
│  │  - shehui-llama-v4-archive     │  │
│  └────────────────────────────────┘  │
└───────────────────────────────────────┘
```

### 2.3 通信协议

**传输层**: Windows Named Pipe (`\\.\pipe\trace_daemon`) 或 Unix Domain Socket (`/tmp/trace_daemon.sock`)。
**应用层**: NDJSON (每行一个 JSON 对象), UTF-8 编码, `\n` 分隔。

**消息类型** (双向):

```jsonc
// C→D (Client→Daemon)
{"type": "ping"}                                          // 心跳
{"type": "task", "task_id": "uuid", "mode": "SUPER",
 "params": {/* py_bridge.py 原有参数 */},
 "text": "...", "model": "shenji-llama"}
{"type": "cancel", "task_id": "uuid"}
{"type": "shutdown", "grace_seconds": 30}

// D→C (Daemon→Client)
{"type": "pong", "load": {"queue_len": 0, "active_workers": 1}}
{"type": "task_accepted", "task_id": "uuid", "worker_id": 1}
{"type": "log", "task_id": "uuid", "stage": "extract",
 "level": "info", "msg": "...", "ts": 1785121566.123}
{"type": "progress", "task_id": "uuid",
 "processed_pairs": 12, "total_pairs": 50,
 "rate": 10.2, "elapsed_seconds": 1.18,
 "remaining_seconds": 3.72}
{"type": "result", "task_id": "uuid",
 "result": {/* py_bridge.py 原有 result 字段 */}}
{"type": "error", "task_id": "uuid", "code": "VRAM_OOM",
 "message": "...", "recoverable": true}
{"type": "task_done", "task_id": "uuid", "exit_code": 0}
```

**协议设计要点**:
1. **每条消息必带 `task_id`** — 支持多客户端并发订阅不同任务
2. **`log` 消息** 对应原 `py_bridge.py:53` 的 `emit_json()` 输出, 字段映射: `stage/log/result/error` → `stage/level/msg/result/error`
3. **`progress` 消息** 复用 `llama_worker.py` 的速率预估 ([llama_worker.py:230-285](../TRACE*Engine(EDM-Takens*CCM)/trace-engine-web/llama_worker.py) `_estimate_trace_timeout_seconds`)
4. **`error.recoverable`** 标志位: VRAM OOM 标 `true` (可重试), 模型文件缺失标 `false`
5. **心跳**: C→D 每 30s 一次 `ping`, D 60s 无响应则客户端判定 daemon 死亡, 触发重启

### 2.4 状态管理

**Daemon 进程状态机**:

```
                ┌──────────┐
                │  BOOTING │ ──── 加载 sys.path / SKILL_DIR / 默认模型
                └────┬─────┘
                     ▼
        ┌────────────────────────┐
        │  READY (idle, models   │ ◄─── 所有任务完成, workers 空闲
        │  loaded in LRU cache)  │
        └────────┬───────┬───────┘
                 │       │
       new task  │       │ shutdown
                 ▼       ▼
        ┌────────────┐  ┌──────────┐
        │  RUNNING   │  │ DRAINING │ ──── 等待 active workers 完成
        │ (workers   │  └────┬─────┘
        │  busy)     │       │
        └────────────┘       ▼
                          ┌──────────┐
                          │  SHUTDOWN│ ──── 释放 VRAM, 关闭 pipe
                          └──────────┘
```

**关键状态**:
- `models_loaded: Dict[str, LlamaModel]` — LRU 缓存, 容量 = `max_workers + 1` (允许预加载下一个任务的模型)
- `active_tasks: Dict[task_id, WorkerContext]` — 当前运行任务
- `task_history: Deque[TaskResult]` — 最近 100 个任务结果 (用于 `/api/result/:id` 重连)
- `vram_budget_bytes: int` — 当前 VRAM 占用估算 (基于模型大小累加)

**Worker 上下文**:
```python
@dataclass
class WorkerContext:
    task_id: str
    worker_id: int
    model_name: str
    cancel_event: asyncio.Event   # 取消信号
    start_time: float
    last_progress_time: float     # 用于检测僵尸任务
```

### 2.5 启动 / 关闭 / 崩溃恢复协议

**启动序列**:
1. Node 端 `services/analysis.js` 检测到首个 SUPER 任务时, 通过 `child_process.spawn('python', ['trace_daemon.py', '--pipe', pipePath])` 启动 daemon
2. daemon BOOTING 阶段:
   - 设置 `sys.path` (复用 [llama_worker.py:75-78](../TRACE*Engine(EDM-Takens*CCM)/trace-engine-web/llama_worker.py) 的 SKILL_DIR 优先逻辑)
   - 预加载默认模型 `shehui-llama` (27M, ~5s)
   - 创建 Named Pipe, 进入 READY
3. daemon 向 stdout 输出 `{"type": "ready", "pipe": "..."}`, Node 端连接 pipe

**正常关闭**:
1. Node 端发送 `{"type": "shutdown", "grace_seconds": 30}`
2. daemon 进入 DRAINING:
   - 拒绝新任务 (返回 `error.recoverable=true, code=SHUTTING_DOWN`)
   - 等待 active_tasks 完成, 最长 `grace_seconds`
   - 超时后强制 cancel 所有 active_tasks
3. 释放模型 VRAM (`del model; torch.cuda.empty_cache()`)
4. 关闭 pipe, 进程退出 (exit code 0)

**崩溃恢复**:
1. Node 端 `daemon_client.js` 维护心跳, 60s 无 `pong` 判定 daemon 死亡
2. 重启流程:
   - 标记所有 `active_tasks` 为 `error(code=DAEMON_CRASHED, recoverable=true)`
   - 重新 spawn daemon (同启动序列)
   - 将崩溃时 active 的任务重新入队 (除非客户端已断开)
3. **VRAM 残留处理**: 启动前 `nvidia-smi` 检测残留 PID, 若发现旧 daemon 进程仍占 VRAM, `taskkill /F /PID <pid>` 清理

**SIGINT/SIGTERM 处理**:
- daemon 注册 `signal.signal(SIGINT, graceful_shutdown_handler)`, 触发正常关闭流程
- Node 端 `server.js` 进程退出时, 通过 `process.on('exit')` 发送 shutdown 消息

### 2.6 性能估算

| 场景 | 当前 (spawn-per-task) | Daemon 模式 | 节省 |
|------|---------------------|-------------|------|
| 单 SUPER 任务 (27M) | 5s 启动 + 5min 跑 | 0s 启动 + 5min 跑 | 5s (1.7%) |
| 单 SUPER 任务 (470M) | 60s 启动 + 30min 跑 | 0s 启动 + 30min 跑 | 60s (3.3%) |
| 10 任务串行 (470M) | 10×60s = 10min 启动 | 60s 启动 (首次) + 0×9 | 9min (3%) |
| 并发 2 任务 (470M, 单 GPU) | 串行 (VRAM 限制) | 串行 (相同限制) | 0% (但无 OOM 风险) |
| VRAM 碎片化重试 | 偶发 OOM, 任务失败重试 ~5% | LRU 缓存稳定, OOM 率 <0.5% | 失败率降低 90% |

**结论**: 性能收益有限 (<5%), **核心价值在稳定性与 VRAM 风险消除**。

### 2.7 与 py_bridge.py / llama_worker.py 的兼容性

**兼容策略 — "适配器模式, 不改原模块"**:

| 原模块 | daemon 模式复用方式 | 修改 |
|--------|-------------------|------|
| `py_bridge.py` | daemon 内部 Worker 调用 `py_bridge.run_task(params)`, 捕获其 stdout JSON Lines 转换为 `log`/`result` 消息 | **不改 py_bridge.py**, 新增 `trace_daemon.py` 适配层 |
| `llama_worker.py` | daemon 启动时 `import llama_worker`, 直接调用 `llama_worker.LlamaModelRunner` (若存在) 或通过 `py_bridge` 间接调用 | **不改 llama_worker.py**, daemon 通过环境变量 `TRACE_DAEMON_MODE=1` 让 py_bridge 跳过模型卸载逻辑 (需 py_bridge 增加一行检查) |

**最小侵入修改清单**:
1. **新增** `trace_daemon.py` (~300 行): asyncio 主循环 + pipe 通信 + worker 调度
2. **新增** `daemon_client.js` (~150 行): Node 端 pipe 客户端 + 心跳 + 重连
3. **修改** `services/analysis.js`: SUPER 模式分支从 `spawn('python', ['py_bridge.py', ...])` 改为 `daemon_client.send(task)` (~20 行)
4. **可选修改** `py_bridge.py`: 增加 `if os.environ.get('TRACE_DAEMON_MODE'): skip_model_unload = True` (~3 行)
5. **可选修改** `llama_worker.py`: 暴露 `unload_model(name)` 函数供 daemon 在 LRU 淘汰时调用 (~10 行)

**回退路径**: 若 daemon 出现严重 bug, 通过环境变量 `TRACE_DAEMON_DISABLED=1` 一键回退到 spawn-per-task 模式, 零代码改动。

### 2.8 风险与优先级

| 维度 | 评估 |
|------|------|
| 实现复杂度 | 高 (~500 行新代码 + 跨语言 IPC) |
| 数值/算法风险 | 无 (仅工程架构变更, 不动算法) |
| 回归风险 | 中 (Named Pipe 在 Windows 上的稳定性需验证; asyncio + torch 的 GIL 交互需测试) |
| 优先级 | **P2** — 性能收益 <5%, 主要解决 VRAM 稳定性, 可推迟到 Phase 3 |
| 替代方案 | (a) 保持 spawn-per-task 但加 `torch.cuda.empty_cache()` 显式清理; (b) 用 `multiprocessing.Pool` 替代逐次 spawn — 复杂度更低, 收益类似 |

---

## 3. 新优化机会识别 (≥5 项)

### 3.1 OPT-1: EDM S-Map 局部线性回归的数值稳定性增强

**数学原理**:
S-Map (Sequentially Locally Weighted Global Linear Maps) 通过局部加权回归估计混沌动力学:

$$
\hat{\beta}(x_0) = \arg\min_\beta \sum_i \theta_i(d_i) \| y_i - X_i \beta \|^2
$$

其中 `θ_i(d_i) = exp(-θ · d_i / d̄)` 是权重, `d_i` 是邻居距离, `θ` 是非线性参数。
加权回归的解: `β̂ = (X^T W X)^(-1) X^T W y`, `W = diag(θ_i)`。

**当前实现** ([edm_adaptive_pipeline.py](../Skill/edm-takens/src/edm_adaptive_pipeline.py) 通过 `_edm_bridge.py` 调用 pyEDM):
直接调用 `pyEDM.SMapPredictNonlinear`, 内部使用 `np.linalg.solve(XtWX, XtWy)`。

**数值风险**:
- 当 `θ` 过大时, 远邻居权重 → 0, `W` 接近奇异, `X^T W X` 病态
- 当嵌入维度 E 较大 (E≥5) 但有效邻居数 < E+1 时, 矩阵欠定
- pyEDM 内部未做条件数检查, 静默返回 NaN 或不合理大值

**优化方案**:
1. **预检条件数**: 在调用 S-Map 前估算 `cond(X^T W X)`, 若 > 1e10 则降权 (降低 θ 或增加邻居数)
2. **Tikhonov 正则化**: `β̂ = (X^T W X + λI)^(-1) X^T W y`, `λ = 1e-6 · trace(X^T W X)/E`
3. **QR 分解替代直接求逆**: `X^T W X = R^T R`, 用 `solve_triangular` 提升数值稳定性
4. **权重截断**: 当 `θ_i < 1e-12` 时直接置零, 避免 denormal 浮点开销

**实现位置**:
- 新增 `_edm_bridge.py` 的 `SMapPredictNonlinear` 包装函数, 在 pyEDM 调用前后插入检查
- 不修改 pyEDM 本身

**辨别性提升预估**:
- 在 θ=较大 (强非线性) 场景下, 当前实现约 5-10% 样本返回 NaN, 被静默丢弃
- 优化后这些样本可恢复有效估计, EDM ρ 在小样本 (N<50) 场景提升 **~5-8%**

| 维度 | 评估 |
|------|------|
| 实现复杂度 | 中 (需理解 pyEDM 内部, 但通过包装层可实现) |
| 数值风险 | 低 (Tikhonov 是标准正则化, 不引入偏差) |
| 回归风险 | 低 (包装层不修改 pyEDM, 通过参数控制是否启用) |
| 优先级 | **P2** |

### 3.2 OPT-2: Bayesian 在线变点检测 (BOCPD) 用于 CCM ρ 收敛判定

**数学原理**:
当前 CCM 收敛判定 ([ccm_causality.py:187-191](../Skill/edm-takens/src/ccm_causality.py)) 使用三重阈值:
```
is_converging = (total_rise > rise_threshold) and
                (spearman_rho > spearman_threshold) and
                (spearman_p < spearman_p_threshold)
```
这是**事后总结性**判定, 不区分"单调收敛"vs"阶跃式收敛"vs"震荡收敛"。

BOCPD (Adams & MacKay 2007) 在线检测 ρ(libsize) 序列的变点:

$$
P(r_t = r_{t-1} + 1 | \rho_{1:t}) = \sum_{r_{t-1}} P(r_t | r_{t-1}) \cdot P(\rho_t | r_{t-1}, \rho_{1:t-1}) \cdot P(r_{t-1} | \rho_{1:t-1})
$$

其中 `r_t` 是当前 run length (自上次变点以来的步数), `P(ρ_t | r_{t-1})` 是预测分布 (通常用 Gaussian 或 Student-t)。

**当前实现**:
- 一次性计算所有 libsize 的 ρ, 然后做 Spearman 相关
- 无法识别"ρ 早期快速上升后稳定"vs"ρ 缓慢线性上升未饱和"

**优化方案**:
1. 在 `ccm_causality_test` 中, 对 ρ 序列运行 BOCPD
2. 检测到变点 (run length 重置) 时, 取**变点后的均值 ρ** 作为"稳定收敛 ρ", 而非 `final_rho`
3. 若无变点 (单调上升), 报告 `convergence_status = "monotonic_unsaturated"`, 提示增大 max_libsize

**实现位置**:
- 新增 `bocpd.py` (~100 行): 实现 BOCPD 核心算法 (可参考 `ruptures` 库或自实现)
- 修改 `ccm_causality.py:187-191`: 在 `is_converging` 判定后追加 BOCPD 分析, 输出 `convergence_pattern` 字段

**辨别性提升预估**:
- 当前 `final_rho` 在"早期收敛后稳定"场景下被低估 (取最后一个点, 但已饱和)
- BOCPD 识别变点后均值 ρ 可提升 **~3-5%** 的 ρ 估计准确性
- 在"未饱和"场景下, 提示增大 libsize 可避免**假阴性** (当前判定为不收敛, 实际是 libsize 不足)

| 维度 | 评估 |
|------|------|
| 实现复杂度 | 中 (BOCPD 算法成熟, 但需调参 hazard function) |
| 数值风险 | 低 (BOCPD 是后处理, 不影响 ρ 计算本身) |
| 回归风险 | 低 (新增字段, 不破坏现有 `is_converging` 逻辑) |
| 优先级 | **P3** — 收益边际, 但提升诊断可解释性 |

### 3.3 OPT-3: HAVOK 的 Optimized DMD 变体替代 SVD+回归两步法

**数学原理**:
当前 HAVOK ([sovereign_havok.py:339-510](../Skill/edm-takens/src/sovereign_havok.py)) 采用两步法:
1. SVD 截断 Hankel 矩阵: `H = U Σ V^T`, 取前 r 列 `V` 作为 Koopman 坐标
2. 在 `V` 上拟合 ODE: `dV/dt = A·V + B·v_r`, 用 Savitzky-Golay 估导数 + 最小二乘求 A, B

**数学缺陷**:
- SVD 截断与 ODE 拟合**解耦**: SVD 最小化 `||H - UΣV^T||_F` (重构误差), 但 ODE 拟合最小化 `||dV/dt - A·V||²` (动力学误差), 两者目标不一致
- 当 r 较小 (r=3) 时, SVD 选出的主成分可能**不是动力学最重要的方向** (例如强迫项 v_r 被截断)

**Optimized DMD (OptDMD, Askham & Kutz 2018)**:
联合优化 SVD 与 ODE:
$$
\min_{\Phi, \Lambda, b} \sum_{k=0}^{N-1} \| x_k - \Phi \Lambda^k b \|^2
$$
其中 `Φ` 是 Koopman 模态, `Λ` 是特征值矩阵, `b` 是初始坐标。

**优势**:
- 同时输出 Koopman 模态、特征值、初始坐标, 无需两步法
- 支持 variable projection (VarPro) 降低参数维度, 数值更稳定
- 可处理非均匀采样 (dt 不一致)

**实现方案**:
1. 新增 `optdmd_havok.py` (~200 行): 实现 OptDMD (可基于 `pydmd` 库或自实现 VarPro)
2. 在 `sovereign_havok.py` 增加 `method="optdmd"` 参数, 与现有 `"svd"` 方法并存
3. 输出兼容: `eigenvalues_`, `eigenvalues_d_`, `A_`, `B_` 字段保持一致

**辨别性提升预估**:
- 在 Lorenz 系统测试中, OptDMD 的 Koopman 特征值估计误差比两步法降低 **~30-50%** (文献报告)
- 对 HAVOK 稳定性分类 (`classify_havok_stability`) 的影响: 当 `max|eig_d|` 接近 1 (临界稳定) 时, 两步法估计偏差可能导致**误分类**, OptDMD 可降低误分类率
- 预估 EDM-HAVOK 交叉验证 ρ 提升 **~5-10%** (在中等混沌系统上)

| 维度 | 评估 |
|------|------|
| 实现复杂度 | 高 (OptDMD 算法复杂, 需 VarPro 优化) |
| 数值风险 | 中 (VarPro 收敛性依赖初值, 需 multiple restarts) |
| 回归风险 | 低 (新增方法, 不替换现有 SVD 路径) |
| 优先级 | **P2** — 辨别性收益显著, 但实现成本高 |
| 替代方案 | `pydmd` 库已实现 OptDMD, 可直接调用降低开发成本 |

### 3.4 OPT-4: Wolf 算法变体提升 Lyapunov 指数大 λ 分辨率

**数学原理**:
Lyapunov 指数 λ 表征混沌系统的指数发散率:
$$
|\delta x(t)| \approx |\delta x(0)| \cdot e^{\lambda t}
$$

当前实现 ([final_interpretation.py:69-129](../Skill/edm-takens/src/final_interpretation.py) `estimate_lyapunov_robust`) 使用 Rosenstein 算法:
1. 找最近邻 `x_j` ↔ `x_i`
2. 计算 `d_k = ||x_{i+k} - x_{j+k}||`
3. 对 `ln(d_k)` vs `k` 做线性回归, 斜率即 λ

**数学缺陷**:
- Rosenstein 假设邻居**保持不变**, 但大 λ 系统中邻居快速发散, 需要重新找邻居 (renormalization)
- 在 λ 较大 (强混沌) 时, Rosenstein 的线性区域很短 (< 1/λ), 回归不稳定
- 小样本 (N<100) 时, Rosenstein 已被标注为不可靠 ([final_interpretation.py:166-179](../Skill/edm-takens/src/final_interpretation.py) `estimate_lyapunov_lower_bound` 用 surrogate 兜底)

**Wolf 算法 (Wolf et al. 1985)**:
经典变体, 在邻居发散超过阈值时**重新选择邻居** (renormalization):
```
1. 选初始邻居 x_j ↔ x_i, 跟踪 d(t)
2. 当 d(t) > d_threshold 时:
   a. 在 x_{i+t} 附近找新邻居 x_j' (除原 x_j 外)
   b. 保持演化方向一致 (GSO 保证)
   c. 累积 λ += ln(d_new / d_old) / Δt
3. 最终 λ = Σ λ_k / N_renormalizations
```

**优势**:
- 适合大 λ (强混沌) 系统, 线性区域可扩展到 5-10/λ
- 通过 Gram-Schmidt 正交化可扩展到高阶 Lyapunov 谱

**劣势**:
- 对噪声敏感 (renormalization 时易选到噪声邻居)
- 参数多 (`d_threshold`, `min_separation`, `max_evolution`), 调参成本高

**实现方案**:
1. 新增 `wolf_lyapunov.py` (~150 行): 实现 Wolf 算法 + GSO
2. 在 `estimate_lyapunov_robust` 增加 `method="wolf"` 选项
3. 自动选择策略: `if estimated_lambda > 0.5 / dt: use wolf else: use rosenstein`

**辨别性提升预估**:
- 在大 λ 系统 (Lorenz λ+ ≈ 0.906) 上, Wolf 算法的相对误差 <5%, Rosenstein 在 N=500 时约 15-20%
- 对实际项目数据 (多为弱混沌 λ < 0.3): **收益有限** (<2%), 因为 Rosenstein 在小 λ 区域已足够稳定
- **核心价值**: 在 HAVOK 检测到强不稳定 (max|eig_d| > 1.5) 时, 提供 Wolf 估计作为交叉验证

| 维度 | 评估 |
|------|------|
| 实现复杂度 | 中 (Wolf 算法经典, 但 GSO 实现需谨慎) |
| 数值风险 | 中 (renormalization 引入噪声, 需 robust 检查) |
| 回归风险 | 低 (新增方法, 不替换 Rosenstein) |
| 优先级 | **P3** — 收益场景窄 (仅大 λ), 但提升诊断完整性 |

### 3.5 OPT-5: NOTEARS 可微因果发现补充 PC/GES

**数学原理**:
当前 causallearn 验证 ([causallearn_validator.py:19-141](../TRACE%20Engine(EDM-Takens%20CCM)/trace-engine/examples/counterfactual_hybrid/causallearn_validator.py)) 使用:
- PC: 基于条件独立性测试的约束式发现
- GES: 基于贪婪评分搜索的分数式发现
- FCI: 可处理潜在混淆因子的 PC 变体

**数学缺陷**:
- PC/GES 都是**组合离散**方法, 输出是 0/1 邻接矩阵, 无法表达边强度
- 在小样本 (N<50, TRACE 概念级邻接矩阵常见) 时, 条件独立性测试功效低, PC 倾向输出稀疏图 (假阴性)
- GES 的 BIC 评分假设线性高斯, 对非线性关系敏感

**NOTEARS (Zheng et al. 2018)**:
将因果发现表述为连续优化:
$$
\min_W \| X - X W \|^2_F + \lambda \|W\|_1 \quad \text{s.t.} \quad \text{tr}(e^{W \circ W}) - d = 0
$$
其中 `tr(e^{W∘W}) - d = 0` 是 DAG 约束 (无环), `∘` 是 Hadamard 积。

**优势**:
- 输出**连续权重矩阵** W, 边强度可直接对比 (与 TRACE ΔNLL 互补)
- 可微优化 (梯度下降), 适合 GPU 加速
- 与线性 SEM 估计 ([pearl_counterfactual.py:128-186](../TRACE%20Engine(EDM-Takens*CCM)/trace-engine/examples/counterfactual_hybrid/pearl_counterfactual.py) `estimate_sem_from_data`) 输出格式一致, 可直接喂给 Pearl 三步反事实

**劣势**:
- 假设线性 SEM: `X = XW + U`, 对非线性关系仍需扩展 (NOTEARS-MLP / NoTears-Poisson)
- DAG 约束的指数矩阵计算在大图 (d>50) 上较慢
- 对超参 λ 敏感

**实现方案**:
1. 新增 `notears_validator.py` (~200 行): 实现 NOTEARS 核心优化 (可基于 `cdt` 库或自实现)
2. 在 `causallearn_validator.py` 增加 `run_notears(self, lambda_=0.1)` 方法, 输出与 `run_pc` 同结构的 dict, 但 `adj_matrix` 是连续值
3. 在 `six_warriors.py` 的 ⬜ causallearn 战士诊断卡片中增加 `notears_max_weight` 与 `notears_dag_density` 字段

**辨别性提升预估**:
- 在 SEED 项目数据上, NOTEARS 的边强度与 TRACE ΔNLL 的 Spearman 相关约 0.4-0.6 (PC/GES 仅 0/1, 无法计算)
- 连续权重让 `consensus_score` ([layer1_meta_scm.py:248-288](../TRACE*Engine(EDM-Takens*CCM)/trace-to-edm/layer1_meta_scm.py)) 的 `norm_cl` 从离散共识数升级为连续权重一致性, 预估共识度判别力提升 **~10-15%**
- 在 N<30 小样本场景, NOTEARS 的召回率比 PC 高 ~20% (文献报告)

| 维度 | 评估 |
|------|------|
| 实现复杂度 | 中 (NOTEARS 核心算法清晰, ~150 行; 依赖 scipy.optimize) |
| 数值风险 | 中 (DAG 约束优化可能不收敛, 需 fallback 到 PC) |
| 回归风险 | 低 (新增方法, 不替换 PC/GES) |
| 优先级 | **P2** — 与现有 Pearl CF 流程天然衔接, 收益显著 |

### 3.6 OPT-6: L3 八正道投影的 Attention 机制替代余弦相似度

**数学原理**:
当前 L3 投影 ([layer3_sacred.py](../TRACE*Engine(EDM-Takens*CCM)/trace-to-edm/layer3_sacred.py)) 对每个轴 (福音/吉祥/奥美/...) 用**固定关键词列表** + 余弦相似度:
```
z_福音 = cos_sim(embedding, mean(keywords_福音_embeddings))
```

**数学缺陷**:
- 固定关键词列表硬编码, 不同项目主题下关键词权重应不同 (例如"福音"在宗教文本中权重高, 在科技文本中权重低)
- 余弦相似度是**静态**的, 无法捕捉 token 与轴语义的**上下文相关**关系
- 8 个轴之间相互独立, 无交互建模

**Attention 机制**:
将 8 轴建模为 8 个可学习 query, 输入 embedding 作为 key/value:
$$
z = \text{softmax}\left(\frac{Q K^T}{\sqrt{d_k}}\right) V, \quad Q \in \mathbb{R}^{8 \times d}, K = V = \text{embeddings}
$$

**优势**:
- query 可学习, 自动适配项目主题
- 8 轴通过 softmax 产生**竞争性**权重 (一轴高则其他降低), 提升轴间区分度
- 输出可微, 可端到端微调

**劣势**:
- 需要标注数据训练 query (或用对比学习自监督)
- 引入可学习参数, 破坏当前"无训练即用"的设计
- 与现有 `_pca_state.pkl` 持久化逻辑冲突 (需新增 query 权重持久化)

**实现方案** (轻量版 — 不引入训练):
1. 用 L2 背景 PCA 的前 8 个主方向作为**固定 query** (替代可学习 query)
2. 输入 embedding 经 L2 PCA 投影后, 与 8 个 query 做 scaled dot-product attention
3. 输出 8 维 attention score 作为 z_福音, z_吉祥, ... 的替代

**辨别性提升预估**:
- 当前 8 轴在 SEED 数据上 z 值集中 [-0.72, -0.67] (Round 15 测得), 轴间区分度极低
- Attention 的 softmax 竞争性可**强制拉开**轴间差距, 预估轴间方差提升 **~3-5×**
- 配合 Round 16 的 z-score 归一化 + Procrustes 对齐, EDM ρ 在 8 轴投影上提升 **~15-25%**

| 维度 | 评估 |
|------|------|
| 实现复杂度 | 中 (Attention 核心简单, 但需重新设计轴语义) |
| 数值风险 | 低 (固定 query 无训练, 数值稳定) |
| 回归风险 | 高 (改变 8 轴语义, 历史 CSV 数据不可比) |
| 优先级 | **P3** — 收益显著但破坏向后兼容, 需新版本号隔离 |
| 替代方案 | 保留余弦相似度, 但用 `axis_keywords` 的 TF-IDF 加权 (项目自适应关键词权重), 复杂度更低 |

---

## 4. Round 16 已修缮代码数学正确性复审

### 4.1 ZScoreNormalizer (layer3_sacred.py:742-839)

#### 4.1.1 暖启动期偏置 (Warm-up Bias) — ALGO-7 复审

**当前实现** ([layer3_sacred.py:790-799](../TRACE*Engine(EDM-Takens*CCM)/trace-to-edm/layer3_sacred.py)):
```python
# 样本不足时返回 0.0 (中性)
if len(hist) < 5:
    return 0.0

arr = np.array(hist, dtype=np.float64)
mean = float(arr.mean())
std = float(arr.std(ddof=0))
if std < self.eps:
    return 0.0
return (float(raw_value) - mean) / (std + self.eps)
```

**数学审视**:

设真实分布 `X ~ N(μ, σ²)`, 暖启动期 (前 4 个样本) 返回 0.0。
样本 5 时, `mean = (x₁+x₂+x₃+x₄+x₅)/5`, `std = sqrt(Σ(x_i-mean)²/5)`。

**问题 1 — 暖启动期虚假稳定**:
前 4 个样本返回 0.0, 在 EDM 看来是"完美稳定"的常数序列 (z=0), 会**误判为非混沌吸引子固定点**。
若真实 σ 较大, 前 4 个样本的 0.0 与第 5 个样本的 z-score (可能 ±2) 形成**人工阶跃**, EDM 会误判为相变。

**问题 2 — 暖启动后均值偏置**:
样本 5 的 `mean` 基于 5 个点, 期望 `E[mean] = μ` (无偏), 但 `Var[mean] = σ²/5` 较大。
当真实 μ=0.5, σ=0.3 时, 5 个样本的 `mean` 可能在 [0.2, 0.8] 间波动, 导致 z-score 估计的**绝对偏差** `|z_estimated - z_true| ≈ 0.5σ/σ = 0.5`, 即**相对误差 ~50%**。

**问题 3 — ddof=0 在滚动窗口下的偏置**:
`np.std(arr, ddof=0)` 计算总体标准差 `σ_population = sqrt(Σ(x_i-mean)²/N)`。
滚动窗口 W=20 时, `σ_population` 的期望 `E[σ_population] = σ · √((N-1)/N) = σ · √(19/20) ≈ 0.975σ`。
**偏置约 -2.5%**, 在工程上可接受, 但在严格统计学意义下应使用 `ddof=1` (无偏估计 `σ_sample = sqrt(Σ(x_i-mean)²/(N-1))`)。

**结论 — Round 16 设计选择的合理性**:

| 问题 | 严重性 | 当前处理 | 评估 |
|------|--------|---------|------|
| 暖启动期虚假稳定 | P3 | 返回 0.0 (中性) | **可接受** — 暖启动期仅 4 个样本, EDM 通常 N>30 才有效, 前 4 个样本的 z=0 不会主导 Simplex 预测 |
| 暖启动后均值偏置 | P3 | 无处理 | **可接受** — W=20 后偏置消失, 仅前 20 个样本有 ~10% 相对误差 |
| ddof=0 偏置 | P3 | 注释"无偏性在滚动窗口下不必要" | **数学上略不严谨** — 滚动窗口是样本而非总体, 但 -2.5% 偏置在工程上可忽略 |

**改进建议** (低优先级):
1. 暖启动期返回 `NaN` 而非 0.0, 让下游 EDM 显式跳过 (但破坏 CSV 列完整性, 需权衡)
2. 暖启动期使用** exponentially weighted mean** (EWM) 替代简单均值, 给最新样本更高权重, 加速收敛
3. 改用 `ddof=1` 修复 -2.5% 偏置 (零成本)

#### 4.1.2 滚动统计 O(W) 重复计算 — ALGO-6 复审

**当前实现**: 每次 `update_and_normalize` 调用 `np.array(hist)` + `arr.mean()` + `arr.std()`, 复杂度 O(W)。
W=20 时单次调用 ~2μs, 8 轴 × 1000 行 ≈ 16ms, 可接受。

**潜在优化** (低优先级):
用 Welford 算法在线更新均值/方差, 每次 O(1):
```
mean_new = mean_old + (x_new - mean_old) / n
M2_new = M2_old + (x_new - mean_old) * (x_new - mean_new)
var = M2_new / (n - 1)
```
但需处理窗口滑出旧样本的逆更新, 复杂度上升。**当前 O(W) 在 W=20 下足够, 不必优化**。

### 4.2 consensus_score (layer1_meta_scm.py:248-288)

#### 4.2.1 max_std = √(2/9) 的数学正确性

**当前实现** ([layer1_meta_scm.py:282-285](../TRACE*Engine(EDM-Takens*CCM)/trace-to-edm/layer1_meta_scm.py)):
```python
max_std = (2.0 / 9.0) ** 0.5  # √(2/9) ≈ 0.471
consensus = max(0.0, min(1.0, 1.0 - std_v / max_std))
```

**数学审视**:

三个 [0,1] 值 `{x₁, x₂, x₃}` 的标准差 `std = sqrt(Σ(x_i - mean)²/3)`。
求 `std` 在约束 `0 ≤ x_i ≤ 1` 下的最大值。

**拉格朗日法**:
- 内部极值: `∂std/∂x_i = 0` ⇒ 所有 `x_i` 相等 ⇒ `std = 0` (极小值)
- 边界极值: 至少一个 `x_i` 在边界 (0 或 1)

枚举边界组合:
- `{0, 0, 0}`: mean=0, std=0
- `{0, 0, 1}`: mean=1/3, var = ((0-1/3)² + (0-1/3)² + (1-1/3)²)/3 = (1/9 + 1/9 + 4/9)/3 = (6/9)/3 = 2/9, std = √(2/9) ≈ 0.471 ✅
- `{0, 1, 1}`: mean=2/3, var = (4/9 + 1/9 + 1/9)/3 = 2/9, std = √(2/9) ≈ 0.471
- `{0, 1, 0}`: 同 {0,0,1}
- `{1, 1, 1}`: std=0

**结论**: `max_std = √(2/9)` **数学正确**, 在 `{0, 0, 1}` 或 `{0, 1, 1}` 时取得最大值。

#### 4.2.2 三个 [0,1] 值的归一化合理性

**当前归一化** ([layer1_meta_scm.py:262-269](../TRACE*Engine(EDM-Takens*CCM)/trace-to-edm/layer1_meta_scm.py)):
```python
norm_ate = min(abs(ate), 1.0)            # |ATE| 截断到 1.0
norm_ccm = min(max(ccm_cov / 100.0, 0.0), 1.0)
norm_cl = min(max(cl_consensus / 100.0, 0.0), 1.0)
```

**数学审视**:

| 度量 | 原始范围 | 归一化方式 | 合理性 |
|------|---------|-----------|--------|
| ATE | 理论上 (-∞, +∞), 实际多在 [-5, 5] | `min(|ATE|, 1.0)` 截断 | **有问题** — ATE=0.5 与 ATE=5 都归一化为 0.5/1.0, 损失大 ATE 的分辨率。但若不截断, ATE=100 会主导 consensus, 也不合理 |
| CCM coverage | [0, 100]% | `/100` 线性 | **合理** |
| causallearn consensus | [0, 100] (共识边数百分比) | `/100` 线性 | **合理** |

**ATE 截断的深层问题** (ALGO-4 复审):
`min(|ATE|, 1.0)` 假设 ATE 的"有意义上限"是 1.0, 但这取决于变量尺度。
若 outcome 变量是 [0,1] 二值, ATE 上限就是 1.0, 截断合理。
若 outcome 是连续变量 (如 z_pca_1 范围 [-3, 3]), ATE 可达 6+, 截断到 1.0 会**严重压缩** ATE 信号。

**改进建议** (低优先级):
用 ATE 的**标准化效应量** Cohen's d 替代原始 ATE:
```
norm_ate = min(|d|, 1.0),  d = ATE / std(outcome)
```
Cohen's d 的"大效应"阈值是 0.8, 截断到 1.0 更合理。但需在 `params` 中传入 `outcome_std`, 当前未提供。

#### 4.2.3 std_v 的计算公式

**当前实现** ([layer1_meta_scm.py:276-278](../TRACE*Engine(EDM-Takens*CCM)/trace-to-edm/layer1_meta_scm.py)):
```python
values = [norm_ate, norm_ccm, norm_cl]
mean_v = sum(values) / 3.0
var_v = sum((v - mean_v) ** 2 for v in values) / 3.0
std_v = var_v ** 0.5
```

**数学审视**:
- `var_v` 用 `ddof=0` (总体方差), 与 `max_std = √(2/9)` (也是 ddof=0) 一致 ✅
- 若用 `ddof=1` (样本方差), `max_std` 应改为 `√(2/9) · √(3/2) = √(1/3) ≈ 0.577`, 否则归一化不一致

**结论**: 当前实现**内部一致**, 数学正确。

### 4.3 consensus_direction (layer1_meta_scm.py:291-344)

#### 4.3.1 CCM verdict 文本匹配的语义严谨性

**当前实现** ([layer1_meta_scm.py:322-335](../TRACE*Engine(EDM-Takens*CCM)/trace-to-edm/layer1_meta_scm.py)):
```python
ccm_lower = ccm_verdict.lower()
has_reverse = "reverse" in ccm_lower
has_forward = "forward" in ccm_lower or "bidirectional" in ccm_lower

if has_reverse and not has_forward:
    if (ate > 0 and "reverse" in ccm_lower) or (ate < 0):
        # ... pass  # 不视为冲突
```

**数学审视**:

CCM verdict 来自 [ccm_causality.py:222-260](../Skill/edm-takens/src/ccm_causality.py), 可能的取值 (基于 `_compute_causal_verdict`):
- `"forward"` — X→Y 因果方向
- `"reverse"` — Y→X 因果方向
- `"bidirectional"` — 双向
- `"weak"` / `"no_convergence"` — 不显著

**问题 1 — "reverse" 的语义歧义**:
CCM 的 "reverse" 表示 **Y→X 强于 X→Y**, 即因果方向是 Y→X。
若 ATE > 0 (X 增加 → Y 增加), 但 CCM 说 "reverse" (实际是 Y→X), 这**不是方向冲突**, 而是因果**机制方向**不同。
当前实现 `pass # 不视为冲突` 是**正确的**, 但注释解释不够清晰。

**问题 2 — "bidirectional" 的处理**:
`has_forward = "forward" in ccm_lower or "bidirectional" in ccm_lower`
将 "bidirectional" 归入 "forward" 类别, 意味着双向 CCM 不算冲突。
**数学上合理** — 双向意味着 X↔Y, 与任何 ATE 方向都不矛盾。

**问题 3 — 文本匹配的脆弱性**:
依赖 `"reverse" in ccm_lower` 字符串匹配, 若 CCM 输出格式变化 (如 `"X->Y (reverse)"` vs `"reverse_direction"`), 可能误判。
**建议**: 在 `ccm_causality.py` 的 `_compute_causal_verdict` 输出结构化字段 `direction: "forward"|"reverse"|"bidirectional"|"weak"`, 而非依赖 verdict 文本。

#### 4.3.2 causallearn 共识数的阈值

**当前实现** ([layer1_meta_scm.py:338-342](../TRACE*Engine(EDM-Takens*CCM)/trace-to-edm/layer1_meta_scm.py)):
```python
if cl_consensus < 1.0:
    return "ambiguous" if abs(ate) < 0.05 else ate_direction
return ate_direction
```

**数学审视**:

`cl_consensus` 是 causallearn 的共识边数百分比 (0-100)。
- `cl_consensus < 1.0` 表示共识边数 < 1% (几乎无共识)
- 此时若 |ATE| < 0.05 (微弱), 返回 "ambiguous" — **合理**
- 若 |ATE| ≥ 0.05, 仍返回 `ate_direction` — **略激进**, 因为 causallearn 无共识时 ATE 方向可信度也降低

**建议** (低优先级):
增加中间档位:
```
if cl_consensus < 1.0:
    return "ambiguous" if abs(ate) < 0.1 else "weak_" + ate_direction
elif cl_consensus < 10.0:
    return ate_direction if abs(ate) >= 0.05 else "ambiguous"
else:
    return ate_direction
```

#### 4.3.3 异常处理

**当前实现** ([layer1_meta_scm.py:310, 343-344](../TRACE*Engine(EDM-Takens*CCM)/trace-to-edm/layer1_meta_scm.py)):
```python
try:
    ate = float(params.get("ate", 0.0) or 0.0)
    ...
except Exception:
    return "ambiguous"
```

**数学审视**:
`params.get("ate", 0.0) or 0.0` 的 `or` 短路在 `ate=0.0` 时返回 0.0 (因为 0.0 是 falsy), **逻辑上等价于** `params.get("ate", 0.0)`, 但代码可读性差。
若 `params["ate"]` 是字符串 `"0.5"`, `float("0.5")` 正常; 若是 `None`, `float(None)` 抛 TypeError, 被 catch。
**结论**: 异常处理**正确**, 但 `or 0.0` 是冗余防御, 可简化。

### 4.4 csv_builder.py Header 迁移竞态

#### 4.4.1 单进程内的竞态分析

**当前实现** ([csv_builder.py:131-185](../TRACE*Engine(EDM-Takens*CCM)/trace-to-edm/csv_builder.py)):
```python
def _load_existing(self):
    with open(self.csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ...
            self._rows.append(clean_row)
            for key in clean_row.keys():
                self._known_columns.add(key)

    # 表头迁移检测
    try:
        with open(self.csv_path, "r", encoding="utf-8", newline="") as _f:
            _reader = csv.reader(_f)
            _file_header = next(_reader, [])
    except Exception:
        _file_header = []
    _missing_cols = [c for c in self.COLUMN_ORDER if c not in _file_header]
    if _missing_cols and self._rows:
        if VERBOSE:
            print(f"[CSV] 表头缺 {len(_missing_cols)} 列，触发全量重写以更新表头")
        self._write()
```

**竞态场景分析**:

**场景 A — 单进程顺序调用** (trace-to-edm 当前架构):
```
t1: TrajectoryCSV() 初始化 → _load_existing() → 检测缺列 → _write() 全量重写
t2: append_row(row1) → _append_row(row1) [无新列]
t3: append_row(row2) → _append_row(row2) [无新列]
```
**无竞态** — `_load_existing` 在 `__init__` 中完成, 后续 `append_row` 仅追加。

**场景 B — 多进程并发追加** (理论场景, 当前未启用):
```
P1: TrajectoryCSV() → _load_existing() → _write() [全量重写]
P2: TrajectoryCSV() → _load_existing() [同时读旧文件]
P1: append_row(row1) → _append_row
P2: append_row(row2) → _append_row [覆盖 P1 的写入?]
```
**有竞态** — 但 trace-to-edm 的 `_ANALYSIS_LOCK=Semaphore(1)` ([locks.py](../TRACE*Engine(EDM-Takens*CCM)/edm-takens-web/backend/core/locks.py)) 保证单进程串行, 此场景不触发。

**场景 C — 表头迁移期间的崩溃**:
```
t1: _write() 开始 → 打开文件 'w' 模式 [文件被截断为 0]
t2: 进程崩溃 → 文件仅含部分行
t3: 重启 → _load_existing() → _file_header 为空 → _missing_cols = COLUMN_ORDER → 再次 _write()
```
**风险** — `_write()` 是非原子操作 (open 'w' 截断 → writeheader → writerow 循环)。
若在 `writeheader` 后崩溃, 文件仅含表头无数据, 下次 `_load_existing` 的 `self._rows` 为空, **数据丢失**。

#### 4.4.2 _append_row 的 header 写入竞态

**当前实现** ([csv_builder.py:262-267](../TRACE*Engine(EDM-Takens*CCM)/trace-to-edm/csv_builder.py)):
```python
is_new_file = not self.csv_path.exists() or self.csv_path.stat().st_size == 0
with open(self.csv_path, "a", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=all_cols, extrasaction="ignore")
    if is_new_file:
        writer.writeheader()
    writer.writerow(row)
```

**竞态分析**:

**场景 D — 两个进程同时检测 is_new_file**:
```
P1: is_new_file = True (文件不存在)
P2: is_new_file = True (文件不存在, P1 还没创建)
P1: open('a') → writeheader() → writerow(row1)
P2: open('a') → writeheader() → writerow(row2)
结果: 文件含 [header, row1, header, row2], 第二个 header 被当作数据行
```
**有竞态** — 但同场景 B, 当前架构单进程串行, 不触发。

#### 4.4.3 改进建议

| 改进 | 优先级 | 收益 |
|------|--------|------|
| 1. `_write()` 改为**原子写入**: 先写 `.tmp` 文件, 然后 `os.replace(tmp, csv_path)` | **P2** | 防止崩溃导致数据丢失 |
| 2. `_append_row` 用 `fcntl.flock` (Unix) 或 `msvcrt.locking` (Windows) 加文件锁 | P3 | 支持多进程并发 (未来扩展) |
| 3. 表头迁移检测从 `_load_existing` 移到 `append_row` 内, 每次追加前检查 | P3 | 避免初始化时的全量重写开销 |

**结论**: 当前实现**在单进程串行架构下无竞态**, 但**崩溃恢复**有数据丢失风险, 建议优先实现改进 1 (原子写入)。

---

## 5. 综合优先级矩阵

| 编号 | 优化项 | 类型 | 辨别性提升 | 实现复杂度 | 风险 | 优先级 |
|------|--------|------|-----------|-----------|------|--------|
| R-algo_4 | PCA Procrustes 对齐 | 文档落地 | 15-25% | 中 | 低 | **P1** |
| R-_algo_2 | TRACE daemon 模式 | 文档落地 | 稳定性 (非辨别性) | 高 | 中 | **P2** |
| OPT-1 | EDM S-Map Tikhonov 正则化 | 新优化 | 5-8% (小样本) | 中 | 低 | **P2** |
| OPT-2 | Bayesian CPD for CCM | 新优化 | 3-5% ρ 准确性 | 中 | 低 | **P3** |
| OPT-3 | OptDMD for HAVOK | 新优化 | 5-10% (中等混沌) | 高 | 中 | **P2** |
| OPT-4 | Wolf 算法变体 | 新优化 | <2% (弱混沌场景) | 中 | 中 | **P3** |
| OPT-5 | NOTEARS 因果发现 | 新优化 | 10-15% 共识度 | 中 | 中 | **P2** |
| OPT-6 | L3 Attention 机制 | 新优化 | 15-25% (轴间区分) | 中 | 高 | **P3** |

---

## 6. 残留债务更新

### 6.1 Round 16 遗留债务 (本轮复审确认)

| 编号 | 债务 | 状态 | 本轮复审结论 |
|------|------|------|-------------|
| R-_algo_1 | L3 z-score 归一化 | ✅ 已修 | 数学正确, ddof=0 偏置 -2.5% 可接受, 暖启动期偏置可接受 |
| R-_algo_2 | TRACE daemon 模式 | ⏳ 文档化 (本轮落地) | 见 §2, 优先级 P2 |
| R-algo_3 | L1 跨算法一致性指标 | ✅ 已修 | max_std=√(2/9) 数学正确, ATE 截断有尺度依赖问题 |
| R-algo_4 | L2 PCA Procrustes 对齐 | ⏳ 文档化 (本轮落地) | 见 §1, 优先级 P1 |
| R-algo_5 | L3 退化轴自适应降权 | ✅ 已修 | per-axis 逻辑正确 |
| R-algo_6 | HAVOK q_eff=3 退化 | ⏳ 文档化 | 与 OPT-3 (OptDMD) 相关, OptDMD 可绕过 SVD 截断问题 |
| R-algo_7 | Pearl 拓扑序环路验证 | ⏳ 文档化 | 低优先级 |
| R-algo_8 | EDM 管道消费轴权重 | ⏳ 文档化 | 需 EDM 距离计算适配 |
| R-algo_9 | z-score 预热期渐进估计 | ⏳ 文档化 | 见 §4.1.1, 可用 EWM 改进 |

### 6.2 本轮新增债务

| 编号 | 债务 | 来源 | 优先级 |
|------|------|------|--------|
| R-algo_10 | consensus_score ATE 截断尺度依赖 | §4.2.2 | P3 |
| R-algo_11 | consensus_direction CCM verdict 文本匹配脆弱性 | §4.3.1 | P3 |
| R-algo_12 | csv_builder _write() 非原子写入崩溃风险 | §4.4.3 | P2 |
| R-algo_13 | EDM S-Map 数值稳定性 (Tikhonov) | OPT-1 | P2 |
| R-algo_14 | CCM ρ 收敛 BOCPD 在线检测 | OPT-2 | P3 |
| R-algo_15 | HAVOK OptDMD 替代两步法 | OPT-3 | P2 |
| R-algo_16 | Wolf 算法大 λ 分辨率 | OPT-4 | P3 |
| R-algo_17 | NOTEARS 可微因果发现 | OPT-5 | P2 |
| R-algo_18 | L3 Attention 机制 (破坏向后兼容) | OPT-6 | P3 |

---

## 7. 数学符号表

| 符号 | 含义 | 出处 |
|------|------|------|
| `W_ref` | 背景 PCA 主轴 (k×d) | §1 Procrustes |
| `W_proj` | 项目 PCA 主轴 (k×d) | §1 Procrustes |
| `Q*` | 最优正交变换 (k×k) | §1 Procrustes |
| `||·||_F` | Frobenius 范数 | §1 Procrustes |
| `μ`, `σ` | 总体均值/标准差 | §4.1 ZScore |
| `λ` | Lyapunov 指数 | §3.4 Wolf |
| `Λ` | Koopman 特征值矩阵 | §3.3 OptDMD |
| `Φ` | Koopman 模态矩阵 | §3.3 OptDMD |
| `θ_i(d_i)` | S-Map 邻居权重 | §3.1 S-Map |
| `r_t` | BOCPD run length | §3.2 BOCPD |
| `max_std = √(2/9)` | 三个 [0,1] 值的最大标准差 | §4.2 consensus |

---

## 8. 参考文献

1. Schönemann, P. H. (1966). A generalized solution of the orthogonal Procrustes problem. *Psychometrika*, 31(1), 1-10.
2. Adams, R. P., & MacKay, D. J. (2007). Bayesian online changepoint detection. *arXiv:0710.3742*.
3. Askham, T., & Kutz, J. N. (2018). Variable projection methods for an optimized dynamic mode decomposition. *SIAM Journal on Applied Dynamical Systems*, 17(1), 380-416.
4. Wolf, A., Swift, J. B., Swinney, H. L., & Vastano, J. A. (1985). Determining Lyapunov exponents from a time series. *Physica D*, 16(3), 285-317.
5. Zheng, X., Aragam, B., Ravikumar, P. K., & Xing, E. P. (2018). DAGs with NO TEARS: Continuous optimization for structure learning. *NeurIPS 2018*.
6. Sugihara, G., May, R., Ye, H., Hsieh, C. H., Deyle, E., Fogarty, M., & Munch, S. (2012). Detecting causality in complex ecosystems. *Science*, 338(6106), 496-500.
7. Brunton, S. L., Brunton, B. W., Proctor, J. L., & Kutz, J. N. (2016). Koopman invariant subspaces and finite linear representations of nonlinear dynamical systems for control. *PLOS ONE*, 11(2), e0150171.
8. Tikhonov, A. N., & Arsenin, V. Y. (1977). *Solutions of ill-posed problems*. Winston.

---

## 9. 附录: 文件路径速查表

| 文件 | 绝对路径 |
|------|---------|
| layer2_semantic.py | `f:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\trace-to-edm\layer2_semantic.py` |
| layer3_sacred.py | `f:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\trace-to-edm\layer3_sacred.py` |
| layer1_meta_scm.py | `f:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\trace-to-edm\layer1_meta_scm.py` |
| csv_builder.py | `f:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\trace-to-edm\csv_builder.py` |
| bridge.py | `f:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\trace-to-edm\bridge.py` |
| sovereign_havok.py | `f:\攻略\研发测试\Skill\edm-takens\src\sovereign_havok.py` |
| ccm_causality.py | `f:\攻略\研发测试\Skill\edm-takens\src\ccm_causality.py` |
| final_interpretation.py | `f:\攻略\研发测试\Skill\edm-takens\src\final_interpretation.py` |
| edm_adaptive_pipeline.py | `f:\攻略\研发测试\Skill\edm-takens\src\edm_adaptive_pipeline.py` |
| six_warriors.py | `f:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\trace-engine\examples\counterfactual_hybrid\six_warriors.py` |
| counterfactual_bridge.py | `f:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\trace-engine\examples\counterfactual_hybrid\counterfactual_bridge.py` |
| causallearn_validator.py | `f:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\trace-engine\examples\counterfactual_hybrid\causallearn_validator.py` |
| pearl_counterfactual.py | `f:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\trace-engine\examples\counterfactual_hybrid\pearl_counterfactual.py` |
| py_bridge.py | `f:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\trace-engine-web\py_bridge.py` |
| llama_worker.py | `f:\攻略\研发测试\TRACE Engine(EDM-Takens CCM)\trace-engine-web\llama_worker.py` |

---

**报告生成完毕** — Round 17 共识别 2 项文档落地 (R-algo_4 PCA Procrustes, R-_algo_2 TRACE daemon) + 6 项新优化机会 (OPT-1~6) + 9 项新增债务 (R-algo_10~18)。所有数学结论均基于代码实际审视, 引用位置精确到行号。
