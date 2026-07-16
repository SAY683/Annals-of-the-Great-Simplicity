# Fourteen Forbidden Rules — Complete Annotated Bibliography

> Every rule, its scientific basis, and every cited paper — indexed by rule number and cross-referenced.
> This file is the single-source-of-truth bibliography for `references/forbidden_rules_reference.md`.

---

## Bibliographic Format

Each entry follows the pattern:
```
[N] First Author et al. (YEAR). "Title." *Journal*, Vol(Issue), Pages.
    → Rules: S{N}, S{M}
    → Role: [foundational method | pitfall demonstration | constructive critique | concept framework | statistical method]
    → In Skill: [cited in file:line | NOT YET CITED]
```

---

# A. Core Method Papers (Rules 1-7)

These papers define the three theoretical pillars of the Skill — Takens embedding,
CCM causality, and HAVOK/Koopman decomposition. All are already cited in the codebase.

## A1. Foundational — Embedding & State-Space Reconstruction

**[B01]** **Takens, F. (1981).** "Detecting strange attractors in turbulence." In *Dynamical Systems and Turbulence*, Lecture Notes in Mathematics, 898, Springer, 366-381.
- → Rules: **S1, S4, S9**
- → Role: foundational method
- → In Skill: `SKILL.md:295`, `references/takens_embedding_reference.md:1-17`

**[B02]** **Packard, N.H., Crutchfield, J.P., Farmer, J.D., & Shaw, R.S. (1980).** "Geometry from a time series." *Physical Review Letters*, 45(9), 712-716.
- → Rules: **S4, S9**
- → Role: foundational method (first delay-embedding paper; noted sensor saturation can distort embedding)
- → In Skill: `references/takens_embedding_reference.md:19-20` (cited but without saturation observation)

**[B03]** **Sauer, T., Yorke, J.A., & Casdagli, M. (1991).** "Embedology." *Journal of Statistical Physics*, 65(3), 579-616.
- → Rules: **S9**
- → Role: concept framework (rigorous genericity conditions; defines "prevalence" for fractal attractors)
- → In Skill: NOT YET CITED

**[B04]** **Abarbanel, H.D.I., Brown, R., Sidorowich, J.J., & Tsimring, L.S. (1993).** "The analysis of observed chaotic data in physical systems." *Reviews of Modern Physics*, 65(4), 1331-1392.
- → Rules: **S14, S8**
- → Role: practical guide (sampling rate selection §IV; stationarity considerations)
- → In Skill: indirectly via Kennel-Brown-Abarbanel (1992) in `_numpy_edm.py:863`

**[B05]** **Letellier, C., Aguirre, L.A., & Maquet, J. (2005).** "Relation between observability and differential embeddings for nonlinear dynamics." *Physical Review E*, 71(6), 066213.
- → Rules: **S9**
- → Role: concept framework (observability matrix; quantifies when measurement function fails genericity)
- → In Skill: NOT YET CITED

## A2. Foundational — EDM (Simplex, S-Map)

**[B06]** **Sugihara, G. & May, R.M. (1990).** "Nonlinear forecasting as a way of distinguishing chaos from measurement error in time series." *Nature*, 344(6268), 734-741.
- → Rules: **S1, S6, S12**
- → Role: foundational method (Simplex projection; prediction decay distinguishes chaos from noise)
- → In Skill: `_numpy_edm.py:9`, `references/takens_embedding_reference.md:21-23`, `docs/ALGORITHM_AUDIT.md`

**[B07]** **Sugihara, G. (1994).** "Nonlinear forecasting for the classification of natural time series." *Philosophical Transactions of the Royal Society A*, 348(1688), 477-495.
- → Rules: **S6**
- → Role: foundational method (S-Map; theta > 0 indicates nonlinearity)
- → In Skill: `_numpy_edm.py:10`, `docs/ALGORITHM_AUDIT.md`

## A3. Foundational — CCM Causality

**[B08]** **Sugihara, G., May, R., Ye, H., Hsieh, C.-H., Deyle, E., Fogarty, M., & Munch, S. (2012).** "Detecting causality in complex ecosystems." *Science*, 338(6106), 496-500.
- → Rules: **S2, S7, S10, S11**
- → Role: foundational method (CCM); also source of common-driver caveat (Supplementary Materials)
- → In Skill: `SKILL.md:294`, `ccm_causality.py:5,69,234`, `_numpy_edm.py:11,436`, `enhanced_cross_validate.py:182`, `forbidden_rules_reference.md:58-59`, `secret_adoption_audit.md:47`

