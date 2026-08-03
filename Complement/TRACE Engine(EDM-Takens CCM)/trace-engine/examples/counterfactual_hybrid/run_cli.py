#!/usr/bin/env python3
"""
因果战队 CLI — 六合一管线统一入口
===================================
Counterfactual Sentai — Six-in-One Pipeline CLI

对标 edm-takens/examples/*/run_analysis.py 的自洽设计：
- 自动检测 graphviz 并配置 PATH
- 自动检测 DoWhy/causallearn 可用性
- 子命令: demo (模拟数据), real (真实 TRACE 数据), clean (清理输出)

用法:
    # 模拟数据演示 (无需 GPU/模型)
    PYTHONIOENCODING=utf-8 python run_cli.py demo

    # 真实 TRACE 数据管线 (需要 Shehui-LLaMA 模型 + PyTorch)
    PYTHONIOENCODING=utf-8 python run_cli.py real

    # 查看环境状态
    python run_cli.py env

    # 清理输出
    python run_cli.py clean

环境变量:
    TRACE_ROOT          TRACE 项目根目录 (默认: 从 Skill 向上探测 TRACE/)
    GRAPHVIZ_BIN_DIR    Graphviz bin 目录 (仅通过环境变量配置)
"""

import sys
import os
import logging
import subprocess
from datetime import datetime
from pathlib import Path

# ══════════════════════════════════════════════════════════════════════
# 引入共享终端主题模块
# ══════════════════════════════════════════════════════════════════════

SHARED_DIR = Path(__file__).resolve().parents[3] / "shared"
sys.path.insert(0, str(SHARED_DIR))
from terminal_theme import (
    T, print_header, print_ascii_logo, log_stage, log_info, log_warn, log_error, log_done,
    stage_bar, verdict_panel, metric_line
)

from _config import setup_graphviz
from project_paths import resolve_paths
from presets import load_presets
from pipeline_helpers import run_full_pipeline


# 简洁的 ASCII 战队标识
# P1-H 修复 (ROUND27 12维度核对): 使用 raw string 避免 \| \_ \ 等无效转义序列
# 触发 SyntaxWarning (Python 3.12+ 升级为 DeprecationWarning, 未来版本变为 SyntaxError)
ASCII_LOGO = [
    r"    ____  _____  ___   ___   ___  _   _ ",
    r"   / __ \|  __ \|__ \ / _ \ / _ \| \ | |",
    r"  | |  | | |__) |  ) | | | | | | |  \| |",
    r"  | |  | | _  /  / /| | | | | | | . ` |",
    r"  | |__| | | \ \ / /_| |_| | |_| | |\  |",
    r"   \____/|_|  \_\____|\___/ \___/|_| \_|",
    r"        COUNTERFACTUAL SENTAI v1.0      ",
]


# ══════════════════════════════════════════════════════════════════════
# 路径配置
# ══════════════════════════════════════════════════════════════════════

SKILL_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SKILL_DIR / "outputs"
DEMO_DIR = OUTPUT_DIR / "demo"
REAL_DIR = OUTPUT_DIR / "real"
CACHE_DIR = OUTPUT_DIR / "cache"

