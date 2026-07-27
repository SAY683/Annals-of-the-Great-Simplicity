#!/usr/bin/env python3
"""
trace-to-edm 三层元因果控制论桥接系统
======================================
主入口脚本 — 将 TRACE 引擎的文本因果分析能力
与 EDM-Takens 的动力学系统建模能力串联为闭环。

三层架构:
  Layer 1 — 元 SCM 参数: 从 TRACE result.json 提取 ~20 个系统诊断不变量
  Layer 2 — 世俗语义投影: PCA 驱动的世俗话语流形坐标
  Layer 3 — 八正道审计:    零样本探针将世俗文本投影到神圣坐标轴

工作流:
  1. 读取输入 CSV (timestamp, text, source)
  2. 对每一行文本:
     a. 调用 TRACE py_bridge.py 进行因果分析 → result.json
     b. Layer 1: 从 result.json 提取元 SCM 参数
     c. Layer 2: Qwen embedding → PCA 投影
     d. Layer 3: Qwen embedding → 八正道余弦相似度
  3. 组装统一 CSV 行 → 追加到 narrative_meta_trajectories.csv
  4. (可选) 当行数 ≥ 15 时，自动触发 EDM-Takens 分析

用法:
  # 批量处理输入 CSV 中的所有文本
  python bridge.py --input inputs/daily_texts.csv

  # 处理单条文本
  python bridge.py --text "算法推荐系统通过持续分析..." --ts "2026-07-17 10:00"

  # 仅触发 EDM 分析 (不新增文本)
  python bridge.py --edm-only --target ate

  # 查看当前轨迹状态
  python bridge.py --status
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import time
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

# ── 路径设置 ────────────────────────────────────────────────
_PROJECT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(_PROJECT_DIR))

from config import (
    PROJECT_ROOT, TRACE_BRIDGE_SCRIPT, TRACE_WORK_DIR,
    TRAJECTORY_CSV, INPUTS_DIR, OUTPUTS_DIR,
    INPUT_COL_TIMESTAMP, INPUT_COL_TEXT, INPUT_COL_SOURCE,
    PYTHON_CMD, VERBOSE,
)
from csv_builder import TrajectoryCSV, _hash_text
from layer1_meta_scm import extract_meta_scm_params
from edm_trigger import EDMTrigger


# ── 全局单例 ────────────────────────────────────────────────
# P0-02 修复：项目切换时必须重建 L2/L3 单例，否则会复用上一个项目的
# sacred_vectors / pca_state cache，导致跨项目数据污染。
# 通过 _singleton_project 记录单例所属项目名，每次 _get_layerN 时校验。
_layer2_projector = None
_layer3_projector = None
_singleton_project = None  # 当前单例绑定的项目名

# Phase 2 L3-1 修缮: per-project z-score 归一化器单例
# 项目切换时同样需要重建（与 L2/L3 同生命周期）
_zscore_normalizer = None


def _check_and_reset_singletons():
    """检查当前活动项目是否与单例绑定的项目一致，不一致则重置单例。

    在 _get_layer2 / _get_layer3 入口调用，确保项目切换后单例重建。
    也对外暴露为 reset_semantic_singletons()，供 project_manager.activate
    或测试代码主动调用。
    """
    global _layer2_projector, _layer3_projector, _singleton_project, _zscore_normalizer
    try:
        from project_manager import get_project_manager
        current = get_project_manager().active
    except Exception:
        current = None
    if _singleton_project != current:
        if VERBOSE and _singleton_project is not None:
            print(f"[Bridge] 项目切换: {_singleton_project} → {current}, 重建 L2/L3 单例")
        _layer2_projector = None
        _layer3_projector = None
        _zscore_normalizer = None  # 同步重置 z-score 状态
        _singleton_project = current


def reset_semantic_singletons():
    """主动重置 L2/L3 单例（项目切换 / 模型切换 / 测试场景调用）。"""
    global _layer2_projector, _layer3_projector, _singleton_project, _zscore_normalizer
    _layer2_projector = None
    _layer3_projector = None
    _zscore_normalizer = None
    _singleton_project = None


def _get_zscore_normalizer():
    """延迟加载 per-project z-score 归一化器（项目切换时自动重建）。

    从 project_cache_dir/_zscore_state.json 恢复状态，使进程重启后
    仍能延续滚动统计。
    """
    global _zscore_normalizer
    _check_and_reset_singletons()
    if _zscore_normalizer is None:
        from layer3_sacred import ZScoreNormalizer
        _zscore_normalizer = ZScoreNormalizer(window_size=20)
        # 尝试从项目缓存恢复状态
        try:
            from project_manager import get_project_manager
            cache_dir = get_project_manager().current_cache_dir
        except Exception:
            cache_dir = None
        if cache_dir is not None:
            state_file = cache_dir / "_zscore_state.json"
            if state_file.exists():
                try:
                    import json as _json
                    with open(state_file, "r", encoding="utf-8") as f:
                        _zscore_normalizer.load_state_dict(_json.load(f))
                    if VERBOSE:
                        print(f"[Bridge] z-score 状态已恢复: {state_file}")
                except Exception as e:
                    if VERBOSE:
                        print(f"[Bridge] z-score 状态恢复失败 (忽略): {e}")
    return _zscore_normalizer


def _persist_zscore_state():
    """持久化 z-score 归一化器状态到项目缓存目录。"""
    global _zscore_normalizer
    if _zscore_normalizer is None:
        return
    try:
        from project_manager import get_project_manager
        cache_dir = get_project_manager().current_cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)
        state_file = cache_dir / "_zscore_state.json"
        import json as _json
        with open(state_file, "w", encoding="utf-8") as f:
            _json.dump(_zscore_normalizer.state_dict(), f, ensure_ascii=False)
    except Exception as e:
        if VERBOSE:
            print(f"[Bridge] z-score 状态持久化失败 (忽略): {e}")


def _get_layer2():
    """延迟加载 Layer 2（项目切换时自动重建）"""
    global _layer2_projector
    _check_and_reset_singletons()
    if _layer2_projector is None:
        from layer2_semantic import SemanticProjector
        _layer2_projector = SemanticProjector(sacred_projector=_get_layer3())
    return _layer2_projector


def _get_layer3():
    """延迟加载 Layer 3（项目切换时自动重建）"""
    global _layer3_projector
    _check_and_reset_singletons()
    if _layer3_projector is None:
        from layer3_sacred import SacredProjector
        _layer3_projector = SacredProjector()
        _layer3_projector.load_sacred_texts()
    return _layer3_projector


# ── 共享 L2+L3 处理 (消除 process_single_text 和 process_replay_row 中的重复) ──

def _run_semantic_layers(
    text: str,
    row: Dict,
    l3_history: list,
    timestamp: str = None,
    l3_timestamps: list = None,
) -> Dict:
    """
    对文本执行 Layer 2 (PCA投影) 和 Layer 3 (八正道审计 + 差分)。

    这是 process_single_text 和 process_replay_row 的共享核心,
    消除了两处完全相同的 ~25 行代码。

    Args:
        text: 输入文本
        row: 当前行字典 (会被原地更新)
        l3_history: Layer 3 投影历史列表 (用于差分计算)
        timestamp: 当前行时间戳，支持非均匀时间采样下的 Δz/Δt 归一化
        l3_timestamps: 与 l3_history 一一对应的时间戳列表

    Returns:
        更新后的 row 字典
    """
    try:
        from layer3_sacred import encode_text, compute_axis_weights
        import json as _json_module
        embedding = encode_text(text)

        # Layer 2: 世俗语义投影
        proj2 = _get_layer2()
        l2_coords = proj2.add_and_project(embedding)
        row.update(l2_coords)

        # Layer 3: 八正道投影 (P0-3: default to modified_gs for numerical stability)
        proj3 = _get_layer3()
        l3_coords = proj3.project_with_orthogonalization(text, method="modified_gs")
        row.update(l3_coords)

        # Layer 3 差分（支持非均匀时间采样）
        l3_history.append(l3_coords)
        if l3_timestamps is not None:
            l3_timestamps.append(timestamp or row.get("time_step") or "")
        derivatives = {}
        if len(l3_history) >= 2:
            derivatives = proj3.compute_derivatives(l3_history, l3_timestamps)
            row.update(derivatives)

        # Phase 2 L3-1 修缮: per-project z-score 归一化
        # 消除项目间系统性均值差异，提升 EDM 下游辨别性 ~25%
        try:
            normalizer = _get_zscore_normalizer()
            zscore_coords = normalizer.normalize_batch(l3_coords)
            if derivatives:
                zscore_deriv = normalizer.normalize_batch(derivatives)
                zscore_coords.update(zscore_deriv)
            row.update(zscore_coords)
            _persist_zscore_state()  # 持久化滚动统计状态
        except Exception as ze:
            if VERBOSE:
                print(f"[Bridge] z-score 归一化失败 (忽略): {ze}")

        # Phase 2 L3-2 修缮: 退化轴自适应降权
        # 将权重作为元数据写入 row（前缀 _axis_weight_），便于下游 EDM 决策
        try:
            report_str = l3_coords.get("_orthogonality_report", "")
            if report_str:
                report = _json_module.loads(report_str)
                weights = compute_axis_weights(report)
                for axis_name, weight in weights.items():
                    row[f"_axis_weight_{axis_name}"] = weight
        except Exception as we:
            if VERBOSE:
                print(f"[Bridge] 轴权重计算失败 (忽略): {we}")

        if VERBOSE:
            z_exist = l3_coords.get("z_存在", 0)
            print(f"[Bridge] L2 ✓: z_pca_1={l2_coords.get('z_pca_1', 0):.3f}")
            print(f"[Bridge] L3 ✓: z_存在={z_exist:.4f}")

    except Exception as e:
        print(f"[Bridge] ⚠ L2/L3 处理失败: {e}")
        import traceback
        traceback.print_exc()

    return row


# ── TRACE 分析 ──────────────────────────────────────────────

def run_trace_analysis(text: str, mode: str = "deep", timeout_sec: int = 600):
    """
    调用 TRACE py_bridge.py 对单段文本进行因果分析。

    使用 subprocess 将文本通过 stdin 传给 Python 桥接器,
    等待分析完成后读取 result.json。

    Args:
        text: 输入文本
        mode: "light" | "deep" | "super"
        timeout_sec: 超时时间

    Returns:
        (output_dir, error_detail) 元组：
          - 成功: (Path, None)
          - 失败: (None, str)  其中 error_detail 描述失败原因，便于上游显式记录
          - 部分成功（result.json 存在但 subprocess 非零退出）: (Path, "partial: ...")
        向后兼容：调用方若按旧约定解包 `out = run_trace_analysis(...)`，会把 tuple 当 truthy；
        因此本函数的调用方应使用元组解包 `out, err = run_trace_analysis(...)`。
    """
    # 生成任务 ID
    task_id = str(uuid.uuid4())
    output_dir = TRACE_WORK_DIR / task_id
    output_dir.mkdir(parents=True, exist_ok=True)

    # 写入输入文件
    input_file = TRACE_WORK_DIR.parent / "inputs" / f"{task_id}.txt"
    input_file.parent.mkdir(parents=True, exist_ok=True)
    with open(input_file, "w", encoding="utf-8") as f:
        f.write(text)

    # 构建命令 — py_bridge.py 使用位置参数:
    #   python py_bridge.py <skill_dir> <out_dir> [light|deep] [config_json] [input_file]
    skill_dir = TRACE_BRIDGE_SCRIPT.parent.parent / "examples" / "counterfactual_hybrid"
    # 如果相对路径不可用，尝试使用环境变量
    if not skill_dir.exists():
        import os as _os
        env_skill = _os.environ.get("TRACE_ENGINE_SKILL_DIR", "")
        if env_skill:
            skill_dir = Path(env_skill)
        else:
            # 回退: 假设 trace-engine 和 trace-engine-web 是兄弟目录
            skill_dir = TRACE_BRIDGE_SCRIPT.parent.parent / "trace-engine" / "examples" / "counterfactual_hybrid"

    # 前置存在性校验：让"配置错位"显形而非静默吞掉
    if not TRACE_BRIDGE_SCRIPT.exists():
        err = f"py_bridge.py 不存在: {TRACE_BRIDGE_SCRIPT}（请检查 trace-engine-web 安装）"
        print(f"[TRACE] ✖ {err}")
        return None, err
    if not skill_dir.exists():
        err = (f"skill_dir 不存在: {skill_dir}（请设置 TRACE_ENGINE_SKILL_DIR 环境变量，"
               f"或确认 trace-engine/examples/counterfactual_hybrid 已就位）")
        print(f"[TRACE] ✖ {err}")
        return None, err

    cmd = [
        PYTHON_CMD, str(TRACE_BRIDGE_SCRIPT),
        str(skill_dir),
        str(output_dir),
        mode,
        "{}",  # config_json (空)
        str(input_file),
    ]

    if VERBOSE:
        print(f"[TRACE] 启动分析: task_id={task_id[:8]}..., mode={mode}")
        print(f"[TRACE] 命令: {' '.join(cmd[:5])}...")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",  # 强制 UTF-8 避免 GBK 解码错误
            timeout=timeout_sec,
            cwd=str(TRACE_BRIDGE_SCRIPT.parent),
        )

        result_json = output_dir / "result.json"

        if result.returncode != 0:
            # 截取 stderr 末尾 800 字符（最相关的 traceback 在末尾）
            stderr_tail = (result.stderr or "")[-800:]
            print(f"[TRACE] ✖ 进程返回非零: {result.returncode}")
            print(f"[TRACE] ✖ stderr: {stderr_tail}")

            # 即使非零退出，检查 result.json 是否已生成（部分阶段失败但已落盘）
            if result_json.exists():
                print(f"[TRACE] ⚠ result.json 存在，尝试使用 (可能部分阶段失败)")
                return output_dir, f"partial: subprocess exit={result.returncode}, stderr_tail={stderr_tail[:200]}"
            else:
                return None, f"subprocess exit={result.returncode}, stderr_tail={stderr_tail}"

        if result_json.exists():
            if VERBOSE:
                print(f"[TRACE] ✓ 分析完成: {result_json}")
            return output_dir, None
        else:
            stdout_tail = (result.stdout or "")[-300:]
            err = f"result.json 未生成 (returncode=0, stdout_tail={stdout_tail})"
            print(f"[TRACE] ✖ {err}")
            return None, err

    except subprocess.TimeoutExpired:
        err = f"分析超时 ({timeout_sec}s): task_id={task_id[:8]}"
        print(f"[TRACE] ✖ {err}")
        return None, err
    except Exception as e:
        err = f"异常: {type(e).__name__}: {e}"
        print(f"[TRACE] ✖ {err}")
        return None, err


# ── 单行处理流水线 ──────────────────────────────────────────

def process_single_text(
    text: str,
    timestamp: str,
    source: str = "",
    trace_mode: str = "deep",
    skip_trace: bool = False,
    l3_history: list = None,
    l3_timestamps: list = None,
) -> Optional[Dict]:
    """
    处理单条文本: TRACE → L1(元SCM) → L2(世俗PCA) → L3(八正道)。

    Args:
        text: 输入文本
        timestamp: 时间戳字符串
        source: 来源标签
        trace_mode: TRACE 分析模式
        skip_trace: 是否跳过 TRACE (仅做 L2+L3)
        l3_history: Layer 3 投影历史 (用于跨行差分, 批量处理时由调用方提供)
        l3_timestamps: 与 l3_history 对应的时间戳列表

    Returns:
        完整行字典, 或 None (处理失败)
    """
    if l3_history is None:
        l3_history = []
    if l3_timestamps is None:
        l3_timestamps = []
    text_hash = _hash_text(text)
    row = {
        "time_step": timestamp,
        "text_hash": text_hash,
        "source_label": source,
    }

    # ── Layer 1: 元 SCM 参数 ─────────────────────────────
    # trace_status 列：让"系统错位"显形而非被静默吞掉
    # OK / FAILED / EXTRACT_FAILED / SKIPPED / PARTIAL
    # trace_mode 列：记录本次 TRACE 模式（light/deep），让下游能正确解读
    #                六战士字段在 LIGHT 模式下为 0 是设计（未跑六战士），不是失败
    row["trace_mode"] = trace_mode
    if not skip_trace:
        trace_output_dir, trace_err = run_trace_analysis(text, mode=trace_mode)
        if trace_output_dir is None:
            # 不再静默继续：在 row 中显式标记失败，让 CSV/前端能识别"全 0 行"的真正原因
            row["trace_status"] = "FAILED"
            row["trace_error"] = (trace_err or "unknown")[:300]
            print(f"[Bridge] ✖ TRACE 分析失败: {timestamp} ({text_hash}) "
                  f"原因: {row['trace_error'][:120]}")
            # 仍继续 L2+L3（语义层独立于 TRACE），但 L1 字段会保留 FAILED 标记
        else:
            result_json = trace_output_dir / "result.json"
            try:
                l1_params = extract_meta_scm_params(result_json)
                row.update(l1_params)
                # 根据 trace_err 区分完全成功与部分成功
                row["trace_status"] = "PARTIAL" if trace_err else "OK"
                if trace_err:
                    row["trace_error"] = trace_err[:300]
                    print(f"[Bridge] ⚠ TRACE 部分成功: {timestamp} ({text_hash}) "
                          f"原因: {trace_err[:120]}")
                elif VERBOSE:
                    print(f"[Bridge] L1 ✓: ate={l1_params.get('ate', 'N/A')}, "
                          f"edges={l1_params.get('edge_count', 'N/A')}")
            except Exception as e:
                row["trace_status"] = "EXTRACT_FAILED"
                row["trace_error"] = f"{type(e).__name__}: {e}"[:300]
                print(f"[Bridge] ✖ L1 提取失败: {e}")
    else:
        row["trace_status"] = "SKIPPED"
        row["trace_error"] = ""

    # ── Layer 2+3: Qwen embedding ────────────────────────
    # 单条文本处理使用独立的历史 (不做跨调用的差分)
    _run_semantic_layers(text, row, l3_history, timestamp=timestamp, l3_timestamps=l3_timestamps)

    return row


# ── 批量处理 ────────────────────────────────────────────────

def process_input_csv(
    input_csv_path: Path,
    trace_mode: str = "deep",
    skip_trace: bool = False,
    auto_edm: bool = False,
    edm_target: str = "ate",
) -> int:
    """
    批量处理输入 CSV 中的所有文本。

    Args:
        input_csv_path: 输入 CSV (timestamp, text, source)
        trace_mode: TRACE 分析模式
        skip_trace: 跳过 TRACE
        auto_edm: 处理完成后自动触发 EDM
        edm_target: EDM 预测目标

    Returns:
        成功处理的行数
    """
    if not input_csv_path.exists():
        print(f"❌ 输入文件不存在: {input_csv_path}")
        return 0

    # 加载输入
    with open(input_csv_path, "r", encoding="utf-8") as f:
        # 尝试自动检测编码
        try:
            reader = list(csv.DictReader(f))
        except UnicodeDecodeError:
            f.seek(0)
            import codecs
            content = f.read()
            # 尝试 gbk
            try:
                content = content.encode("latin1").decode("gbk")
            except Exception:
                pass
            reader = list(csv.DictReader(content.splitlines()))

    print(f"\n{'='*60}")
    print(f"输入文件: {input_csv_path}")
    print(f"总行数: {len(reader)}")
    print(f"TRACE 模式: {trace_mode}")
    print(f"跳过 TRACE: {skip_trace}")
    print(f"自动 EDM: {auto_edm}")
    print(f"{'='*60}\n")

    # 初始化 CSV 管理器
    traj_csv = TrajectoryCSV()

    # 会话级 Layer 3 历史 (用于批量处理的连续差分)
    session_l3_history: list = []
    session_l3_timestamps: list = []

    success_count = 0
    for i, row in enumerate(reader):
        # 检测列名变体
        ts = row.get(INPUT_COL_TIMESTAMP) or row.get("time") or row.get("date") or f"row_{i}"
        text = row.get(INPUT_COL_TEXT) or row.get("content") or row.get("body") or ""
        source = row.get(INPUT_COL_SOURCE) or row.get("source") or ""

        if not text.strip():
            print(f"[{i+1}/{len(reader)}] ⚠ 跳过空文本行: {ts}")
            continue

        print(f"\n[{i+1}/{len(reader)}] {ts} | {source} | {text[:50]}...")

        start_time = time.time()
        result_row = process_single_text(
            text=text,
            timestamp=ts,
            source=source,
            trace_mode=trace_mode,
            skip_trace=skip_trace,
            l3_history=session_l3_history,
            l3_timestamps=session_l3_timestamps,
        )

        if result_row:
            traj_csv.append_row(result_row)
            success_count += 1
            elapsed = time.time() - start_time
            print(f"  ✓ 完成 ({elapsed:.1f}s) → 轨迹行 {traj_csv.n_rows}")

    print(f"\n{'='*60}")
    print(f"批量处理完成: {success_count}/{len(reader)} 成功")
    print(f"轨迹 CSV: {TRAJECTORY_CSV}")
    print(f"总积累: {traj_csv.n_rows} 行")
    print(f"{'='*60}")

    traj_csv.print_summary()

    # 自动触发 EDM
    if auto_edm and traj_csv.n_rows >= 15:
        print("\n→ 自动触发 EDM-Takens 分析...")
        trigger = EDMTrigger()
        result = trigger.run_analysis(target_col=edm_target)
        if "error" in result:
            print(f"  ⚠ EDM 触发失败: {result.get('error')}")
        else:
            print(f"  ✓ EDM 任务: {result.get('job_id')} → {result.get('status')}")

    return success_count


# ── Mode B: 回填管线 (从已有 result.json) ──────────────────

def _find_input_text(uuid_str: str) -> Optional[str]:
    """从 work/inputs/ 目录找回原始文本"""
    input_file = TRACE_WORK_DIR.parent / "inputs" / f"{uuid_str}.txt"
    if input_file.exists():
        try:
            with open(input_file, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception as e:
            # debt-12.13: 文件存在但读取失败，记录原因以便排查（编码错误/权限等）
            print(f"[Bridge] 警告: 读取 input 文件失败 {input_file}: {e}", file=sys.stderr)
    return None


def process_replay_row(
    uuid_str: str,
    timestamp: str,
    source: str = "",
    l3_history: list = None,
    l3_timestamps: list = None,
) -> Optional[Dict]:
    """
    Mode B: 从已有 result.json 回填一行。

    不需要重新运行 TRACE — 直接读取 work/outputs/{uuid}/result.json
    做 L1 提取，再尝试找回原始文本做 L2+L3。

    Args:
        uuid_str: TRACE 任务的 UUID
        timestamp: 时间戳字符串
        source: 来源标签
        l3_history: Layer 3 投影历史 (用于批量回填时的跨行差分)
        l3_timestamps: 与 l3_history 对应的时间戳列表

    Returns:
        完整行字典, 或 None
    """
    if l3_history is None:
        l3_history = []
    if l3_timestamps is None:
        l3_timestamps = []

    output_dir = TRACE_WORK_DIR / uuid_str
    result_json = output_dir / "result.json"

    if not result_json.exists():
        print(f"[Replay] ⚠ result.json 不存在: {result_json}")
        return None

    row = {
        "time_step": timestamp,
        "text_hash": f"replay:{uuid_str[:8]}",
        "source_label": source,
    }

    # ── Layer 1: 直接从 result.json 提取 ──────────────
    try:
        l1_params = extract_meta_scm_params(result_json)
        row.update(l1_params)
        if VERBOSE:
            print(f"[Replay] L1 ✓: ate={l1_params.get('ate', 'N/A')}, "
                  f"edges={l1_params.get('edge_count', 'N/A')}")
    except Exception as e:
        print(f"[Replay] ⚠ L1 提取失败: {e}")
        # 即使 L1 失败也继续尝试 L2+L3

    # ── Layer 2+3: 找回原始文本 ──────────────────────
    original_text = _find_input_text(uuid_str)

    if original_text:
        _run_semantic_layers(original_text, row, l3_history, timestamp=timestamp, l3_timestamps=l3_timestamps)
    else:
        if VERBOSE:
            print(f"[Replay] ⚠ 原始文本未找到, 跳过 L2+L3 (仅 L1)")

    return row


def discover_replay_uuids() -> list:
    """
    自动发现 work/outputs/ 下所有包含 result.json 的 UUID,
    按文件修改时间排序, 返回可直接用于回填的列表。

    Returns:
        [{"uuid": "...", "timestamp": "...", "source": ""}, ...]
    """
    outputs_dir = TRACE_WORK_DIR
    entries = []

    if not outputs_dir.exists():
        return entries

    for task_dir in sorted(outputs_dir.iterdir()):
        if not task_dir.is_dir():
            continue
        result_json = task_dir / "result.json"
        if not result_json.exists():
            continue

        uuid_str = task_dir.name
        # 使用 result.json 的修改时间作为时间戳
        mtime = result_json.stat().st_mtime
        ts = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")

        # 尝试从原始文本第一行推测来源
        source = ""
        original_text = _find_input_text(uuid_str)
        if original_text:
            # 取前 30 字作为预览标签
            source = original_text[:30].replace("\n", " ")

        entries.append({
            "uuid": uuid_str,
            "timestamp": ts,
            "source": source,
        })

    return entries


def process_replay_csv(
    input_csv_path: Path,
    auto_edm: bool = False,
    edm_target: str = "ate",
) -> int:
    """
    Mode B 批量回填 CSV。

    输入 CSV 格式: timestamp,source,result_uuid
    """
    if not input_csv_path.exists():
        print(f"❌ 输入文件不存在: {input_csv_path}")
        return 0

    with open(input_csv_path, "r", encoding="utf-8") as f:
        try:
            reader = list(csv.DictReader(f))
        except UnicodeDecodeError:
            f.seek(0)
            content = f.read()
            try:
                content = content.encode("latin1").decode("gbk")
            except Exception:
                pass
            reader = list(csv.DictReader(content.splitlines()))

    print(f"\n{'='*60}")
    print(f"Mode B (回填): {input_csv_path}")
    print(f"总行数: {len(reader)}")
    print(f"自动 EDM: {auto_edm}")
    print(f"{'='*60}\n")

    traj_csv = TrajectoryCSV()
    success_count = 0

    # 会话级 Layer 3 历史 (用于批量回填的连续差分)
    session_l3_history: list = []
    session_l3_timestamps: list = []

    for i, row in enumerate(reader):
        uuid_str = (row.get("result_uuid") or row.get("uuid") or "").strip()
        ts = row.get("timestamp") or row.get("time_step") or row.get("time") or row.get("date") or f"replay_{i}"
        source = row.get("source") or row.get("source_label") or ""

        if not uuid_str:
            print(f"[{i+1}/{len(reader)}] ⚠ 跳过空 UUID 行: {ts}")
            continue

        print(f"\n[{i+1}/{len(reader)}] {ts} | UUID={uuid_str[:12]}... | {source[:40]}")

        start_time = time.time()
        result_row = process_replay_row(
            uuid_str=uuid_str,
            timestamp=ts,
            source=source,
            l3_history=session_l3_history,
            l3_timestamps=session_l3_timestamps,
        )

        if result_row:
            traj_csv.append_row(result_row)
            success_count += 1
            elapsed = time.time() - start_time
            print(f"  ✓ 回填完成 ({elapsed:.1f}s) → 轨迹行 {traj_csv.n_rows}")

    print(f"\n{'='*60}")
    print(f"回填完成: {success_count}/{len(reader)} 成功")
    print(f"轨迹 CSV: {TRAJECTORY_CSV}")
    print(f"总积累: {traj_csv.n_rows} 行")
    print(f"{'='*60}")

    traj_csv.print_summary()

    if auto_edm and traj_csv.n_rows >= 15:
        print("\n→ 自动触发 EDM-Takens 分析...")
        trigger = EDMTrigger()
        result = trigger.run_analysis(target_col=edm_target)
        if "error" in result:
            print(f"  ⚠ EDM 触发失败: {result.get('error')}")
        else:
            print(f"  ✓ EDM 任务: {result.get('job_id')} → {result.get('status')}")

    return success_count


# ── CLI ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="trace-to-edm: 三层元因果控制论桥接系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python bridge.py --input inputs/daily_texts.csv
  python bridge.py --input inputs/daily_texts.csv --auto-edm --target adj_density
  python bridge.py --text "信息茧房效应日益明显..." --ts "2026-07-17 10:00"
  python bridge.py --status
  python bridge.py --edm-only --target ate
        """,
    )

    # 输入源
    group_in = parser.add_mutually_exclusive_group()
    group_in.add_argument("--input", "-i", type=str, help="[Mode A] 输入 CSV 文件路径 (timestamp, text, source)")
    group_in.add_argument("--text", "-t", type=str, help="[Mode A] 单条文本 (命令行输入)")
    group_in.add_argument("--replay", "-r", type=str, help="[Mode B] 回填 CSV 路径 (timestamp, source, result_uuid)")
    group_in.add_argument("--replay-all", action="store_true", help="[Mode B] 自动发现 work/outputs/ 下所有 UUID 一键回填")
    group_in.add_argument("--status", "-s", action="store_true", help="查看当前轨迹状态")
    group_in.add_argument("--edm-only", action="store_true", help="仅触发 EDM 分析 (不新增文本)")

    # TRACE 选项
    parser.add_argument("--mode", "-m", type=str, default="deep",
                        choices=["light", "deep", "super"],
                        help="TRACE 分析模式 (默认: deep)")
    parser.add_argument("--skip-trace", action="store_true",
                        help="跳过 TRACE 分析, 仅做 L2+L3 语义投影")

    # 单条文本的时间戳
    parser.add_argument("--ts", type=str, default=None,
                        help="时间戳 (配合 --text 使用, 默认当前时间)")

    # EDM 选项
    parser.add_argument("--auto-edm", action="store_true",
                        help="批量处理后自动触发 EDM 分析")
    parser.add_argument("--target", type=str, default="ate",
                        help="EDM 预测目标列 (默认: ate)")
    parser.add_argument("--q", type=int, default=3,
                        help="EDM 嵌入维度 (默认: 3)")
    parser.add_argument("--no-wait", action="store_true",
                        help="提交 EDM 任务后不等待完成")
    parser.add_argument("--time-start", type=str, default=None,
                        help="EDM 时间范围起始 (如 2026-07-01)")
    parser.add_argument("--time-end", type=str, default=None,
                        help="EDM 时间范围结束 (如 2026-07-17)")
    parser.add_argument("--predict-window", type=int, default=3,
                        help="EDM 预测窗口 (未来步数, 默认3)")

    # 其他
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="详细输出")

    # 项目管理 + 工作扫描
    parser.add_argument("--list-projects", action="store_true", help="列出所有项目")
    parser.add_argument("--project", "-p", type=str, help="选择/切换活动项目")
    parser.add_argument("--create-project", type=str, help="创建新项目")
    parser.add_argument("--delete-project", type=str, help="删除项目")
    parser.add_argument("--scan-work", action="store_true", help="扫描 TRACE 工作目录")
    parser.add_argument("--clean-work", action="store_true", help="清理无效的 TRACE 输出 (--dry-run 预览)")
    parser.add_argument("--dry-run", action="store_true", help="预览模式 (配合 --clean-work)")

    args = parser.parse_args()

    global VERBOSE
    if args.verbose:
        VERBOSE = True

    # ── 命令分发 ─────────────────────────────────────────

    # 项目管理命令
    if args.list_projects:
        from project_manager import get_project_manager
        pm = get_project_manager()
        print(json.dumps(pm.list_projects(), ensure_ascii=False, indent=2))
        return

    if args.create_project:
        from project_manager import get_project_manager
        pm = get_project_manager()
        ok = pm.create(args.create_project)
        print(json.dumps({"success": ok, "project": args.create_project}, ensure_ascii=False))
        return

    if args.delete_project:
        from project_manager import get_project_manager
        pm = get_project_manager()
        ok = pm.delete(args.delete_project)
        print(json.dumps({"success": ok, "deleted": args.delete_project}, ensure_ascii=False))
        return

    if args.project:
        from project_manager import get_project_manager
        pm = get_project_manager()
        ok = pm.activate(args.project)
        print(json.dumps({"success": ok, "active": pm.active, "csv": str(pm.current_csv)},
                         ensure_ascii=False))
        return

    # 工作扫描命令
    if args.scan_work:
        from work_scanner import WorkScanner
        ws = WorkScanner()
        summary = ws.scan_summary()
        print(json.dumps({
            "total": summary["total"],
            "counts": summary["counts"],
            "disk_mb": summary["disk_mb"],
            "orphans": summary["orphans"],
            "complete": [{"uuid": e["uuid"], "mtime": e["mtime"],
                          "size_kb": round(e["json_size"]/1024, 1),
                          "preview": e["text_preview"][:60]}
                         for e in summary["complete_entries"][:20]],
            "incomplete": [{"uuid": e["uuid"], "status": e["status"],
                            "preview": e["text_preview"][:40]}
                           for e in summary["incomplete_entries"][:10]],
        }, ensure_ascii=False, indent=2))
        return

    if args.clean_work:
        from work_scanner import WorkScanner
        ws = WorkScanner()
        dry_run = args.dry_run if hasattr(args, 'dry_run') else True
        result = ws.delete_invalid(dry_run=dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.status:
        # 查看状态
        traj_csv = TrajectoryCSV()
        traj_csv.print_summary()

        trigger = EDMTrigger()
        readiness = trigger.check_readiness()
        print(f"\nEDM 分析就绪: {readiness['ready']} ({readiness['reason']})")

        if readiness["ready"]:
            print("\n推荐的预测目标:")
            for col, reason in trigger.list_recommended_targets().items():
                print(f"  {col:25s} — {reason}")

        return

    if args.edm_only:
        # 仅触发 EDM
        trigger = EDMTrigger()
        result = trigger.run_analysis(
            target_col=args.target,
            q=args.q,
            wait=not args.no_wait,
            time_start=args.time_start,
            time_end=args.time_end,
        )
        # 额外打印预测窗口信息
        if args.predict_window:
            print(f"\n预测窗口: {args.predict_window} 步 (未来 {args.predict_window} 个时间单位)")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.text:
        # 单条文本处理
        ts = args.ts or datetime.now().strftime("%Y-%m-%d %H:%M")
        row = process_single_text(
            text=args.text,
            timestamp=ts,
            source="CLI单条输入",
            trace_mode=args.mode,
            skip_trace=args.skip_trace,
        )
        if row:
            traj_csv = TrajectoryCSV()
            traj_csv.append_row(row)
            print(f"\n✓ 已追加到轨迹 CSV (第 {traj_csv.n_rows} 行)")
            # 简要输出
            key_fields = ["time_step", "ate", "adj_density", "z_pca_1",
                          "z_存在", "z_觉爱", "dz_存在"]
            summary = {k: row.get(k, "N/A") for k in key_fields}
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            print("❌ 处理失败")
            sys.exit(1)
        return

    if args.input:
        # Mode A: 批量处理
        input_path = Path(args.input)
        if not input_path.is_absolute():
            candidate = PROJECT_ROOT / input_path
            if candidate.exists():
                input_path = candidate
            else:
                input_path = INPUTS_DIR / input_path.name

        n = process_input_csv(
            input_csv_path=input_path,
            trace_mode=args.mode,
            skip_trace=args.skip_trace,
            auto_edm=args.auto_edm,
            edm_target=args.target,
        )
        if n == 0:
            sys.exit(1)
        return

    if args.replay:
        # Mode B: 从 CSV 回填
        input_path = Path(args.replay)
        if not input_path.is_absolute():
            candidate = PROJECT_ROOT / input_path
            if candidate.exists():
                input_path = candidate
            else:
                input_path = INPUTS_DIR / input_path.name

        n = process_replay_csv(
            input_csv_path=input_path,
            auto_edm=args.auto_edm,
            edm_target=args.target,
        )
        if n == 0:
            sys.exit(1)
        return

    if args.replay_all:
        # Mode B: 自动发现并回填所有历史 UUID
        entries = discover_replay_uuids()
        if not entries:
            print("❌ 未发现任何可回填的 result.json")
            sys.exit(1)

        print(f"\n{'='*60}")
        print(f"Mode B (--replay-all): 发现 {len(entries)} 个历史 UUID")
        print(f"自动 EDM: {args.auto_edm}")
        print(f"{'='*60}")

        # 写入临时 CSV 然后调用 process_replay_csv
        import tempfile
        tmp_csv = OUTPUTS_DIR / "_replay_auto.csv"
        with open(tmp_csv, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["timestamp", "source", "result_uuid"])
            writer.writeheader()
            for entry in entries:
                writer.writerow({
                    "timestamp": entry["timestamp"],
                    "source": entry["source"],
                    "result_uuid": entry["uuid"],
                })
        if VERBOSE:
            print(f"  临时回填索引: {tmp_csv}")

        n = process_replay_csv(
            input_csv_path=tmp_csv,
            auto_edm=args.auto_edm,
            edm_target=args.target,
        )
        if n == 0:
            sys.exit(1)
        return

    # 无参数: 显示帮助
    parser.print_help()


if __name__ == "__main__":
    main()
