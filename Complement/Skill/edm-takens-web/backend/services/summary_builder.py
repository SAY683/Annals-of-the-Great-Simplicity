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
    havok = pipe.get("havok")
    if havok:
        import numpy as np
        from sovereign_havok import classify_havok_stability
        max_ev = float(max(abs(havok.eigenvalues_d_)))
        summary["havok"] = {
            "rank": int(havok.r_),
            "explained_variance": float(havok.explained_var_),
            "regression_r2": float(havok.regression_r2_),
            "kurtosis": float(havok.kurtosis_vr_),
            "max_eigenvalue": max_ev,
            "stability_tier": classify_havok_stability(max_ev),
            "sampling_adequacy": getattr(havok, "sampling_adequacy_", None),
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
            })
        summary["ccm"] = {
            "n_pairs": ccm_batch.get("n_pairs"),
            "n_significant_raw": ccm_batch.get("n_significant_raw"),
            "n_significant_corrected": ccm_batch.get("n_significant_corrected"),
            "method": ccm_batch.get("method"),
            "pairs": ccm_pairs_summary,
        }

    # P1 修复项 4：暴露 post-audit verdict 给前端。
    post_audit_obj = pipe_dict.get("post_audit")
    if post_audit_obj is not None:
        summary["post_audit_verdict"] = getattr(post_audit_obj, "verdict", None)
        summary["post_audit_passed"] = getattr(post_audit_obj, "passed", None)
        summary["post_audit_warnings"] = getattr(post_audit_obj, "warnings", None)
        summary["post_audit_failures"] = getattr(post_audit_obj, "failures", None)

    # Pull interpretation key takeaways if available
    if isinstance(interp, dict):
        for key in ["stability_tier", "heavy_tailed_variables", "n_ccm_significant"]:
            if key in interp:
                summary[key] = interp[key]

    return summary


def _task_summary(task_id: str) -> Optional[dict]:
    """Build a lightweight summary for a task directory."""
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
    return {
        "task_id": task_id,
        "updated_at": os.path.getmtime(task_dir),
        "images": images,
        "config": config,
    }