**[B09]** **Sugihara, G., Deyle, E.R., & Ye, H. (2016).** "Multiview embedding: spatially explicit prediction for short time series." *Science*, 353(6302), 922-925.
- → Rules: **S4**
- → Role: foundational method (Multiview — spatial diversity compensates for short temporal records)
- → In Skill: `_numpy_edm.py:592,727,737`, `secret_adoption_audit.md:122`, `forbidden_rules_reference.md:98`

## A4. Foundational — HAVOK / Koopman

**[B10]** **Brunton, S.L., Brunton, B.W., Proctor, J.L., Kaiser, E., & Kutz, J.N. (2017).** "Chaos as an intermittently forced linear system." *Nature Communications*, 8, 19.
- → Rules: **S3, S5, S6**
- → Role: foundational method (HAVOK decomposition; intermittently forced linear dynamics)
- → In Skill: `SKILL.md:19,92,281,293`, `sovereign_havok.py:4,9,73,128,138`, `docs/ALGORITHM_AUDIT.md`

## A5. Foundational — Numerical Methods

**[B11]** **Gavish, M. & Donoho, D.L. (2014).** "The optimal hard threshold for singular values is 4/√3." *IEEE Transactions on Information Theory*, 60(8), 5040-5053.
- → Rules: **S3, S5**
- → Role: statistical method (optimal SVD truncation threshold for unknown noise)
- → In Skill: `SKILL.md:280`, `sovereign_havok.py:77,220`

**[B12]** **Rosenstein, M.T., Collins, J.J., & De Luca, C.J. (1993).** "A practical method for calculating largest Lyapunov exponents from small data sets." *Physica D*, 65(1-2), 117-134.
- → Rules: **S1**
- → Role: foundational method (Lyapunov exponent estimation from short time series)
- → In Skill: `enhanced_cross_validate.py:62-68` (algorithm name mentioned but no formal citation), `docs/ALGORITHM_AUDIT.md`

**[B13]** **Fraser, A.M. & Swinney, H.L. (1986).** "Independent coordinates for strange attractors from mutual information." *Physical Review A*, 33(2), 1134-1140.
- → Rules: **S8** (indirectly — AMI for τ selection)
- → Role: foundational method (Average Mutual Information for optimal delay τ)
- → In Skill: `docs/ALGORITHM_AUDIT.md`

**[B14]** **Kennel, M.B., Brown, R., & Abarbanel, H.D.I. (1992).** "Determining embedding dimension for phase-space reconstruction using a geometrical construction." *Physical Review A*, 45(6), 3403-3411.
- → Rules: **S8** (indirectly — FNN for E selection)
- → Role: foundational method (False Nearest Neighbors method)
- → In Skill: `_numpy_edm.py:862-863`, `_edm_bridge.py:52,58`

---

# B. Pitfall Demonstration Papers (Rules 8-14)

These papers document specific failure modes of nonlinear dynamics methods.
They are the scientific basis for the "forbidden rules" framework.

## B1. Stationarity & Nonstationarity (Secret 8)

**[B15]** **Kantz, H. & Schreiber, T. (2004).** *Nonlinear Time Series Analysis*, 2nd Edition. Cambridge University Press.
- → Rules: **S8, S9, S12, S14**
- → Role: concept framework (the definitive textbook; Ch.3 on stationarity, Ch.7 on non-stationary extensions)
- → In Skill: `references/forbidden_rules_reference.md:31` (mentioned as "Kantz algorithm" only; full textbook not cited)

**[B16]** **Schreiber, T. (1997).** "Detecting and analyzing nonstationarity in a time series using nonlinear cross-predictions." *Physical Review Letters*, 78(5), 843-846.
- → Rules: **S8**
- → Role: pitfall demonstration / foundational method (cross-prediction nonstationarity test)
- → In Skill: NOT YET CITED

**[B17]** **Kennel, M.B. (1997).** "Statistical test for dynamical nonstationarity in observed time-series data." *Physical Review E*, 56(1), 316-321.
- → Rules: **S8**
- → Role: pitfall demonstration / foundational method (KS-test on neighbor-distance distributions)
- → In Skill: NOT YET CITED

**[B18]** **Dickey, D.A. & Fuller, W.A. (1979).** "Distribution of the estimators for autoregressive time series with a unit root." *Journal of the American Statistical Association*, 74(366), 427-431.
- → Rules: **S8**
- → Role: statistical method (Augmented Dickey-Fuller test — unit root detection)
- → In Skill: NOT YET CITED

