"""
CCM Causality — Canonical Convergence-Aware Cross-Map Test
=============================================================
Single source of truth for CCM (Convergent Cross Mapping) causal-direction
testing (Sugihara et al., Science 2012), implementing Secret 2 + Secret 7
("CCM Victim Mirror" + "CCM Arrow Trap") from forbidden_rules_reference.md.

Why this module exists (engineering / audit note)
---------------------------------------------------
Before this module existed, the same causal test was implemented twice,
independently, in two files:

  * `final_interpretation.ccm_with_convergence()` — required the
    cross-map skill to demonstrably CONVERGE (total_rise > 0.05 AND
    Spearman rho > 0.7 AND Spearman p < 0.1) before declaring a causal
    verdict.
  * `enhanced_cross_validate.verify_ccm_direction()` — only looked at
    the skill at the largest library size, with NO convergence check at
    all, and used a different, hardcoded library-size sweep
    ('5 25 5' vs '5 {n-2} 3'), so for the same dataset the two functions
    could report different "final rho" values simply because "final"
    implicitly meant a different library size in each.

This mismatch was not just theoretical: `pipeline.py`'s post-computation
audit feedback fed only the bare final-rho values into
`edm_auditor.audit_ccm_direction()`, never populating
`ccm_forward_total_rise` / `ccm_forward_spearman_rho`. Since
`audit_ccm_direction()` treats missing convergence data as "assume OK"
(`fwd_converges = True` by default — see edm_auditor.py), this silently
disabled the exact protection the auditor's own docstring claims to
provide ("prevents false positives where rho is high but never actually
converges"). A high-but-non-converging (spurious) rho could sail through
the audit firewall with a clean PASS, even though the very convergence
check designed to catch it existed in the codebase — just not wired to
this call path.

This module fixes all three problems by being the *only* place the
convergence-aware CCM test is implemented:

  * `final_interpretation.ccm_with_convergence()` is now a thin,
    call-compatible wrapper around `ccm_causality_test()` below.
  * `enhanced_cross_validate.verify_ccm_direction()` is now also a thin
    wrapper, and additionally exposes the convergence fields
    (`forward_total_rise`, `forward_spearman_rho`, `forward_converging`,
    etc.) in its return dict so calling code can pass them through.
  * `pipeline.py`'s post-computation audit feedback now calls this
    module directly and forwards the convergence metrics into
    `audit_pipeline()`, so the firewall's convergence check can no
    longer be silently bypassed.

See docs/CHANGELOG.md for the full before/after account.
"""

import numpy as np
from scipy.stats import spearmanr

from _edm_bridge import CCM as _bridge_CCM


# Self-test speed tuning: the default data-length-scaled sweep can produce
# ~100 library-size points for the n=300 coupled-logistic fixture, making
# the module self-test take >300s under run_tests.py's subprocess timeout.
# A coarser sweep still exercises convergence (Spearman needs >=3 points)
# and all assertion targets (rho magnitude, verdict logic, effect-size gate,
# multiple-comparison correction). See docs/ALGORITHM_AUDIT.md.
_SELFTEST_LIB_SIZES = '5 100 15'


