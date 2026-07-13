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
from pathlib import Path

from _config import get_graphviz_bin_dir
from project_paths import resolve_paths

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
    """通过环境变量 GRAPHVIZ_BIN_DIR 配置 graphviz PATH"""
    gv_dir = get_graphviz_bin_dir()
    if gv_dir is None:
        return None
    c = str(gv_dir)
    current = os.environ.get('PATH', '')
    if c not in current:
        os.environ['PATH'] = f"{c};{current}"
    return c

def cmd_env():
    """打印环境状态"""
    print("═" * 50)
    print("  因果战队 CLI · 环境状态")
    print("═" * 50)

    # Python
    print(f"\n  Python: {sys.version.split()[0]}")

    # Graphviz
    gv = _setup_graphviz()
    if gv:
        try:
            result = subprocess.run(['dot', '-V'], capture_output=True, text=True, timeout=5)
            ver = result.stderr.strip() if result.stderr else result.stdout.strip()
            print(f"  Graphviz: ✓ ({ver})  [{gv}]")
        except Exception:
            print(f"  Graphviz: ⚠ bin found but dot -V failed  [{gv}]")
    else:
        print(f"  Graphviz: ✗ 未找到 (下载: https://graphviz.org/download/)")

    # Core deps
    for mod, name in [('numpy', 'NumPy'), ('torch', 'PyTorch'), ('transformers', 'Transformers')]:
        try:
            m = __import__(mod)
            ver = getattr(m, '__version__', '?')
            print(f"  {name}: ✓ {ver}")
        except ImportError:
            print(f"  {name}: ✗ 未安装")

    # Causal deps
    for mod, name in [('dowhy', 'DoWhy'), ('causallearn', 'causal-learn'),
                       ('networkx', 'NetworkX'), ('pandas', 'Pandas'),
                       ('statsmodels', 'StatsModels'), ('sklearn', 'Scikit-learn'),
                       ('matplotlib', 'Matplotlib'), ('graphviz', 'Graphviz(Py)')]:
        try:
            m = __import__(mod)
            ver = getattr(m, '__version__', '?')
            print(f"  {name}: ✓ {ver}")
        except ImportError:
            print(f"  {name}: ✗ 未安装")

    # Models (通过 _paths 解析，支持 TRACE_ROOT 环境变量)
    try:
        paths = resolve_paths()
        for model_name in ['Shehui-LLaMA', 'Shenji-LLaMA']:
            model_dir = paths.model_dir(model_name)
            if model_dir.exists():
                safetensors = list(model_dir.glob("model.safetensors"))
                size_mb = safetensors[0].stat().st_size / 1e6 if safetensors else 0
                print(f"  {model_name}: ✓ ({size_mb:.0f}MB)")
            else:
                print(f"  {model_name}: ✗ 未找到")
    except FileNotFoundError as e:
        print(f"  模型检测: ✗ {e}")

    # Outputs
    for label, d in [('demo', DEMO_DIR), ('real', REAL_DIR), ('cache', CACHE_DIR)]:
        files = list(d.glob('*'))
        print(f"  outputs/{label}: {len(files)} files")

    print()


# ══════════════════════════════════════════════════════════════════════
# 子命令
# ══════════════════════════════════════════════════════════════════════

def cmd_demo():
    """运行模拟数据演示管线"""
    print("═" * 50)
    print("  因果战队 · 模拟数据演示")
    print("═" * 50)

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

    print(f"\n[1/5] TRACE → DoWhy 桥接...")
    bridge = TRACE2DoWhy(adj, TOKENS, threshold=0.5, concept_min_freq=2)
    bridge.aggregate_concepts()
    bridge.build_model()
    bridge.identify(treatment='算法推荐', outcome='信息茧房')
    print(f"  概念: {len(bridge.concept_names)} → 边: {len(bridge.significant_edges)}")
    for i, e in enumerate(bridge.significant_edges[:5]):
        print(f"    {i+1}. {e[0]} → {e[1]} (ΔNLL={e[2]:.2f})")

    print(f"\n[2/5] 效应估计 + 反驳...")
    bridge.estimate()
    bridge.refute()
    est = bridge.estimate_result
    ci = DoWhy14Adapter.get_confidence_interval(est)
    print(f"  {bridge.treatment} → {bridge.outcome}")
    print(f"  ATE={est.value:.4f}  95%CI=[{ci[0]:.4f},{ci[1]:.4f}]")

    print(f"\n[3/5] 反事实扫描...")
    bridge.counterfactual_scan(n_top_edges=5)
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

    print(f"\n✅ 完成 — 输出在 {DEMO_DIR}")