# 确保目录存在
for d in [DEMO_DIR, REAL_DIR, CACHE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ══════════════════════════════════════════════════════════════════════
# 环境自检
# ══════════════════════════════════════════════════════════════════════

def _setup_graphviz():
    """通过环境变量 GRAPHVIZ_BIN_DIR 配置 graphviz PATH。

    debt-05: PATH 配置逻辑统一委托给 _config.setup_graphviz()，
    使用 os.pathsep 跨平台分隔符（替代原硬编码的 ';'）。
    保留本包装函数以维持 cmd_env/cmd_demo/cmd_real 的调用契约。
    """
    return setup_graphviz()

def cmd_env():
    """打印环境状态"""
    print_header("因果战队 CLI · 环境状态", dept="ANALYSIS", subtitle="Sentai Environment Diagnostics")
    print_ascii_logo(ASCII_LOGO, dept="ANALYSIS")

    # Python
    log_info(f"Python: {sys.version.split()[0]}")

    # Graphviz
    gv = _setup_graphviz()
    if gv:
        try:
            result = subprocess.run(['dot', '-V'], capture_output=True, text=True, timeout=5)
            ver = result.stderr.strip() if result.stderr else result.stdout.strip()
            log_info(f"Graphviz OK  ({ver})  [{gv}]")
        except Exception:
            log_warn(f"Graphviz bin found but dot -V failed  [{gv}]")
    else:
        log_error(f"Graphviz not found  (下载: https://graphviz.org/download/)")

    # Core deps
    for mod, name in [('numpy', 'NumPy'), ('torch', 'PyTorch'), ('transformers', 'Transformers')]:
        try:
            m = __import__(mod)
            ver = getattr(m, '__version__', '?')
            log_info(f"{name}: {ver}")
        except ImportError:
            log_error(f"{name}: 未安装")

    # Causal deps
    for mod, name in [('dowhy', 'DoWhy'), ('causallearn', 'causal-learn'),
                       ('networkx', 'NetworkX'), ('pandas', 'Pandas'),
                       ('statsmodels', 'StatsModels'), ('sklearn', 'Scikit-learn'),
                       ('matplotlib', 'Matplotlib'), ('graphviz', 'Graphviz(Py)')]:
        try:
            m = __import__(mod)
            ver = getattr(m, '__version__', '?')
            log_info(f"{name}: {ver}")
        except ImportError:
            log_error(f"{name}: 未安装")

    # Models (通过 _paths 解析，支持 TRACE_ROOT 环境变量)
    try:
        paths = resolve_paths()
        for model_name in ['shehui-llama', 'shenji-llama']:
            model_dir = paths.model_dir(model_name)
            if model_dir.exists():
                safetensors = list(model_dir.glob("model.safetensors"))
                size_mb = safetensors[0].stat().st_size / 1e6 if safetensors else 0
                log_info(f"{model_name}: ({size_mb:.0f}MB)")
            else:
                log_error(f"{model_name}: 未找到")
    except FileNotFoundError as e:
        log_error(f"模型检测: {e}")

    # Outputs
    for label, d in [('demo', DEMO_DIR), ('real', REAL_DIR), ('cache', CACHE_DIR)]:
        files = list(d.glob('*'))
        log_info(f"outputs/{label}: {len(files)} files")

    print()


# ══════════════════════════════════════════════════════════════════════
# 子命令
# ══════════════════════════════════════════════════════════════════════

def cmd_demo():
    """运行模拟数据演示管线"""
    print_header("因果战队 · 模拟数据演示", dept="ANALYSIS", subtitle="Demo Simulation")
    print_ascii_logo(ASCII_LOGO, dept="ANALYSIS")

    stage_bar(["IDENTIFY", "ESTIMATE", "REFUTE", "COUNTERFACTUAL", "REPORT"], current="IDENTIFY")

    _setup_graphviz()

    import numpy as np
    sys.path.insert(0, str(SKILL_DIR))
    from counterfactual_bridge import TRACE2DoWhy, DoWhy14Adapter
    from dowhy_auditor import DoWhyAuditor
    from enhanced_viz import render_dashboard

    # 模拟数据 ("算法推荐与信息茧房" 论证文)
    CONCEPTS = ['算法推荐', '用户行为', '信息茧房', '观点极化', '社会共识', '公共讨论', '透明度']
    ADJ = np.array([[0,3.21,8.47,0,0,0,0],[0,0,5.33,0,0,0,0],[0,0,0,7.12,0,1.85,0],
        [0,0,0,0,6.50,2.10,0],[0,0,0,0,0,4.33,0],[0,0,2.95,0,0,0,0],[0,0,3.10,0,1.20,2.80,0]])
    TOKENS = (['算法推荐']*3+['用户行为']*2+['信息茧房']*5+['观点极化']*4+
              ['社会共识']*3+['公共讨论']*4+['透明度']*3+['的']*3+['导致']*2+['从而']*1)
    n_tokens=len(TOKENS); adj=np.zeros((n_tokens,n_tokens))
    pos={c:[i for i,t in enumerate(TOKENS) if t==c] for c in CONCEPTS}
    for ci,cs in enumerate(CONCEPTS):
        for cj,cd in enumerate(CONCEPTS):
            if ADJ[ci,cj]>0:
                for si in pos[cs]:
                    for sj in pos[cd]:
                        if si<sj: adj[si,sj]=ADJ[ci,cj]

    log_stage("TRACE → DoWhy 桥接 + 全管线（聚合→建模→识别→估计→反驳→反事实）")
    # 加载 demo 预设参数，避免硬编码绕过 presets.yaml
    demo_preset = load_presets("demo")
    bridge = TRACE2DoWhy(
        adj, TOKENS,
        threshold=demo_preset.trace2dowhy.threshold,
        concept_min_freq=demo_preset.trace2dowhy.concept_min_freq,
        max_edges_for_dowhy=demo_preset.trace2dowhy.max_edges_for_dowhy,
    )
    # debt-05: 管线核心序列抽取到 pipeline_helpers.run_full_pipeline（双轨入口合并）
    run_full_pipeline(
        bridge,
        preset=demo_preset,
        identify_kwargs={'treatment': '算法推荐', 'outcome': '信息茧房'},
        n_top_edges=5,
    )
    log_info(f"概念: {len(bridge.concept_names)} → 边: {len(bridge.significant_edges)}")
    for i, e in enumerate(bridge.significant_edges[:5]):
        metric_line(f"{i+1}. {e[0]} → {e[1]}", e[2])

    log_stage("效应估计 + 反驳结果")
    est = bridge.estimate_result
    ci = DoWhy14Adapter.get_confidence_interval(est)
    log_info(f"{bridge.treatment} → {bridge.outcome}")
    metric_line("ATE", est.value)
    log_info(f"95% CI=[{ci[0]:.4f}, {ci[1]:.4f}]")

    log_stage("反事实扫描结果")
    for r in bridge.scan_results[:5]:
        metric_line(f"{r['source']}→{r['target']}", r['ite'])

    log_stage("审计防火墙")
    auditor = DoWhyAuditor(bridge)
    audit = auditor.audit('full')
    verdict_panel(audit.verdict, audit.n_pass, audit.n_warn, audit.n_fail)

    log_stage("生成输出")
    # Dashboard
    dash_path = render_dashboard(bridge, str(DEMO_DIR / "dashboard.png"), dpi=150)
    log_info(f"仪表板: {dash_path}")
    # DOT graph
    gv_path = bridge.visualize(str(DEMO_DIR / "causal_graph"), format="png")
    log_info(f"DAG: {gv_path}")
    # Report
    report = bridge.report()
    (DEMO_DIR / "report.md").write_text(report, encoding='utf-8')
    log_info(f"报告: {DEMO_DIR / 'report.md'} ({len(report)} chars)")

    log_done(f"完成 — 输出在 {DEMO_DIR}")


def cmd_real(preset="llama"):
    """运行真实 TRACE 数据管线

    Parameters
    ----------
    preset : str
        使用的参数预设。真实 TRACE 数据默认使用 llama 预设（threshold=0.01），
        以适配 Shehui/Shenji-LLaMA V4 过拟合模型的低 ΔNLL 范围。
    """
    import json, numpy as np
    from _logging import setup_logging, log_env_info
    from project_paths import resolve_paths

    paths = resolve_paths()
    logger = setup_logging(paths.outputs_dir / "logs", "sentai_real")
    log_env_info(logger)

    # 加载 preset（llama 为 V4 过拟合模型专属）
    try:
        p = load_presets(preset)
    except Exception as e:
        logger.warning(f"加载预设 {preset} 失败: {e}，回退到 llama")
        p = load_presets("llama")

    print_header("因果战队 · 真实 TRACE 数据管线", dept="ANALYSIS", subtitle=f"Preset: {preset}")
    print_ascii_logo(ASCII_LOGO, dept="ANALYSIS")

    stage_bar(["IDENTIFY", "ESTIMATE", "REFUTE", "COUNTERFACTUAL", "SIX-WARRIOR", "AUDIT", "REPORT"], current="IDENTIFY")

    metric_line("threshold", p.trace2dowhy.threshold)
    print()

    _setup_graphviz()

    # 检查是否有缓存的 TRACE 结果
    adj_cache = CACHE_DIR / "real_adj.npy"
    tokens_cache = CACHE_DIR / "real_tokens.json"
    meta_cache = CACHE_DIR / "real_cache_meta.json"

    if not adj_cache.exists() or not tokens_cache.exists():
        log_warn(f"未找到 TRACE 缓存文件 ({CACHE_DIR})")
        log_info("请先运行 TRACE 管线生成缓存，或运行:")
        log_info("  python run_real_pipeline.py")
        return

    # MOD-01: 缓存版本检查 — 基于文本 hash 检测缓存失效
    import hashlib, json as _json
    def _compute_text_hash(filepath):
        h = hashlib.sha256()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest()[:16]

    if meta_cache.exists():
        try:
            meta = _json.loads(meta_cache.read_text(encoding='utf-8'))
            cached_hash = meta.get('text_hash', '')
            # 尝试找到当前文本文件
            data_dir = paths.data_dir()
            current_text = None
            candidate = data_dir / meta.get('text_file', '政治意识.txt')
            if candidate.exists():
                current_text = candidate
            else:
                txts = list(data_dir.rglob("*.txt")) if data_dir.exists() else []
                if txts:
                    current_text = txts[0]
            if current_text and cached_hash:
                current_hash = _compute_text_hash(current_text)
                if current_hash != cached_hash:
                    log_warn(f"TRACE 缓存已失效（文本内容变更: {cached_hash} → {current_hash}）")
                    log_info("请重新运行: python run_real_pipeline.py")
                    return
                # P1-6 修复 (Round 27 审计): 比对 model_dir，模型切换后缓存失效。
                # 原实现仅比对 text_hash，切换模型（如 shehui→shenji）后仍复用旧 adj.npy，
                # 导致错误的因果边集。当前模型来自 TRACE_MODEL_DIR 环境变量（若设置）。
                cached_model = meta.get('model_dir', '')
                _cur_model_env = __import__('os').environ.get('TRACE_MODEL_DIR', '')
                if _cur_model_env and cached_model:
                    _cur_model_name = __import__('pathlib').Path(_cur_model_env).name
                    if cached_model != _cur_model_name:
                        log_warn(f"TRACE 缓存已失效（模型变更: {cached_model} → {_cur_model_name}）")
                        log_info("请重新运行: python run_real_pipeline.py")
                        return
                log_info(f"TRACE 缓存有效 (hash={cached_hash})")
        except Exception as e:
            log_warn(f"缓存元数据读取失败 ({e})，继续使用缓存")
    else:
        log_warn("未找到缓存元数据 (real_cache_meta.json)，建议重新运行 run_real_pipeline.py")

    import numpy as np, json
    sys.path.insert(0, str(SKILL_DIR))
    from counterfactual_bridge import TRACE2DoWhy, DoWhy14Adapter
    from dowhy_auditor import DoWhyAuditor
    from six_warriors import assemble_all_six, render_six_panel_report
    from six_panel_viz import render_chart_suite
    from collections import Counter

    adj = np.load(str(adj_cache))
    tokens = json.loads(tokens_cache.read_text(encoding='utf-8'))

    log_stage("TRACE → DoWhy 桥接 + 全管线（聚合→建模→识别→估计→反驳→反事实）")
    logger.info(
        f"TRACE→DoWhy: threshold={p.trace2dowhy.threshold}, "
        f"min_freq={p.trace2dowhy.concept_min_freq}, "
        f"max_edges={p.trace2dowhy.max_edges_for_dowhy}"
    )
    bridge = TRACE2DoWhy(
        adj, tokens,
        threshold=p.trace2dowhy.threshold,
        concept_min_freq=p.trace2dowhy.concept_min_freq,
        max_edges_for_dowhy=p.trace2dowhy.max_edges_for_dowhy,
        filter_mode=p.trace2dowhy.filter_mode,
        filter_percentile=p.trace2dowhy.filter_percentile,
        random_state=p.trace2dowhy.random_state,
        classical_mode=getattr(p.trace2dowhy, 'classical_mode', False),
        # P1-1/P1-2 修复 (Round 27 审计): 传入 dowhy/counterfactual section 参数，
        # 否则 presets.yaml 中的 refutation_deviation_threshold / sem_regularization / sem_alpha 永不生效。
        refutation_deviation_threshold=getattr(p.get('dowhy') or {}, 'refutation_deviation_threshold', 0.3),
        sem_regularization=getattr(p.get('counterfactual') or {}, 'sem_regularization', None),
        sem_alpha=getattr(p.get('counterfactual') or {}, 'sem_alpha', 0.01),
    )
    # debt-05: 管线核心序列抽取到 pipeline_helpers.run_full_pipeline（双轨入口合并）
    run_full_pipeline(bridge, preset=p)
    logger.info(f"Concepts: {len(bridge.concept_names)}, Edges: {len(bridge.significant_edges)}, Mode: {bridge.mode_name}")
    log_info(f"Tokens: {len(tokens)} → Concepts: {len(bridge.concept_names)} → Edges: {len(bridge.significant_edges)}")
    log_info(f"Mode: {bridge.mode_name}")
    for i, e in enumerate(bridge.significant_edges[:6]):
        metric_line(f"{i+1}. {e[0]:12s} → {e[1]:12s}", e[2])

    log_stage("效应估计 + 反驳结果")
    est = bridge.estimate_result
    ci = DoWhy14Adapter.get_confidence_interval(est)
    logger.info(f"ATE={est.value:.4f}, CI=[{ci[0]:.4f},{ci[1]:.4f}]")
    log_info(f"{bridge.treatment} → {bridge.outcome}")
    metric_line("ATE", est.value)
    log_info(f"95% CI=[{ci[0]:.4f}, {ci[1]:.4f}]")

    log_stage("反事实扫描结果")
    # scan_results 已由 run_full_pipeline 计算

    log_stage("六战士合体")
    cards = assemble_all_six(adj, tokens, bridge=bridge)
    # debt-04 audit 修复：将六战士卡片注入 bridge，激活 report() 中的复合诊断引擎
    bridge.set_six_warriors_cards(cards)
    logger.info(f"Six warriors: {', '.join(f'{k}={c.status}' for k,c in cards.items())}")
    for key, card in cards.items():
        icon = f'[{card.status.upper()}]'
        log_info(f"{card.color} {card.warrior_id:12s} {icon:14s} {card.verdict}")

    log_stage("审计防火墙")
    auditor = DoWhyAuditor(bridge)
    audit = auditor.audit('full')
    logger.info(f"Auditor: {audit.verdict} (P={audit.n_pass}, W={audit.n_warn}, F={audit.n_fail})")
    verdict_panel(audit.verdict, audit.n_pass, audit.n_warn, audit.n_fail)

    log_stage("生成多云化图谱套件")
    charts = render_chart_suite(bridge, cards, str(REAL_DIR), dpi=150)
    logger.info(f"Generated {len(charts)} chart files")
    for chart_path in charts:
        log_info(f"{chart_path}")
        logger.debug(f"  Chart: {chart_path}")
    report = render_six_panel_report(cards) + "\n\n" + bridge.report()
    (REAL_DIR / "report.md").write_text(report, encoding='utf-8')
    logger.info(f"Report: {REAL_DIR / 'report.md'} ({len(report)} chars)")

    log_done(f"完成 — 输出在 {REAL_DIR}")
    file_handler = next((h for h in logger.handlers if isinstance(h, logging.FileHandler)), None)
    log_file = Path(file_handler.baseFilename) if file_handler else None
    log_info(f"日志: {log_file}")


def cmd_clean():
    """清理输出目录"""
    import shutil
    for d in [DEMO_DIR, REAL_DIR]:
        if d.exists():
            shutil.rmtree(str(d))
            d.mkdir()
    log_done(f"已清理 {DEMO_DIR} 和 {REAL_DIR}")


# ══════════════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════════════

COMMANDS = {
    'env':   (cmd_env,   "检查环境状态（依赖、模型、graphviz）"),
    'demo':  (cmd_demo,  "运行模拟数据演示管线（无需 GPU/模型）"),
    'real':  (cmd_real,  "运行真实 TRACE 数据管线（需缓存文件）"),
    'clean': (cmd_clean, "清理输出目录"),
}

def _parse_preset(args):
    """从命令行解析 --preset 参数，默认 llama（V4 过拟合模型专属）。"""
    preset = "llama"
    if "--preset" in args:
        idx = args.index("--preset")
        if idx + 1 < len(args):
            preset = args[idx + 1]
    return preset


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print("因果战队 CLI — 六合一管线统一入口")
        print(f"\n用法: python run_cli.py <command> [--preset <name>]\n")
        for name, (_, desc) in COMMANDS.items():
            print(f"  {name:8s}  {desc}")
        print(f"\n选项:")
        print(f"  --preset <name>   参数预设 (default / standard / deep / archival / llama)")
        print(f"                    llama 预设专为 Shehui/Shenji-LLaMA V4 设计")
        print(f"\n环境变量:")
        print(f"  GRAPHVIZ_BIN_DIR  Graphviz bin 目录")
        print(f"  PYTHONIOENCODING  建议设为 utf-8")
        sys.exit(0)

    cmd_name = sys.argv[1]
    cmd_func, _ = COMMANDS[cmd_name]
    if cmd_name == "real":
        cmd_func(preset=_parse_preset(sys.argv[2:]))
    else:
        cmd_func()


if __name__ == "__main__":
    main()
