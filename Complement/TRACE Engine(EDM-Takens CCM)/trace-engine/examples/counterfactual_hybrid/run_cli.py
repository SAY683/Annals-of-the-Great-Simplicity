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

from _config import setup_graphviz
from project_paths import resolve_paths
from presets import load_presets
from pipeline_helpers import run_full_pipeline

# ══════════════════════════════════════════════════════════════════════
# 昭和/平成特摄防卫队基地终端氛围
# ══════════════════════════════════════════════════════════════════════

class T:
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    GREEN = '\033[38;5;82m'
    CYAN = '\033[38;5;51m'
    YELLOW = '\033[38;5;220m'
    RED = '\033[38;5;196m'
    BLUE = '\033[38;5;75m'
    ORANGE = '\033[38;5;208m'
    BG_DARK = '\033[48;5;232m'


def _supports_color():
    return sys.stdout.isatty() and os.environ.get('TERM') not in (None, 'dumb')


def _colorize(s, color):
    return f"{color}{s}{T.RESET}" if _supports_color() else s


def _print_header(title):
    if not _supports_color():
        print("═" * 58)
        print(f"  {title}")
        print("═" * 58)
        return
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"{T.BG_DARK}{T.CYAN}╔══════════════════════════════════════════════════════════╗{T.RESET}")
    print(f"{T.BG_DARK}{T.CYAN}║{T.RESET} {T.GREEN}{T.BOLD}SENTAI CAUSAL BASE TERMINAL{T.RESET}  {T.DIM}[MISSION CLOCK] {now}{T.RESET}{' ' * 15}{T.CYAN}║{T.RESET}")
    print(f"{T.BG_DARK}{T.CYAN}║{T.RESET} {title}{' ' * (56 - len(title))}{T.CYAN}║{T.RESET}")
    print(f"{T.BG_DARK}{T.CYAN}╚══════════════════════════════════════════════════════════╝{T.RESET}")
    print()


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
    _print_header("因果战队 CLI · 环境状态 (Sentai Environment)")

    # Python
    print(f"  Python: {sys.version.split()[0]}")

    # Graphviz
    gv = _setup_graphviz()
    if gv:
        try:
            result = subprocess.run(['dot', '-V'], capture_output=True, text=True, timeout=5)
            ver = result.stderr.strip() if result.stderr else result.stdout.strip()
            print(f"  Graphviz: {_colorize('✓', T.GREEN)} ({ver})  [{gv}]")
        except Exception:
            print(f"  Graphviz: {_colorize('⚠', T.YELLOW)} bin found but dot -V failed  [{gv}]")
    else:
        print(f"  Graphviz: {_colorize('✗', T.RED)} 未找到 (下载: https://graphviz.org/download/)")

    # Core deps
    for mod, name in [('numpy', 'NumPy'), ('torch', 'PyTorch'), ('transformers', 'Transformers')]:
        try:
            m = __import__(mod)
            ver = getattr(m, '__version__', '?')
            print(f"  {name}: {_colorize('✓', T.GREEN)} {ver}")
        except ImportError:
            print(f"  {name}: {_colorize('✗', T.RED)} 未安装")

    # Causal deps
    for mod, name in [('dowhy', 'DoWhy'), ('causallearn', 'causal-learn'),
                       ('networkx', 'NetworkX'), ('pandas', 'Pandas'),
                       ('statsmodels', 'StatsModels'), ('sklearn', 'Scikit-learn'),
                       ('matplotlib', 'Matplotlib'), ('graphviz', 'Graphviz(Py)')]:
        try:
            m = __import__(mod)
            ver = getattr(m, '__version__', '?')
            print(f"  {name}: {_colorize('✓', T.GREEN)} {ver}")
        except ImportError:
            print(f"  {name}: {_colorize('✗', T.RED)} 未安装")

    # Models (通过 _paths 解析，支持 TRACE_ROOT 环境变量)
    try:
        paths = resolve_paths()
        for model_name in ['shehui-llama', 'shenji-llama']:
            model_dir = paths.model_dir(model_name)
            if model_dir.exists():
                safetensors = list(model_dir.glob("model.safetensors"))
                size_mb = safetensors[0].stat().st_size / 1e6 if safetensors else 0
                print(f"  {model_name}: {_colorize('✓', T.GREEN)} ({size_mb:.0f}MB)")
            else:
                print(f"  {model_name}: {_colorize('✗', T.RED)} 未找到")
    except FileNotFoundError as e:
        print(f"  模型检测: {_colorize('✗', T.RED)} {e}")

    # Outputs
    for label, d in [('demo', DEMO_DIR), ('real', REAL_DIR), ('cache', CACHE_DIR)]:
        files = list(d.glob('*'))
        print(f"  outputs/{label}: {_colorize(str(len(files)), T.CYAN)} files")

    print()