def cmd_real():
    """运行真实 TRACE 数据管线"""
    import json, numpy as np
    from _logging import setup_logging, log_env_info
    from project_paths import resolve_paths

    paths = resolve_paths()
    logger = setup_logging(paths.outputs_dir / "logs", "sentai_real")
    log_env_info(logger)

    print("═" * 50)
    print("  因果战队 · 真实 TRACE 数据管线")
    print("═" * 50)

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

    print(f"\n[1/5] TRACE → DoWhy 桥接...")
    logger.info(f"TRACE→DoWhy: threshold={0.3}, min_freq={2}, max_edges={8}")
    bridge = TRACE2DoWhy(adj, tokens, threshold=0.3, concept_min_freq=2, max_edges_for_dowhy=8)
    bridge.aggregate_concepts()
    bridge.build_model()
    bridge.identify()
    logger.info(f"Concepts: {len(bridge.concept_names)}, Edges: {len(bridge.significant_edges)}, Mode: {bridge.mode_name}")
    print(f"  Tokens: {len(tokens)} → Concepts: {len(bridge.concept_names)} → Edges: {len(bridge.significant_edges)}")
    print(f"  Mode: {bridge.mode_name}")
    for i, e in enumerate(bridge.significant_edges[:6]):
        print(f"    {i+1}. {e[0]:12s} → {e[1]:12s}  ΔNLL={e[2]:.3f}")

    print(f"\n[2/5] 效应估计 + 反驳...")
    bridge.estimate()
    bridge.refute()
    est = bridge.estimate_result
    ci = DoWhy14Adapter.get_confidence_interval(est)
    logger.info(f"ATE={est.value:.4f}, CI=[{ci[0]:.4f},{ci[1]:.4f}]")
    print(f"  {bridge.treatment} → {bridge.outcome}")
    print(f"  ATE={est.value:.4f}  95%CI=[{ci[0]:.4f},{ci[1]:.4f}]")

    print(f"\n[3/5] 六战士合体...")
    cards = assemble_all_six(adj, tokens, bridge=bridge)
    logger.info(f"Six warriors: {', '.join(f'{k}={c.status}' for k,c in cards.items())}")
    for key, card in cards.items():
        icon = f'[{card.status.upper()}]'
        print(f"  {card.color} {card.warrior_id:12s} {icon:14s} {card.verdict}")
    bridge.counterfactual_scan(n_top_edges=min(5, len(bridge.significant_edges)))

    print(f"\n[4/5] 审计防火墙...")
    auditor = DoWhyAuditor(bridge)
    audit = auditor.audit('full')
    logger.info(f"Auditor: {audit.verdict} (P={audit.n_pass}, W={audit.n_warn}, F={audit.n_fail})")
    print(f"  Verdict: {audit.verdict} (PASS={audit.n_pass}, WARN={audit.n_warn}, FAIL={audit.n_fail})")

    print(f"\n[5/5] 生成多云化图谱套件...")
    charts = render_chart_suite(bridge, cards, str(REAL_DIR), dpi=150)
    logger.info(f"Generated {len(charts)} chart files")
    for p in charts:
        print(f"  {p}")
        logger.debug(f"  Chart: {p}")
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

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print("因果战队 CLI — 六合一管线统一入口")
        print(f"\n用法: python run_cli.py <command>\n")
        for name, (_, desc) in COMMANDS.items():
            print(f"  {name:8s}  {desc}")
        print(f"\n环境变量:")
        print(f"  GRAPHVIZ_BIN_DIR  Graphviz bin 目录")
        print(f"  PYTHONIOENCODING  建议设为 utf-8")
        sys.exit(0)

    cmd_name = sys.argv[1]
    cmd_func, _ = COMMANDS[cmd_name]
    cmd_func()


if __name__ == "__main__":
    main()