**[B19]** **Kwiatkowski, D., Phillips, P.C.B., Schmidt, P., & Shin, Y. (1992).** "Testing the null hypothesis of stationarity against the alternative of a unit root." *Journal of Econometrics*, 54(1-3), 159-178.
- → Rules: **S8**
- → Role: statistical method (KPSS test — stationarity as H₀, complementary to ADF)
- → In Skill: NOT YET CITED

**[B20]** **Eckmann, J.-P. & Ruelle, D. (1985).** "Ergodic theory of chaos and strange attractors." *Reviews of Modern Physics*, 57(3), 617-656.
- → Rules: **S14, S8**
- → Role: concept framework (N_min ~ 10^d for attractor reconstruction; ergodic sampling requirements)
- → In Skill: NOT YET CITED

## B2. CCM Pitfalls — Seasonality, Common Drivers, Multiple Comparisons (Secrets 10, 11, 13)

**[B21]** **Cobey, S. & Baskerville, E.B. (2016).** "Limits to causal inference with state-space reconstruction." *Nature Communications*, 7, 12891.
- → Rules: **S10**
- → Role: pitfall demonstration (periodic external forcing induces spurious CCM convergence)
- → In Skill: `SKILL.md:228,284`, `references/edge_cases_reference.md:51`, `docs/thresholds_and_heuristics.md:18`

**[B22]** **McCracken, J.M. & Weigel, R.S. (2014).** "Convergent cross-mapping and pairwise asymmetric inference." *Physical Review E*, 90(6), 062903.
- → Rules: **S10**
- → Role: pitfall demonstration (earlier identification of periodic-forcing confound; proposed de-seasonalize-and-re-CCM control)
- → In Skill: NOT YET CITED

**[B23]** **Mønster, D., Fusaroli, R., Tylén, K., Roepstorff, A., & Sherson, J.F. (2017).** "Causal inference from noisy time-series data — testing the Convergent Cross-Mapping algorithm in the presence of noise and external influence." *Future Generation Computer Systems*, 73, 52-62.
- → Rules: **S10**
- → Role: pitfall demonstration (systematic false-positive-rate curves for CCM under periodic forcing + noise)
- → In Skill: NOT YET CITED

**[B24]** **Cummins, B., Gedeon, T., & Spendlove, K. (2015).** "On the validity of convergent cross mapping." Unpublished manuscript, arXiv:1508.04882.
- → Rules: **S10**
- → Role: constructive critique (comprehensive analysis of CCM failure modes)
- → In Skill: NOT YET CITED

**[B25]** **Deyle, E.R., Maher, M.C., Hernandez, R.D., Basu, S., & Sugihara, G. (2016).** "Tracking and forecasting ecosystem interactions in real time." *Proceedings of the Royal Society B*, 283(1822), 20152258.
- → Rules: **S11**
- → Role: applied demonstration (CCM in real ecosystems with explicit mechanistic-interpretation caveats)
- → In Skill: NOT YET CITED

**[B26]** **Pearl, J. (2009).** *Causality: Models, Reasoning, and Inference*, 2nd Edition. Cambridge University Press.
- → Rules: **S11**
- → Role: concept framework (formal definition of unobserved confounding; §1.4: identifiability limits)
- → In Skill: NOT YET CITED

**[B27]** **Runge, J., Nowack, P., Kretschmer, M., Flaxman, S., & Sejdinovic, D. (2019).** "Detecting and quantifying causal associations in large nonlinear time series datasets." *Science Advances*, 5(11), eaau4996.
- → Rules: **S11, S13**
- → Role: constructive critique / alternative method (PCMCI — conditional-independence causal discovery with FDR control)
- → In Skill: NOT YET CITED

## B3. Prediction Decay & Determinism Testing (Secret 12)

**[B28]** **Farmer, J.D. & Sidorowich, J.J. (1987).** "Predicting chaotic time series." *Physical Review Letters*, 59(8), 845-848.
- → Rules: **S12**
- → Role: foundational method (first systematic study of prediction decay in chaotic systems)
- → In Skill: NOT YET CITED

**[B29]** **Casdagli, M. (1989).** "Nonlinear prediction of chaotic time series." *Physica D*, 35(3), 335-356.
- → Rules: **S12**
- → Role: foundational method (radial basis function prediction; three-class decay profile taxonomy)
- → In Skill: NOT YET CITED

**[B30]** **Kaplan, D.T. & Glass, L. (1992).** "Direct test for determinism in a time series." *Physical Review Letters*, 68(4), 427-430.
- → Rules: **S12**
- → Role: foundational method (δ-ε determinism test; geometrically related to prediction decay)
- → In Skill: NOT YET CITED

