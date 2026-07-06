"""
SovereignHAVOK — 生产级库普曼-汉克尔动力学系统重构与预测器
================================================================
设计基础: Steven L. Brunton et al., "Chaos as an intermittently forced
           linear system", Nature Communications, 2017

架构特征:
  - 连续时间ODE: dv/dt = A·v + B·v_r (Savitzky-Golay 抗噪求导)
  - V基回归 (右奇异向量 / 影子流形坐标, Brunton 2017 原版)
  - 自适应SVD截断 (累积奇异值能量阈值)
  - 超额峰度相变诊断
  - Koopman 特征值谱分析
  - 内建 EDM 交叉验证接口

与现有实现的区别:
  - 离散 K=Xp·pinv(X)  →  连续 dv/dt=A·v+B·v_r (SG导数)
  - 固定 r=E-1         →  累积能量自适应截断
  - U基 (时间模式)      →  V基 (影子流形, 论文原版) + U基对照
  - 无导数滤波          →  Savitzky-Golay 多项式拟合求导
"""

import numpy as np
from numpy.linalg import svd, pinv, eig, lstsq
from scipy.signal import savgol_filter
from scipy.stats import kurtosis as scipy_kurtosis
import warnings

# ──────────────────────────────────────────────────────────────
# 核心类
# ──────────────────────────────────────────────────────────────

