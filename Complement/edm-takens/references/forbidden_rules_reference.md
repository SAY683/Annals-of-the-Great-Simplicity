# Advanced Pitfall Avoidance: Three Forbidden Rules

These three counter-intuitive rules were discovered through repeated failure
in real nonlinear dynamics and causality analysis. They are not taught in
standard textbooks — they are learned the hard way.

## Secret 1: Lyapunov Horizon

### The Physical Limit
Every chaotic system is exponentially sensitive to initial conditions.
The divergence rate is quantified by the Maximal Lyapunov Exponent (MLE):

  lambda_max = lim_{t->inf} (1/t) * ln( |delta(t)| / |delta(0)| )

The system's fundamental predictability limit:

  Lyapunov time: tau_L = 1 / lambda_max

### The Forbidden Rule
- Predictions up to 1*tau_L are deterministic and reliable
- Predictions from 1*tau_L to 3*tau_L show exponentially growing errors
- Predictions BEYOND 3*tau_L to 5*tau_L are scientifically meaningless

### Practical Implementation
To estimate lambda_max from data:
1. Reconstruct attractor via delay embedding (using optimal tau, E from the skill pipeline)
2. Track divergence of nearby trajectories:
   - For each reference point, find its nearest neighbor in state space
   - Compute log distance vs time for each pair
3. lambda_max = slope of the linear region in the log-distance plot
   (the Rosenstein algorithm or Kantz algorithm)

**If tau_L corresponds to 3 days, do not predict day 10.**
Any algorithm claiming to predict chaotic systems beyond 5*tau_L is fraudulent.

## Secret 2: CCM Victim Mirror Principle

### The Counter-Intuitive Rule
If variable X causes variable Y (X -> Y), then:
- Y's shadow manifold M_Y can estimate X's state
- NOT the reverse (X's manifold M_X may not predict Y)

**Why?** The effect Y's dynamics are constrained by the cause X.
Every perturbation in X leaves a dynamical fingerprint in Y's trajectory.
Y's reconstructed attractor M_Y therefore contains information about X.

### The Common Mistake
90% of CCM beginners get this backward. They try to use M_X to predict Y,
which fails because X (as cause) does NOT carry Y's dynamics.

### Practical Implementation
To test "rainfall (X) affects rabbit population (Y)":
1. Reconstruct M_Y from Y (rabbit time series)
2. Cross-map: use nearest neighbors in M_Y to estimate X (rainfall)
3. Compute prediction skill rho(X|M_Y) — this measures causal strength X->Y
4. Cross-convergence: rho must INCREASE with library size L

See also: Sugihara et al., "Detecting Causality in Complex Ecosystems", Science 2012.

## Secret 3: Hankel Matrix Golden Aspect Ratio

### The Numerical Stability Problem
For HAVOK and DMD methods, the Hankel matrix is:

  H = [ x(t_i + j-1) ],  size = p x q
  where q = embedding dimension (delay columns)
        p = n - q + 1 (time rows)

SVD of a tall-thin matrix (p >> q) produces well-conditioned singular vectors.
SVD of a square or tall matrix (p ~ q or p < q) produces numerically
degraded spectra with false mode coupling.

### The Golden Ratio
**p >= 10 * q** — the matrix must be extremely flat/wide.

### Why This Matters
- When p/q is too small, the left and right singular vectors become
  numerically coupled (the "curse of the aspect ratio")
- The Koopman operator K = X_p * pinv(X) becomes ill-conditioned
- False "stiff" eigenvalues appear in the spectrum
- Physical modes mix with numerical artifacts

### Practical Implementation
| n (data length) | q (delay columns) | p = n-q+1 | p/q ratio | Safe? |
|-----------------|-------------------|-----------|-----------|-------|
| 500             | 100               | 401       | 4.0       | NO    |
| 500             | 45                | 456       | 10.1      | YES   |
| 1000            | 90                | 911       | 10.1      | YES   |
| 200             | 18                | 183       | 10.2      | YES   |

**When data is short: sacrifice q to maintain p/q >= 10.**
A smaller embedding dimension with a well-conditioned SVD is FAR better
than a larger embedding with a numerically broken regression.

## Secret 4: Multiview Embedding — Saving Short Data from Starvation
### (My Feasibility Rating: HIGHEST — Strongly Recommended)

Source: Sugihara et al., Science 2016. pyEDM implementation: pyEDM.Multiview()

**The Problem** — When N < 100, single-variable delay embedding wastes precious data as delay padding. For N=60 and E=5, only ~40 embedding vectors remain. You are starving your own analysis.

**The Solution** — Use SPATIAL diversity (multiple observed variables) instead of TEMPORAL delay. With K correlated variables, Multiview produces K-choose-E candidate models and selects the best by out-of-sample prediction skill.

  V_delay(t) = [X(t), X(t-1), X(t-2), X(t-3)]          — 3 delays, 4D
  V_multiview(t) = [X(t), Y(t), Z(t), X(t-1)]            — 3 variables + 1 delay

**When to use:**
- Short data (N < 100) with multiple observed correlated variables
- Game analytics: embed [result, kills, damage, deaths] jointly
- Any multivariate time series where cross-correlations encode dynamics
- Whenever pyEDM.Multiview gives higher out-of-sample rho than Simplex

**Implementation in pyEDM:**
  pyEDM.Multiview(dataFrame=df, E=3, columns=['kills','damage','deaths'],
                  target='result', lib='1 25', pred='26 32')

## Secret 5: SVD Reconstruction Residual — Attractor Deformation Alarm
### (My Feasibility Rating: HIGH — Adopt with Caveats)

**The Concept** — Monitor the normalized truncated SVD reconstruction residual:
  Residual = ||H - U_r * diag(Sigma_r) * V_r^T||_F / ||H||_F

When the system undergoes a regime shift (attractor dissolving), the old SVD basis (U_r, V_r from original fit) cannot span the new dynamics — the residual jumps.

**Detection Rule** — Residual > 2.5x running_mean for 3 consecutive windows -> alarm

**Action** — Drop oldest 50% of Hankel data, re-fit SVD on remaining window

**My Caveats (critical for correct implementation):**
1. The 50% drop is HEURISTIC. Better approach: use an F-test for structural break to find the optimal cutoff.
2. Needs at least N=200 post-deformation for reasonable SVD statistics.
3. For real-time use: exponentially-weighted sliding window is smoother than hard 50% cutoff.
4. Not applicable when deformation evolves faster than the embedding window size.
5. SovereignHAVOK users: add this to your fit() loop as an is_valid_ check.

## Secret 6: CCM Arrow Trap — Code-Level Direction Enforcement
### (Merged into Secret 2 — Enhancement, not new rule)

The CCM Victim Mirror Principle (Secret 2) is correct. This is an implementation
note for automated pipelines:

  pyEDM.CCM(columns='Y', target='X') — measures X's influence on Y
  CONVERGING CCM(Y->X) with L + non-converging CCM(X->Y) -> X causes Y
  Both converge -> bidirectional coupling or common driver
  Neither converges -> no causal relationship

Always explicitly verify both directions when automating CCM in a pipeline.

## Secret 7 (cross-validation): EDM + HAVOK Must Cross-Validate
EDM tells IF (theta>0). HAVOK tells WHEN (forcing spikes). Only when both
independently agree on the system dynamics can the diagnosis be trusted.