**[B31]** **Weigend, A.S. & Gershenfeld, N.A. (Eds.) (1994).** *Time Series Prediction: Forecasting the Future and Understanding the Past.* Addison-Wesley.
- → Rules: **S12**
- → Role: edited volume (multi-author; Ch.1 & 7 on decay-profile classification)
- → In Skill: NOT YET CITED

## B4. Multiple Comparison & Surrogate Methods (Secret 13)

**[B32]** **Benjamini, Y. & Hochberg, Y. (1995).** "Controlling the false discovery rate: a practical and powerful approach to multiple testing." *Journal of the Royal Statistical Society, Series B*, 57(1), 289-300.
- → Rules: **S13**
- → Role: statistical method (False Discovery Rate control — preferred for exploratory CCM scans)
- → In Skill: NOT YET CITED

**[B33]** **Bonferroni, C.E. (1936).** "Teoria statistica delle classi e calcolo delle probabilità." *Pubblicazioni del R Istituto Superiore di Scienze Economiche e Commerciali di Firenze*, 8, 3-62.
- → Rules: **S13**
- → Role: statistical method (classical multiple-comparison correction; α/K for confirmatory analyses)
- → In Skill: NOT YET CITED (implicit in any α-based test but not cited)

**[B34]** **Vejmelka, M., Paluš, M., & Šušmáková, K. (2009).** "Non-random correlation structures and dimensionality reduction in multivariate climate data." *Climate Dynamics*, 33(5), 591-602.
- → Rules: **S13**
- → Role: applied demonstration (systematic false-positive inflation without correction in nonlinear dependence testing)
- → In Skill: NOT YET CITED

**[B35]** **Theiler, J., Eubank, S., Longtin, A., Galdrikian, B., & Farmer, J.D. (1992).** "Testing for nonlinearity in time series: the method of surrogate data." *Physica D*, 58(1-4), 77-94.
- → Rules: **S6, S13** (indirectly — surrogates for significance testing)
- → Role: foundational method (surrogate data testing)
- → In Skill: `SKILL.md:282`, `docs/ALGORITHM_AUDIT.md`

**[B36]** **Schreiber, T. & Schmitz, A. (2000).** "Surrogate time series." *Physica D*, 142(3-4), 346-382.
- → Rules: **S6, S10**
- → Role: foundational method (IAAFT surrogate generation algorithm)
- → In Skill: `surrogate_test.py:37`, `docs/ALGORITHM_AUDIT.md`, `docs/ALGORITHM_AUDIT.md`

**[B37]** **Theiler, J. & Prichard, D. (1996).** "Constrained-realization Monte-Carlo method for hypothesis testing." *Physica D*, 94(4), 221-235.
- → Rules: **S6** (end-point matching for IAAFT)
- → Role: statistical method (end-point matching prevents FFT periodicity artifact in surrogate generation)
- → In Skill: `docs/CHANGELOG.md` (end-point matching fix documented; paper not formally cited)

## B5. Sampling Adequacy (Secret 14)

**[B38]** **Broomhead, D.S. & King, G.P. (1986).** "Extracting qualitative dynamics from experimental data." *Physica D*, 20(2-3), 217-236.
- → Rules: **S14**
- → Role: foundational method (SSA as partial remedy for undersampled data; cannot recover un-sampled information)
- → In Skill: NOT YET CITED

**[B39]** **Gibson, J.F., Farmer, J.D., Casdagli, M., & Eubank, S. (1992).** "An analytic approach to practical state space reconstruction." *Physica D*, 57(1-2), 1-30.
- → Rules: **S14**
- → Role: foundational method (analytical derivation of optimal sampling rates for state-space reconstruction)
- → In Skill: NOT YET CITED

---

# C. Cross-Reference Index

## By Rule

