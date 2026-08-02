# ALG-08: 新增独立pytest测试
"""
Router module — pytest suite.

Verifies src/router.py:
  - Data grading (DataGrade enum) across N / regularity / SNR combinations
  - Goal-driven step selection (predict / detect_nl / causal / phase / explore)
  - Parameter passing through RouteStep.args
  - Blocker / warning generation for problematic inputs
  - Plan serialization (to_dict) and error handling
"""
import os
import sys

import pytest

_SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SKILL_SRC = os.path.join(_SKILL_ROOT, 'src')
sys.path.insert(0, _SKILL_SRC)

from router import (
    Router,
    quick_route,
    route_and_execute,
    DataGrade,
    AnalysisGoal,
    AnalysisLabel,
    RouteStep,
    AnalysisPlan,
    NotAutoExecutableError,
    _call_step,
    _resolve_step_callable,
)


# ── Q1: Data grading ─────────────────────────────────────

def test_grade_inadequate_below_min_samples():
    """N < 20 应被分级为 INADEQUATE 并产生 blocker。"""
    plan = quick_route(n_samples=15)
    assert plan.data_grade == DataGrade.INADEQUATE
    assert len(plan.blocks) >= 1
    assert any('Bayesian' in b or 'minimum' in b.lower() for b in plan.blocks)


def test_grade_marginal_irregular_sampling():
    """不规则采样应被降级为 MARGINAL（即使 N 较大）。"""
    plan = quick_route(n_samples=200, is_regular=False)
    assert plan.data_grade == DataGrade.MARGINAL


def test_grade_marginal_low_snr():
    """低 SNR 应被降级为 MARGINAL。"""
    plan = quick_route(n_samples=200, snr_estimate="low")
    assert plan.data_grade == DataGrade.MARGINAL


def test_grade_adequate_mid_samples():
    """N 在 [50, 100) 且 SNR 正常应被分级为 ADEQUATE。"""
    plan = quick_route(n_samples=75, snr_estimate="moderate")
    assert plan.data_grade == DataGrade.ADEQUATE


def test_grade_excellent_large_clean():
    """N >= 100、规则采样、SNR 正常应被分级为 EXCELLENT。"""
    plan = quick_route(n_samples=500, is_regular=True, snr_estimate="high")
    assert plan.data_grade == DataGrade.EXCELLENT


# ── Q2: Goal-driven routing ──────────────────────────────

def test_goal_causal_includes_ccm_and_surrogate_steps():
    """goal=causal 且 N>=100、n_vars>=2 应包含 CCM 与 Surrogate 步骤。"""
    plan = quick_route(n_samples=100, n_variables=3, goal="causal")
    step_names = [s.name for s in plan.steps]
    assert any('CCM' in n for n in step_names), "causal 应包含 CCM 步骤"
    assert any('Surrogate' in n for n in step_names), "causal 应包含 Surrogate 步骤"


def test_goal_phase_includes_havok_step():
    """goal=phase 应包含 HAVOK 步骤。"""
    plan = quick_route(n_samples=200, n_variables=2, goal="phase")
    assert any('HAVOK' in s.name for s in plan.steps)


def test_goal_predict_blocks_on_marginal():
    """goal=predict 在 MARGINAL 数据上应产生 blocker。"""
    plan = quick_route(n_samples=40, is_regular=False, goal="predict")
    assert plan.data_grade == DataGrade.MARGINAL
    assert len(plan.blocks) >= 1
    assert any('Prediction' in b or 'predict' in b.lower() for b in plan.blocks)


def test_goal_unknown_falls_back_to_explore():
    """未知 goal 字符串应回退为 AnalysisGoal.EXPLORE。"""
    plan = quick_route(n_samples=100, goal="not_a_real_goal")
    assert plan.goal == AnalysisGoal.EXPLORE


def test_secret_13_triggers_multicomparison_step():
    """ccm_pairs >= 5 应触发多比较校正步骤（Secret 13）。"""
    plan = quick_route(n_samples=100, n_variables=8, goal="causal", ccm_pairs=6)
    assert any('Multi-Comparison' in s.name or '多比较' in s.name for s in plan.steps)


def test_secret_13_skipped_when_few_pairs():
    """ccm_pairs < 5 不应触发多比较校正步骤。"""
    plan = quick_route(n_samples=100, n_variables=2, goal="causal", ccm_pairs=2)
    assert not any('Multi-Comparison' in s.name for s in plan.steps)


# ── Q3: Parameter passing ────────────────────────────────

def test_step_args_carry_n_and_is_binary():
    """Configuration Audit 步骤的 args 应携带 n 与 is_binary。"""
    plan = quick_route(n_samples=60, n_variables=2, is_binary_target=True,
                       goal="explore")
    audit_steps = [s for s in plan.steps if 'Audit' in s.name]
    assert len(audit_steps) == 1
    assert audit_steps[0].args.get('n') == 60
    assert audit_steps[0].args.get('is_binary') is True


def test_surrogate_step_n_surrogates_depends_on_grade():
    """Surrogate 步骤的 n_surrogates 应随 data_grade 调整（EXCELLENT=99, 其他=19）。"""
    # EXCELLENT
    plan_excellent = quick_route(n_samples=200, n_variables=2, goal="detect_nl")
    surr_step_excellent = next(s for s in plan_excellent.steps if 'Surrogate' in s.name)
    assert surr_step_excellent.args.get('n_surrogates') == 99
    # MARGINAL (低 SNR)
    plan_marginal = quick_route(n_samples=200, snr_estimate="low",
                                n_variables=2, goal="detect_nl")
    surr_step_marginal = next(s for s in plan_marginal.steps if 'Surrogate' in s.name)
    assert surr_step_marginal.args.get('n_surrogates') == 19


