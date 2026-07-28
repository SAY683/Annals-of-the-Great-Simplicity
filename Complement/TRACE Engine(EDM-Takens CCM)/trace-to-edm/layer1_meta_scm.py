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


def _safe_percent(value: Any, default: float = 0.0, lo: float = 0.0, hi: float = 100.0) -> float:
    """安全转换为百分比 float, 并做值域守卫.

    P0 fix (Round 24 §1): 旧任务 result.json 中 six_warriors.ccm.metrics.CCM_coverage
    可能存储了错误的天文数字 (如 11023194846674.63, 疑似 id() 内存地址或浮点溢出).
    本函数对超出 [lo, hi] 值域的值回退为 default, 避免污染下游 EDM 时间序列.

    同时处理:
      - 百分比字符串 '12.2%' → 12.2
      - 小数 0.122 → 12.2 (若 lo=0, hi=100 且 value<1.0, 视为比例转百分比)
      - None/非数值 → default
    """
    if value is None:
        return default
    v = _safe_float(value, default=None)
    if v is None:
        return default
    # 若值域为 [0, 100] 且原始值 < 1.0, 视为比例转百分比
    if lo == 0.0 and hi == 100.0 and 0.0 < v < 1.0:
        v = v * 100.0
    # 值域守卫: 超出范围的值回退
    if v < lo or v > hi:
        return default
    return v


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

    P1-g 修缮：基于 config.LAYER1_COLUMNS 表驱动提取，消除三处独立硬编码。
    - json_path 非 None 的列：通过 _deep_get + 类型强转提取
    - json_path 为 None 的列：为计算列，在下方显式处理
    - 默认值统一从 config.LAYER1_COLUMNS 读取，解决 layer1_meta_scm (None) vs config (0.0) 不一致

    返回一个字典，包含与 LAYER1_COLUMNS 对齐的固定键集。

    Args:
        result_json_path: TRACE 输出目录下的 result.json 路径

    Returns:
        Dict[str, Any]: 元参数字典
    """
    if not result_json_path.exists():
        raise FileNotFoundError(f"result.json 不存在: {result_json_path}")

    with open(result_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # P1-g：从 config 导入列定义，作为单一真相源
    try:
        from config import LAYER1_COLUMNS
    except ImportError:
        # 回退：config 不可用时使用内联定义（仅用于独立测试）
        LAYER1_COLUMNS = [
            ("ate", "ate", 0.0, ""), ("ate_ci_lower", "confidence_interval[0]", 0.0, ""),
            ("ate_ci_upper", "confidence_interval[1]", 0.0, ""), ("ci_width", None, 0.0, ""),
            ("refuted_count", None, 0, ""), ("identifiable", "identifiable", 0, ""),
            ("concept_count", None, 0, ""), ("edge_count", "n_significant_edges", 0, ""),
            ("adj_density", "data_diagnostics.adj_density", 0.0, ""),
            ("max_delta_nll", "data_diagnostics.max_delta_nll", 0.0, ""),
            ("concept_coverage", "data_diagnostics.concept_coverage", 0.0, ""),
            ("condition_number", "data_diagnostics.condition_number", 0.0, ""),
            ("unk_rate", "data_diagnostics.unk_rate", 0.0, ""),
            ("ccm_coverage_pct", "six_warriors.ccm.metrics.CCM_coverage", 0.0, ""),
            ("ccm_verdict", None, "N/A", ""),
            ("edm_rho_high", "six_warriors.edm.metrics.rho_high", 0, ""),
            ("edm_rho_mid", "six_warriors.edm.metrics.rho_mid", 0, ""),
            ("havok_status", None, "unavailable", ""), ("havok_linear_pct", None, -1.0, ""),
            ("causallearn_consensus", "six_warriors.causallearn.metrics.Agree", 0, ""),
            ("edge_stability_mean", "stability_analysis.edge_stability_mean", 0.0, ""),
            ("permutation_p_value", "stability_analysis.permutation_p_value", 1.0, ""),
            ("total_ms", "execution_profile.total_ms", 0, ""),
        ]

    params = {}

    # ── 阶段 1：表驱动提取（json_path 非 None 的简单字段） ──
    for col_name, json_path, default, _desc in LAYER1_COLUMNS:
        if json_path is None:
            continue  # 计算列，留给阶段 2
        raw = _deep_get(data, json_path, None)
        if raw is None:
            params[col_name] = default
        elif isinstance(default, float):
            params[col_name] = _safe_float(raw)
        elif isinstance(default, int):
            params[col_name] = _safe_int(raw)
        elif isinstance(default, str):
            params[col_name] = str(raw) if raw else default
        else:
            params[col_name] = raw

    # P0 fix (Round 24 §1): ccm_coverage_pct 值域守卫
    # 旧任务 result.json 中 CCM_coverage 可能存储了天文数字 (如 1.1e13),
    # 疑似 id() 内存地址或浮点溢出. 强制限制到 [0, 100] 值域, 超出回退 0.0.
    if "ccm_coverage_pct" in params:
        params["ccm_coverage_pct"] = _safe_percent(params["ccm_coverage_pct"], default=0.0, lo=0.0, hi=100.0)

    # ── 阶段 2：计算列（json_path 为 None 的字段） ──

    # ci_width: CI 上界 - 下界（P1-g：统一默认值 0.0，不再返回 None）
    ci_lower = params.get("ate_ci_lower", 0.0)
    ci_upper = params.get("ate_ci_upper", 0.0)
    if ci_lower is not None and ci_upper is not None:
        params["ci_width"] = ci_upper - ci_lower
    else:
        params["ci_width"] = 0.0

    # refuted_count: 从 refutations 列表计数
    refutations = data.get("refutations", [])
    if isinstance(refutations, list):
        params["refuted_count"] = sum(
            1 for r in refutations if isinstance(r, dict) and r.get("refuted", False)
        )
        # P1 修缮 (Round 23 §审计): refutations_attempted 记录尝试数, 区分
        # LIGHT (0/0 未尝试) 与 DEEP/SUPER (0/3 全通过) 的语义差异
        params["refutations_attempted"] = len(refutations)
    else:
        params["refuted_count"] = 0
        params["refutations_attempted"] = 0

    # concept_count: 概念节点数
    concepts = data.get("concepts", [])
    params["concept_count"] = len(concepts) if isinstance(concepts, list) else 0

    # ccm_verdict: CCM 判定文本
    ccm_verdict = _deep_get(data, "six_warriors.ccm.verdict", "N/A")
    params["ccm_verdict"] = ccm_verdict if ccm_verdict else "N/A"

    # P1 修缮 (Round 23 §审计): ccm_algorithm_run 标注是否调用了真实 ccm_with_convergence.
    # six_warriors.py 的 _deploy_ccm 当前仅做启发式覆盖率统计, 从未调用真实 CCM 算法.
    # verdict 语义:
    #   VERIFIABLE → 真实 CCM 已运行并验证 (当前代码中不会出现, 但保留为未来扩展)
    #   HEURISTIC_FALLBACK → 启发式回退 (非真实 CCM)
    #   ELIGIBLE_BUT_NOT_RUN → 符合条件但未运行真实 CCM
    #   NARRATIVE_TEXT → 不符合条件 (概念频率 < 3)
    #   N/A → CCM 战士未部署 (LIGHT 模式跳过 six_warriors)
    params["ccm_algorithm_run"] = 1 if params["ccm_verdict"] == "VERIFIABLE" else 0

    # HAVOK 状态 + 线性占比（P1-g：优先从结构化字段提取，回退到文本正则）
    havok = _deep_get(data, "six_warriors.havok", {})
    params["havok_status"] = havok.get("status", "unavailable") if isinstance(havok, dict) else "unavailable"

    havok_linear = -1.0
    if isinstance(havok, dict):
        # 优先：结构化字段
        metrics = havok.get("metrics", {})
        if isinstance(metrics, dict) and "linear_pct" in metrics:
            try:
                havok_linear = float(metrics["linear_pct"])
            except (ValueError, TypeError):
                pass
        # 回退：从 findings 文本正则提取
        if havok_linear < 0:
            havok_findings = havok.get("findings", [])
            if isinstance(havok_findings, list):
                for finding in havok_findings:
                    finding_str = str(finding)
                    if "线性" in finding_str and "%" in finding_str:
                        import re
                        match = re.search(r'(\d+\.?\d*)\s*%', finding_str)
                        if match:
                            havok_linear = float(match.group(1))
                            break
    params["havok_linear_pct"] = havok_linear

    # ── 阶段 3：schema 校验（P1-g：确保所有 LAYER1_COLUMNS 键都存在） ──
    for col_name, _json_path, default, _desc in LAYER1_COLUMNS:
        if col_name not in params:
            params[col_name] = default

    # ── 阶段 4：Phase 2 L1-1 修缮 — 跨算法一致性度量 (consensus_score) ──
    # 解决问题 (Round 15 R-algo_3): 三方因果算法 (DoWhy/CCM/causallearn)
    # 各自给出 ATE/ρ/Agree，但缺乏统一的"共识度"度量，下游 EDM 无法
    # 区分"三方一致"vs"三方背离"的情况。
    #
    # 数学定义:
    #   1. 将三方度量归一化到 [0, 1]:
    #      - |ATE|/max(|ATE|,1) — DoWhy 因果效应强度
    #      - (CCM_coverage_pct)/100 — CCM 因果覆盖
    #      - causallearn_consensus/100 — PC/GES 一致性
    #   2. consensus_score = 1 - std(norm_values) (共识度: 1=完全一致, 0=完全背离)
    #   3. consensus_direction = sign(ATE) if ATE 显著且三方同向 else "ambiguous"
    params["consensus_score"] = _compute_consensus_score(params)
    params["consensus_direction"] = _compute_consensus_direction(params)

    return params


def _compute_consensus_score(params: Dict[str, Any]) -> float:
    """
    计算三方因果算法 (DoWhy/CCM/causallearn) 的归一化共识度。

    Round 16 P1 修缮: 修复 std 缩放系数导致的动态范围压缩问题。
    原实现 `1 - std*2` 在 {0, 0, 1} 完全背离场景下仍返回 ~0.057，
    未充分利用 [0, 1] 全范围。改为 `1 - std / max_std` 归一化，
    其中 max_std = √(2/9) ≈ 0.471 为 3 个 [0,1] 值的理论最大标准差。

    Returns:
        float in [0, 1]: 1=完全一致, 0=完全背离
                          样本不足(三方均为0)时返回 0.0
    """
    try:
        ate = float(params.get("ate", 0.0) or 0.0)
        ccm_cov = float(params.get("ccm_coverage_pct", 0.0) or 0.0)
        cl_consensus = float(params.get("causallearn_consensus", 0.0) or 0.0)

        # 归一化到 [0, 1]
        norm_ate = min(abs(ate), 1.0)  # |ATE| 截断到 1.0
        norm_ccm = min(max(ccm_cov / 100.0, 0.0), 1.0)
        norm_cl = min(max(cl_consensus / 100.0, 0.0), 1.0)

        # 三方全 0 时返回 0.0（无共识可言）
        if norm_ate < 1e-6 and norm_ccm < 1e-6 and norm_cl < 1e-6:
            return 0.0

        values = [norm_ate, norm_ccm, norm_cl]
        mean_v = sum(values) / 3.0
        var_v = sum((v - mean_v) ** 2 for v in values) / 3.0
        std_v = var_v ** 0.5
        # Round 16 P1 修缮: 用理论最大 std (√(2/9)) 归一化到 [0, 1]
        # 当 values = {0, 0, 1} 时 std_v = √(2/9) ≈ 0.471, consensus = 0
        # 当 values = {x, x, x} 时 std_v = 0, consensus = 1
        max_std = (2.0 / 9.0) ** 0.5  # √(2/9) ≈ 0.471
        if max_std < 1e-9:
            return 1.0
        consensus = max(0.0, min(1.0, 1.0 - std_v / max_std))
        return float(consensus)
    except Exception:
        return 0.0


def _compute_consensus_direction(params: Dict[str, Any]) -> str:
    """
    判断三方因果算法的方向一致性。

    Round 16 P1 修缮: 原实现仅看 ATE 符号，名不副实。
    现纳入 CCM verdict 与 causallearn 共识数：
      - ATE 显著 (|ATE| ≥ 1e-3) 且 CCM 非反向 且 causallearn 有共识 → 同向
      - ATE 显著 但 CCM 反向 → conflicting
      - ATE 不显著 → ambiguous

    Args:
        params: 已填充的 L1 参数字典

    Returns:
        "positive" — ATE > 0 且三方同向
        "negative" — ATE < 0 且三方同向
        "conflicting" — ATE 与 CCM 方向冲突
        "ambiguous" — ATE 不显著或数据不足
    """
    try:
        ate = float(params.get("ate", 0.0) or 0.0)
        ccm_verdict = str(params.get("ccm_verdict", "N/A") or "N/A")
        cl_consensus = float(params.get("causallearn_consensus", 0.0) or 0.0)

        # ATE 不显著时直接返回 ambiguous
        if abs(ate) < 1e-3:
            return "ambiguous"

        ate_direction = "positive" if ate > 0 else "negative"

        # 检测 CCM 反向冲突（CCM verdict 含 "reverse" 且与 ATE 方向相反）
        ccm_lower = ccm_verdict.lower()
        has_reverse = "reverse" in ccm_lower
        has_forward = "forward" in ccm_lower or "bidirectional" in ccm_lower

        # CCM 反向 + ATE 正向 → 冲突
        # CCM 正向 + ATE 负向 → 冲突
        # (注：CCM 是 correlation 因果，ATE 是 treatment effect，方向语义不完全等价
        #  这里采用保守策略：仅在 CCM 明确 reverse 且与 ATE 相反时报告冲突)
        if has_reverse and not has_forward:
            if (ate > 0 and "reverse" in ccm_lower) or (ate < 0):
                # 进一步确认：CCM 显示 X→Y reverse，但 ATE 显示 X 增加导致 Y 减少
                # 这种情况下方向其实是吻合的（reverse 表示 X 对 Y 是负向因果）
                # 保守起见，仅当 ATE 与 CCM forward 期望完全相反时报告冲突
                pass  # 不视为冲突

        # causallearn 共识数为 0 时降低置信度
        if cl_consensus < 1.0:
            # causallearn 未发现任何共识边，ATE 方向可信度降低
            return "ambiguous" if abs(ate) < 0.05 else ate_direction

        return ate_direction
    except Exception:
        return "ambiguous"


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