| Rule | Primary Papers | Supporting Papers |
|------|---------------|-------------------|
| **S1** Lyapunov Horizon | B12 (Rosenstein 1993) | B06 (Sugihara & May 1990) |
| **S2** CCM Victim Mirror | B08 (Sugihara et al. 2012) | B37 (Theiler & Prichard 1996) |
| **S3** Hankel Golden Ratio | B10 (Brunton et al. 2017) | B11 (Gavish & Donoho 2014) |
| **S4** Multiview Embedding | B09 (Sugihara et al. 2016) | B01 (Takens 1981), B02 (Packard et al. 1980) |
| **S5** SVD Residual Monitor | B10 (Brunton et al. 2017) | B11 (Gavish & Donoho 2014) |
| **S6** EDM-HAVOK Cross-Validation | B06 (Sugihara & May 1990), B07 (Sugihara 1994), B10 | B35 (Theiler et al. 1992), B36 (Schreiber & Schmitz 2000), B37 |
| **S7** CCM Arrow Trap | B08 (Sugihara et al. 2012) | — |
| **S8** Stationarity Gate | B15 (Kantz & Schreiber 2004), B16 (Schreiber 1997), B17 (Kennel 1997) | B18 (Dickey-Fuller 1979), B19 (KPSS 1992), B20 (Eckmann-Ruelle 1985) |
| **S9** Observation Genericity | B01 (Takens 1981), B03 (Sauer et al. 1991), B05 (Letellier et al. 2005) | B02 (Packard et al. 1980) |
| **S10** Seasonality Confound | B21 (Cobey & Baskerville 2016) | B22 (McCracken & Weigel 2014), B23 (Mønster et al. 2017), B24 (Cummins et al. 2015) |
| **S11** Common Driver Disclaimer | B08 (Sugihara et al. 2012, Supp. Mat.), B26 (Pearl 2009) | B25 (Deyle et al. 2016), B27 (Runge et al. 2019) |
| **S12** Prediction Decay Profile | B28 (Farmer & Sidorowich 1987), B29 (Casdagli 1989) | B06 (Sugihara & May 1990), B30 (Kaplan & Glass 1992), B31 (Weigend & Gershenfeld 1994) |
| **S13** Multiple Comparison | B32 (Benjamini & Hochberg 1995), B33 (Bonferroni 1936) | B27 (Runge et al. 2019), B34 (Vejmelka et al. 2009) |
| **S14** Sampling Adequacy | B38 (Broomhead & King 1986), B39 (Gibson et al. 1992) | B04 (Abarbanel et al. 1993), B20 (Eckmann & Ruelle 1985) |

## By Citation Status in Current Skill

### Already Cited in Codebase (15 papers)
B01, B02, B06, B07, B08, B09, B10, B11, B12, B13, B14, B15, B21, B35, B36

### Partially / Informally Cited (2 papers)
B04 (via Kennel-Brown-Abarbanel 1992), B37 (end-point matching fix, no formal cite)

### NOT YET CITED — Implementation Gap (22 papers)
B03, B05, B16, B17, B18, B19, B20, B22, B23, B24, B25, B26, B27, B28, B29, B30, B31, B32, B33, B34, B38, B39

## By Implementation Priority

| Priority | Papers to Cite Now | Associated Rules |
|----------|-------------------|-----------------|
| **P0** (immediate) | B15, B16, B17, B18, B19 | S8 (Stationarity Gate) |
| **P1** (this iteration) | B21→B24 (already B21 done), B26, B03, B05 | S9, S10, S11 |
| **P2** (done) | B28, B29, B32, B33 | S12, S13 (已实现) |
| **P3** (future) | B38, B39, B20, B30, B31 | S14, S12 extended |

---

# D. Implementation Status Summary

| Rule | Adoption | Papers Cited | Papers Needed | New Module | Firewall Action |
|------|----------|-------------|---------------|------------|-----------------|
| S1 | 🔶 DEFERRED | 2/2 | — | — | WARN/FAIL |
| S2 | ✅ ADOPTED | 2/2 | — | — | WARN |
| S3 | ✅ ADOPTED | 2/2 | — | — | FAIL (p/q<3) |
| S4 | ✅ ADOPTED | 3/3 | — | — | Advisory |
| S5 | ✅ ADOPTED | 2/2 | — | — | FAIL (>2.5x) |
| S6 | ✅ ADOPTED | 5/5 | — | — | WARN |
| S7 | ✅ ADOPTED | 1/1 | — | — | WARN |
| **S8** | ✅ ADOPTED | 1/6 | B16-B19 | `audit_stationarity()` | WARN |
| **S9** | ✅ ADOPTED | 2/4 | B03, B05 | `audit_observation_genericity()` | WARN |
| **S10** | ✅ ADOPTED | 1/4 | B22-B24 | `audit_seasonality_confound()` | WARN |
| **S11** | ✅ ADOPTED | 1/4 | B25-B27 | (output language update) | Advisory |
| **S12** | ✅ ADOPTED | 0/4 | B28-B31 | `profile_prediction_decay()` | Advisory |
| **S13** | ✅ ADOPTED | 0/4 | B32-B34 | `ccm_batch_test()` | WARN |
| **S14** | ✅ ADOPTED | 0/4 | B38-B39 | `_check_sampling_adequacy()` | Advisory |

---

*End of bibliography. This file is the canonical citation authority for all fourteen
forbidden rules. When implementing a new rule, add its papers here first; when
adding a paper to the codebase, update its "In Skill" entry above.*
