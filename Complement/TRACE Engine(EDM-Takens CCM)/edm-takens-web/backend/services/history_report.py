"""Human-readable report rendering for EDM history tasks."""
import html
import json
import os
import re
import time

from fastapi import HTTPException

from core.locks import RESULTS_DIR
from services.file_management import _safe_task_path
from services.history_service import lookup_summary_by_task_id
from services.summary_builder import _task_summary


def _fmt_rho(rho):
    """将相关系数 ρ 转译为人话强度的中文标签."""
    if rho is None:
        return "N/A"
    abs_rho = abs(rho)
    # P1 修复 (Round 21 §P0-C): ρ 精度从 3 位提升到 4 位, 与论文要求一致.
    if abs_rho >= 0.85:
        return f"{rho:.4f} (极强)"
    if abs_rho >= 0.7:
        return f"{rho:.4f} (强)"
    if abs_rho >= 0.5:
        return f"{rho:.4f} (中等)"
    if abs_rho >= 0.3:
        return f"{rho:.4f} (弱)"
    return f"{rho:.4f} (极弱/无)"


def _fmt_stability(tier):
    """将稳定性分级翻译为人话."""
    if not tier:
        return "未提供"
    mapping = {
        "Stable / dissipative": "稳定 (耗散系统, 可长期预测)",
        "Near-critical / stable": "近临界 (稳定但接近相变点, 需警惕突发重组)",
        "Chaotic / unstable": "混沌 (不稳定, 长期预测不可靠)",
        # final_interpretation 中的分级标签
        "Highly dissipative": "强耗散 (高度稳定, 系统会自发回归平衡)",
        "Divergent": "发散 (不稳定, 系统持续偏离平衡)",
        "Near-critical": "近临界 (稳定但接近相变点)",
    }
    if isinstance(tier, str) and tier in mapping:
        return mapping[tier]
    # 退化或未知分级: 尽量给出中文解释
    if isinstance(tier, str) and "degenerate" in tier.lower():
        return f"退化 (信号近常量或样本量不足, 无法判定): {tier}"
    return str(tier)


def _fmt_direction(direction):
    """将 CCM 方向判定翻译为人话因果链描述."""
    if not direction:
        return "未判定"
    mapping = {
        "forward": "单向因果 (源 → 目标)",
        "reverse": "反向因果 (目标 → 源)",
        "forward_dominant": "主导正向 (源 → 目标, 反向较弱)",
        "reverse_dominant": "主导反向 (目标 → 源, 正向较弱)",
        "bidirectional": "双向耦合 (互相影响, 存在反馈回路)",
        "none": "无显著因果",
        "inconclusive": "无法判定",
    }
    return mapping.get(direction, str(direction))


def _fmt_timestamp(ts):
    """Unix 时间戳 → 可读时间."""
    if ts is None:
        return "N/A"
    try:
        from datetime import datetime
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)


def _fmt_kurtosis(kurt):
    """将峭度数值转译为分布形态的人话描述."""
    if kurt is None:
        return "N/A"
    try:
        k = float(kurt)
    except (TypeError, ValueError):
        return str(kurt)
    if k > 1.5:
        return f"{k:.3f} (重尾 — 罕见极端事件频繁, 需警惕突发)"
    if k < 0.5:
        return f"{k:.3f} (近高斯 — 事件分布较均匀)"
    return f"{k:.3f} (轻尾 — 偶发极端事件)"