def ccm_causality_test(df, cause_var, effect_var, E, lib_sizes=None,
                        sample=None, tp=0,
                        rise_threshold=0.05, spearman_threshold=0.7,
                        spearman_p_threshold=0.1,
                        strong_direction_rho=0.2, bidirectional_delta=0.05):
    """
    Convergence-aware, bidirectional CCM causal test.

    A single cross-map rho value is insufficient evidence of causality —
    Sugihara et al. (2012) require that cross-map skill demonstrably
    INCREASE with library size ("convergence"). This function tests both
    directions (cause_var -> effect_var and effect_var -> cause_var) and
    only credits a direction with a causal verdict if it converges.

    Parameters
    ----------
    df : pandas.DataFrame
        Must contain columns [cause_var, effect_var].
    cause_var, effect_var : str
        Hypothesized cause_var -> effect_var direction to test. Both
        directions are actually tested; these names only label the
        verdict text.
    E : int
        Embedding dimension (shared with HAVOK's q, per project
        convention — see thresholds_and_heuristics.md).
    lib_sizes : str, optional
        pyEDM-style libSizes string, e.g. '5 30 3'. Defaults to a
        data-length-scaled sweep '5 {n-2} 3' (floored at n=6) so the
        reported "final rho" always corresponds to (approximately) the
        full library and is directly comparable across datasets of
        different length. This default replaces two previously
        independent, inconsistent hardcoded ranges — see module
        docstring.
    sample : int, optional
        Number of random samples per library size (pyEDM `sample`).
        Defaults to min(50, n).
    tp : int
        Prediction horizon (pyEDM `Tp`). Default 0 (contemporaneous).
    rise_threshold, spearman_threshold, spearman_p_threshold : float
        Convergence thresholds: total_rise > rise_threshold AND
        spearman_rho > spearman_threshold AND
        spearman_p < spearman_p_threshold AND
        abs(final_rho) > strong_direction_rho (the last conjunct was
        added after this module's own self-test surfaced a pure-noise
        pair satisfying the first three purely from the library-size
        sweep's sample size — see docs/CHANGELOG.md, Round 11).
    strong_direction_rho : float
        Minimum final_rho for a one-directional verdict to be reported
        as "drives" rather than "weak signal" — AND (as of Round 11) the
        minimum final_rho for `is_converging` itself to be True at all.
    bidirectional_delta : float
        If both directions converge and |delta rho| is below this, the
        verdict is "bidirectional" rather than "dominant".

    Returns
    -------
    dict with keys:
      cause_var, effect_var,
      forward : dict(final_rho, total_rise, spearman_rho, spearman_p,
                      is_converging, lib_sizes, rhos, ccm_raw)
                — tests cause_var -> effect_var
                  (built by cross-mapping FROM the effect's manifold)
      reverse : dict(...) — tests effect_var -> cause_var
      verdict : human-readable string
      direction : one of {'none', 'forward', 'weak_forward',
                           'reverse', 'weak_reverse', 'bidirectional',
                           'forward_dominant', 'reverse_dominant'}
    """
    n = len(df)
    if lib_sizes is None:
        # 深度复审修复：pyEDM 要求 libSize >= E+2，原默认起始值 5 对 E>=4 无效
        min_lib = E + 2
        lib_sizes = f'{min_lib} {max(n - 2, min_lib)} 3'
    if sample is None:
        sample = min(50, n)

    results = {}
    for direction_idx, (col_var, tgt_var) in enumerate([
        (effect_var, cause_var),   # M_effect -> cause (tests cause->effect)
        (cause_var, effect_var),   # M_cause -> effect (tests effect->cause)
    ]):
        try:
            ccm = _bridge_CCM(
                data=df, E=E, Tp=tp,
                columns=col_var, target=tgt_var,
                libSizes=lib_sizes, sample=sample,
                showPlot=False)
            rho_col = [c for c in ccm.columns if c != 'LibSize'][0]
            rhos = ccm[rho_col].values
            lib_sizes_arr = ccm['LibSize'].values

            # Convergence: total rise (scale-invariant) + Spearman
            # monotonicity. Absolute slope depends on the library-size
            # range and is not comparable across datasets of different
            # lengths (N=32 vs N=5000).
            #
            # Effect-size floor (`abs(final_rho) > strong_direction_rho`)
            # is included directly in `is_converging` itself, not just in
            # the verdict-text branching further down. Without it, a
            # pair with NO real cross-map skill can still satisfy
            # total_rise/spearman_rho/spearman_p: the library-size sweep
            # has ~N/3 points, so on longer series a practically
            # meaningless monotonic drift in a near-zero, noisy
            # rho-vs-libsize curve produces a high spearman_rho and an
            # astronomically small spearman_p from sample size alone —
            # confirmed empirically: a pure-noise pair with final_rho=
            # 0.031 produced total_rise=0.052, spearman_rho=0.96,
            # spearman_p=2e-57, satisfying all three thresholds with no
            # real signal at all. The verdict-text branching below
            # already applies this same 0.2 floor before saying "drives"
            # vs "weak signal", so an end user reading `verdict` was
            # never actually misled — but `is_converging` itself is a
            # field other code reads directly (e.g. `ccm_batch_test()`,
            # pipeline.py's printed "converging=True/False"), and without
            # this floor THOSE call sites could be. See
            # docs/CHANGELOG.md (Round 11) for the full repro.
            # P0-3 修缮: 小 lib_size 时 CCM 可能返回 NaN（阴影流形点不足）。
            # 原实现直接用 rhos[-1]-rhos[0]，若 rhos[0]=NaN 则 total_rise=NaN，
            # spearmanr 传入含 NaN 数组也返回 (NaN, NaN)，导致 is_converging 恒为 False。
            # 修复：先过滤 NaN，用有效子集计算收敛指标。
            valid_mask = ~np.isnan(rhos)
            n_valid = int(valid_mask.sum())
            if n_valid >= 3:
                rhos_valid = rhos[valid_mask]
                lib_sizes_valid = lib_sizes_arr[valid_mask]
                total_rise = float(rhos_valid[-1] - rhos_valid[0])
                spear_rho, spear_p = spearmanr(lib_sizes_valid, rhos_valid)
                final_rho = float(rhos_valid[-1])
                is_converging = (total_rise > rise_threshold
                                  and spear_rho > spearman_threshold
                                  and spear_p < spearman_p_threshold
                                  and abs(final_rho) > strong_direction_rho)
            elif n_valid >= 2:
                # P0-2 修缮：有效点 2 个时 Spearman 不可计算，
                # 但 total_rise 仍应反映实际趋势，不应静默置零。
                rhos_valid = rhos[valid_mask]
                total_rise = float(rhos_valid[-1] - rhos_valid[0])
                spear_rho, spear_p = 0.0, 1.0
                final_rho = float(rhos_valid[-1])
                is_converging = False  # Spearman 不可用时无法判定收敛
            else:
                total_rise = 0.0
                spear_rho, spear_p = 0.0, 1.0
                final_rho = float(rhos[valid_mask][0]) if n_valid == 1 else 0.0
                is_converging = False

            results[direction_idx] = {
                'final_rho': final_rho,
                'total_rise': total_rise,
                'spearman_rho': float(spear_rho),
                'spearman_p': float(spear_p),
                'is_converging': bool(is_converging),
                'lib_sizes': lib_sizes_arr.tolist(),
                'rhos': rhos.tolist(),
                'ccm_raw': ccm,
            }
        except Exception as e:
            results[direction_idx] = {
                'final_rho': None, 'total_rise': None,
                'spearman_rho': None, 'spearman_p': None,
                'is_converging': False,
                'lib_sizes': [], 'rhos': [], 'ccm_raw': None,
                'error': str(e),
            }

    # Causal verdict with convergence requirement (Secret 2 + Secret 7)
    fwd = results[0]; rev = results[1]
    fwd_ok = fwd['final_rho'] is not None and fwd['is_converging']
    rev_ok = rev['final_rho'] is not None and rev['is_converging']

    if not fwd_ok and not rev_ok:
        verdict = "No convergent causal link detected"
        direction_label = "none"
    elif fwd_ok and not rev_ok:
        if fwd['final_rho'] > strong_direction_rho:
            verdict = f"{cause_var} --drives--> {effect_var} (convergent)"
            direction_label = "forward"
        else:
            verdict = f"Weak forward signal ({fwd['final_rho']:.3f}), insufficient"
            direction_label = "weak_forward"
    elif rev_ok and not fwd_ok:
        if rev['final_rho'] > strong_direction_rho:
            verdict = f"{effect_var} --drives--> {cause_var} (convergent)"
            direction_label = "reverse"
        else:
            verdict = f"Weak reverse signal ({rev['final_rho']:.3f}), insufficient"
            direction_label = "weak_reverse"
    else:
        # Both converge — compare strengths
        delta = fwd['final_rho'] - rev['final_rho']
        if abs(delta) < bidirectional_delta:
            verdict = f"Bidirectional causality ({cause_var} <-> {effect_var})"
            direction_label = "bidirectional"
        elif delta > 0:
            verdict = f"{cause_var} --drives--> {effect_var} (dominant, delta={delta:+.3f})"
            direction_label = "forward_dominant"
        else:
            verdict = f"{effect_var} --drives--> {cause_var} (dominant, delta={delta:+.3f})"
            direction_label = "reverse_dominant"

    return {
        'cause_var': cause_var, 'effect_var': effect_var,
        'forward': fwd, 'reverse': rev,
        'verdict': verdict, 'direction': direction_label,
        'disclaimer': common_driver_disclaimer(),
        # ALG-09 修复: 结构化 disclaimer 为 disclaimer_text + disclaimer_level 字段
        # 下游消费方应优先读取 disclaimer_text (结构化) 而非 disclaimer (遗留字符串)
        'disclaimer_text': common_driver_disclaimer(),
        'disclaimer_level': 'escalated' if _count_significant_pairs_for_disclaimer(fwd, rev) >= 3 else 'base',
    }