def test_tau_step_only_when_n_ge_30():
    """Tau Optimization 步骤仅在 N >= 30 时出现。"""
    plan_small = quick_route(n_samples=25, goal="explore")
    assert not any('Tau' in s.name for s in plan_small.steps)
    plan_ok = quick_route(n_samples=50, goal="explore")
    assert any('Tau' in s.name for s in plan_ok.steps)


# ── Q4: Warnings & error handling ────────────────────────

def test_binary_target_triggers_warning():
    """is_binary_target=True 应在 warnings 中提示 rho 上限。"""
    plan = quick_route(n_samples=100, is_binary_target=True, goal="explore")
    assert any('Binary' in w or 'binary' in w.lower() for w in plan.warnings)


def test_no_preregistration_marks_exploratory():
    """无预注册应标记为 EXPLORATORY 并产生 warning。"""
    plan = quick_route(n_samples=100, has_preregistration=False)
    assert plan.label == AnalysisLabel.EXPLORATORY
    assert any('pre-registration' in w.lower() or 'exploratory' in w.lower()
               for w in plan.warnings)


def test_has_preregistration_marks_confirmatory():
    """有预注册应标记为 CONFIRMATORY 且不触发 exploratory warning。"""
    plan = quick_route(n_samples=100, has_preregistration=True)
    assert plan.label == AnalysisLabel.CONFIRMATORY
    assert not any('pre-registration' in w.lower() for w in plan.warnings)


def test_multiview_warning_when_many_vars_small_n():
    """n_vars >= 3 且 N < 100 应触发 Multiview embedding warning。"""
    plan = quick_route(n_samples=60, n_variables=4, goal="explore")
    assert any('Multiview' in w or 'multiview' in w.lower() for w in plan.warnings)


def test_phase_transition_warning_small_n():
    """goal=phase 且 N < 100 应触发相位转变检测的 warning。"""
    plan = quick_route(n_samples=60, n_variables=2, goal="phase")
    assert any('Phase transition' in w or 'phase' in w.lower() for w in plan.warnings)


# ── Q5: Plan serialization ───────────────────────────────

def test_plan_to_dict_contains_required_keys():
    """AnalysisPlan.to_dict() 应包含文档承诺的所有键。"""
    plan = quick_route(n_samples=100, n_variables=2, goal="explore")
    d = plan.to_dict()
    for key in ('data_grade', 'goal', 'label', 'steps', 'warnings', 'blocks',
                'timestamp'):
        assert key in d, f"to_dict 缺少键 {key}"
    assert isinstance(d['steps'], list)
    assert len(d['steps']) >= 1
    # 每步应包含 order/name/module/function/mandatory/rationale
    for step_dict in d['steps']:
        for k in ('order', 'name', 'module', 'function', 'mandatory', 'rationale'):
            assert k in step_dict, f"step 缺少键 {k}"


def test_plan_print_plan_does_not_raise(capsys):
    """AnalysisPlan.print_plan() 在多种场景下不应抛异常。"""
    plans = [
        quick_route(n_samples=15),  # INADEQUATE with blocks
        quick_route(n_samples=100, n_variables=2, goal="causal",
                    has_preregistration=True),
        quick_route(n_samples=60, is_binary_target=True, goal="explore"),
    ]
    for plan in plans:
        plan.print_plan()  # 不应抛异常
    captured = capsys.readouterr()
    assert 'ANALYSIS PLAN' in captured.out


# ── _call_step / NotAutoExecutableError ──────────────────

def test_call_step_injects_data_for_single_required_param():
    """函数只有一个必需位置参数时，_call_step 应将 data 注入。"""
    def _fn_single_required(arr, opt=1):
        return {'len': len(arr), 'opt': opt}
    data = [1.0, 2.0, 3.0]
    result = _call_step(_fn_single_required, data, {'opt': 7})
    assert result['len'] == 3
    assert result['opt'] == 7


def test_call_step_injects_data_keyword_when_all_optional():
    """所有参数可选但存在 data 关键字时，应通过 data= 注入。"""
    def _fn_all_optional(data=None, n=None):
        return {'has_data': data is not None, 'n': n}
    result = _call_step(_fn_all_optional, [1.0, 2.0], {'n': 5})
    assert result['has_data'] is True
    assert result['n'] == 5


def test_call_step_raises_not_auto_executable_when_needs_more():
    """需要多个必需参数（除 data 外）时应抛 NotAutoExecutableError。"""
    def _fn_needs_more(arr, target_col, k=3):
        return arr, target_col, k
    with pytest.raises(NotAutoExecutableError):
        _call_step(_fn_needs_more, [1.0, 2.0], {'k': 3})


def test_call_step_does_not_inject_data_into_unrelated_keyword():
    """无 data 关键字时不应将 data 注入其他参数。"""
    def _fn_no_data_kwarg(x=None, n=None):
        return {'x': x, 'n': n}
    result = _call_step(_fn_no_data_kwarg, [1.0, 2.0], {'n': 5})
    assert result['x'] is None
    assert result['n'] == 5