def build_human_report_md(task_id: str) -> str:
    """生成人话版 Markdown 报告内容（供 /export/md 与 /export/html 复用）."""
    base = _task_summary(task_id)
    if base is None:
        raise HTTPException(status_code=404, detail="Task not found")
    rich = lookup_summary_by_task_id(task_id) or {}

    config = base.get("config") or {}
    params = base.get("params") or {}
    images = base.get("images", []) or []
    target_col = rich.get("target_col") or config.get("target_col") or "(未指定)"
    project_name = rich.get("project_name") or config.get("project_name") or "(默认)"
    intensity = rich.get("intensity") or "(未设置)"
    intensity_notes = rich.get("intensity_notes") or []
    intensity_params = rich.get("intensity_params") or {}

    # 数据集/样本信息 (从解释结果中提取, 若缺失则回退到 config)
    n_samples = rich.get("n_samples") or config.get("n_samples")
    unit = rich.get("unit") or "样本"
    available_variables = rich.get("available_variables") or []
    skipped_variables = rich.get("skipped_variables") or []
    lyap_reliable = rich.get("lyapunov_reliable_variables") or []

    lines = []
    lines.append(f"# EDM-Takens 分析报告: {task_id}\n")
    lines.append(f"> 自动生成 — 面向非技术读者的人话版解读.\n")
    lines.append(f"> _报告生成时间: {_fmt_timestamp(time.time())}_\n")
    lines.append("")

    # ─────────────────────────────────────────────────────
    # 1. 概览
    # ─────────────────────────────────────────────────────
    lines.append("## 1. 概览\n")
    lines.append(f"- **任务 ID**: `{task_id}`")
    lines.append(f"- **完成时间**: {_fmt_timestamp(base.get('updated_at'))}")
    lines.append(f"- **项目名称**: {project_name}")
    lines.append(f"- **数据源**: `{params.get('filename') or '(未记录)'}`")
    lines.append(f"- **目标变量**: `{target_col}`")
    if n_samples is not None:
        lines.append(f"- **样本量**: {n_samples} {unit}")
    if available_variables:
        lines.append(f"- **成功分析的变量**: {', '.join(f'`{v}`' for v in available_variables)}")
    if skipped_variables:
        lines.append(f"- **跳过的变量 (数据不足/近常量)**: {', '.join(f'`{v}`' for v in skipped_variables)}")
    lines.append(f"- **分析强度档位**: {intensity}")
    if intensity_params:
        q_disp = intensity_params.get("q", "自动")
        max_e_disp = intensity_params.get("max_e", "默认")
        auto_fix_disp = intensity_params.get("auto_fix", True)
        lines.append(f"  - 嵌入维度 q={q_disp}, 最大嵌入维度 max_e={max_e_disp}, 自动修正={auto_fix_disp}")
    if intensity_notes:
        lines.append(f"- **强度说明**:")
        for note in intensity_notes:
            lines.append(f"  - {note}")
    lines.append(f"- **生成图表数**: {len(images)} 张")
    if images:
        lines.append(f"  - 图表文件: {', '.join(f'`{img}`' for img in images)}")
    # 列映射说明 (display_map)
    column_mapping = rich.get("column_mapping")
    if column_mapping and isinstance(column_mapping, dict) and column_mapping:
        mapping_items = [f"`{k}` → `{v}`" for k, v in column_mapping.items() if k != v]
        if mapping_items:
            lines.append(f"- **列名映射** (内部→显示): {', '.join(mapping_items)}")
    lines.append("")

    # ─────────────────────────────────────────────────────
    # 2. 稳定性诊断
    # ─────────────────────────────────────────────────────
    lines.append("## 2. 稳定性诊断 (HAVOK)\n")
    lines.append("> HAVOK (HAVOK 分析) 通过奇异值分解重构系统动力学, "
                 "判断系统是稳定、近临界还是混沌.\n")
    havok = rich.get("havok") or {}
    if havok:
        tier = havok.get("stability_tier")
        lines.append(f"- **整体稳定性判定**: {_fmt_stability(tier)}")
        if havok.get("max_eigenvalue") is not None:
            try:
                max_ev = float(havok['max_eigenvalue'])
                lines.append(f"- **最大特征值 |λ_max|**: {max_ev:.4f}")
                # 人话解读: 特征值大小决定系统稳定性
                if max_ev < 0.05:
                    lines.append(f"  - _解读_: |λ_max| < 0.05 → 系统耗散, 稳定可预测.")
                elif max_ev < 0.5:
                    lines.append(f"  - _解读_: 0.05 ≤ |λ_max| < 0.5 → 近临界, 接近相变点.")
                else:
                    lines.append(f"  - _解读_: |λ_max| ≥ 0.5 → 系统混沌, 长期预测不可靠.")
            except (TypeError, ValueError):
                lines.append(f"- **最大特征值 |λ_max|**: {havok['max_eigenvalue']}")
        lines.append(f"- **HAVOK 秩 r**: {havok.get('rank')} (线性主导模态数, 越大表示系统越复杂)")
        # 解释方差占比
        try:
            ev = havok.get('explained_variance', 0)
            ev = float(ev) if ev is not None else 0.0
            lines.append(f"- **线性解释方差占比**: {ev * 100:.1f}%")
            lines.append(f"  - _解读_: 前 r 个模态能解释的方差比例, 越高表示线性近似越有效.")
        except (TypeError, ValueError):
            lines.append("- **线性解释方差占比**: N/A")
        # 回归 R²
        try:
            r2 = havok.get('regression_r2', 0)
            r2 = float(r2) if r2 is not None else 0.0
            lines.append(f"- **回归 R²**: {r2:.3f}")
            if r2 >= 0.8:
                lines.append(f"  - _解读_: R² ≥ 0.8 → 线性模型拟合良好.")
            elif r2 >= 0.5:
                lines.append(f"  - _解读_: 0.5 ≤ R² < 0.8 → 拟合一般, 非线性成分不可忽视.")
            else:
                lines.append(f"  - _解读_: R² < 0.5 → 线性拟合差, 非线性主导.")
        except (TypeError, ValueError):
            lines.append("- **回归 R²**: N/A")
        # 峭度
        kurt = havok.get('kurtosis')
        lines.append(f"- **强迫项峭度**: {_fmt_kurtosis(kurt)}")
        # 采样充分性
        sampling_adequacy = havok.get('sampling_adequacy')
        if sampling_adequacy is not None:
            try:
                sa = float(sampling_adequacy)
                if sa >= 0.8:
                    sa_desc = "充分 — 结论可信"
                elif sa >= 0.5:
                    sa_desc = "勉强 — 结论应谨慎解读"
                else:
                    sa_desc = "不足 — 结论可能不可靠, 建议增加样本量"
                lines.append(f"- **采样充分性**: {sa:.3f} ({sa_desc})")
            except (TypeError, ValueError):
                lines.append(f"- **采样充分性**: {sampling_adequacy}")
        # 条件数诊断
        cond_raw = havok.get("condition_number_raw")
        if cond_raw is None:
            cond_str = havok.get("condition_number", "N/A")
            if cond_str not in (None, "N/A", "nan"):
                try:
                    cond_raw = float(cond_str)
                except (TypeError, ValueError):
                    cond_raw = None
        if cond_raw is not None and cond_raw == cond_raw:  # NaN check
            if cond_raw > 1e10:
                lines.append(f"- **A 矩阵条件数**: {cond_raw:.2e} ⚠️ **病态** — 特征值/稳定性结论可信度受损")
            elif cond_raw > 1e6:
                lines.append(f"- **A 矩阵条件数**: {cond_raw:.2e} ⚠️ 接近病态, 稳定性结论应谨慎解读")
            else:
                lines.append(f"- **A 矩阵条件数**: {cond_raw:.2e} ✓ 良好")
        if havok.get("is_degenerate"):
            lines.append("- ⚠️ **HAVOK 退化**: 信号近常量或样本量不足, 稳定性结论仅供参考.")
        lines.append("")
        lines.append("> **整体解读**: 稳定性分级告诉我们系统是 \"可预测的稳定系统\" 还是 \"不可预测的混沌系统\". "
                     "近临界意味着系统正在接近相变点, 一次小扰动可能引发结构性重组; "
                     "混沌则意味着长期预测不可靠, 需要缩短预测视野或增加数据.\n")
    else:
        lines.append("- 未提供 HAVOK 诊断信息 (可能因样本量不足或信号退化).\n")

    # ─────────────────────────────────────────────────────
    # 3. 各变量 EDM 预测技能
    # ─────────────────────────────────────────────────────
    lines.append("## 3. 各变量 EDM 预测技能\n")
    lines.append("> EDM (经验动态建模) 用过去状态预测未来值, "
                 "ρ (相关系数) 越接近 1 表示预测越准; "
                 "S-Map 的 θ 越大表示系统越非线性.\n")
    variables = rich.get("variables") or {}
    if variables:
        lines.append("| 变量 | Simplex ρ | S-Map 最大 ρ | 最佳 θ | 非线性? | 预测能力判定 |")
        lines.append("|------|-----------|-------------|--------|---------|-------------|")
        for var_name, m in variables.items():
            if not isinstance(m, dict):
                lines.append(f"| `{var_name}` | N/A | N/A | N/A | (数据缺失) | 无法判定 |")
                continue
            rho_s = _fmt_rho(m.get("rho_simplex"))
            rho_sm = _fmt_rho(m.get("rho_smap_max"))
            theta = m.get("theta_best")
            theta_str = f"{theta:.2f}" if theta is not None else "N/A"
            nonlin = "是 ✓" if m.get("is_nonlinear") else "否"
            # 预测能力人话判定
            rho_simplex = m.get("rho_simplex")
            if rho_simplex is not None and abs(rho_simplex) >= 0.7:
                skill = "强预测能力"
            elif rho_simplex is not None and abs(rho_simplex) >= 0.5:
                skill = "中等预测能力"
            elif rho_simplex is not None and abs(rho_simplex) >= 0.3:
                skill = "弱预测能力"
            else:
                skill = "几乎不可预测"
            lines.append(f"| `{var_name}` | {rho_s} | {rho_sm} | {theta_str} | {nonlin} | {skill} |")
        lines.append("")
        lines.append("> **解读**: ρ 越接近 1 表示预测越准. "
                     "若 S-Map ρ 显著高于 Simplex ρ, 说明系统具有非线性特征, "
                     "线性模型 (如 AR / VAR) 会严重低估其可预测性. "
                     "θ 为 S-Map 的最佳非线性参数, θ=0 为纯线性, θ 越大非线性越强.\n")
    else:
        lines.append("- 未提供变量级 EDM 指标.\n")

    # ─────────────────────────────────────────────────────
    # 4. CCM 因果链
    # ─────────────────────────────────────────────────────
    lines.append("## 4. CCM 因果链 (Sugihara 因果关系)\n")
    lines.append("> CCM (收敛交叉映射) 通过 \"能否从效应的流形预测原因\" 来判定因果方向. "
                 "收敛 + p 值显著 = 存在因果链.\n")
    ccm = rich.get("ccm") or {}
    ccm_directions = rich.get("ccm_directions") or []
    if ccm and ccm.get("pairs"):
        lines.append(f"- **测试对数**: {ccm.get('n_pairs', len(ccm['pairs']))}")
        lines.append(f"- **原始显著数 (p<0.05)**: {ccm.get('n_significant_raw', 0)}")
        lines.append(f"- **Bonferroni 校正后显著数**: {ccm.get('n_significant_corrected', 0)}")
        lines.append(f"- **多重假设校正方法**: {ccm.get('method', 'N/A')}")
        lines.append("")
        lines.append("| 源 → 目标 | p 值 | 校正后显著? | 收敛? | 最终 ρ | Spearman ρ | 方向判定 |")
        lines.append("|-----------|------|-------------|-------|--------|-----------|---------|")
        for p in ccm["pairs"]:
            if not isinstance(p, dict):
                lines.append(f"| (数据缺失) | N/A | N/A | N/A | N/A | N/A | N/A |")
                continue
            cause = p.get("cause", "?")
            effect = p.get("effect", "?")
            pval = p.get("p_value")
            pval_str = f"{pval:.4f}" if pval is not None else "N/A"
            sig = "是 ✓" if p.get("significant_corrected") else "否"
            conv = "是 ✓" if p.get("is_converging") else "否"
            final_rho = p.get("final_rho")
            final_rho_str = f"{final_rho:.4f}" if final_rho is not None else "N/A"
            spearman = p.get("spearman_rho")
            spearman_str = f"{spearman:.4f}" if spearman is not None else "N/A"
            # 方向判定 (优先从 ccm_directions 取, 其次从 pair verdict 取)
            direction = None
            for d in ccm_directions:
                if isinstance(d, dict) and d.get("cause") == cause and d.get("effect") == effect:
                    direction = d.get("direction")
                    break
            if direction is None:
                direction = p.get("verdict") or "未判定"
            dir_str = _fmt_direction(direction)
            lines.append(f"| `{cause}` → `{effect}` | {pval_str} | {sig} | {conv} | {final_rho_str} | {spearman_str} | {dir_str} |")
        lines.append("")
        lines.append("> **解读**: ")
        lines.append("> - **p 值**: 越小越显著, p<0.05 为显著, Bonferroni 校正后更严格.")
        lines.append("> - **收敛 (converging)**: 库大小增加时 ρ 是否收敛, 收敛=存在因果链.")
        lines.append("> - **最终 ρ**: 收敛时的最大相关系数, 越高因果链越强.")
        lines.append("> - **Spearman ρ**: 单调相关性, 辅助验证线性关系强度.")
        lines.append("> - **方向判定**: forward=源→目标, reverse=目标→源, bidirectional=双向耦合.\n")
    else:
        lines.append("- 未提供 CCM 因果分析结果 (可能因样本量不足或变量对数 < 2).\n")

    # ─────────────────────────────────────────────────────
    # 5. 图谱解析 (新增 — P1 修复 Round 24 §1)
    # ─────────────────────────────────────────────────────
    lines.append("## 5. 图谱解析 (dynamics_interpretation.png)\n")
    has_interp_img = any("dynamics_interpretation" in img or "interpretation" in img.lower() for img in images)
    if has_interp_img:
        interp_img_name = next(
            (img for img in images if "dynamics_interpretation" in img or "interpretation" in img.lower()),
            "dynamics_interpretation.png"
        )
        lines.append(f"> 任务结果目录中包含图谱文件 `{interp_img_name}`, "
                     "该图通过 SovereignHAVOK + EDM + CCM 三件套生成, "
                     "包含以下面板:\n")
        lines.append("### 5.1 面板含义解读\n")
        lines.append("- **时序面板** (左列): 各变量的原始时间序列, 展示数据本身的波动模式.")
        lines.append("- **强迫项面板** (右列): HAVOK 提取的 v_r 强迫项, "
                     "代表系统无法用线性模态解释的 \"外部扰动\". "
                     "峭度越高表示极端事件越频繁.")
        lines.append("- **特征值谱**: 离散特征值 λ_d 的分布, "
                     "|λ_max| 决定系统稳定性 (见第 2 节).")
        lines.append("- **CCM 收敛曲线**: 库大小 L → ρ 的关系, "
                     "曲线上升并收敛 = 存在因果链; 平坦 = 无因果.")
        lines.append("- **S-Map 非线性曲线**: θ → ρ 的关系, "
                     "θ 增大时 ρ 上升 = 系统非线性; 平坦 = 系统线性.")
        lines.append("- **综合摘要面板**: 文字形式的稳定性分级、重尾变量、显著因果对数.")
        lines.append("")
        # 5.2 基于可用数据的图谱内容解读
        lines.append("### 5.2 本次图谱内容解读\n")
        if havok:
            tier = havok.get("stability_tier", "")
            try:
                if isinstance(tier, str) and ("Stable" in tier or "dissipative" in tier.lower()):
                    lines.append("- **稳定性面板**: 显示耗散特征值, 系统会自发回归平衡 — 稳定可预测.")
                elif isinstance(tier, str) and ("Near-critical" in tier or "near-critical" in tier.lower()):
                    lines.append("- **稳定性面板**: 特征值接近临界, 系统可能在扰动下发生结构性重组.")
                elif isinstance(tier, str) and ("Chaotic" in tier or "Divergent" in tier):
                    lines.append("- **稳定性面板**: 特征值发散, 系统混沌 — 长期预测不可靠.")
                else:
                    lines.append(f"- **稳定性面板**: {tier}")
            except Exception:
                lines.append(f"- **稳定性面板**: {tier}")
        if variables:
            nonlin_count = sum(1 for v in variables.values() if isinstance(v, dict) and v.get("is_nonlinear"))
            total = len(variables)
            lines.append(f"- **S-Map 非线性面板**: {nonlin_count}/{total} 个变量呈现非线性特征 "
                         f"({'需用非线性模型' if nonlin_count > 0 else '可用线性模型近似'}).")
        if ccm and ccm.get("pairs"):
            n_conv = sum(1 for p in ccm["pairs"] if isinstance(p, dict) and p.get("is_converging"))
            n_total = len(ccm["pairs"])
            lines.append(f"- **CCM 收敛面板**: {n_conv}/{n_total} 对变量呈现收敛 (存在因果链).")
            n_sig = ccm.get("n_significant_corrected", 0)
            lines.append(f"- **统计显著性**: Bonferroni 校正后 {n_sig} 对显著 (p<0.05).")
        if lyap_reliable:
            lines.append(f"- **李雅普诺夫指数面板**: 变量 {', '.join(f'`{v}`' for v in lyap_reliable)} "
                         f"的李雅普诺夫指数可靠 — 可估算预测视野.")
        elif n_samples is not None and isinstance(n_samples, (int, float)) and n_samples < 100:
            lines.append("- **李雅普诺夫指数面板**: 样本量不足 (<100), 无法可靠估算 — 建议增加数据.")
        lines.append("")
        lines.append("> **如何阅读图谱**: 对照本节解读查看 `dynamics_interpretation.png`, "
                     "图中的颜色与变量一一对应, 上方为时序, 下方为强迫项. "
                     "若需查看大图, 在 Web 控制台点击历史任务的 \"查看\" 按钮.\n")
    else:
        lines.append("- 本次任务结果目录中未找到 `dynamics_interpretation.png` 图谱文件. "
                     "可能因解释阶段被跳过 (例如 Stage 1 失败导致 Stage 3 跳过).")
        lines.append("")
        # 即便没有图谱, 仍然根据已有数据给出文字解读
        if havok or variables or ccm:
            lines.append("### 5.1 基于数据的文字解读\n")
            if havok:
                lines.append(f"- **稳定性**: {_fmt_stability(havok.get('stability_tier'))}")
            if variables:
                nonlin_count = sum(1 for v in variables.values() if isinstance(v, dict) and v.get("is_nonlinear"))
                lines.append(f"- **非线性**: {nonlin_count}/{len(variables)} 个变量呈现非线性.")
            if ccm and ccm.get("pairs"):
                n_conv = sum(1 for p in ccm["pairs"] if isinstance(p, dict) and p.get("is_converging"))
                lines.append(f"- **因果链**: {n_conv}/{len(ccm['pairs'])} 对收敛.")
            lines.append("")

    # ─────────────────────────────────────────────────────
    # 6. 八正道审计 (新增 — P1 修复 Round 24 §1, 重命名自原 "后审计")
    # ─────────────────────────────────────────────────────
    lines.append("## 6. 八正道审计 (Eightfold Path Audit)\n")
    lines.append("> 八正道审计是 EDM 流水线的最后一道质量关卡, "
                 "从 8 个维度检查分析是否可信: "
                 "数据质量、样本量、嵌入维度、HAVOK 退化、CCM 收敛、多重假设校正、"
                 "可复现性、数值稳定性. 通过 = 可信, 警告 = 可参考, 失败 = 不可信.\n")
    pa_verdict = rich.get("post_audit_verdict")
    if pa_verdict:
        # 裁决中文映射
        verdict_cn = {
            "PASS": "通过 ✓ — 分析结果可信",
            "PASS_WITH_NOTES": "通过 (附说明) ✓ — 可信但需关注警告",
            "WARN": "警告 ▲ — 结果可参考但存在隐患",
            "FAIL": "未通过 ✗ — 结果不可信, 建议重做",
            "BLOCKED": "阻断 ✗ — 流水线被阻断, 无法完成",
            "INCONCLUSIVE": "无法判定 ▲ — 数据不足以裁决",
        }
        verdict_disp = verdict_cn.get(str(pa_verdict).upper(), str(pa_verdict))
        lines.append(f"- **审计裁决**: {verdict_disp}")
        if rich.get("post_audit_passed") is not None:
            passed = "通过 ✓" if rich.get("post_audit_passed") else "未通过 ✗"
            lines.append(f"- **是否通过**: {passed}")
        # 警告项
        warns_raw = rich.get("post_audit_warnings")
        warn_count = rich.get("post_audit_warning_count")
        if isinstance(warns_raw, (list, tuple)):
            warns = list(warns_raw)
            if warn_count is None:
                warn_count = len(warns)
        elif isinstance(warns_raw, int):
            warns = []
            if warn_count is None:
                warn_count = warns_raw
        else:
            warns = []
            if warn_count is None:
                warn_count = 0
        if warns:
            lines.append(f"- **警告项** ({warn_count} 项):")
            for w in warns:
                lines.append(f"  - ⚠️ {w}")
        elif warn_count:
            lines.append(f"- **警告项**: {warn_count} 项 (历史数据未保存消息)")

        # 失败项
        fails_raw = rich.get("post_audit_failures")
        fail_count = rich.get("post_audit_failure_count")
        if isinstance(fails_raw, (list, tuple)):
            fails = list(fails_raw)
            if fail_count is None:
                fail_count = len(fails)
        elif isinstance(fails_raw, int):
            fails = []
            if fail_count is None:
                fail_count = fails_raw
        else:
            fails = []
            if fail_count is None:
                fail_count = 0
        if fails:
            lines.append(f"- **失败项** ({fail_count} 项):")
            for f in fails:
                lines.append(f"  - ✗ {f}")
        elif fail_count:
            lines.append(f"- **失败项**: {fail_count} 项 (历史数据未保存消息)")
        lines.append("")
        lines.append("> **解读**: 警告 (WARN) 表示分析可进行但需关注隐患; "
                     "失败 (FAIL) 表示对应环节不可信, 下游结论应作废. "
                     "通过 (PASS) 仅代表审计未发现问题, 不保证结论 \"正确\" — 仍需结合领域知识判断.\n")
    else:
        lines.append("- 八正道审计: 未运行 (可能因 Stage 1 失败导致审计被跳过).\n")

    # ─────────────────────────────────────────────────────
    # 7. 数据质量与采样充分性
    # ─────────────────────────────────────────────────────
    lines.append("## 7. 数据质量与采样充分性\n")
    dq_warn = rich.get("data_quality_warning")
    if dq_warn:
        lines.append(f"- ⚠️ **数据质量警告**: {dq_warn}")
    else:
        lines.append("- **数据质量**: 无警告.")
    if n_samples is not None:
        try:
            n = int(n_samples)
            if n < 30:
                lines.append(f"- ⚠️ **样本量偏少** ({n} {unit}): EDM 建议 N≥30, 当前处于下限, 结论仅供参考.")
            elif n < 100:
                lines.append(f"- **样本量** ({n} {unit}): 勉强可用, 李雅普诺夫指数无法可靠估算, 建议 N≥100.")
            else:
                lines.append(f"- **样本量** ({n} {unit}): 充足, 各项诊断均可信.")
        except (TypeError, ValueError):
            lines.append(f"- **样本量**: {n_samples}")
    if skipped_variables:
        lines.append(f"- **跳过的变量** ({len(skipped_variables)} 个): "
                     f"{', '.join(f'`{v}`' for v in skipped_variables)} — 数据不足或近常量, 无法分析.")
    if havok and havok.get("is_degenerate"):
        lines.append("- ⚠️ **HAVOK 退化**: 信号近常量, 强迫项/特征值诊断无意义.")
    lines.append("")

    # ─────────────────────────────────────────────────────
    # 8. 配置参数附录
    # ─────────────────────────────────────────────────────
    lines.append("## 8. 配置参数附录\n")
    if config:
        lines.append("### 8.1 运行配置 (PipelineConfig)\n")
        lines.append("| 参数 | 值 | 含义 |")
        lines.append("|------|----|------|")
        # 中文参数说明映射
        config_cn = {
            "data_path": "数据文件路径",
            "n_samples": "样本量",
            "n_variables": "变量数",
            "target_col": "目标变量",
            "columns": "分析变量列表",
            "E": "嵌入维度",
            "tau": "时间延迟",
            "theta": "S-Map 非线性参数",
            "q": "HAVOK 延迟嵌入维度",
            "r": "HAVOK 秩",
            "energy_threshold": "能量阈值",
            "dt": "时间步长",
            "window_length": "SVD 窗口长度",
            "poly_order": "多项式阶数",
            "basis": "HAVOK 基函数",
            "n_surrogates": "代理样本数",
            "surrogate_method": "代理检验方法",
            "timestamp": "运行时间戳",
            "analysis_type": "分析类型",
            "random_seed": "随机种子",
            "audit_verdict": "审计裁决",
            "audit_findings_summary": "审计发现摘要",
        }
        for k in sorted(config.keys()):
            v = config[k]
            if isinstance(v, (list, dict)):
                v = json.dumps(v, ensure_ascii=False)
            cn_desc = config_cn.get(k, "")
            lines.append(f"| `{k}` | `{v}` | {cn_desc} |")
        lines.append("")
    if params:
        lines.append("### 8.2 任务输入参数\n")
        lines.append("| 参数 | 值 | 含义 |")
        lines.append("|------|----|------|")
        params_cn = {
            "filename": "数据文件名",
            "target_col": "目标变量",
            "selected_vars": "选中变量",
            "q": "嵌入维度",
            "max_e": "最大嵌入维度",
            "intensity": "分析强度档位",
            "project_name": "项目名称",
            "auto_fix": "自动修正次优配置",
        }
        for k in sorted(params.keys()):
            v = params[k]
            if isinstance(v, (list, dict)):
                v = json.dumps(v, ensure_ascii=False)
            cn_desc = params_cn.get(k, "")
            lines.append(f"| `{k}` | `{v}` | {cn_desc} |")
        lines.append("")

    # ─────────────────────────────────────────────────────
    # 9. 一句话总结
    # ─────────────────────────────────────────────────────
    lines.append("## 9. 一句话总结\n")
    summary_parts = []
    if havok:
        tier = havok.get("stability_tier", "") or ""
        if not isinstance(tier, str):
            tier = str(tier) if tier is not None else ""
        if "Stable" in tier or "dissipative" in tier.lower():
            summary_parts.append("系统稳定可预测")
        elif "Near-critical" in tier or "near-critical" in tier.lower():
            summary_parts.append("系统接近临界点, 警惕突发重组")
        elif "Chaotic" in tier or "Divergent" in tier:
            summary_parts.append("系统混沌, 长期预测不可靠")
    if ccm and ccm.get("n_significant_corrected", 0) > 0:
        summary_parts.append(f"识别出 {ccm['n_significant_corrected']} 条显著因果链 (Bonferroni 校正后)")
    elif ccm:
        summary_parts.append("未识别出显著因果链")
    if variables:
        nonlin_count = sum(1 for v in variables.values() if isinstance(v, dict) and v.get("is_nonlinear"))
        if nonlin_count > 0:
            summary_parts.append(f"{nonlin_count}/{len(variables)} 个变量呈非线性")
    if pa_verdict:
        if str(pa_verdict).upper() in ("FAIL", "BLOCKED"):
            summary_parts.append("八正道审计未通过, 结果不可信")
        elif str(pa_verdict).upper() == "WARN":
            summary_parts.append("八正道审计警告, 结果可参考但存在隐患")

    if summary_parts:
        lines.append("**" + "; ".join(summary_parts) + ".**")
    else:
        lines.append("_数据不足, 无法给出总结._")
    lines.append("")
    lines.append("---")
    lines.append(f"_报告由 EDM-Takens Web 自动生成于 {_fmt_timestamp(time.time())}._")
    lines.append(f"_如需查看原始图表, 请在 Web 控制台打开任务 `{task_id}`._")

    md_content = "\n".join(lines)

    # P1 fix (Round 25 §2): 实际落盘到任务结果目录, 而非仅声称落盘.
    try:
        task_dir = _safe_task_path(task_id, RESULTS_DIR)
        if task_dir and os.path.isdir(task_dir):
            report_path = os.path.join(task_dir, "report.md")
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(md_content)
    except Exception:
        pass  # 落盘失败不影响浏览器展示

    return md_content