# ══════════════════════════════════════════════════════════════════════
# 子命令
# ══════════════════════════════════════════════════════════════════════

def cmd_demo():
    """运行模拟数据演示管线"""
    _print_header("因果战队 · 模拟数据演示 (Demo Simulation)")

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
    T=len(TOKENS); adj=np.zeros((T,T))
    pos={c:[i for i,t in enumerate(TOKENS) if t==c] for c in CONCEPTS}
    for ci,cs in enumerate(CONCEPTS):
        for cj,cd in enumerate(CONCEPTS):
            if ADJ[ci,cj]>0:
                for si in pos[cs]:
                    for sj in pos[cd]:
                        if si<sj: adj[si,sj]=ADJ[ci,cj]

    print(f"\n[1/5] TRACE → DoWhy 桥接 + 全管线（聚合→建模→识别→估计→反驳→反事实）...")
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
    print(f"  概念: {len(bridge.concept_names)} → 边: {len(bridge.significant_edges)}")
    for i, e in enumerate(bridge.significant_edges[:5]):
        print(f"    {i+1}. {e[0]} → {e[1]} (ΔNLL={e[2]:.2f})")

    print(f"\n[2/5] 效应估计 + 反驳结果...")
    est = bridge.estimate_result
    ci = DoWhy14Adapter.get_confidence_interval(est)
    print(f"  {bridge.treatment} → {bridge.outcome}")
    print(f"  ATE={est.value:.4f}  95%CI=[{ci[0]:.4f},{ci[1]:.4f}]")

    print(f"\n[3/5] 反事实扫描结果...")
    for r in bridge.scan_results[:5]:
        print(f"  {r['source']}→{r['target']}: ITE={r['ite']:+.4f}")

    print(f"\n[4/5] 审计防火墙...")
    auditor = DoWhyAuditor(bridge)
    audit = auditor.audit('full')
    print(f"  Verdict: {audit.verdict} (PASS={audit.n_pass}, WARN={audit.n_warn}, FAIL={audit.n_fail})")

    print(f"\n[5/5] 生成输出...")
    # Dashboard
    dash_path = render_dashboard(bridge, str(DEMO_DIR / "dashboard.png"), dpi=150)
    print(f"  仪表板: {dash_path}")
    # DOT graph
    gv_path = bridge.visualize(str(DEMO_DIR / "causal_graph"), format="png")
    print(f"  DAG: {gv_path}")
    # Report
    report = bridge.report()
    (DEMO_DIR / "report.md").write_text(report, encoding='utf-8')
    print(f"  报告: {DEMO_DIR / 'report.md'} ({len(report)} chars)")

    print(f"\n{_colorize('✅ 完成', T.GREEN)} — 输出在 {DEMO_DIR}")


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

    _print_header(f"因果战队 · 真实 TRACE 数据管线 | Preset: {preset}")
    print(f"  threshold={p.trace2dowhy.threshold}")
    print()

    _setup_graphviz()

    # 检查是否有缓存的 TRACE 结果
    adj_cache = CACHE_DIR / "real_adj.npy"
    tokens_cache = CACHE_DIR / "real_tokens.json"

    if not adj_cache.exists() or not tokens_cache.exists():
        print(f"\n⚠ 未找到 TRACE 缓存文件 ({CACHE_DIR})")
        print(f"  请先运行 TRACE 管线生成缓存，或运行:")
        print(f"    python run_real_pipeline.py")
        return

    import numpy as np, json
    sys.path.insert(0, str(SKILL_DIR))
    from counterfactual_bridge import TRACE2DoWhy, DoWhy14Adapter
    from dowhy_auditor import DoWhyAuditor
    from six_warriors import assemble_all_six, render_six_panel_report
    from six_panel_viz import render_chart_suite
    from collections import Counter

    adj = np.load(str(adj_cache))
    tokens = json.loads(tokens_cache.read_text(encoding='utf-8'))

    print(f"\n[1/5] TRACE → DoWhy 桥接 + 全管线（聚合→建模→识别→估计→反驳→反事实）...")
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
    )
    # debt-05: 管线核心序列抽取到 pipeline_helpers.run_full_pipeline（双轨入口合并）
    run_full_pipeline(bridge, preset=p)
    logger.info(f"Concepts: {len(bridge.concept_names)}, Edges: {len(bridge.significant_edges)}, Mode: {bridge.mode_name}")
    print(f"  Tokens: {len(tokens)} → Concepts: {len(bridge.concept_names)} → Edges: {len(bridge.significant_edges)}")
    print(f"  Mode: {bridge.mode_name}")
    for i, e in enumerate(bridge.significant_edges[:6]):
        print(f"    {i+1}. {e[0]:12s} → {e[1]:12s}  ΔNLL={e[2]:.3f}")

    print(f"\n[2/5] 效应估计 + 反驳结果...")
    est = bridge.estimate_result
    ci = DoWhy14Adapter.get_confidence_interval(est)
    logger.info(f"ATE={est.value:.4f}, CI=[{ci[0]:.4f},{ci[1]:.4f}]")
    print(f"  {bridge.treatment} → {bridge.outcome}")
    print(f"  ATE={est.value:.4f}  95%CI=[{ci[0]:.4f},{ci[1]:.4f}]")

    print(f"\n[3/5] 反事实扫描结果...")
    # scan_results 已由 run_full_pipeline 计算

    print(f"\n[4/5] 六战士合体...")
    cards = assemble_all_six(adj, tokens, bridge=bridge)
    # debt-04 audit 修复：将六战士卡片注入 bridge，激活 report() 中的复合诊断引擎
    bridge.set_six_warriors_cards(cards)
    logger.info(f"Six warriors: {', '.join(f'{k}={c.status}' for k,c in cards.items())}")
    for key, card in cards.items():
        icon = f'[{card.status.upper()}]'
        print(f"  {card.color} {card.warrior_id:12s} {icon:14s} {card.verdict}")

    print(f"\n[5/6] 审计防火墙...")
    auditor = DoWhyAuditor(bridge)
    audit = auditor.audit('full')
    logger.info(f"Auditor: {audit.verdict} (P={audit.n_pass}, W={audit.n_warn}, F={audit.n_fail})")
    print(f"  Verdict: {audit.verdict} (PASS={audit.n_pass}, WARN={audit.n_warn}, FAIL={audit.n_fail})")

    print(f"\n[6/6] 生成多云化图谱套件...")
    charts = render_chart_suite(bridge, cards, str(REAL_DIR), dpi=150)
    logger.info(f"Generated {len(charts)} chart files")
    for chart_path in charts:
        print(f"  {chart_path}")
        logger.debug(f"  Chart: {chart_path}")
    report = render_six_panel_report(cards) + "\n\n" + bridge.report()
    (REAL_DIR / "report.md").write_text(report, encoding='utf-8')
    logger.info(f"Report: {REAL_DIR / 'report.md'} ({len(report)} chars)")

    print(f"\n✅ 完成 — 输出在 {REAL_DIR}")
    file_handler = next((h for h in logger.handlers if isinstance(h, logging.FileHandler)), None)
    log_file = Path(file_handler.baseFilename) if file_handler else None
    print(f"   日志: {log_file}")


def cmd_clean():
    """清理输出目录"""
    import shutil
    for d in [DEMO_DIR, REAL_DIR]:
        if d.exists():
            shutil.rmtree(str(d))
            d.mkdir()
    print(f"✅ 已清理 {DEMO_DIR} 和 {REAL_DIR}")


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
