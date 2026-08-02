# EDM-Takens Skill — Design Philosophy & Business Logic

## Architecture: Defense in Depth

The Skill implements three concentric protection layers. Each layer catches
different classes of failure before they can produce garbage results.

```
┌─────────────────────────────────────────────┐
│  LAYER 1: Environment Validation            │  ← environment_check.py
│  "Can we even run?"                         │
│  - Python version, package deps, file paths │
│  - Platform quirks (Windows multiproc, MKL) │
│  - Generates pip-freeze version report      │
├─────────────────────────────────────────────┤
│  LAYER 2: Configuration Audit (Firewall)    │  ← edm_auditor.py
│  "Is this request physically possible?"     │
│  - Hankel ratio (numerical stability)       │
│  - Lyapunov horizon (physics limit)         │
│  - CCM direction (logic correctness)        │
│  - Embedding dimension vs sample size       │
│  - BLOCKS: physically impossible requests   │
│  - AUTO-CORRECTS: numerically suboptimal    │
│  - WARNS: statistically marginal            │
├─────────────────────────────────────────────┤
│  LAYER 3: Algorithmic Cross-Validation      │  ← verify_algorithms.py
│  "Do two independent methods agree?"        │
│  - EDM vs HAVOK on same data                │
│  - V-basis vs U-basis consistency           │
│  - Surrogate data test (destroy structure)  │
│  - Noise injection (kurtosis should drop)   │
│  - ONLY trust diagnosis when both agree     │
└─────────────────────────────────────────────┘
```

## Auto-Correction Philosophy

Not all problems should be auto-corrected. The guiding principle:

| Problem Class | Auto-Correct? | Rationale |
|--------------|---------------|-----------|
| Numerical suboptimality | YES | Can fix without changing scientific validity |
| Data insufficiency | NO (warn) | Can't create data from nothing |
| Physical impossibility | NO (block) | Would produce scientifically false results |
| Logic error (wrong direction) | NO (warn) | Requires human interpretation |

### Auto-Correction Rules

1. **Hankel p/q < 10**: AUTO-REDUCE q to q_safe = (n+1)//11
   - Rationale: smaller q with well-conditioned SVD > larger q with broken regression
   - User notified: "q reduced from X to Y for numerical stability"

2. **SG window > p//4**: AUTO-CAP to p//4 (already in sovereign_havok.py)
   - Rationale: over-smoothing destroys derivative fidelity
   - User notified via diagnostic report

3. **E > N/5**: AUTO-CAP E to max(N//5, 2)
   - Rationale: sparse attractor cannot support high embedding dimension
   - User warned: "results from sparse attractor may be unreliable"

4. **Missing tau**: AUTO-COMPUTE via AMI analysis
   - Rationale: better to estimate than use default tau=1
   - User notified: "tau auto-computed as X via AMI"

5. **Binary target**: AUTO-SUGGEST continuous covariate approach
   - Does NOT auto-switch (requires domain knowledge)
   - Rationale: binary EDM has known limitations (rho ceiling ~0.87)

## Business Scenarios & Decision Logic

### Scenario A: "I have 30 games, tell me what drives winning"
```
Layer 1: env_check → PASS (all deps OK)
Layer 2: audit → WARN (N<50, binary target)
         → Auto-compute tau, auto-cap E to 3
         → Recommend Multiview if multiple variables
Layer 3: HAVOK + EDM → cross-validate
         → If agree: confident diagnosis
         → If disagree: "need more data, trust neither"
Output: "Your kills are predictable (rho=0.85). CCM says result→kills.
         You need 70+ more games for phase transition detection."
```

### Scenario B: "Predict win/loss for next 50 games from 32 games"
```
Layer 1: env_check → PASS
Layer 2: audit → BLOCK
         → Lyapunov: cannot estimate (N<100)
         → If forced: "pred_horizon >> any reasonable tau_L estimate"
         → Auditor: FAIL. "This prediction is scientifically meaningless."
```

### Scenario C: "Run HAVOK with E=10 on 32 data points"
```
Layer 1: env_check → PASS
Layer 2: audit → BLOCK
         → Hankel: p/q = (32-10+1)/10 = 2.3 < 3
         → Auto-correct: q reduced from 10 to 3
         → Auditor: WARN. "q auto-corrected. Re-run with q=3."
```

## Dependency Version Report

Working versions (from edm_env2, Python 3.13.2, Windows 10):
See requirements.txt for full pip freeze.

Key version constraints:
- numpy >= 1.22 (SVD numerical stability)
- scipy >= 1.8  (Savitzky-Golay filter, kurtosis)
- pyEDM >= 2.5 (Multiview support, numProcess parameter)
- pandas >= 1.4 (DataFrame operations)
- matplotlib >= 3.5 (visualization)

Known environment issues:
- Windows + Python 3.13: pyEDM.Multiview multiprocessing may fail
  Workaround: use numProcess=1 or Linux/macOS
- Intel MKL on Windows: set OMP_NUM_THREADS=1 to prevent subprocess memory issues
