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
from scipy.linalg import expm
import warnings

# P2-1 修复: 统一硬编码 eps 为单一真相源常量
from _numeric_constants import EPS_DISTANCE, EPS_VARIANCE, EPS_ENERGY

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
        truncation_method: str = "energy",
        regression_method: str = "lstsq",
        ridge_alpha: float = 0.01,
        noise_sigma: float = None,
    ):
        """
        Parameters
        ----------
        q_delays : int
            Hankel matrix delay columns (embedding dimension).
            Should match AMI first minimum.
        dt : float
            Sampling time interval.
        energy_threshold : float
            Cumulative singular value energy threshold.
            Used when truncation_method='energy'.
        poly_order : int
            Savitzky-Golay derivative filter polynomial order.
        window_length : int
            Savitzky-Golay derivative filter window length (must be odd).
        basis : str
            "V" (right singular vectors, Brunton canonical)
            or "U" (left singular vectors, time-evolution modes).
        truncation_method : str
            "energy": cumulative energy >= threshold (default).
            "gavish_donoho": Gavish & Donoho (2014) optimal hard threshold.
            Threshold = 2.858 * median(singular_values) for unknown noise.
            When noise_sigma is provided, uses the known-noise formula
            lambda(beta) * sigma * sqrt(q) (P3-6.2 修复).
        regression_method : str
            "lstsq": ordinary least squares (default).
            "ridge": ridge regression with L2 regularization.
        ridge_alpha : float
            Regularization strength for ridge regression (default 0.01).
        noise_sigma : float, optional
            Known noise standard deviation for Gavish-Donoho threshold.
            When provided with truncation_method='gavish_donoho', uses
            the known-noise formula instead of the median-based estimate.
            P3-6.2 修复 (科研严谨性审查).
        """
        if window_length % 2 == 0:
            window_length -= 1
        if energy_threshold <= 0 or energy_threshold > 1:
            raise ValueError("energy_threshold must be in (0, 1]")

        self.q = q_delays
        self.dt = dt
        self.energy_threshold = energy_threshold
        self.poly_order = poly_order
        self.window_length = window_length
        self.basis = basis.upper()
        self.truncation_method = truncation_method
        self.regression_method = regression_method
        self.ridge_alpha = ridge_alpha
        # P3-6.2 修复: 已知噪声水平用于 Gavish-Donoho 阈值
        self.noise_sigma = noise_sigma
        # ROUND26 P2-3: 条件数自适应正则化标志
        self._auto_ridge_triggered = False

        # ── 拟合后填充的内部状态 ──
        self.r_ = None              # 自动截断阶数
        self.U_ = None              # 左奇异向量 (时间模式)
        self.Sigma_ = None          # 奇异值向量
        self.V_ = None              # 右奇异向量 (影子流形坐标)
        self.A_ = None              # 连续时间线性演化矩阵 (r-1 × r-1)
        self.B_ = None              # 外部强迫影响向量 (r-1 × 1)
        self.K_d_ = None            # [LEGACY/DIAGNOSTIC ONLY] first-order Euler
                                     # discrete operator (I + dt*A). NOT used for
                                     # prediction or stability classification —
                                     # those use the exact F_ = expm(A*dt) and
                                     # eigenvalues_d_ = eig(expm(A*dt)) instead
                                     # (see fit() step 8b). Kept only so external
                                     # callers/notebooks comparing against the
                                     # old Euler approximation still have it
                                     # available; do not wire new code to it.
        self.kurtosis_vr_ = None    # 强迫项超额峰度 (fisher定义)
        self.explained_var_ = None  # 前 r 个模态的解释方差比
        self.forcing_ = None        # 强迫项时间序列
        self.sampling_adequacy_ = None  # Secret 14 诊断结果 (dict)
        self.state_ = None          # 内部线性状态 v (p × r-1)
        self.eigenvalues_ = None    # Koopman 特征值
        self.is_valid_ = False      # 拟合是否成功
        self.is_degenerate_ = False  # 退化标记：近常量/零能量数据，结果不可信

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
            # P1-1 修缮：用 scipy.linalg.hankel 向量化构建，替代 Python 双重循环
            # 性能提升 5-10×（C 级内存拷贝 vs Python 循环）
            from scipy.linalg import hankel
            H = hankel(data[:self.q], data[self.q - 1:self.q - 1 + p])
            # hankel 返回 (self.q, p)，正好匹配 V-basis 形状
            return H
        else:
            # U-basis: H is (p x q), U(p x K) has p time steps
            # P1-1 修缮：同样向量化，转置得到 (p, q)
            from scipy.linalg import hankel
            H = hankel(data[:self.q], data[self.q - 1:self.q - 1 + p])
            return H.T  # (q, p) -> (p, q)

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
        max_safe_wl = max(3, p // 4)  # 小数据下至少保留 3-point window
        if max_safe_wl % 2 == 0:
            max_safe_wl -= 1
        wl = min(self.window_length, max_safe_wl)
        if wl % 2 == 0:
            wl -= 1
        if wl > p or wl < self.poly_order + 2:
            # Fallback: central finite difference
            # P1-7 修缮：向量化计算，替代按列循环
            dv = np.empty_like(v)
            dv[1:-1, :] = (v[2:, :] - v[:-2, :]) / (2 * self.dt)
            dv[0, :] = (v[1, :] - v[0, :]) / self.dt
            dv[-1, :] = (v[-1, :] - v[-2, :]) / self.dt
            return dv

        # P1-7 修缮：savgol_filter 支持 axis 参数，一次性处理所有列
        # 性能提升 2-3×（高 r 场景更显著），scipy 1.7+ 稳定支持
        dv = savgol_filter(
            v,
            window_length=wl,
            polyorder=self.poly_order,
            deriv=1,
            delta=self.dt,
            axis=0,
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
            # P2 修复：q_eff < 3 表示 Hankel 矩阵列数不足以进行有意义的
            # SVD 截断（至少需要 3 个奇异值才能分出 2 线性 + 1 强迫项）。
            # 此路径属于数据退化情形，必须显式设置 _degenerate_energy=True，
            # 否则该标志位会保留前次 fit() 的残留值，导致 fit() 中的
            # explained_var_ 报告逻辑误判（可能把退化数据报告为正常）。
            self._degenerate_energy = True
            return max_r
        total_energy = float(np.sum(s ** 2))
        if total_energy < EPS_ENERGY:
            # Degenerate: normalized signal has ~zero energy (e.g. the input
            # was exactly constant, or became constant after normalization).
            # cumulative would be 0/0 = NaN here, which fit() detects via
            # self._degenerate_energy and reports explained_var_=0.0 instead
            # of letting NaN propagate silently into reports/audits (see
            # fit() and Reviewer improvement P2).
            self._degenerate_energy = True
            return min(max(3, q_eff // 4), max_r)
        self._degenerate_energy = False
        cumulative = np.cumsum(s ** 2) / total_energy
        if self.truncation_method == "gavish_donoho":
            # Gavish & Donoho (2014) optimal hard threshold
            # For unknown noise: threshold = 2.858 * median(singular_values)
            # P3-6.2 修复 (科研严谨性审查): 支持已知噪声水平的 Gavish-Donoho 阈值.
            # 当用户提供 noise_sigma 时, 使用 lambda(beta) 系数 (beta = p/q).
            # 这比未知噪声的 2.858 系数更精确, 适用于噪声水平已知的实验数据.
            #
            # S2-1 修复 (科研严谨性审查 Round 27): 原 _auto_truncate(self, s) 仅接收 s,
            # 但此处引用 H.shape 会抛 NameError (H 是 fit() 的局部变量).
            # 改为从 self._H_shape_ 读取 (fit() 在调用 _auto_truncate 前赋值).
            #
            # S2-2 修复 (科研严谨性审查 Round 27): Gavish-Donoho 2014 原文公式为
            #   tau = lambda(beta) * sigma * sqrt(min(m, n))
            # 其中 beta = min(m,n)/max(m,n). 原代码用 sqrt(_q) 是错误的 (应取
            # min(_p, _q)). 同时校准 lambda(beta) 表值 (Gavish & Donoho 2014
            # Table 1 精确值): beta=1.0 -> 2.858, beta=0.5 -> 2.1538,
            # beta=0.25 -> 1.8355, beta=0.1 -> 1.5494 (β→0 极限 4/π * sqrt(2) ≈ 1.8002).
            if hasattr(self, 'noise_sigma') and self.noise_sigma is not None and self.noise_sigma > 0:
                # S2-1 修复: 从 self._H_shape_ 读取, fit() 在调用前赋值
                if not hasattr(self, '_H_shape_'):
                    # 防御性回退: 若 _H_shape_ 未设置, 退到未知噪声路径
                    threshold = 2.858 * np.median(s)
                else:
                    _p, _q = self._H_shape_
                    _min_dim = min(_p, _q)
                    _max_dim = max(_p, _q)
                    _beta = _min_dim / _max_dim if _max_dim > 0 else 1.0
                    # S2-2 修复: lambda(beta) 精确值 (Gavish & Donoho 2014 Table 1)
                    # 用分段线性插值近似表中离散值
                    if _beta >= 0.99:
                        _lambda_beta = 2.858
                    elif _beta >= 0.5:
                        # [0.5, 1.0] 区间线性插值: 2.1538 -> 2.858
                        _lambda_beta = 2.1538 + (2.858 - 2.1538) * (_beta - 0.5) / 0.5
                    elif _beta >= 0.25:
                        # [0.25, 0.5] 区间线性插值: 1.8355 -> 2.1538
                        _lambda_beta = 1.8355 + (2.1538 - 1.8355) * (_beta - 0.25) / 0.25
                    elif _beta >= 0.1:
                        # [0.1, 0.25] 区间线性插值: 1.5494 -> 1.8355
                        _lambda_beta = 1.5494 + (1.8355 - 1.5494) * (_beta - 0.1) / 0.15
                    else:
                        # β < 0.1 极限值 (Gavish-Donoho 2014):
                        # 论文标题: "The optimal hard threshold for singular values is 4/√3"
                        # λ(β→0) = ω(β→0)/μ(β→0) = (4/√3)/1 ≈ 2.3094
                        # P0 修复 (ROUND33 三视角评审-数学家交叉验证):
                        #   原代码 1.5494 是 β=0.1 表值, 注释误标为 4/π·√2≈1.8002.
                        #   项目参考文献 fourteen_rules_bibliography.md:85 明确论文标题为 4/√3.
                        #   数学论证: β→0 时 MP 分布中位数 μ(β→0)→1, 故 λ(β→0)=4/√3.
                        #   ROUND32 声称已修复但实际未落地 (叙事化修缮), 本轮真实修复.
                        _lambda_beta = 4.0 / np.sqrt(3.0)  # ≈ 2.309401076...
                    # P1 修复 (ROUND33 三视角评审-数学家): Gavish-Donoho 原文公式为
                    # τ = λ(β)·σ·√(max(m,n)), numpy.svd 返回奇异值量级为 σ·√(max).
                    # 旧代码用 √min 会低估阈值, 保留过多噪声模态.
                    threshold = _lambda_beta * self.noise_sigma * np.sqrt(_max_dim)
            else:
                # 未知噪声: 用中位数倍数 (原实现)
                threshold = 2.858 * np.median(s)
            r = int(np.sum(s > threshold))
            r = max(3, min(r, max_r))
        else:
            r = int(np.searchsorted(cumulative, self.energy_threshold) + 1)
        # Floor: at least 3 modes total (2 linear + 1 forcing)
        # For very short q: use at most q_eff-1 (leave at least 1 for forcing)
        min_r = min(max(3, q_eff // 4), q_eff - 1)
        r = max(min_r, min(r, max_r))
        return r

    def _compute_kurtosis(self, x: np.ndarray) -> float:
        """计算超额峰度 (Fisher定义, 正态分布=0)。"""
        return float(scipy_kurtosis(x, fisher=True))

    def _check_sampling_adequacy(
        self, sigma_threshold: float = 1.5,
        min_spike_width: int = 2,
        undersampled_fraction_threshold: float = 0.3,
        min_spikes_for_verdict: int = 3,
    ) -> dict:
        """
        Secret 14: Nonlinear Sampling Adequacy.

        HAVOK's forcing term v_r is intermittent — most of the time it's
        small (the system evolves linearly), punctuated by sharp spikes
        when the trajectory visits the nonlinear region driving chaotic
        switching. If the sampling interval is too coarse relative to how
        fast those spikes actually happen, a spike gets aliased into 1-2
        samples — its true shape and duration are lost, and downstream
        kurtosis/forcing-based diagnostics (Secret 6's Δkurtosis check,
        spike-timing analysis) are measuring an artifact of the sampling
        rate, not the dynamics.

        Algorithm: find contiguous above-`sigma_threshold`*std regions in
        `forcing_`; a region narrower than `min_spike_width` samples is
        "undersampled". If the undersampled fraction of all spikes exceeds
        `undersampled_fraction_threshold` (and there are enough spikes to
        say anything at all — `min_spikes_for_verdict`), flag it.

        Per references/forbidden_rules_reference.md (Secret 14), this
        rule "rarely triggers" for this skill's primary use case (game-log
        data with a natural, fixed 1-game sampling interval — there's no
        sampling RATE to have gotten wrong) and is included mainly for
        completeness / future sensor-data use cases where sampling rate is
        an actual design choice. Threshold values `[E]`.

        Returns
        -------
        dict with: n_spikes, n_undersampled, undersampled_fraction,
        is_adequate (bool or None if not enough spikes to assess), note.
        Called automatically at the end of fit() (see self.sampling_adequacy_).
        """
        if self.forcing_ is None:
            return {"assessable": False, "note": "forcing_ not computed"}

        forcing = self.forcing_
        sigma = np.std(forcing)
        if sigma < EPS_DISTANCE:
            return {"assessable": False, "note": "forcing_ has ~zero variance"}

        above = np.abs(forcing) > sigma_threshold * sigma
        # Find contiguous run lengths of `above`
        spikes = []
        run_start = None
        for i, a in enumerate(above):
            if a and run_start is None:
                run_start = i
            elif not a and run_start is not None:
                spikes.append(i - run_start)
                run_start = None
        if run_start is not None:
            spikes.append(len(above) - run_start)

        n_spikes = len(spikes)
        if n_spikes < min_spikes_for_verdict:
            return {
                "assessable": False, "n_spikes": n_spikes,
                "note": f"Only {n_spikes} spike(s) detected "
                        f"(< {min_spikes_for_verdict}) — too few to assess "
                        f"sampling adequacy.",
            }

        n_undersampled = sum(1 for w in spikes if w < min_spike_width)
        undersampled_fraction = n_undersampled / n_spikes
        is_adequate = undersampled_fraction <= undersampled_fraction_threshold

        return {
            "assessable": True,
            "n_spikes": n_spikes,
            "n_undersampled": n_undersampled,
            "undersampled_fraction": float(undersampled_fraction),
            "is_adequate": is_adequate,
            "note": (
                "Sampling appears adequate for the forcing term's spike "
                "structure." if is_adequate else
                f"{undersampled_fraction:.0%} of detected forcing spikes "
                f"are narrower than {min_spike_width} samples — spike "
                f"shape/duration may be aliased by the sampling interval. "
                f"Kurtosis and spike-timing diagnostics should be treated "
                f"as lower bounds on the true intermittency."
            ),
        }

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

        # 0. Input validation — prevent silent garbage results (P2 safeguard)
        if not np.all(np.isfinite(data)):
            raise ValueError(
                "Data contains NaN or Inf. HAVOK SVD would produce all-NaN "
                "diagnostics with is_valid_=True (silent garbage). Clean the "
                "series before calling fit().")
        if n < 3:
            raise ValueError(f"Data length n={n} is too short (need >= 3).")
        if np.std(data) < EPS_VARIANCE:
            self.is_degenerate_ = True
            # debt-21: 短路后续计算——近常量数据的 SVD 必然 rank-1，
            # kurtosis/eigenvalues/regression 均无意义。设为 NaN/空并提前返回，
            # 避免 fit() 继续执行产生垃圾数值。diagnose()/report()/
            # predict_*() 顶部检查 is_degenerate_ 并返回简化报告。
            self.r_ = 0
            self.explained_var_ = 0.0
            self.kurtosis_vr_ = float('nan')
            self.eigenvalues_d_ = np.array([])
            self.eigenvalues_ = np.array([])
            self.regression_r2_ = float('nan')
            self.forcing_ = np.array([])
            self.state_ = np.zeros((0, 0))
            self.sampling_adequacy_ = {
                "assessable": False,
                "note": "degenerate input (near-constant, std < 1e-12)"}
            self.is_valid_ = True  # fit() completed, but result is degenerate
            warnings.warn(
                "Near-constant data (std < 1e-12): SVD will be rank-1, "
                "kurtosis/eigenvalue diagnostics are meaningless. "
                "Fit returns early with is_degenerate_=True. "
                "Pipeline layer should abort or annotate via "
                "is_degenerate_=True.",
                RuntimeWarning)
            return self

        # 1. Normalize
        self.mean_ = float(np.mean(data))
        self.std_ = float(np.std(data)) if np.std(data) > EPS_VARIANCE else 1.0
        normalized = (data - self.mean_) / self.std_

        # 2. Build Hankel matrix
        # V-basis: H(q x p) -> V(p x K) has p = n-q+1 time steps
        # U-basis: H(p x q) -> U(p x K) has p = n-q+1 time steps
        H = self._build_hankel(normalized)
        p_steps = n - self.q + 1  # number of time steps in state space

        # 3. Economy SVD
        U, s, Vt = svd(H, full_matrices=False)
        self.Sigma_ = s

        # S2-1 修复 (科研严谨性审查 Round 27): 在调用 _auto_truncate 前存储 H 的形状,
        # 供 Gavish-Donoho 已知噪声阈值公式使用 (beta = min/max, sqrt(min)).
        # 原 _auto_truncate 引用未定义的 H, 现通过 self._H_shape_ 传递.
        self._H_shape_ = H.shape

        # 4. Auto-determine truncation rank r
        self.r_ = self._auto_truncate(s)
        total_energy = float(np.sum(s ** 2))
        if getattr(self, "_degenerate_energy", False) or total_energy < EPS_ENERGY:
            # Degenerate: total singular-value energy is ~0 (constant or
            # near-constant normalized signal). sum/sum would be 0/0 = NaN;
            # report an explicit 0.0 instead so explained_var_ never
            # silently becomes NaN and defeats downstream comparisons
            # (e.g. `explained_var_ > 0.7`) without any visible signal of
            # why. The input-validation warning above already flags this
            # data as untrustworthy; this just keeps the failure loud
            # instead of silent (Reviewer improvement P2 philosophy).
            #
            # debt-21: 短路后续计算——零能量 SVD 的回归/特征值/kurtosis
            # 均无意义。设为 NaN/空并提前返回，与 std<1e-12 路径一致。
            self.is_degenerate_ = True
            self.explained_var_ = 0.0
            self.kurtosis_vr_ = float('nan')
            self.eigenvalues_d_ = np.array([])
            self.eigenvalues_ = np.array([])
            self.regression_r2_ = float('nan')
            self.forcing_ = np.array([])
            self.state_ = np.zeros((0, 0))
            self.sampling_adequacy_ = {
                "assessable": False,
                "note": "degenerate input (zero singular-value energy)"}
            self.is_valid_ = True
            return self
        else:
            self.explained_var_ = float(np.sum(s[: self.r_] ** 2) / total_energy)

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
        # ROUND26 算法审视 P2-3 修复: 条件数自适应正则化
        # cond(Theta) > 1e10 时 Theta.T@Theta 病态, lstsq 的 rcond=None 自动
        # 截断可能保留过小奇异值导致 Xi 方差爆炸。此时自动切换到 ridge 回归
        # (Tikhonov 正则化), 抑制小奇异值放大。阈值 1e10 依据: cond(Theta²)=
        # cond(Theta)², 1e10²=1e20 已超 float64 有效精度 (~1e16)。
        cond_theta = float(np.linalg.cond(Theta))
        if self.regression_method == "ridge" or cond_theta > 1e10:
            if self.regression_method != "ridge" and cond_theta > 1e10:
                # 自动切换: 记录到 diagnose() 报告
                self._auto_ridge_triggered = True
            # Ridge regression (L2 regularization)
            # Xi = (Theta^T @ Theta + alpha*I)^(-1) @ Theta^T @ dv_dt
            n_features = Theta.shape[1]
            I_reg = np.eye(n_features)
            Xi = pinv(Theta.T @ Theta + self.ridge_alpha * I_reg) @ Theta.T @ dv_dt
        else:
            self._auto_ridge_triggered = False
            Xi, residuals, rank, s_lstsq = lstsq(Theta, dv_dt, rcond=None)

        # Xi = [A_part | B_part]^T, A_part:(r-1)x(r-1), B_part:(1)x(r-1)
        Xi_T = Xi.T  # (r-1, r)
        self.A_ = Xi_T[:, : self.r_ - 1]          # (r-1, r-1)
        self.B_ = Xi_T[:, self.r_ - 1 : self.r_]  # (r-1, 1)

        # 8. Discrete-time Koopman operator (first-order Euler)
        self.K_d_ = np.eye(self.r_ - 1) + self.dt * self.A_

        # 8b. Exact discrete-time evolution via matrix exponential
        # v(t+dt) = exp(A*dt)·v(t) + G·v_r  where G = ∫₀ᵈᵗ exp(A*(dt-s))·B ds
        # Construct augmented matrix [[A*dt, B*dt], [0, 0]] and exponentiate
        # to get both F=exp(A*dt) and G in one call (handles singular A correctly)
        n_aug = self.r_
        M_aug = np.zeros((n_aug, n_aug))
        M_aug[:self.r_-1, :self.r_-1] = self.A_ * self.dt
        M_aug[:self.r_-1, self.r_-1] = self.B_.ravel() * self.dt
        expM_aug = expm(M_aug)
        self.F_ = expM_aug[:self.r_-1, :self.r_-1]  # exact discrete transition
        self.G_ = expM_aug[:self.r_-1, self.r_-1]   # forcing response per unit v_r

        # 9. Forcing kurtosis diagnostic
        self.kurtosis_vr_ = self._compute_kurtosis(self.forcing_)

        # 10. Koopman eigenvalue spectrum
        # Continuous-time eigenvalues (A matrix): dv/dt = A·v + B·v_r
        # Stability criterion: Re(λ) < 0 (stable), Re(λ) > 0 (unstable)
        self.eigenvalues_ = eig(self.A_)[0]

        # Discrete-time eigenvalues (matrix exponential of A*dt):
        # Stability criterion: |λ_d| < 1 (stable), |λ_d| > 1 (unstable)
        # Uses proper matrix exponential instead of first-order Euler
        # to avoid truncation error at large dt.
        K_d_proper = expm(self.A_ * self.dt)
        self.eigenvalues_d_ = eig(K_d_proper)[0]

        # 11. Regression quality
        # Note: This is the "uncentered R²" (no intercept), appropriate for
        # models without intercept. For derivative signals with mean ≈ 0,
        # this is close to the standard R².
        dv_pred = Theta @ Xi
        self.regression_r2_ = float(
            1 - np.sum((dv_dt - dv_pred) ** 2) / (np.sum(dv_dt ** 2) + EPS_VARIANCE)
        )

        self.is_valid_ = True

        # 12. Secret 14: Nonlinear Sampling Adequacy
        # Cheap, best-effort diagnostic on the forcing term already
        # computed above — see _check_sampling_adequacy() docstring.
        self.sampling_adequacy_ = self._check_sampling_adequacy()

        return self

    # ── 预测 ──────────────────────────────────────────────

    def predict_next_state(
        self, current_v: np.ndarray, current_vr: float
    ) -> np.ndarray:
        """
        One-step prediction using exact discrete-time evolution.

        Solves dv/dt = A·v + B·v_r EXACTLY via matrix exponential:
          v(t+dt) = exp(A·dt)·v(t) + G·v_r
        where G = ∫ exp(A·(dt-s))·B ds is precomputed in fit().

        This replaces the first-order Euler approximation used previously,
        which accumulated significant truncation error at dt≥1 (game data).

        Parameters
        ----------
        current_v : np.ndarray, shape (r-1,)
        current_vr : float
            Forcing term value (assumed constant over [t, t+dt]).

        Returns
        -------
        next_v : np.ndarray, shape (r-1,)
        """
        if not self.is_valid_:
            raise RuntimeError("请先调用 fit()")
        # debt-21: degenerate 短路——退化模型的 F_/G_ 未计算，
        # 预测无意义，返回 NaN 向量而非抛异常（保持加法优先原则，
        # 调用方可通过 is_degenerate_ 提前判断）。
        if self.is_degenerate_:
            r_minus_1 = max(0, (self.r_ or 1) - 1)
            return np.full(r_minus_1, float('nan'))
        v_col = np.asarray(current_v, dtype=float).reshape(-1, 1)
        # v(t+dt) = F·v(t) + G·v_r  (exact for piecewise-constant v_r)
        next_v = self.F_ @ v_col + self.G_.reshape(-1, 1) * current_vr
        return next_v.ravel()

    def predict_n_steps(
        self, v0: np.ndarray, vr_sequence: np.ndarray, n_steps: int
    ) -> np.ndarray:
        """
        Multi-step forward prediction using exact discrete evolution.

        Each step uses the matrix exponential F = exp(A·dt) with the
        precomputed forcing response G. No truncation error accumulation
        from Euler integration.

        Parameters
        ----------
        v0 : np.ndarray, shape (r-1,)
            Initial state.
        vr_sequence : np.ndarray, shape (n_steps,)
            Future forcing sequence (external estimate; 0 where unknown).
        n_steps : int
            Number of prediction steps.

        Returns
        -------
        trajectory : np.ndarray, shape (n_steps+1, r-1)
        """
        # debt-21: degenerate 短路——返回全 NaN 轨迹。
        if self.is_degenerate_:
            r_minus_1 = max(0, (self.r_ or 1) - 1)
            return np.full((n_steps + 1, r_minus_1), float('nan'))
        trajectory = np.zeros((n_steps + 1, self.r_ - 1))
        trajectory[0] = v0
        v_current = np.asarray(v0, dtype=float).reshape(-1, 1)
        for t in range(n_steps):
            vr = vr_sequence[t] if t < len(vr_sequence) else 0.0
            v_current = self.F_ @ v_current + self.G_.reshape(-1, 1) * vr
            trajectory[t + 1] = v_current.ravel()
        return trajectory

    # ── 诊断 ──────────────────────────────────────────────

    def diagnose(self) -> dict:
        """
        Return complete diagnostic report as a dictionary.
        """
        if not self.is_valid_:
            return {"error": "Model not fitted"}

        # debt-21: degenerate 短路——返回简化报告，避免访问 NaN/空字段。
        if self.is_degenerate_:
            return {
                "embedding_dim_q": self.q,
                "truncation_rank_r": self.r_,
                "degenerate": True,
                "explained_variance": "0.0000%",
                "regression_r2": "NaN",
                "kurtosis_vr": "NaN",
                "forcing_type": "Degenerate (near-constant/zero-energy input)",
                "stability": "Indeterminate (degenerate)",
                "max_eigenvalue_d": "N/A",
                "min_eigenvalue_d": "N/A",
                "spike_count": 0,
                "spike_positions": [],
                "basis": self.basis,
                "condition_number": "N/A",
                "sampling_adequacy": self.sampling_adequacy_,
                # 数值版本字段（_raw）——与下方正常分支保持同名同构，
                # 便于程序化消费方在 degenerate 与正常两种情形下使用统一键名。
                "truncation_rank_r_raw": int(self.r_),
                "explained_variance_raw": 0.0,
                "regression_r2_raw": float(self.regression_r2_),
                "kurtosis_vr_raw": float(self.kurtosis_vr_),
                "max_eigenvalue_d_raw": None,
                "min_eigenvalue_d_raw": None,
                "condition_number_raw": None,
            }

        # Stability from discrete-time eigenvalues (|λ_d| vs 1)
        # Continuous eigenvalues of A are used for spectral analysis only;
        # stability thresholds (1.05, 0.90) apply to discrete-time |λ_d|.
        # Delegates to the module-level classify_havok_stability() so
        # pipeline.py and enhanced_cross_validate.py (which independently
        # re-implemented this same 1.05/0.90 tiering) cannot drift out of
        # sync with this canonical definition — see classify_havok_stability.
        growth_rates = np.abs(self.eigenvalues_d_)
        max_growth = float(np.max(growth_rates))
        min_growth = float(np.min(growth_rates))

        # Classify system type
        stability = classify_havok_stability(max_growth)

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
            "max_eigenvalue_d": f"{max_growth:.4f}",      # discrete-time |λ_d|
            "min_eigenvalue_d": f"{min_growth:.4f}",
            "spike_count": len(spike_indices),
            "spike_positions": spike_indices.tolist(),
            "basis": self.basis,
            "condition_number": (
                f"{float(np.linalg.cond(self.A_)):.2f}"
                if np.isfinite(np.linalg.cond(self.A_))
                else "Singular (inf)"
            ),
            "sampling_adequacy": self.sampling_adequacy_,  # Secret 14
            # 数值版本字段（_raw）——格式化字符串字段旁附同名数值副本，
            # 便于程序化消费方直接读取 float/int，无需解析百分号/小数字符串。
            # 现有字符串字段保持不变（向后兼容）。
            "truncation_rank_r_raw": int(self.r_),
            "explained_variance_raw": float(self.explained_var_),
            "regression_r2_raw": float(self.regression_r2_),
            "kurtosis_vr_raw": float(self.kurtosis_vr_),
            "max_eigenvalue_d_raw": float(max_growth),
            "min_eigenvalue_d_raw": float(min_growth),
            "condition_number_raw": float(np.linalg.cond(self.A_)),
            # ROUND26 P2-3: 条件数自适应正则化标志
            "auto_ridge_triggered": bool(self._auto_ridge_triggered),
        }

    def report(self) -> str:
        """Generate human-readable diagnostic report."""
        d = self.diagnose()
        if "error" in d:
            return d["error"]
        # debt-21: degenerate 短路——简化报告
        if d.get("degenerate"):
            lines = [
                "=" * 62,
                "  SovereignHAVOK Dynamics Diagnostic Report",
                "=" * 62,
                f"  Embedding dim q      : {d['embedding_dim_q']}",
                f"  Truncation rank r    : {d['truncation_rank_r']}",
                f"  Regression basis     : {d['basis']}",
                "  *** DEGENERATE INPUT ***",
                f"  {d['forcing_type']}",
                "  Kurtosis/eigenvalue/stability diagnostics are NOT meaningful.",
                "  Explained variance    : 0.0000%",
                "  Regression R^2        : NaN",
                "  Kurtosis (v_r)        : NaN",
                "  Stability             : Indeterminate (degenerate)",
                "=" * 62,
            ]
            return "\n".join(lines)

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
            f"  Max |eig_d|          : {d['max_eigenvalue_d']}",
            f"  Min |eig_d|          : {d['min_eigenvalue_d']}",
            f"  Stability            : {d['stability']}",
            "",
            f"  Spike count          : {d['spike_count']}",
        ]
        if d["spike_positions"]:
            lines.append(f"  Spike time indices   : {d['spike_positions']}")
        sa = d.get("sampling_adequacy") or {}
        if sa.get("assessable"):
            tag = "OK" if sa["is_adequate"] else "WARN"
            lines.append(
                f"  Sampling adequacy    : [{tag}] "
                f"{sa['n_undersampled']}/{sa['n_spikes']} spikes "
                f"undersampled ({sa['undersampled_fraction']:.0%})")
        lines.append("=" * 62)
        return "\n".join(lines)


# ──────────────────────────────────────────────────────────────
# 共享分类函数 (Shared classification — single source of truth)
# ──────────────────────────────────────────────────────────────

def classify_havok_stability(
    max_eigenvalue_d: float,
    divergent_threshold: float = 1.05,
    dissipative_threshold: float = 0.90,
) -> str:
    """
    Classify HAVOK discrete-time Koopman stability from max|eigenvalue_d|.

    Single source of truth for the divergent / near-critical / dissipative
    tiering. Before this function existed, `sovereign_havok.diagnose()`,
    `pipeline.py`, and `enhanced_cross_validate.py` each independently
    re-implemented the same 1.05 / 0.90 threshold check. The three copies
    happened to agree, but nothing enforced that — a future edit to one
    copy (e.g. tightening the divergence threshold) could silently leave
    the others stale, producing a classification mismatch across reports
    for the identical model. Centralizing it here removes that risk, the
    same way `classify_hankel_ratio` in edm_auditor.py was centralized.

    Parameters
    ----------
    max_eigenvalue_d : float
        max(abs(eigenvalues_d_)) — discrete-time Koopman eigenvalue moduli.
    divergent_threshold : float
        Above this, at least one mode is growing (default 1.05).
    dissipative_threshold : float
        Below this, all modes are strongly damped (default 0.90).

    Returns
    -------
    str : one of "Divergent (unstable modes)",
                 "Highly dissipative (fast convergence)",
                 "Near-critical / stable"
    """
    if max_eigenvalue_d > divergent_threshold:
        return "Divergent (unstable modes)"
    elif max_eigenvalue_d < dissipative_threshold:
        return "Highly dissipative (fast convergence)"
    else:
        return "Near-critical / stable"


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

        if len(preds) > 3 and np.std(preds) > EPS_VARIANCE:
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

    # Test 6: Secret 14 sampling adequacy — must distinguish genuinely
    # inadequate sampling from adequate sampling, not just always warn.
    print("\n-- Test 6: Secret 14 Sampling Adequacy --")

    def _lorenz(x, y, z, s=10, r=28, b=8/3):
        return s * (y - x), x * (r - z) - y, x * y - b * z

    dt6 = 0.01
    n6 = 3000
    xs = np.zeros(n6); xs[0] = 1.0
    yv, zv = 1.0, 1.0
    for i in range(1, n6):
        dx, dy, dz = _lorenz(xs[i - 1], yv, zv)
        xs[i] = xs[i - 1] + dx * dt6; yv += dy * dt6; zv += dz * dt6
    fine = xs[300:2300]
    coarse = fine[::20]

    sh_fine = SovereignHAVOK(q_delays=40, window_length=15, poly_order=3, dt=dt6).fit(fine)
    sh_coarse = SovereignHAVOK(q_delays=15, window_length=7, poly_order=2, dt=dt6 * 20).fit(coarse)

    sa_fine = sh_fine.sampling_adequacy_
    sa_coarse = sh_coarse.sampling_adequacy_
    print(f"  Fine sampling:   undersampled={sa_fine.get('undersampled_fraction', 'N/A')}, "
          f"is_adequate={sa_fine.get('is_adequate')}")
    print(f"  Coarse sampling: undersampled={sa_coarse.get('undersampled_fraction', 'N/A')}, "
          f"is_adequate={sa_coarse.get('is_adequate')}")
    assert sa_fine.get("assessable"), "fine-sampled series should have enough spikes to assess"
    assert sa_coarse.get("assessable"), "coarse-sampled series should have enough spikes to assess"
    assert sa_fine["undersampled_fraction"] < sa_coarse["undersampled_fraction"], (
        "20x coarser subsampling of the identical underlying dynamics must "
        "show a HIGHER undersampled fraction, not just always warn")
    print("  PASS: Secret 14 distinguishes fine vs. coarse sampling of identical dynamics")

    print("\n" + "=" * 62)
    print("  All self-tests passed!")
    print("=" * 62)