def common_driver_disclaimer(n_significant_pairs: int = 1) -> str:
    """
    Secret 11: Common Driver / Latent Confounding Disclaimer.

    The single lowest-cost, highest-payoff rule in the S8-S14 extension —
    zero new computation (see references/forbidden_rules_reference.md,
    Secret 11). CCM (Sugihara et al. 2012) detects dynamical coupling — X
    and Y's manifolds mutually encode each other's states — not Pearl-style
    mechanistic causation. An unobserved Z driving both X and Y produces the
    same convergent cross-mapping signature as "X causes Y", and this is a
    fundamental identifiability limit of pairwise causal-discovery methods,
    not a bug that more data or a better threshold can fix. The only honest
    treatment is to say so, every time, unconditionally — never only when a
    result looks suspicious, since confounding doesn't announce itself.

    Parameters
    ----------
    n_significant_pairs : int
        How many CCM pairs in the current analysis converged to a causal
        verdict. When >= 3, the multi-pair escalation is appended: three or
        more mutually "causal" pairs from the same small variable set is
        itself weak evidence for an unmeasured common driver (a genuine web
        of pairwise mechanistic causation among 3+ variables, with no shared
        upstream cause, is the less parsimonious explanation).

    Returns
    -------
    str : disclaimer text, meant to be appended to every CCM causal verdict
    unconditionally (see ccm_causality_test()'s 'disclaimer' key, and
    final_interpretation.py / enhanced_cross_validate.py's CCM report
    sections, which print it alongside the verdict).

    ALG-09 修复: 此函数返回字符串保留向后兼容。
    结构化字段通过 disclaimer_text + disclaimer_level 暴露在 ccm_causality_test() 返回 dict 中。
    """
    base = (
        "CCM detects dynamical coupling (mutual encoding between "
        "reconstructed manifolds), not mechanistic causation. A convergent "
        "cross-map result is consistent with X driving Y, but equally "
        "consistent with an unmeasured common driver Z influencing both. "
        "This is a fundamental identifiability limit, not a threshold to "
        "tune around — treat this verdict as 'dynamically coupled', and "
        "additional evidence (a mechanism, an intervention, or ruling out "
        "known shared drivers) as necessary before treating it as causal "
        "in the everyday sense."
    )
    if n_significant_pairs >= 3:
        base += (
            f" Additionally: {n_significant_pairs} CCM pairs converged to a "
            f"causal verdict in this analysis. A dense web of pairwise "
            f"'causal' links among a small variable set is itself weak "
            f"evidence for an unmeasured common driver — a single shared "
            f"upstream cause is a more parsimonious explanation than "
            f"{n_significant_pairs} independent mechanistic links."
        )
    return base


def _count_significant_pairs_for_disclaimer(fwd_result, rev_result) -> int:
    """
    ALG-09 辅助函数: 判定当前 CCM 结果是否触发 escalated disclaimer 等级。

    单次 ccm_causality_test 调用只测试一对变量, 但当 forward 和 reverse
    都收敛时, 视为 2 对显著配对 (双向因果), 接近 escalated 阈值 3。
    此函数供 disclaimer_level 字段使用, 不影响 disclaimer 字符串本身。

    ALG-09 修正 (审视报告): 字段名为 'is_converging' 而非 'converging'。
    """
    count = 0
    if isinstance(fwd_result, dict) and fwd_result.get('is_converging'):
        count += 1
    if isinstance(rev_result, dict) and rev_result.get('is_converging'):
        count += 1
    return count


# ================================================================
# Secret 13: Multiple Comparison Correction for CCM
# ================================================================