def md_to_html(md: str) -> str:
    """极简 Markdown → HTML，仅支持本项目报告用到的语法.

    不引入外部 Markdown 库，避免依赖膨胀。
    """
    lines = md.split('\n')
    out = []
    i = 0
    in_ul = False
    in_ol = False

    def escape(s: str) -> str:
        return html.escape(s, quote=True)

    def inline(s: str) -> str:
        s = escape(s)
        s = s.replace('\\*', '\x00asterisk\x00')
        s = s.replace('\\`', '\x00backtick\x00')
        s = s.replace('\\_', '\x00underscore\x00')
        # code
        s = re.sub(r'`([^`]*)`', r'<code>\1</code>', s)
        # bold
        s = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', s)
        # italic
        s = re.sub(r'_([^_]+)_', r'<em>\1</em>', s)
        s = s.replace('\x00asterisk\x00', '*').replace('\x00backtick\x00', '`').replace('\x00underscore\x00', '_')
        return s

    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul:
            out.append('</ul>')
            in_ul = False
        if in_ol:
            out.append('</ol>')
            in_ol = False

    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()
        stripped = line.lstrip()

        # 空行
        if not stripped:
            close_lists()
            i += 1
            continue

        # 表格
        if stripped.startswith('|') and stripped.endswith('|'):
            close_lists()
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                table_lines.append(lines[i].strip())
                i += 1
            if len(table_lines) >= 2:
                header = [c.strip() for c in table_lines[0].split('|')[1:-1]]
                body_rows = []
                for r in table_lines[2:]:
                    cells = [c.strip() for c in r.split('|')[1:-1]]
                    if cells:
                        body_rows.append(cells)
                if header and body_rows:
                    out.append('<table>')
                    out.append('<thead><tr>' + ''.join(f'<th>{inline(h)}</th>' for h in header) + '</tr></thead>')
                    out.append('<tbody>')
                    for row in body_rows:
                        out.append('<tr>' + ''.join(f'<td>{inline(c)}</td>' for c in row) + '</tr>')
                    out.append('</tbody></table>')
            continue

        # 无序列表
        m = re.match(r'^(\s*)[-*]\s+(.*)', raw)
        if m:
            if in_ol:
                out.append('</ol>')
                in_ol = False
            if not in_ul:
                out.append('<ul>')
                in_ul = True
            out.append(f'<li>{inline(m.group(2))}</li>')
            i += 1
            continue

        # 有序列表
        m = re.match(r'^(\s*)\d+\.\s+(.*)', raw)
        if m:
            if in_ul:
                out.append('</ul>')
                in_ul = False
            if not in_ol:
                out.append('<ol>')
                in_ol = True
            out.append(f'<li>{inline(m.group(2))}</li>')
            i += 1
            continue

        close_lists()

        # 引用
        if stripped.startswith('>'):
            out.append(f'<blockquote>{inline(stripped[1:].strip())}</blockquote>')
            i += 1
            continue

        # 标题
        if stripped.startswith('# '):
            out.append(f'<h1>{inline(stripped[2:])}</h1>')
            i += 1
            continue
        if stripped.startswith('## '):
            out.append(f'<h2>{inline(stripped[3:])}</h2>')
            i += 1
            continue
        if stripped.startswith('### '):
            out.append(f'<h3>{inline(stripped[4:])}</h3>')
            i += 1
            continue
        if stripped.startswith('#### '):
            out.append(f'<h4>{inline(stripped[5:])}</h4>')
            i += 1
            continue

        # 段落
        out.append(f'<p>{inline(line)}</p>')
        i += 1

    close_lists()
    return '\n'.join(out)


# P2 (§20.12): 新增 HTML 版人话报告端点，便于浏览器直接查看格式化的报告.
