"""
Services — summary builder (debt-19).

Extracted from api.py. Builds the analysis summary dict that gets returned
to the frontend, and lightweight per-task summaries for history/compare.
"""
import json
import os
from typing import Optional

from core.locks import RESULTS_DIR
from services.file_management import _safe_task_path


def _build_summary(
    result,
    variables,
    original_target: Optional[str] = None,
    display_map: Optional[dict] = None,
    profile: Optional[dict] = None,
    project_name: Optional[str] = None,
    data_quality_warning: Optional[str] = None,
):
    summary = {
        "pipeline": "ok",
        "cross_validation": "ok",
        "interpretation": "ok",
        "warnings": [],
    }
    if original_target:
        summary["target_col"] = original_target
    if display_map:
        summary["column_mapping"] = display_map
    if project_name:
        summary["project_name"] = project_name
    if profile:
        summary["intensity"] = profile.get("level")
        summary["intensity_notes"] = profile.get("notes", [])
        summary["intensity_params"] = profile.get("params")
    if data_quality_warning:
        summary["data_quality_warning"] = data_quality_warning

    pipe = result.get("pipeline") or {}
    if pipe.get("error"):
        summary["pipeline"] = f"error: {pipe['error']}"
    cv = result.get("cross_validation") or {}
    if cv.get("error"):
        summary["cross_validation"] = f"error: {cv['error']}"
    interp = result.get("interpretation") or {}
    if interp.get("error"):
        summary["interpretation"] = f"error: {interp['error']}"

    # Pull HAVOK diagnostics if available
    # P0 fix: 当 HAVOK 退化（近常量信号、样本量不足）时 eigenvalues_d_
    # 为空数组，max(abs(...)) 会抛 ValueError(max of empty sequence)。
    # 之前 pipeline.py 中已通过 _havok_skip_eigen 跳过打印，但 summary
    # 仍然无条件访问 eigenvalues_d_，导致整个任务崩溃为 KeyError。
    havok = pipe.get("havok")
    if havok:
        import numpy as np
        from sovereign_havok import classify_havok_stability
        _eig = getattr(havok, 'eigenvalues_d_', None)
        _is_degenerate = bool(getattr(havok, 'is_degenerate_', False))
        if _eig is not None and len(_eig) > 0 and not _is_degenerate:
            max_ev = float(np.max(np.abs(_eig)))
            stab_tier = classify_havok_stability(max_ev)
        else:
            # 退化或空特征值：标记为 N/A，不再崩溃
            max_ev = None
            stab_tier = "N/A (degenerate HAVOK — insufficient or near-constant data)"
        summary["havok"] = {
            "rank": int(havok.r_),
            "explained_variance": float(havok.explained_var_),
            "regression_r2": float(havok.regression_r2_),
            "kurtosis": float(havok.kurtosis_vr_),
            "max_eigenvalue": max_ev,
            "stability_tier": stab_tier,
            "sampling_adequacy": getattr(havok, "sampling_adequacy_", None),
            "is_degenerate": _is_degenerate,
        }

    # Per-variable EDM skill metrics from cross-validation
    if isinstance(cv, dict) and "error" not in cv:
        edmtakens_vars = {}
        for var, r in cv.items():
            if not isinstance(r, dict):
                continue
            edm = r.get("edm") or {}
            if "rho_simplex" not in edm:
                continue
            display_name = display_map.get(var, var) if display_map else var
            edmtakens_vars[display_name] = {
                "rho_simplex": (
                    float(edm["rho_simplex"]) if edm["rho_simplex"] is not None else None
                ),
                "rho_smap_max": (
                    float(edm["rho_smap_max"]) if edm.get("rho_smap_max") is not None else None
                ),
                "theta_best": (
                    float(edm["theta_best"]) if edm.get("theta_best") is not None else None
                ),
                "is_nonlinear": bool(edm.get("is_nonlinear")),
            }
        if edmtakens_vars:
            summary["variables"] = edmtakens_vars

    # CCM p-values and corrected significance counts from pipeline batch test
    # S1-4 修复 (科研披露落地 Round 28): 透传 4 个科研披露字段到前端:
    #   - is_strict_confirmatory (批次级): BH uniform-null 假设披露
    #   - methodology_disclaimer (批次级): 方法学免责声明
    #   - effective_lib_sizes (每对): out-of-sample 模式下的实际建树库大小
    #   - out_of_sample_used (每对): 是否启用 out-of-sample 评估
    # 这些字段让科研用户能区分:
    #   confirmatory  -> "FDR-controlled at q=0.05 (IAAFT null, Bonferroni-corrected)"
    #   exploratory   -> "Exploratory FDR estimate (effect-size gated Spearman, BH)"
    # 以及收敛曲线 x 轴语义:
    #   out_of_sample_used=True  -> "ρ vs effective library size (train split)"
    #   out_of_sample_used=False -> "ρ vs library size (in-sample)"
    pipe_dict = pipe if isinstance(pipe, dict) else {}
    ccm_batch = pipe_dict.get("ccm_batch")
    if isinstance(ccm_batch, dict):
        ccm_pairs_summary = []
        for p in ccm_batch.get("pairs", []):
            raw = p.get("raw_result") or {}
            fwd = raw.get("forward") or {}
            ccm_pairs_summary.append({
                "cause": p.get("cause"),
                "effect": p.get("effect"),
                "p_value": p.get("p_value"),
                "significant_corrected": p.get("significant_corrected"),
                "lib_sizes": fwd.get("lib_sizes", []),
                "rhos": fwd.get("rhos", []),
                "final_rho": fwd.get("final_rho"),
                "total_rise": fwd.get("total_rise"),
                "spearman_rho": fwd.get("spearman_rho"),
                "is_converging": fwd.get("is_converging"),
                "verdict": p.get("verdict"),
                # S1-4 修复: 透传 effective_lib_sizes 和 out_of_sample_used
                # out-of-sample 模式下 effective_lib_sizes = lib_sizes // 2,
                # 收敛曲线的 x 轴语义已改变. 前端必须据此选择措辞.
                "effective_lib_sizes": fwd.get("effective_lib_sizes", fwd.get("lib_sizes", [])),
                "out_of_sample_used": bool(fwd.get("out_of_sample_used", False)),
            })
        summary["ccm"] = {
            "n_pairs": ccm_batch.get("n_pairs"),
            "n_significant_raw": ccm_batch.get("n_significant_raw"),
            "n_significant_corrected": ccm_batch.get("n_significant_corrected"),
            "method": ccm_batch.get("method"),
            "pairs": ccm_pairs_summary,
            # S1-4 修复: 批次级科研披露字段
            # is_strict_confirmatory=True 当且仅当 use_surrogate_p=True +
            # analysis_label in {'confirmatory', 'preregistered'}.
            # 前端据此选择措辞:
            #   True  -> "FDR-controlled at q=0.05 (IAAFT null, Bonferroni-corrected)"
            #   False -> "Exploratory FDR estimate (effect-size gated Spearman, BH)"
            "is_strict_confirmatory": bool(ccm_batch.get("is_strict_confirmatory", False)),
            "methodology_disclaimer": ccm_batch.get("methodology_disclaimer"),
        }

    # P1 修复项 4：暴露 post-audit verdict 给前端。
    # P0 fix (Round 23 §续): AuditReport.warnings/failures 是整数计数器而非消息列表,
    # 真正的消息在 findings 里。暴露计数 + 消息列表双字段, 避免下游误迭代整数。
    post_audit_obj = pipe_dict.get("post_audit")
    if post_audit_obj is not None:
        summary["post_audit_verdict"] = getattr(post_audit_obj, "verdict", None)
        summary["post_audit_passed"] = getattr(post_audit_obj, "passed", None)
        summary["post_audit_warning_count"] = int(getattr(post_audit_obj, "warnings", 0) or 0)
        summary["post_audit_failure_count"] = int(getattr(post_audit_obj, "failures", 0) or 0)
        # 从 findings 提取实际消息 (只取 WARN/FAIL 状态的)
        findings = getattr(post_audit_obj, "findings", []) or []
        warn_msgs = []
        fail_msgs = []
        for f in findings:
            status = getattr(f, "status", "")
            msg = getattr(f, "message", "")
            secret = getattr(f, "secret_ref", "")
            entry = f"[{secret}] {msg}" if secret else msg
            if status == "WARN":
                warn_msgs.append(entry)
            elif status == "FAIL":
                fail_msgs.append(entry)
        summary["post_audit_warnings"] = warn_msgs
        summary["post_audit_failures"] = fail_msgs

    # Pull interpretation key takeaways if available
    if isinstance(interp, dict):
        for key in ["stability_tier", "heavy_tailed_variables", "n_ccm_significant"]:
            if key in interp:
                summary[key] = interp[key]
        # P1 修复 (Round 24 §1): 暴露更多解释数据供人话版报告使用.
        # 此前仅提取 3 个字段, 导致 markdown 报告缺失 "图谱解析" 章节
        # (无法解读 dynamics_interpretation.png) 以及李雅普诺夫/变量分析.
        for key in [
            "lyapunov_reliable_variables",
            "available_variables",
            "skipped_variables",
            "unit",
            "n_samples",
        ]:
            if key in interp:
                summary[key] = interp[key]
        # ccm_results 包含方向判定 (forward/reverse/bidirectional) — 比 ccm_batch
        # 中的 significant_corrected 更直观, 单独暴露供人话版报告使用.
        if "ccm_results" in interp and isinstance(interp["ccm_results"], list):
            summary["ccm_directions"] = [
                {
                    "cause": r.get("cause"),
                    "effect": r.get("effect"),
                    "direction": r.get("direction"),
                    "verdict": r.get("verdict"),
                }
                for r in interp["ccm_results"]
                if isinstance(r, dict)
            ]

    return summary