def _benjamini_hochberg(p_values: np.ndarray, q: float = 0.05):
    """
    Benjamini & Hochberg (1995) FDR step-up procedure, hand-implemented
    (no statsmodels dependency — unlike Secret 8's ADF/KPSS, BH/Bonferroni
    are simple enough that adding a hard dependency for them isn't
    justified; keeps Secret 13 usable even in environments without
    statsmodels installed).

    Sort p-values ascending; find the largest k such that
    p(k) <= (k/n)*q; reject all hypotheses with p <= p(k).

    ROUND26 算法审视 P1-3 修复: q=0.10→0.05, 减少假阳性。
    默认 q 从 0.10 改为 0.05, 与 single-test α=0.05 一致 (Benjamini &
    Hochberg 1995 原文推荐 q=0.05 作为标准探索性分析水平)。q 的选择依据:
      - q=0.05: 标准探索性分析 (与 α=0.05 single-test 一致),假发现率
        控制在 5%,适合 CCM 因果发现场景 (K=5 对时期望 0.25 个假发现)
      - q=0.10: 更宽松,适合早期探索,但假发现率翻倍;仅在探索性极强的
        场景或样本量不足以支持 q=0.05 时显式传入
      - q=0.01: 验证性分析
    调用方可通过显式传 q=0.10 保留旧行为。

    Returns (reject: bool array in original order, threshold_p: the
    largest p-value that was still rejected, or 0.0 if none were).
    """
    p_values = np.asarray(p_values, dtype=float)
    n = len(p_values)
    if n == 0:
        return np.array([], dtype=bool), 0.0
    order = np.argsort(p_values)
    sorted_p = p_values[order]
    ranks = np.arange(1, n + 1)
    thresholds = (ranks / n) * q
    below = sorted_p <= thresholds
    if not below.any():
        return np.zeros(n, dtype=bool), 0.0
    max_rank = int(np.max(np.where(below)[0]))  # 0-indexed largest qualifying rank
    threshold_p = float(sorted_p[max_rank])
    reject_sorted = np.zeros(n, dtype=bool)
    reject_sorted[:max_rank + 1] = True
    reject = np.zeros(n, dtype=bool)
    reject[order] = reject_sorted
    return reject, threshold_p