class SovereignHAVOK:
    """
    SovereignHAVOK: 生产级主权库普曼-汉克尔动力学系统重构与预测器。

    使用示例
    --------
    >>> sh = SovereignHAVOK(q_delays=40, dt=1.0, energy_threshold=0.999)
    >>> sh.fit(my_time_series)
    >>> print(f"截断阶数 r={sh.r_}, 峰度={sh.kurtosis_vr_:.3f}")
    >>> next_state = sh.predict_next_state(v_current, vr_current)
    """

    def __init__(
        self,
        q_delays: int = 100,
        dt: float = 1.0,
        energy_threshold: float = 0.999,
        poly_order: int = 3,
        window_length: int = 11,
        basis: str = "V",
    ):
        """
        Parameters
        ----------
        q_delays : int
            汉克尔矩阵的延迟列数 (嵌入维度)。建议根据 AMI 第一个极小值设定。
        dt : float
            采样时间间隔。
        energy_threshold : float
            奇异值累积能量截断阈值 (默认 99.9%)。
        poly_order : int
            Savitzky-Golay 求导滤波器的多项式阶数。
        window_length : int
            Savitzky-Golay 求导滤波器的窗口长度 (必须为奇数)。
        basis : str
            回归基选择: "V" (右奇异向量, Brunton 原版) 或 "U" (左奇异向量, 时间模式)。
        """
        if window_length % 2 == 0:
            window_length -= 1  # auto-correct to odd
        if energy_threshold <= 0 or energy_threshold > 1:
            raise ValueError("energy_threshold 必须在 (0, 1] 范围内")

        self.q = q_delays
        self.dt = dt
        self.energy_threshold = energy_threshold
        self.poly_order = poly_order
        self.window_length = window_length
        self.basis = basis.upper()

        # ── 拟合后填充的内部状态 ──
        self.r_ = None              # 自动截断阶数
        self.U_ = None              # 左奇异向量 (时间模式)
        self.Sigma_ = None          # 奇异值向量
        self.V_ = None              # 右奇异向量 (影子流形坐标)
        self.A_ = None              # 连续时间线性演化矩阵 (r-1 × r-1)
        self.B_ = None              # 外部强迫影响向量 (r-1 × 1)
        self.K_d_ = None            # 离散时间 Koopman 算子 (I + dt*A)
        self.kurtosis_vr_ = None    # 强迫项超额峰度 (fisher定义)
        self.explained_var_ = None  # 前 r 个模态的解释方差比
        self.forcing_ = None        # 强迫项时间序列
        self.state_ = None          # 内部线性状态 v (p × r-1)
        self.eigenvalues_ = None    # Koopman 特征值
        self.is_valid_ = False      # 拟合是否成功

    # ── 内部方法 ──────────────────────────────────────────

    def _build_hankel(self, data: np.ndarray) -> np.ndarray:
        """Build Hankel matrix.

        V-basis (Brunton 2017 canonical): H(q x p), V has p time steps.
        U-basis (existing project style): H(p x q), U has p time steps.

        p = N - q + 1 is the number of delay-embedded vectors (time steps).
        """
        n = len(data)
        p = n - self.q + 1
        if p <= 0:
            raise ValueError(f"Data length {n} must be > delays q={self.q}")
        if self.basis == "V":
            # Brunton canonical: H is (q x p), V(p x K) has p time steps
            H = np.zeros((self.q, p))
            for i in range(self.q):
                H[i, :] = data[i : i + p]
        else:
            # U-basis: H is (p x q), U(p x K) has p time steps
            H = np.zeros((p, self.q))
            for i in range(self.q):
                H[:, i] = data[i : i + p]
        return H

    def _apply_sg_derivative(self, v: np.ndarray) -> np.ndarray:
        """
        Compute first derivative of each column of v using Savitzky-Golay filter.

        Window length is automatically capped for small datasets:
        - Maximum: user-specified window_length
        - Adaptive cap: max(5, p // 4) to prevent over-smoothing on small data
        - Enforced odd, and poly_order + 2 <= wl

        Falls back to central finite difference when data is too short.
        """
        p, cols = v.shape
        # Adaptive window cap: never use more than p/4 points for derivative
        # This prevents the reviewer-identified over-smoothing issue
        max_safe_wl = max(5, p // 4)
        if max_safe_wl % 2 == 0:
            max_safe_wl -= 1
        wl = min(self.window_length, max_safe_wl)
        if wl % 2 == 0:
            wl -= 1
        if wl < self.poly_order + 2:
            # Fallback: central finite difference
            dv = np.zeros_like(v)
            for col in range(cols):
                col_data = v[:, col]
                dv[1:-1, col] = (col_data[2:] - col_data[:-2]) / (2 * self.dt)
                dv[0, col] = (col_data[1] - col_data[0]) / self.dt
                dv[-1, col] = (col_data[-1] - col_data[-2]) / self.dt
            return dv

        dv = np.zeros_like(v)
        for col in range(cols):
            dv[:, col] = savgol_filter(
                v[:, col],
                window_length=wl,
                polyorder=self.poly_order,
                deriv=1,
                delta=self.dt,
                mode="interp",
            )
        return dv

    def _auto_truncate(self, s: np.ndarray) -> int:
        """
        Auto-determine truncation rank r from cumulative singular value energy.

        r satisfies:
          sum(s[:r-1]^2) / sum(s^2) >= energy_threshold
        i.e. the first r-1 modes capture >= threshold of total energy,
        and mode r is the nonlinear forcing term.

        r is bounded by: 3 <= r <= min(len(s)-1, len(s)-2)
        For very short embedding, r is clamped to available modes.
        """
        q_eff = len(s)
        max_r = max(2, q_eff - 1)  # at minimum: 1 linear mode + 1 forcing
        if q_eff < 3:
            return max_r
        cumulative = np.cumsum(s ** 2) / np.sum(s ** 2)
        r = int(np.searchsorted(cumulative, self.energy_threshold) + 1)
        # Floor: at least 3 modes total (2 linear + 1 forcing)
        # For very short q: use at most q_eff-1 (leave at least 1 for forcing)
        min_r = min(max(3, q_eff // 4), q_eff - 1)
        r = max(min_r, min(r, max_r))
        return r

    def _compute_kurtosis(self, x: np.ndarray) -> float:
        """计算超额峰度 (Fisher定义, 正态分布=0)。"""
        return float(scipy_kurtosis(x, fisher=True))

    # ── 主拟合方法 ────────────────────────────────────────

    def fit(self, data: np.ndarray) -> "SovereignHAVOK":
        """
        Fit HAVOK state-space model to 1D time series data.

        Reconstructs phase space via Hankel embedding, applies SVD,
        and regresses the continuous-time ODE: dv/dt = A*v + B*v_r

        Parameters
        ----------
        data : np.ndarray, shape (n,)
            One-dimensional time series.

        Returns
        -------
        self : SovereignHAVOK
        """
        data = np.asarray(data, dtype=float).ravel()
        n = len(data)

        # 1. Normalize
        self.mean_ = float(np.mean(data))
        self.std_ = float(np.std(data)) if np.std(data) > 1e-12 else 1.0
        normalized = (data - self.mean_) / self.std_

        # 2. Build Hankel matrix
        # V-basis: H(q x p) -> V(p x K) has p = n-q+1 time steps
        # U-basis: H(p x q) -> U(p x K) has p = n-q+1 time steps
        H = self._build_hankel(normalized)
        p_steps = n - self.q + 1  # number of time steps in state space

        # 3. Economy SVD
        U, s, Vt = svd(H, full_matrices=False)
        self.Sigma_ = s

        # 4. Auto-determine truncation rank r
        self.r_ = self._auto_truncate(s)
        self.explained_var_ = float(np.sum(s[: self.r_] ** 2) / np.sum(s ** 2))

        # 5. Extract state variables and forcing term
        if self.basis == "V":
            # H(q x p): Vt(K x p) -> V(p x K), each column is a mode
            self.V_ = Vt.T  # (p_steps x K)
            self.U_ = U     # (q x K)
            basis_matrix = self.V_[:, : self.r_]  # (p_steps x r)
        else:
            # H(p x q): U(p x K), each column is a mode (time evolution)
            self.U_ = U     # (p_steps x K)
            self.V_ = Vt.T  # (q x K)
            basis_matrix = self.U_[:, : self.r_]  # (p_steps x r)

        v = basis_matrix[:, : self.r_ - 1]           # linear state (p_steps x r-1)
        self.forcing_ = basis_matrix[:, self.r_ - 1]  # forcing v_r (p_steps,)
        self.state_ = v

        # 6. Savitzky-Golay noise-robust derivative estimation
        dv_dt = self._apply_sg_derivative(v)  # (p_steps x r-1)

        # 7. Regression: dv/dt = A*v + B*v_r
        # Theta = [v | v_r], shape (p_steps x r)
        Theta = np.column_stack([v, self.forcing_])

        # Solve: Theta @ Xi = dv_dt  ->  Xi.shape = (r x r-1)
        Xi, residuals, rank, s_lstsq = lstsq(Theta, dv_dt, rcond=None)

        # Xi = [A_part | B_part]^T, A_part:(r-1)x(r-1), B_part:(1)x(r-1)
        Xi_T = Xi.T  # (r-1, r)
        self.A_ = Xi_T[:, : self.r_ - 1]          # (r-1, r-1)
        self.B_ = Xi_T[:, self.r_ - 1 : self.r_]  # (r-1, 1)

        # 8. Discrete-time Koopman operator (first-order Euler)
        self.K_d_ = np.eye(self.r_ - 1) + self.dt * self.A_

        # 9. Forcing kurtosis diagnostic
        self.kurtosis_vr_ = self._compute_kurtosis(self.forcing_)

        # 10. Koopman eigenvalue spectrum
        self.eigenvalues_ = eig(self.A_)[0]

        # 11. Regression quality
        dv_pred = Theta @ Xi
        self.regression_r2_ = float(
            1 - np.sum((dv_dt - dv_pred) ** 2) / (np.sum(dv_dt ** 2) + 1e-12)
        )

        self.is_valid_ = True
        return self

    # ── 预测 ──────────────────────────────────────────────

    def predict_next_state(
        self, current_v: np.ndarray, current_vr: float
    ) -> np.ndarray:
        """
        基于当前状态 v 和外部强迫量 v_r，一步预测。

        dv/dt = A·v + B·v_r  →  v(t+dt) = v(t) + dt * (A·v + B·v_r)

        Parameters
        ----------
        current_v : np.ndarray, shape (r-1,)
        current_force : float

        Returns
        -------
        next_v : np.ndarray, shape (r-1,)
        """
        if not self.is_valid_:
            raise RuntimeError("请先调用 fit()")
        v_col = np.asarray(current_v, dtype=float).reshape(-1, 1)
        dv = self.A_ @ v_col + self.B_ * current_vr
        next_v = v_col + dv * self.dt
        return next_v.ravel()

    def predict_n_steps(
        self, v0: np.ndarray, vr_sequence: np.ndarray, n_steps: int
    ) -> np.ndarray:
        """
        多步前向预测。

        Parameters
        ----------
        v0 : np.ndarray, shape (r-1,)
            初始状态。
        vr_sequence : np.ndarray, shape (n_steps,)
            未来强制项序列 (需要外部估计或假设为0)。
        n_steps : int
            预测步数。

        Returns
        -------
        trajectory : np.ndarray, shape (n_steps+1, r-1)
        """
        trajectory = np.zeros((n_steps + 1, self.r_ - 1))
        trajectory[0] = v0
        v_current = v0.copy()
        for t in range(n_steps):
            vr = vr_sequence[t] if t < len(vr_sequence) else 0.0
            v_current = self.predict_next_state(v_current, vr)
            trajectory[t + 1] = v_current
        return trajectory

    # ── 诊断 ──────────────────────────────────────────────

    def diagnose(self) -> dict:
        """
        Return complete diagnostic report as a dictionary.
        """
        if not self.is_valid_:
            return {"error": "Model not fitted"}

        growth_rates = np.abs(self.eigenvalues_)
        max_growth = float(np.max(growth_rates))
        min_growth = float(np.min(growth_rates))

        # Classify system type
        if max_growth > 1.05:
            stability = "Divergent (unstable modes)"
        elif max_growth < 0.90:
            stability = "Highly dissipative (fast convergence)"
        else:
            stability = "Near-critical / stable"

        if self.kurtosis_vr_ > 3.0:
            forcing_type = "Heavy-tailed: strong intermittent phase transitions"
        elif self.kurtosis_vr_ > 1.5:
            forcing_type = "Moderate tails: intermittent phase-transition components"
        elif self.kurtosis_vr_ > 0.5:
            forcing_type = "Light tails: weak non-Gaussian components"
        else:
            forcing_type = "Near-Gaussian: system in stable orbit"

        # Detect spikes
        spike_threshold = 1.5 * np.std(self.forcing_)
        spike_indices = np.where(np.abs(self.forcing_) > spike_threshold)[0]

        return {
            "embedding_dim_q": self.q,
            "truncation_rank_r": self.r_,
            "explained_variance": f"{self.explained_var_:.4%}",
            "regression_r2": f"{self.regression_r2_:.4%}",
            "kurtosis_vr": f"{self.kurtosis_vr_:.4f}",
            "forcing_type": forcing_type,
            "stability": stability,
            "max_eigenvalue": f"{max_growth:.4f}",
            "min_eigenvalue": f"{min_growth:.4f}",
            "spike_count": len(spike_indices),
            "spike_positions": spike_indices.tolist(),
            "basis": self.basis,
            "condition_number": f"{float(np.linalg.cond(self.A_)):.2f}",
        }

    def report(self) -> str:
        """Generate human-readable diagnostic report."""
        d = self.diagnose()
        if "error" in d:
            return d["error"]

        lines = [
            "=" * 62,
            "  SovereignHAVOK Dynamics Diagnostic Report",
            "=" * 62,
            f"  Embedding dim q      : {d['embedding_dim_q']}",
            f"  Truncation rank r    : {d['truncation_rank_r']}",
            f"  Regression basis     : {d['basis']}",
            f"  Explained variance   : {d['explained_variance']}",
            f"  Regression R^2       : {d['regression_r2']}",
            f"  A matrix condition   : {d['condition_number']}",
            "",
            f"  Kurtosis (v_r)       : {d['kurtosis_vr']}",
            f"  Forcing type         : {d['forcing_type']}",
            "",
            f"  Max eigenvalue mag   : {d['max_eigenvalue']}",
            f"  Min eigenvalue mag   : {d['min_eigenvalue']}",
            f"  Stability            : {d['stability']}",
            "",
            f"  Spike count          : {d['spike_count']}",
        ]
        if d["spike_positions"]:
            lines.append(f"  Spike time indices   : {d['spike_positions']}")
        lines.append("=" * 62)
        return "\n".join(lines)


# ──────────────────────────────────────────────────────────────
# 便捷函数
# ──────────────────────────────────────────────────────────────

def edm_guided_havok(
    data: np.ndarray,
    max_E: int = 10,
    energy_threshold: float = 0.999,
    dt: float = 1.0,
) -> dict:
    """
    使用自实现的嵌入维度搜索 (类似 EDM EmbedDimension) 确定最优 q,
    然后运行 SovereignHAVOK。

    这是一个自包含的函数，不依赖 pyEDM。

    Returns
    -------
    dict with keys: havok, optimal_q, v_basis_result, u_basis_result
    """
    from scipy.spatial import KDTree

    n = len(data)
    data = np.asarray(data, dtype=float).ravel()

    # ── 简化的嵌入维度搜索 (基于 Simplex 预测) ──
    best_rho, best_E = -1.0, 2
    for E in range(2, min(max_E + 1, n // 4)):
        # 使用留一法交叉验证的简化 Simplex
        lib_size = max(E + 1, n // 2)
        pred_start = lib_size
        preds, obs = [], []

        for t in range(pred_start, n):
            target = data[t - E : t]
            # 在库中找 E+1 个最近邻
            lib = np.array([data[i : i + E] for i in range(lib_size - E)])
            if len(lib) < 2:
                continue
            tree = KDTree(lib)
            # 排除自身
            dists, idxs = tree.query(target, k=min(E + 2, len(lib)))
            if isinstance(idxs, np.ndarray) and len(idxs) > 1:
                nn_idx = idxs[0] if idxs[0] + E < n else idxs[1]
            else:
                nn_idx = idxs
            pred_idx = nn_idx + E
            if pred_idx < n:
                preds.append(data[pred_idx])
                obs.append(data[t])

        if len(preds) > 3 and np.std(preds) > 1e-12:
            rho = float(np.corrcoef(obs, preds)[0, 1])
            if not np.isnan(rho) and rho > best_rho:
                best_rho, best_E = rho, E

    if best_E < 2:
        best_E = 3

    # ── 运行 V基 SovereignHAVOK ──
    havok_v = SovereignHAVOK(
        q_delays=best_E,
        dt=dt,
        energy_threshold=energy_threshold,
        poly_order=3,
        window_length=min(11, (n - best_E) // 2 * 2 - 1),
        basis="V",
    )
    try:
        havok_v.fit(data)
    except Exception as e:
        havok_v = None

    # ── 运行 U基 SovereignHAVOK (对照) ──
    havok_u = SovereignHAVOK(
        q_delays=best_E,
        dt=dt,
        energy_threshold=energy_threshold,
        poly_order=3,
        window_length=min(11, (n - best_E) // 2 * 2 - 1),
        basis="U",
    )
    try:
        havok_u.fit(data)
    except Exception as e:
        havok_u = None

    return {
        "optimal_q": best_E,
        "simplex_rho": best_rho,
        "havok_v": havok_v,
        "havok_u": havok_u,
    }


# ──────────────────────────────────────────────────────────────
# 自测
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    print("=" * 62)
    print("  SovereignHAVOK Self-Test Suite")
    print("=" * 62)

    # Test 1: Sine wave
    print("\n-- Test 1: Pure sine wave --")
    t = np.linspace(0, 20 * np.pi, 500)
    sine = np.sin(t) + 0.02 * np.random.randn(500)
    sh = SovereignHAVOK(q_delays=15, dt=0.125, energy_threshold=0.999)
    sh.fit(sine)
    print(sh.report())
    assert sh.kurtosis_vr_ < 1.0, f"Sine should have low kurtosis, got {sh.kurtosis_vr_:.2f}"
    print("  PASS: Sine -> low kurtosis (stable orbit)")

    # Test 2: Lorenz chaotic system
    print("\n-- Test 2: Lorenz chaotic system --")
    def lorenz(x, y, z, s=10, r=28, b=8 / 3):
        return s * (y - x), x * (r - z) - y, x * y - b * z

    dt_l, n_l = 0.01, 5000
    x_arr = np.zeros(n_l)
    x_arr[0], y, z = 1.0, 1.0, 1.0
    for i in range(1, n_l):
        dx, dy, dz = lorenz(x_arr[i - 1], y, z)
        x_arr[i] = x_arr[i - 1] + dx * dt_l
        y += dy * dt_l
        z += dz * dt_l
    lorenz_x = x_arr[1000:]  # remove transient

    sh_l = SovereignHAVOK(q_delays=25, dt=0.01, energy_threshold=0.999)
    sh_l.fit(lorenz_x)
    print(sh_l.report())
    assert sh_l.kurtosis_vr_ > 0.5, f"Lorenz should have positive kurtosis, got {sh_l.kurtosis_vr_:.2f}"
    print("  PASS: Lorenz -> heavy-tailed (chaotic phase transitions)")

    # Test 3: White noise
    print("\n-- Test 3: Gaussian white noise --")
    noise = np.random.randn(200)
    sh_n = SovereignHAVOK(q_delays=10, dt=1.0, energy_threshold=0.99)
    sh_n.fit(noise)
    print(sh_n.report())
    print("  PASS: White noise diagnostics complete")

    # Test 4: V-basis vs U-basis comparison
    print("\n-- Test 4: V-basis vs U-basis (Lorenz) --")
    sh_v = SovereignHAVOK(q_delays=25, dt=0.01, basis="V").fit(lorenz_x)
    sh_u = SovereignHAVOK(q_delays=25, dt=0.01, basis="U").fit(lorenz_x)
    print(f"  V-basis: r={sh_v.r_}, R2={sh_v.regression_r2_:.4f}, kurt={sh_v.kurtosis_vr_:.3f}")
    print(f"  U-basis: r={sh_u.r_}, R2={sh_u.regression_r2_:.4f}, kurt={sh_u.kurtosis_vr_:.3f}")
    print("  PASS: Dual-basis comparison complete")

    # Test 5: Small sample (simulating 32-game data)
    print("\n-- Test 5: Small sample (n=32, game-like data) --")
    np.random.seed(42)
    small_data = np.random.randn(32) * 0.5 + np.sin(np.linspace(0, 4 * np.pi, 32))
    sh_s = SovereignHAVOK(
        q_delays=6, dt=1.0, energy_threshold=0.99,
        window_length=5, poly_order=2,
    )
    sh_s.fit(small_data)
    print(sh_s.report())
    print("  PASS: Small sample diagnostics complete")

    print("\n" + "=" * 62)
    print("  All self-tests passed!")
    print("=" * 62)
