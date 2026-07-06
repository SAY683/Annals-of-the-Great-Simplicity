# Edge Cases: Data Regimes and Corrections

## 1. Binary / Discrete Data

**Problem**: EDM was designed for continuous measurements on smooth manifolds.
Binary data (win/loss, 0/1) has only two states; simplex neighborhoods become
flat and rho can be inflated by Bernoulli variance alone.

**Mitigation**:
- Report accuracy alongside rho for binary targets
- Prefer EDM on continuous covariates (kills, damage, rating) that drive the
  binary outcome
- Logistic transform of simplex output: p = 1 / (1 + exp(-pred))

**rho bound for binary data**: For Bernoulli(p=0.5), maximum possible rho is
about 0.87 even for a perfect predictor.

## 2. Small Sample Size (N < 3^E)

**Problem**: To densely populate an E-dimensional attractor, O(3^E) samples
are needed. For N=32 and E=5, the attractor is extremely sparse.

**Mitigation**:
- Constrain E_max = min(10, max(3, N/5))
- Use bootstrap resampling of the library to estimate uncertainty
- Report library-to-embedding ratio: N / (2*E+1)
- Prefer out-of-sample or cross-validated rho over training rho

## 3. Non-Stationary Attractor (Regime Shift)

**Detection**: If prediction rho on a sliding test window drops abruptly,
the attractor may have changed.

**Action**:
- Drop pre-shift portion of the library
- Rebuild embedding using only post-shift data
- Use sliding window library for real-time forecasting

## 4. High-Dimensional Data (D > 10)

**Problem**: pyEDM's univariate embedding assumes 1D input. High-D data
(e.g. LLM embeddings of dimension 1536) needs multivariate EDM (M-EDM).

**Action**:
- Reduce via PCA/SVD to 3-10 principal components before embedding
- Or use multivariate pyEDM with multiple column inputs
- For very high dimensions, prefer HAVOK over classic pyEDM

## 5. Synchrony False Positives in CCM

**Cobey-Baskerville criterion** (2016): Cross-map convergence must be
monotonic with library size. Flat or oscillatory convergence => false positive.

**Surrogate data test**: Generate N phase-randomized surrogates (Ebisuzaki
method), run CCM on each, compare real rho to surrogate distribution.
If p > 0.05, reject the causality claim.

## 6. HAVOK Matrix Aspect Ratio (Numerical Stability)

**Problem**: HAVOK constructs a Hankel matrix H of size p x q (p = n-q+1 time rows, q delay columns). SVD of non-flat matrices produces numerically degraded spectra.

**Golden rule**: p >= 10 * q. For n=500, use q <= 45. Always prioritize matrix condition over embedding dimension.

**Warning signs**: Koopman eigenvalues with sudden jumps, forcing term with no physical spikes, regression R2 suspiciously high (>0.999).