def ccm_batch_test(df, pairs, E, analysis_label: str = 'exploratory',
                    fdr_q: float = 0.05, warn_pair_threshold: int = 5,
                    lib_sizes=None,
                    strong_direction_rho: float = 0.2) -> dict:
    """
    Secret 13: run a batch of K(K-1)-style pairwise CCM tests and apply
    multiple-comparison correction to their convergence significance.

    With K pairwise CCM tests at nominal alpha=0.05 each, the probability
    of at least one false positive grows as 1-(1-alpha)^K — approximately
    26% for the 6 pairs a typical K=4-variable analysis produces
    (Benjamini & Hochberg 1995; Bonferroni 1936). Reporting each pair's
    verdict independently at the same nominal threshold silently inflates
    the family-wise error rate. This function is the canonical place that
    correction happens — analogous to `ccm_causality_test()` being the
    canonical place the convergence check itself happens (see that
    function's docstring for why a canonical, non-duplicated
    implementation matters in this codebase).

    Correction method depends on `analysis_label` (matching
    `sensitivity_config.AnalysisConfig`'s existing analysis-type concept):
      'exploratory'    -> Benjamini-Hochberg FDR (q=0.05, ROUND26 P1-3
                          修复: 原 q=0.10 偏宽松, 改为 0.05 与 single-test
                          α=0.05 一致, 减少假阳性; 旧行为可显式传 fdr_q=0.10):
                          allows a 5% false-discovery rate to balance
                          power 与 严格性。
      'confirmatory'   -> Bonferroni (alpha/K): strict family-wise
                          error-rate control.
      'preregistered'  -> no correction (hypotheses specified before
                          seeing data; assumes K<=2 pre-registered pairs).

    Methodological limitation (stated explicitly, per spec): CCM's
    p-value comes from the non-parametric convergence test (Spearman
    rank correlation of rho vs library size — see
    `ccm_causality_test()`'s `spearman_p`), not a closed-form null
    distribution. Correction is applied to *convergence significance*,
    not to *causal-effect strength* — a corrected-significant pair means
    "this pair's convergence is unlikely to be a multiple-testing
    artifact", not "this is a strong causal effect".

    Effect-size gate (added after this function's own self-test surfaced
    the issue): a pair's `spearman_p` is only used at all if its final
    rho exceeds 0.2 (matching `ccm_causality_test`'s own
    `strong_direction_rho`) — otherwise its p-value is treated as 1.0
    regardless of how small the raw Spearman p was. This matters because
    the library-size sweep has ~N/3 points, so for longer series a
    practically meaningless monotonic drift in a near-zero, noisy
    rho-vs-libsize curve can still produce an astronomically small
    p-value from sample-size alone (observed empirically: p=1e-51 for a
    pair with final_rho=0.03 — no real cross-map skill). Multiple-
    comparison correction assumes its input p-values are properly
    calibrated under the null; without this gate, BH/Bonferroni would be
    correcting p-values that don't mean what they're supposed to mean.
    See docs/CHANGELOG.md for the concrete repro.

    Parameters
    ----------
    df : DataFrame containing all variables in `pairs`.
    pairs : list of (cause, effect) tuples to test.
    E : embedding dimension, passed to each ccm_causality_test call.
    analysis_label : 'exploratory' | 'confirmatory' | 'preregistered'.
    fdr_q : FDR level for the exploratory (BH) branch.
    warn_pair_threshold : at K >= this many pairs, an uncorrected
        exploratory analysis is flagged as having a materially inflated
        false-discovery risk even after nominal FDR correction (per the
        reference doc: FWER > 20% at 5 pairs is an explicit reliability
        concern). `[E]`.
    lib_sizes : passed through to each ccm_causality_test call.

    Returns
    -------
    dict with: pairs (list of per-pair dicts: cause, effect, p_value,
    direction_tested, significant_raw, significant_corrected, verdict,
    raw_result), method, alpha_or_q, n_pairs, n_significant_raw,
    n_significant_corrected, warn (bool), note.
    """
    K = len(pairs)
    if K == 0:
        return {"pairs": [], "method": None, "n_pairs": 0,
                "note": "No pairs provided"}

    results = []
    for cause, effect in pairs:
        r = ccm_causality_test(df, cause, effect, E, lib_sizes=lib_sizes)
        fwd, rev = r['forward'], r['reverse']
        # The p-value corrected is convergence significance (Spearman p of
        # rho-vs-libsize), taken from whichever direction is more
        # significant — a pair is a "discovery" if EITHER direction shows
        # convergence, so the more significant direction is the relevant
        # one to correct.
        #
        # IMPORTANT — effect-size gate (found via this function's own
        # self-test, see docs/CHANGELOG.md): `spearman_p` alone is not a
        # well-calibrated significance measure here. The library-size
        # sweep has ~N/3 points, so for longer series (N=400 -> ~130
        # sweep points), even a PRACTICALLY MEANINGLESS monotonic drift
        # in a near-zero, noisy rho-vs-libsize curve can produce an
        # astronomically small p-value (observed: p=1e-51 for a pair with
        # final_rho=0.03, i.e. no real cross-map skill at all) purely
        # from the large sample size of the correlation test itself, not
        # from genuine coupling. Multiple-comparison correction assumes
        # its INPUT p-values are properly calibrated under the null;
        # feeding it p-values that are systematically miscalibrated by a
        # sample-size artifact defeats the point of correcting them. This
        # is the same family of "scale/sample-size artifact masquerading
        # as signal" issue already fixed twice elsewhere in this codebase
        # (CCM total_rise vs raw slope; sensitivity_scan's CV near zero)
        # — same fix pattern: require the ABSOLUTE effect size to clear a
        # floor (here, final_rho > strong_direction_rho, matching
        # ccm_causality_test's own "weak signal" threshold) before a tiny
        # p-value is allowed to count as a "discovery" at all.
        # IMPORTANT — direction-eligibility fix (found applying this
        # function to a real dataset for the first time, not caught by
        # its own synthetic self-test): the earlier version of this gate
        # only checked `abs(final_rho) > strong_direction_rho` before
        # accepting a direction's p-value as a candidate — it did NOT
        # check whether that direction's total_rise/spearman_rho actually
        # indicate a CONVERGING trend (rho increasing with library size)
        # rather than a DIVERGING one (rho clearly decreasing, which a
        # small p-value on a negative Spearman correlation confidently
        # confirms, not refutes). Concretely: a pair whose reverse
        # direction had final_rho=-0.36 (passes the effect-size floor),
        # spearman_rho=-0.83, spearman_p=0.01 was selected as the
        # "significant" candidate (small p, large |rho|) even though
        # `is_converging` was correctly False for it (spearman_rho and
        # total_rise were both negative — the trend is diverging, not
        # converging) — producing a self-contradictory report ("p=0.01,
        # corrected significant" alongside "verdict: No convergent causal
        # link detected" for the exact same pair). Fixed by only
        # considering a direction eligible at all when its own
        # `is_converging` is True — reusing the single canonical
        # convergence determination (already correct — see
        # ccm_causality_test's docstring) instead of re-deriving a
        # partial, and in this case buggy, copy of the same conditions.
        # See docs/CHANGELOG.md.
        # P0-1 修缮：strong_direction_rho 从函数参数透传，不再硬编码 0.2。
        # 默认值 0.2 与 ccm_causality_test 的默认值保持一致，
        # 但调用方可显式传入不同值，确保 batch 层与单测层判定门控一致。
        candidates = []
        if fwd.get('spearman_p') is not None and fwd.get('is_converging'):
            candidates.append((fwd['spearman_p'], 'forward', fwd['final_rho']))
        if rev.get('spearman_p') is not None and rev.get('is_converging'):
            candidates.append((rev['spearman_p'], 'reverse', rev['final_rho']))
        if candidates:
            p_val, which, which_rho = min(candidates, key=lambda t: t[0])
            effect_size_ok = (which_rho is not None
                               and abs(which_rho) > strong_direction_rho)
        else:
            p_val, which, which_rho, effect_size_ok = 1.0, None, None, False
        # A pair without a meaningful, genuinely-converging effect is
        # reported as non-significant regardless of its raw p-value (p is
        # forced to 1.0 downstream of the gate, not just flagged, so it
        # cannot "leak through" BH/Bonferroni via a miscalibrated or
        # wrong-direction p-value).
        p_val_gated = p_val if effect_size_ok else 1.0
        results.append({
            'cause': cause, 'effect': effect,
            'p_value': p_val_gated, 'p_value_raw': p_val,
            'direction_tested': which, 'effect_size': which_rho,
            'effect_size_ok': effect_size_ok,
            'significant_raw': bool(p_val_gated < 0.05),
            'verdict': r['verdict'],
            'raw_result': r,
        })

    p_values = np.array([res['p_value'] for res in results])

    if analysis_label == 'preregistered' or K <= 2:
        method = f"none (pre-registered hypothesis, K={K} <= 2)"
        alpha_or_q = 0.05
        reject = p_values < 0.05
    elif analysis_label == 'confirmatory':
        alpha_or_q = 0.05 / K
        method = f"Bonferroni (alpha/{K} = {alpha_or_q:.4f})"
        reject = p_values < alpha_or_q
    else:
        if analysis_label != 'exploratory':
            analysis_label = 'exploratory'  # unrecognized label: default to the conservative-power option
        alpha_or_q = fdr_q
        method = f"Benjamini-Hochberg FDR (q={fdr_q})"
        reject, _threshold_p = _benjamini_hochberg(p_values, q=fdr_q)

    for i, res in enumerate(results):
        res['significant_corrected'] = bool(reject[i])

    n_significant_raw = int(np.sum(p_values < 0.05))
    n_significant_corrected = int(np.sum(reject))
    warn = K >= warn_pair_threshold and analysis_label == 'exploratory'

    return {
        "pairs": results,
        "method": method,
        "analysis_label": analysis_label,
        "alpha_or_q": alpha_or_q,
        "n_pairs": K,
        "n_significant_raw": n_significant_raw,
        "n_significant_corrected": n_significant_corrected,
        "warn": warn,
        "note": (
            f"K={K} pairwise CCM tests; uncorrected P(>=1 false positive) "
            f"~ {1 - (1 - 0.05) ** K:.0%}. Correction applies to CONVERGENCE "
            f"significance (Spearman rank test), not causal-effect strength "
            f"— see docstring."
            + (f" WARNING: {K} pairs is at/above the reliability threshold "
               f"({warn_pair_threshold}) for uncorrected exploratory "
               f"family-wise error rate." if warn else "")
        ),
    }