def _task_summary(task_id: str, task_dir: Optional[str] = None) -> Optional[dict]:
    """Build a lightweight summary for a task directory.

    若指定 ``task_dir``，则直接使用该路径（用于归档 zip 临时解压预览等场景）；
    否则从 ``RESULTS_DIR`` 下按 ``task_id`` 解析。返回的字典包含 config 与
    params 字段（分别来自 ``config_*.json`` 与 ``params_*.json``，文件不存在
    则对应字段为 None）。
    """
    if task_dir is None:
        task_dir = _safe_task_path(task_id, RESULTS_DIR)
    if not task_dir or not os.path.isdir(task_dir):
        return None
    images = sorted(
        [f for f in os.listdir(task_dir) if f.lower().endswith((".png", ".jpg", ".jpeg"))],
        reverse=True,
    )
    config_files = [
        f for f in os.listdir(task_dir)
        if f.startswith("config_") and f.endswith(".json")
    ]
    config_path = os.path.join(task_dir, sorted(config_files)[-1]) if config_files else None
    config = None
    if config_path and os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception:
            config = None
    # 读取 params_*.json（与 config_*.json 同 timestamp 命名模式，不存在则 None）
    params_files = [
        f for f in os.listdir(task_dir)
        if f.startswith("params_") and f.endswith(".json")
    ]
    params = None
    if params_files:
        params_path = os.path.join(task_dir, sorted(params_files)[-1])
        try:
            with open(params_path, "r", encoding="utf-8") as f:
                params = json.load(f)
        except Exception:
            params = None
    return {
        "task_id": task_id,
        "updated_at": os.path.getmtime(task_dir),
        "images": images,
        "config": config,
        "params": params,
    }
