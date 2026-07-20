"""
Layer 1: 元 SCM 参数流迹提取器
==============================
从 TRACE 引擎的 result.json 中提取系统诊断不变量（meta-SCM parameters）。

核心思想:
  不管文本内容是什么（外交、党建、经济、民生），TRACE 引擎输出的
  result.json 结构是恒定的。我们提取的不是"词汇频率"，而是"因果系统
  本身的调节参数"——这些参数在任何文本上都是对齐的。

提取的 20 个不变参数包括:
  - DoWhy 因果效应: ATE, CI, 可识别性, 反驳次数
  - 图结构: 节点数, 边数, 密度, 最强信号
  - 六战士: CCM 覆盖率, EDM 可预测性, HAVOK 线性度, causallearn 共识
  - 稳定性: 边稳定性, 置换检验 p 值
  - 执行: 总耗时

用法:
  from layer1_meta_scm import extract_meta_scm_params
  params = extract_meta_scm_params(result_json_path)
  # → { "ate": 28.13, "adj_density": 0.53, ... }
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional


def _deep_get(d: Dict, key_path: str, default: Any = None) -> Any:
    """
    用点号分隔的路径从嵌套字典中安全取值。
    例如: _deep_get(obj, "six_warriors.ccm.metrics.CCM_coverage")
    支持数组索引: _deep_get(obj, "confidence_interval[0]")

    鲁棒性:
      - 中间节点为 None → 返回 default
      - 中间节点为非 dict/list → 返回 default (而非崩溃)
      - 数组索引越界 → 返回 default
    """
    if d is None:
        return default

    parts = key_path.replace("[", ".").replace("]", "").split(".")
    current = d

    for part in parts:
        if part == "":
            continue
        if current is None:
            return default
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            try:
                idx = int(part)
                if 0 <= idx < len(current):
                    current = current[idx]
                else:
                    return default
            except (ValueError, IndexError):
                return default
        else:
            # 中间节点不是 dict 也不是 list (比如是字符串), 无法继续深入
            return default

    return current


def _safe_float(value: Any, default: float = 0.0) -> float:
    """安全转换为 float，处理百分比字符串如 '12.2%'"""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        value = value.strip().rstrip('%')
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _safe_int(value: Any, default: int = 0) -> int:
    """安全转换为 int"""
    if value is None:
        return default
    try:
        return int(float(str(value).strip().rstrip('%')))
    except (ValueError, TypeError):
        return default


def _safe_bool_to_int(value: Any) -> int:
    """bool → 1/0"""
    if value is True:
        return 1
    if value is False:
        return 0
    return 0


def extract_meta_scm_params(result_json_path: Path) -> Dict[str, Any]:
    """
    从 TRACE result.json 提取全部元 SCM 参数。

    返回一个字典，包含 ~22 个固定键。
    所有键在任何文本的 result.json 上都是对齐的。

    Args:
        result_json_path: TRACE 输出目录下的 result.json 路径

    Returns:
        Dict[str, Any]: 22 个不变的元参数
    """
    if not result_json_path.exists():
        raise FileNotFoundError(f"result.json 不存在: {result_json_path}")

    with open(result_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # ── 提取所有预定义参数 ──────────────────────────────
    params = {}

    # 基础因果效应
    ate = _safe_float(data.get("ate"))
    params["ate"] = ate

    # CI 缺失或长度不足时显式用 None 标记，避免与真实 ci_width=0 混淆
    ci = data.get("confidence_interval")
    if isinstance(ci, list) and len(ci) >= 2:
        ci_lower = _safe_float(ci[0])
        ci_upper = _safe_float(ci[1])
        params["ate_ci_lower"] = ci_lower
        params["ate_ci_upper"] = ci_upper
        params["ci_width"] = ci_upper - ci_lower
    else:
        params["ate_ci_lower"] = None
        params["ate_ci_upper"] = None
        params["ci_width"] = None

    # 反驳次数
    refutations = data.get("refutations", [])
    refuted_count = sum(1 for r in refutations if r.get("refuted", False))
    params["refuted_count"] = refuted_count

    # 可识别性
    params["identifiable"] = _safe_bool_to_int(data.get("identifiable"))

    # 图结构
    concepts = data.get("concepts", [])
    params["concept_count"] = len(concepts)
    params["edge_count"] = _safe_int(data.get("n_significant_edges"))
    params["adj_density"] = _safe_float(_deep_get(data, "data_diagnostics.adj_density"))
    params["max_delta_nll"] = _safe_float(_deep_get(data, "data_diagnostics.max_delta_nll"))

    # 数据诊断
    params["concept_coverage"] = _safe_float(_deep_get(data, "data_diagnostics.concept_coverage"))
    params["condition_number"] = _safe_float(_deep_get(data, "data_diagnostics.condition_number"))
    params["unk_rate"] = _safe_float(_deep_get(data, "data_diagnostics.unk_rate"))

    # CCM
    ccm_coverage_raw = _deep_get(data, "six_warriors.ccm.metrics.CCM_coverage", "0%")
    params["ccm_coverage_pct"] = _safe_float(ccm_coverage_raw)
    ccm_verdict = _deep_get(data, "six_warriors.ccm.verdict", "N/A")
    params["ccm_verdict"] = ccm_verdict if ccm_verdict else "N/A"

    # EDM
    params["edm_rho_high"] = _safe_int(_deep_get(data, "six_warriors.edm.metrics.rho_high"))
    params["edm_rho_mid"] = _safe_int(_deep_get(data, "six_warriors.edm.metrics.rho_mid"))

    # HAVOK — 可能不可用
    havok = _deep_get(data, "six_warriors.havok", {})
    params["havok_status"] = havok.get("status", "unavailable") if havok else "unavailable"

    # 尝试从 findings 文本提取线性占比
    havok_linear = -1.0
    havok_findings = havok.get("findings", []) if havok else []
    for finding in havok_findings:
        if "线性" in str(finding) and "%" in str(finding):
            import re
            match = re.search(r'(\d+\.?\d*)\s*%', str(finding))
            if match:
                havok_linear = float(match.group(1))
                break
    params["havok_linear_pct"] = havok_linear

    # causallearn 共识
    params["causallearn_consensus"] = _safe_int(
        _deep_get(data, "six_warriors.causallearn.metrics.Agree")
    )

    # 稳定性
    stability = data.get("stability_analysis", {})
    params["edge_stability_mean"] = _safe_float(stability.get("edge_stability_mean"))
    params["permutation_p_value"] = _safe_float(stability.get("permutation_p_value", 1.0))

    # 执行剖面
    exec_profile = data.get("execution_profile", {})
    params["total_ms"] = _safe_int(exec_profile.get("total_ms"))

    return params


def extract_all_from_directory(work_output_dir: Path) -> Dict[str, Dict[str, Any]]:
    """
    遍历 TRACE work/outputs/ 目录，提取所有已完成任务的元参数。

    Returns:
        { uuid: {params_dict}, ... }
    """
    results = {}
    if not work_output_dir.exists():
        return results

    for task_dir in work_output_dir.iterdir():
        if not task_dir.is_dir():
            continue
        result_file = task_dir / "result.json"
        if result_file.exists():
            try:
                params = extract_meta_scm_params(result_file)
                results[task_dir.name] = params
            except Exception as e:
                print(f"[L1] 警告: 无法解析 {task_dir.name}: {e}")

    return results


# ── 自检 ────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    from config import TRACE_WORK_DIR

    print("=" * 60)
    print("Layer 1 自检: 元 SCM 参数提取器")
    print("=" * 60)

    all_params = extract_all_from_directory(TRACE_WORK_DIR)

    if not all_params:
        print("⚠ 未找到任何 TRACE 输出。")
        print(f"  预期路径: {TRACE_WORK_DIR}")
        sys.exit(0)

    print(f"✓ 找到 {len(all_params)} 个 TRACE 任务输出\n")

    for uuid, params in list(all_params.items())[:3]:
        print(f"--- {uuid[:12]}... ---")
        for key, value in sorted(params.items()):
            print(f"  {key:30s} = {value}")
        print()

    # 验证所有键都存在
    expected_keys = [
        "ate", "ate_ci_lower", "ate_ci_upper", "ci_width",
        "refuted_count", "identifiable", "concept_count", "edge_count",
        "adj_density", "max_delta_nll", "concept_coverage",
        "condition_number", "unk_rate", "ccm_coverage_pct",
        "ccm_verdict", "edm_rho_high", "edm_rho_mid",
        "havok_status", "havok_linear_pct", "causallearn_consensus",
        "edge_stability_mean", "permutation_p_value", "total_ms",
    ]

    for uuid, params in all_params.items():
        missing = [k for k in expected_keys if k not in params]
        if missing:
            print(f"⚠ {uuid[:12]}: 缺少键: {missing}")
        else:
            print(f"✓ {uuid[:12]}: 所有 {len(expected_keys)} 个参数完整")
        break

    print("\nLayer 1 自检完成 ✓")