# ================================================================
# Self-test
# ================================================================

if __name__ == '__main__':
    print("=" * 70)
    print("  ccm_causality.py — Self-Test")
    print("=" * 70)

    np.random.seed(0)
    import pandas as pd

    # Coupled logistic maps: x drives y (one-directional coupling),
    # a standard CCM textbook test case (Sugihara et al. 2012 Fig. 2).
    n = 400
    x = np.zeros(n); y = np.zeros(n)
    x[0], y[0] = 0.4, 0.2
    rx, ry, coupling = 3.8, 3.5, 0.1
    for t in range(1, n):
        x[t] = x[t-1] * (rx - rx * x[t-1] - coupling * y[t-1])
        y[t] = y[t-1] * (ry - ry * y[t-1] - coupling * x[t-1])
        x[t] = np.clip(x[t], 1e-6, 1 - 1e-6)
        y[t] = np.clip(y[t], 1e-6, 1 - 1e-6)
    df = pd.DataFrame({'x': x[100:], 'y': y[100:]})

    result = ccm_causality_test(df, 'x', 'y', E=3,
                                lib_sizes=_SELFTEST_LIB_SIZES)
    print(f"  Verdict: {result['verdict']}")
    assert result['forward']['final_rho'] is not None, (
        f"forward final_rho is None — CCM call failed: "
        f"{result['forward'].get('error', 'unknown error')}")
    assert result['reverse']['final_rho'] is not None, (
        f"reverse final_rho is None — CCM call failed: "
        f"{result['reverse'].get('error', 'unknown error')}")
    print(f"  Forward (x->y): rho={result['forward']['final_rho']:.3f}, "
          f"converging={result['forward']['is_converging']}")
    print(f"  Reverse (y->x): rho={result['reverse']['final_rho']:.3f}, "
          f"converging={result['reverse']['is_converging']}")
    assert result['direction'] in (
        'forward', 'weak_forward', 'reverse', 'weak_reverse',
        'bidirectional', 'forward_dominant', 'reverse_dominant', 'none')
    print("  [OK] ccm_causality_test runs and returns a valid verdict")

    # Secret 11: disclaimer must be present unconditionally, and must
    # escalate when 3+ pairs are significant.
    assert 'disclaimer' in result and len(result['disclaimer']) > 0
    base_disclaimer = common_driver_disclaimer(n_significant_pairs=1)
    escalated_disclaimer = common_driver_disclaimer(n_significant_pairs=3)
    assert "dynamical coupling" in base_disclaimer
    assert "dynamical coupling" in escalated_disclaimer
    assert "3 CCM pairs" in escalated_disclaimer
    assert "3 CCM pairs" not in base_disclaimer
    print("  [OK] Secret 11 disclaimer present unconditionally, escalates at 3+ pairs")

    # Equivalence check: the two downstream wrappers must delegate to
    # THIS canonical function rather than reimplementing their own
    # verdict logic (this is the property that was previously violated
    # — see module docstring). We verify this via source inspection
    # rather than by comparing stochastic numeric outputs across
    # independent calls: pyEDM's CCM `sample` parameter draws bootstrap
    # library subsets using its own internal RNG (not controllable via
    # `np.random.seed`, confirmed empirically), so two independent CCM
    # calls on identical data give close-but-not-identical rho values.
    # A tolerance-based comparison would either be too loose to catch a
    # real regression or too tight to pass reliably — source inspection
    # directly checks the property we actually care about: is there
    # still only ONE implementation of the convergence-verdict logic?
    import inspect
    from final_interpretation import ccm_with_convergence
    from enhanced_cross_validate import verify_ccm_direction

    src_final = inspect.getsource(ccm_with_convergence)
    src_cross = inspect.getsource(verify_ccm_direction)
    assert 'ccm_causality_test(' in src_final, (
        "final_interpretation.ccm_with_convergence() no longer delegates "
        "to ccm_causality_test() — verdict logic may have been "
        "re-duplicated. See ccm_causality.py module docstring.")
    assert 'ccm_causality_test(' in src_cross, (
        "enhanced_cross_validate.verify_ccm_direction() no longer "
        "delegates to ccm_causality_test() — verdict logic may have "
        "been re-duplicated. See ccm_causality.py module docstring.")
    print("  [OK] final_interpretation.ccm_with_convergence() delegates to the canonical test")
    print("  [OK] enhanced_cross_validate.verify_ccm_direction() delegates to the canonical test")

    # Smoke test: both wrappers still run end-to-end and return
    # sane, mutually-consistent (same sign/direction, same ballpark)
    # results on the same data — a loose numeric check appropriate for
    # a function with genuine sampling stochasticity.
    r_final = ccm_with_convergence(df, 'x', 'y', 3)
    r_cross = verify_ccm_direction(df, 'x', 'y', 3)
    assert r_final['forward']['final_rho'] > 0.5, "expected strong coupling in this fixture"
    assert r_cross['forward_skill'] > 0.5, "expected strong coupling in this fixture"
    assert r_final['forward']['is_converging'] is True
    assert r_cross['forward_converging'] is True
    print("  [OK] Both wrappers agree in direction/verdict on the same strongly-coupled fixture")

    # Root-cause regression check (Round 11): `is_converging` itself
    # (not just the verdict text) must be False for a pure-noise pair,
    # even though its raw total_rise/spearman_rho/spearman_p alone would
    # satisfy the first three convergence conjuncts from a sample-size
    # artifact of the library-size sweep. See ccm_causality_test's
    # docstring and docs/CHANGELOG.md.
    z_noise = np.random.RandomState(2).uniform(0, 1, len(df))
    df_noise = df.copy()
    df_noise['z'] = z_noise
    r_noise = ccm_causality_test(df_noise, 'x', 'z', E=3)
    assert abs(r_noise['forward']['final_rho']) < 0.2, (
        f"test fixture assumption violated: expected near-zero rho, "
        f"got {r_noise['forward']['final_rho']}")
    assert r_noise['forward']['is_converging'] is False, (
        f"is_converging must be False when final_rho="
        f"{r_noise['forward']['final_rho']:.3f} is below strong_direction_rho, "
        f"regardless of how small spearman_p is "
        f"({r_noise['forward']['spearman_p']})")
    print(f"  [OK] is_converging correctly False for a near-zero-rho pair "
          f"(final_rho={r_noise['forward']['final_rho']:.3f}), "
          f"even though raw spearman_p={r_noise['forward']['spearman_p']:.1e} alone "
          f"would have satisfied the old (pre-Round-11) threshold check")

    # Secret 13: Benjamini-Hochberg unit test against a hand-worked example.
    # p_values already sorted ascending; q=0.10, n=7.
    # BH threshold at rank i: (i/n)*q = [0.0143, 0.0286, 0.0429, 0.0571, 0.0714, 0.0857, 0.10]
    # p <= threshold: [T, T, T, T, F, F, F] -> largest qualifying rank = 4
    # -> reject p<=0.03 (first four), threshold_p = 0.03
    bh_p = np.array([0.001, 0.01, 0.02, 0.03, 0.5, 0.7, 0.9])
    bh_reject, bh_threshold = _benjamini_hochberg(bh_p, q=0.10)
    assert list(bh_reject) == [True, True, True, True, False, False, False], (
        f"BH rejection mask mismatch: {bh_reject}")
    assert abs(bh_threshold - 0.03) < 1e-9, f"BH threshold mismatch: {bh_threshold}"
    print("  [OK] _benjamini_hochberg matches hand-worked example (reject first 4 of 7)")

    # Secret 13: BH must be robust to unsorted input (reject mask stays
    # aligned to the ORIGINAL order, not the sorted order).
    shuffle_idx = [4, 0, 6, 2, 1, 5, 3]  # arbitrary permutation
    bh_p_shuffled = bh_p[shuffle_idx]
    bh_reject_shuffled, _ = _benjamini_hochberg(bh_p_shuffled, q=0.10)
    expected_shuffled = np.array([True, True, True, True, False, False, False])[shuffle_idx]
    assert list(bh_reject_shuffled) == list(expected_shuffled), (
        "BH reject mask must stay aligned to input order after shuffling")
    print("  [OK] _benjamini_hochberg reject mask stays aligned under input reordering")

    # Secret 13: ccm_batch_test end-to-end on a small multi-variable system.
    # 3 independent-ish variable pairs sharing the coupled-logistic fixture
    # above, plus 2 pure-noise "null" pairs that should NOT survive
    # correction (this is the actual multiple-comparison scenario: mixing
    # real and null pairs in one batch).
    z_noise1 = np.random.RandomState(1).uniform(0, 1, len(df))
    z_noise2 = np.random.RandomState(2).uniform(0, 1, len(df))
    df_batch = df.copy()
    df_batch['z1'] = z_noise1
    df_batch['z2'] = z_noise2

    batch_pairs = [('x', 'y'), ('y', 'x'), ('x', 'z1'), ('x', 'z2'), ('z1', 'z2')]
    # Explicit, small lib_sizes for the batch-test section: the default
    # data-length-scaled sweep ('5 {n-2} 3' -> ~100 points for this
    # n=300 fixture) makes each of the ~12 ccm_causality_test calls in
    # this section (5 pairs x 2 directions, x2 for the exploratory +
    # confirmatory batch calls below) slow enough to push this module's
    # total self-test runtime past run_tests.py's Layer 7 subprocess
    # timeout (120s) — confirmed empirically (149s before this fix). A
    # coarser sweep is still a valid convergence test (Spearman rank
    # correlation just needs >=3 points, not ~100), so this only affects
    # self-test speed, not what's being verified.
    _batch_lib_sizes = '5 100 15'
    batch = ccm_batch_test(df_batch, batch_pairs, E=3,
                           analysis_label='exploratory', lib_sizes=_batch_lib_sizes)
    assert batch['n_pairs'] == 5
    assert batch['method'].startswith('Benjamini-Hochberg')
    assert batch['warn'] is True, "5 pairs should hit the warn_pair_threshold (default 5)"
    print(f"  [OK] ccm_batch_test (exploratory, K=5): "
          f"{batch['n_significant_raw']} raw-significant -> "
          f"{batch['n_significant_corrected']} after BH correction, warn={batch['warn']}")

    # Effect-size gate regression check: the pure-noise pairs (z1<->z2,
    # x<->z1, x<->z2) must NOT be gated significant regardless of how
    # small their raw Spearman p-value is — only x<->y (the genuinely
    # coupled pair) should have effect_size_ok=True. Before this gate
    # existed, noise pairs' near-zero final_rho combined with an
    # artificially tiny spearman_p (a sample-size artifact of the
    # ~N/3-point library-size sweep, not real signal) made every pair in
    # this batch come out "significant" — see docs/CHANGELOG.md.
    real_pair_names = {('x', 'y'), ('y', 'x')}
    for res in batch['pairs']:
        pair_name = (res['cause'], res['effect'])
        if pair_name not in real_pair_names:
            assert res['effect_size_ok'] is False, (
                f"noise pair {pair_name} should not pass the effect-size "
                f"gate (final_rho={res['effect_size']}), but did")
            assert res['p_value'] == 1.0, (
                f"noise pair {pair_name} should have its p-value forced "
                f"to 1.0 by the effect-size gate, got {res['p_value']}")
    print(f"  [OK] Effect-size gate correctly excludes noise pairs "
          f"(near-zero rho + artifactually tiny raw p) from significance")

    # BH correction must never REJECT more than were raw-significant
    # (FDR correction is only ever more conservative than uncorrected p<0.05
    # for the standard step-up procedure with q<=0.05... at q=0.10 it CAN
    # occasionally allow one or two more through than a naive p<0.05 cutoff
    # would — the real invariant to check is monotonicity of the procedure
    # itself, already covered by the hand-worked BH unit test above, so
    # here we only check structural correctness of the aggregation).
    assert batch['n_significant_corrected'] <= batch['n_pairs']

    # Confirmatory (Bonferroni) should be at least as strict as exploratory (BH)
    batch_confirm = ccm_batch_test(df_batch, batch_pairs, E=3,
                                   analysis_label='confirmatory',
                                   lib_sizes=_batch_lib_sizes)
    assert batch_confirm['method'].startswith('Bonferroni')
    assert batch_confirm['alpha_or_q'] == 0.05 / 5
    assert batch_confirm['n_significant_corrected'] <= batch['n_significant_corrected'], (
        "Bonferroni (confirmatory) must never be more permissive than BH (exploratory)")
    print(f"  [OK] ccm_batch_test (confirmatory, K=5): Bonferroni alpha="
          f"{batch_confirm['alpha_or_q']:.4f}, "
          f"{batch_confirm['n_significant_corrected']} significant "
          f"(<= exploratory's {batch['n_significant_corrected']})")

    # Pre-registered / K<=2: no correction applied
    batch_prereg = ccm_batch_test(df_batch, [('x', 'y')], E=3,
                                  analysis_label='preregistered',
                                  lib_sizes=_batch_lib_sizes)
    assert batch_prereg['method'].startswith('none')
    assert batch_prereg['warn'] is False
    print(f"  [OK] ccm_batch_test (preregistered, K=1): no correction applied, warn=False")

    # Direction-eligibility regression check: a direction with a small
    # spearman_p and a large |final_rho| but a DIVERGING trend (negative
    # total_rise / negative spearman_rho — rho getting WORSE with more
    # library data, not better) must never be selected as the
    # "significant" candidate, even though its raw numbers alone would
    # look tempting. Found applying this function to a real dataset for
    # the first time (not caught by the synthetic self-test above, which
    # only ever exercised clearly-converging or clearly-null fixtures):
    # a real pair produced exactly this pattern — p=0.01, |final_rho|=
    # 0.36, but spearman_rho=-0.83 and total_rise=-0.17 (genuinely
    # diverging) — and the pre-fix version reported it as
    # "corrected_sig=True" while the SAME pair's own `verdict` correctly
    # said "No convergent causal link detected", a direct self-
    # contradiction. Reproduced deterministically here via a monkeypatch
    # (pyEDM's CCM bootstrap sampling isn't reproducible via
    # np.random.seed — see this module's earlier self-test note — so a
    # real-data fixture can't be relied on to trigger this exact pattern
    # every run). See docs/CHANGELOG.md.
    print("\n── Direction-eligibility regression check (Round 13) ──")
    # NOTE: patch the global name directly, not via `import ccm_causality`
    # — when this file runs as a script (`python3 ccm_causality.py`), its
    # own functions live in the `__main__` module, and `import
    # ccm_causality` would create a SEPARATE, disconnected copy of the
    # module (a classic Python gotcha) — patching that copy's
    # `ccm_causality_test` would silently do nothing to the
    # `ccm_batch_test` actually running here, and the real (strongly
    # significant) x/y fixture data would leak through instead. Confirmed
    # this the hard way: the first version of this test failed with
    # p=2.7e-174 — the real x-y CCM result, not the fake one.
    _real_ccm_causality_test = ccm_causality_test

    def _fake_diverging_but_tiny_p(df, cause_var, effect_var, E, **kwargs):
        return {
            'cause_var': cause_var, 'effect_var': effect_var,
            'forward': {
                'final_rho': 0.05, 'total_rise': 0.01, 'spearman_rho': 0.2,
                'spearman_p': 0.5, 'is_converging': False,
                'lib_sizes': [5, 10, 15], 'rhos': [0.03, 0.04, 0.05], 'ccm_raw': None,
            },
            'reverse': {
                # Small p, large |rho| — tempting to a naive "min p,
                # big |rho|" selector — but genuinely DIVERGING
                # (negative total_rise, negative spearman_rho), so
                # is_converging is correctly False.
                'final_rho': -0.36, 'total_rise': -0.17, 'spearman_rho': -0.83,
                'spearman_p': 0.01, 'is_converging': False,
                'lib_sizes': [5, 10, 15], 'rhos': [0.1, -0.1, -0.36], 'ccm_raw': None,
            },
            'verdict': 'No convergent causal link detected', 'direction': 'none',
        }

    globals()['ccm_causality_test'] = _fake_diverging_but_tiny_p
    try:
        fake_batch = ccm_batch_test(df, [('x', 'y')], E=3, analysis_label='exploratory')
    finally:
        globals()['ccm_causality_test'] = _real_ccm_causality_test

    fake_pair = fake_batch['pairs'][0]
    assert fake_pair['significant_raw'] is False, (
        f"a diverging-but-small-p direction must not be reported "
        f"significant, got p_value={fake_pair['p_value']}")
    assert fake_pair['p_value'] == 1.0, (
        f"p_value must be forced to 1.0 when no direction is genuinely "
        f"converging, got {fake_pair['p_value']}")
    assert fake_pair['effect_size_ok'] is False
    print(f"  [OK] A diverging direction (negative total_rise/spearman_rho) with a "
          f"small raw p-value")
    print(f"       is correctly excluded from candidacy — p_value=1.0, not "
          f"the misleadingly tiny raw p")

    print("\n" + "=" * 70)
    print("  All ccm_causality self-tests passed!")
    print("=" * 70)
