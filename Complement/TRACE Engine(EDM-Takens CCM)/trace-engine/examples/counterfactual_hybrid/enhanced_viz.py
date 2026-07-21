"""
Enhanced Causal DAG Visualization
==================================
对标 edm-takens 的 game_dashboard.png，生成多面板因果诊断图。

Panel layout:
  1. Causal DAG (左上) — 边颜色按反驳状态, 边宽度按 ATE, 节点大小按 centrality
  2. Refutation Summary (右上) — 三层反驳的效应量对比柱状图
  3. Counterfactual Comparison (底部) — 最强 5 条边的观测 vs 反事实

Usage:
    from enhanced_viz import EnhancedCausalViz
    viz = EnhancedCausalViz(bridge)
    viz.render("outputs/enhanced_dashboard.png")
"""

import warnings

import numpy as np

# ── 检查 matplotlib 可用性 ──
try:
    import matplotlib
    matplotlib.use('Agg')  # non-interactive backend
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch
    # CJK 字体支持
    import matplotlib.font_manager as fm
    _CJK_PRIORITY = ['microsoft yahei', 'simhei', 'noto sans cjk',
                     'simsun', 'stfangsong', 'fangsong']
    _CJK_FONTS = sorted(
        [f for f in fm.fontManager.ttflist
         if any(k in f.name.lower() for k in _CJK_PRIORITY)
         and 'extg' not in f.name.lower()],  # 排除字形不全的 SimSun-ExtG
        key=lambda f: next(i for i, k in enumerate(_CJK_PRIORITY) if k in f.name.lower())
    )
    if _CJK_FONTS:
        _CJK_FAMILY = _CJK_FONTS[0].name
        plt.rcParams['font.family'] = _CJK_FAMILY
        plt.rcParams['axes.unicode_minus'] = False
    _MPL_AVAILABLE = True
except ImportError:
    _MPL_AVAILABLE = False


class EnhancedCausalViz:
    """
    生成多面板因果诊断仪表板。

    对标 edm-takens examples/*/figures/*_dashboard.png 的设计语言:
    - 蓝/橙/灰配色
    - 清晰的层级标题
    - 数据-ink 比例最大化
    - 每个面板有独立的诊断标注
    """

    # 配色方案 (WCAG AA 兼容)
    COLORS = {
        'pass':       '#2E86AB',   # 蓝色 — 通过反驳
        'marginal':   '#F18F01',   # 橙色 — 部分反驳
        'fail':       '#C73E1D',   # 红色 — 反驳
        'observed':   '#2E86AB',   # 蓝色
        'counterfactual': '#F18F01',  # 橙色
        'grid':       '#D5D8DC',
        'text':       '#2C3E50',
        'bg':         '#FAFBFC',
        'node_fill':  '#E8F0FE',
        'node_edge':  '#5D6D7E',
    }

    def __init__(self, bridge):
        """
        Parameters
        ----------
        bridge : TRACE2DoWhy
            已完成全部管线（build_model, identify, estimate, refute, counterfactual_scan）
        """
        if not _MPL_AVAILABLE:
            raise ImportError("matplotlib 未安装: pip install matplotlib")
        self.bridge = bridge

    def render(self, filepath: str, dpi: int = 150):
        """
        渲染完整的多面板仪表板。

        Parameters
        ----------
        filepath : str
            输出路径 (.png)
        dpi : int
        """
        fig = plt.figure(figsize=(20, 14), facecolor=self.COLORS['bg'])
        gs = fig.add_gridspec(3, 3, hspace=0.35, wspace=0.30,
                              height_ratios=[0.08, 1.0, 0.9])

        # ── 标题行 ──
        ax_title = fig.add_subplot(gs[0, :])
        self._render_title(ax_title)

        # ── Panel 1: Causal DAG (左列，跨 2 行) ──
        ax_dag = fig.add_subplot(gs[1, 0])
        self._render_dag_panel(ax_dag)

        # ── Panel 2: Refutation Summary (中列) ──
        ax_ref = fig.add_subplot(gs[1, 1])
        self._render_refutation_panel(ax_ref)

        # ── Panel 3: ATE Comparison (右列) ──
        ax_ate = fig.add_subplot(gs[1, 2])
        self._render_ate_panel(ax_ate)

        # ── Panel 4: Counterfactual Comparison (底部全宽) ──
        ax_cf = fig.add_subplot(gs[2, :])
        self._render_counterfactual_panel(ax_cf)

        fig.savefig(filepath, dpi=dpi, bbox_inches='tight',
                    facecolor=self.COLORS['bg'], edgecolor='none')
        plt.close(fig)
        return filepath

    # ── 标题 ──

    def _render_title(self, ax):
        bridge = self.bridge
        n_edges = len(bridge.significant_edges)
        n_concepts = len([n for n in bridge.concept_names if n != '<other>'])

        # _check 是 dict 而非对象，需用键访问而非 getattr
        n_refuted = 0
        if bridge.refutation_results:
            for r in bridge.refutation_results.values():
                check = getattr(r, '_check', None)
                refuted = check['refuted'] if isinstance(check, dict) else getattr(r, 'refuted', False)
                if refuted:
                    n_refuted += 1

        mode = "DoWhy 0.14 do-calculus" if not bridge.simulation else "Simulation (SEM)"

        title = (
            f"TRACE + DoWhy + Counterfactual Causal Diagnosis Dashboard\n"
            f"{n_concepts} concepts · {n_edges} edges (ΔNLL > {bridge.threshold}) · "
            f"{mode} · {n_refuted}/3 refutations"
        )

        ax.text(0.5, 0.5, title, transform=ax.transAxes,
                ha='center', va='center', fontsize=14, fontweight='bold',
                color=self.COLORS['text'], fontfamily='monospace')
        ax.axis('off')

    # ── Panel 1: DAG ──

    def _render_dag_panel(self, ax):
        bridge = self.bridge
        edges = bridge.significant_edges

        if not edges:
            ax.text(0.5, 0.5, "No significant edges", ha='center', va='center')
            ax.set_title("Causal DAG", fontweight='bold')
            return

        # 过滤有效概念：保留所有非 <other> 概念（包括单字，以兼容字级 BPE）
        # 优先显示参与显著边的概念，避免 DAG 过于稀疏导致 max_deg=0
        valid = [n for n in bridge.concept_names if n != '<other>']
        edge_concepts = set()
        for src, dst, _ in edges:
            if src != '<other>' and dst != '<other>':
                edge_concepts.add(src)
                edge_concepts.add(dst)
        if edge_concepts:
            valid = [n for n in valid if n in edge_concepts]
        n_valid = len(valid)

        if n_valid == 0:
            ax.text(0.5, 0.5, "No valid concepts", ha='center', va='center')
            return

        # 计算节点位置 (圆形布局)
        angles = np.linspace(0, 2 * np.pi, n_valid, endpoint=False)
        radius = 0.38
        cx, cy = 0.5, 0.5
        positions = {}
        for i, name in enumerate(valid):
            positions[name] = (cx + radius * np.cos(angles[i]),
                               cy + radius * np.sin(angles[i]))

        # 计算节点中心性 (入度 + 出度)
        in_deg = {}
        out_deg = {}
        for name in valid:
            in_deg[name] = 0
            out_deg[name] = 0
        for src, dst, _ in edges:
            if src in valid and dst in valid:
                out_deg[src] = out_deg.get(src, 0) + 1
                in_deg[dst] = in_deg.get(dst, 0) + 1

        max_deg = max(
            max(in_deg.values(), default=1),
            max(out_deg.values(), default=1)
        )
        if max_deg == 0:
            max_deg = 1  # 防止后续除零；所有节点同等大小

        # 获取 refutation 状态
        refuted_edges = set()
        if bridge.refutation_results and bridge.estimate_result:
            orig = bridge.estimate_result.value
            for name, result in bridge.refutation_results.items():
                check = getattr(result, '_check', None)
                is_refuted = check['refuted'] if check else False
                if is_refuted:
                    # 标记当前 treatment→outcome 的边
                    refuted_edges.add((bridge.treatment, bridge.outcome))

        # 计算 ATE 映射
        ate_map = {}
        if hasattr(bridge, 'scan_results') and bridge.scan_results:
            for r in bridge.scan_results:
                ate_map[(r['source'], r['target'])] = abs(r['ite'])

        # 绘制边
        for src, dst, dnl in sorted(edges, key=lambda e: e[2]):
            if src not in valid or dst not in valid:
                continue

            # 颜色
            edge_key = (src, dst)
            if edge_key in refuted_edges:
                color = self.COLORS['fail']
                alpha = 0.9
            else:
                color = self.COLORS['pass']
                alpha = 0.6

            # 宽度 (基于 ATE 如果有，否则基于 ΔNLL)
            ate_val = ate_map.get(edge_key, dnl)
            lw = 1.0 + 3.0 * min(abs(ate_val) / 10.0, 1.0)

            # 画箭头
            x1, y1 = positions[src]
            x2, y2 = positions[dst]

            # 缩短箭头，给节点留空间
            dx = x2 - x1
            dy = y2 - y1
            dist = np.sqrt(dx*dx + dy*dy)
            if dist == 0:
                continue
            node_r = 0.04 + 0.02 * ((in_deg[dst] + out_deg[dst]) / max_deg)
            shrink = node_r / dist
            x1s = x1 + dx * shrink
            y1s = y1 + dy * shrink
            x2s = x2 - dx * shrink
            y2s = y2 - dy * shrink

            ax.annotate('', xy=(x2s, y2s), xytext=(x1s, y1s),
                       arrowprops=dict(
                           arrowstyle='-|>', color=color, alpha=alpha,
                           lw=lw, mutation_scale=12,
                           connectionstyle='arc3,rad=0.05'
                       ))

            # 标签
            mid_x = (x1 + x2) / 2
            mid_y = (y1 + y2) / 2
            if ate_val > 0:
                label = f'{ate_val:.1f}'
                ax.text(mid_x, mid_y, label, fontsize=6, ha='center',
                       color=self.COLORS['text'], alpha=0.8,
                       bbox=dict(boxstyle='round,pad=0.1', fc='white',
                                 ec='none', alpha=0.7))

        # 绘制节点
        for name in valid:
            x, y = positions[name]
            deg = (in_deg[name] + out_deg[name]) / max_deg
            node_size = 0.028 + 0.025 * deg

            circle = plt.Circle((x, y), node_size, fc=self.COLORS['node_fill'],
                               ec=self.COLORS['node_edge'], lw=1.5, zorder=3)
            ax.add_patch(circle)
            ax.text(x, y, name, fontsize=7.5, ha='center', va='center',
                   color=self.COLORS['text'], fontweight='bold', zorder=4)

        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.set_aspect('equal')
        ax.axis('off')
        ax.set_title("Causal DAG\n(color=refutation, width=ATE, size=centrality)",
                    fontsize=10, fontweight='bold', color=self.COLORS['text'])

        # 图例
        from matplotlib.lines import Line2D
        legend_elements = [
            Line2D([0], [0], color=self.COLORS['pass'], lw=2,
                   label='Robust'),
            Line2D([0], [0], color=self.COLORS['fail'], lw=2,
                   label='Refuted'),
        ]
        ax.legend(handles=legend_elements, loc='lower right', fontsize=7,
                 framealpha=0.8)

    # ── Panel 2: Refutation Summary ──

    def _render_refutation_panel(self, ax):
        bridge = self.bridge

        if not bridge.refutation_results or not bridge.estimate_result:
            ax.text(0.5, 0.5, "No refutation data", ha='center', va='center')
            ax.set_title("Refutation Summary", fontweight='bold')
            return

        orig = bridge.estimate_result.value
        refuters = list(bridge.refutation_results.keys())
        new_effects = [bridge.refutation_results[r].new_effect for r in refuters]

        x = np.arange(len(refuters))
        width = 0.35

        bars_orig = ax.bar(x - width/2, [orig]*len(refuters), width,
                           color=self.COLORS['pass'], alpha=0.5,
                           label=f'Original ATE ({orig:.3f})')
        bars_new = ax.bar(x + width/2, new_effects, width,
                          color=self.COLORS['marginal'], alpha=0.8,
                          label='New Effect')

        # 标注 refuted
        for i, (name, result) in enumerate(bridge.refutation_results.items()):
            check = getattr(result, '_check', None)
            refuted = check['refuted'] if check else False
            if refuted:
                ax.annotate('[!]', (i + width/2, new_effects[i]),
                          textcoords="offset points", xytext=(0, 12),
                          ha='center', fontsize=14, color=self.COLORS['fail'])

        ax.set_xticks(x)
        ax.set_xticklabels([r.replace('_', ' ')[:15] for r in refuters],
                          rotation=25, ha='right', fontsize=7)
        ax.set_ylabel('ATE', fontsize=9)
        ax.set_title("Refutation Triangulation\n(≥2/3 must pass)",
                    fontsize=10, fontweight='bold', color=self.COLORS['text'])
        ax.legend(fontsize=7, framealpha=0.9)
        ax.axhline(y=0, color=self.COLORS['grid'], lw=0.5, linestyle='--')
        ax.grid(axis='y', alpha=0.3, color=self.COLORS['grid'])

    # ── Panel 3: ATE Comparison ──

    def _render_ate_panel(self, ax):
        bridge = self.bridge

        if not hasattr(bridge, 'scan_results') or not bridge.scan_results:
            ax.text(0.5, 0.5, "No scan data", ha='center', va='center')
            ax.set_title("ATE vs ΔNLL", fontweight='bold')
            return

        scan = bridge.scan_results[:8]  # top 8
        names = [f"{r['source'][:4]}→{r['target'][:4]}" for r in scan]
        dnl_vals = [r['trace_dnl'] for r in scan]
        ite_vals = [abs(r['ite']) for r in scan]

        x = np.arange(len(names))
        width = 0.35

        ax.bar(x - width/2, [v/max(dnl_vals)*max(ite_vals) if max(dnl_vals) > 0 else 0
                             for v in dnl_vals], width,
               color=self.COLORS['pass'], alpha=0.4, label='ΔNLL (scaled)')
        ax.bar(x + width/2, ite_vals, width,
               color=self.COLORS['marginal'], alpha=0.8, label='|ITE|')

        ax.set_xticks(x)
        ax.set_xticklabels(names, rotation=45, ha='right', fontsize=7)
        ax.set_ylabel('Causal Strength', fontsize=9)
        ax.set_title("TRACE ΔNLL vs Counterfactual |ITE|\n(low correlation = heterogeneous defense)",
                    fontsize=10, fontweight='bold', color=self.COLORS['text'])
        ax.legend(fontsize=7)
        ax.grid(axis='y', alpha=0.3, color=self.COLORS['grid'])

        # 添加相关系数标注
        if len(dnl_vals) >= 3:
            corr = np.corrcoef(dnl_vals, ite_vals)[0, 1]
            ax.text(0.98, 0.95, f'ρ = {corr:.3f}', transform=ax.transAxes,
                   ha='right', va='top', fontsize=8, fontweight='bold',
                   color=self.COLORS['fail'] if abs(corr) < 0.5 else self.COLORS['pass'])

    # ── Panel 4: Counterfactual Comparison ──

    def _render_counterfactual_panel(self, ax):
        bridge = self.bridge

        if not hasattr(bridge, 'scan_results') or not bridge.scan_results:
            ax.text(0.5, 0.5, "No counterfactual data", ha='center', va='center')
            ax.set_title("Counterfactual Analysis", fontweight='bold')
            return

        scan = bridge.scan_results[:5]
        names = [f"{r['source']} → {r['target']}" for r in scan]

        x = np.arange(len(names))
        width = 0.3

        observed = [r['observed'] for r in scan]
        counterfactual = [r['counterfactual'] for r in scan]

        bars_obs = ax.bar(x - width/2, observed, width,
                         color=self.COLORS['observed'], alpha=0.7,
                         label='Observed Outcome')
        bars_cf = ax.bar(x + width/2, counterfactual, width,
                        color=self.COLORS['counterfactual'], alpha=0.7,
                        label='Counterfactual (do(T=1))')

        # ITE 标注
        for i, r in enumerate(scan):
            ite = r['ite']
            color = self.COLORS['marginal'] if abs(ite) > 0.1 else self.COLORS['grid']
            ax.annotate(f'ITE={ite:+.2f}',
                       (i, max(r['observed'], r['counterfactual'], 0)),
                       textcoords="offset points", xytext=(0, 6),
                       ha='center', fontsize=7, fontweight='bold',
                       color=color)

        ax.set_xticks(x)
        ax.set_xticklabels(names, rotation=20, ha='right', fontsize=8)
        ax.set_ylabel('Outcome Value', fontsize=9)
        ax.set_title(
            "Pearl Counterfactual: Observed vs. What-If\n"
            "Abduction → Action → Prediction — 'What if the cause were different?'",
            fontsize=10, fontweight='bold', color=self.COLORS['text'])
        ax.legend(fontsize=8, loc='upper left')
        ax.axhline(y=0, color=self.COLORS['grid'], lw=0.5, linestyle='--')
        ax.grid(axis='y', alpha=0.3, color=self.COLORS['grid'])

        # 底部注释
        ax.text(0.5, -0.25,
                "ITE > 0: treatment increases outcome. "
                "ITE < 0: treatment decreases outcome. "
                "|ITE| large + ΔNLL large → HIGH CONFIDENCE causal edge.",
                transform=ax.transAxes, ha='center', fontsize=7,
                color=self.COLORS['node_edge'], fontstyle='italic')


# ── 便捷函数 ──

def render_dashboard(bridge, filepath: str, dpi: int = 150) -> str:
    """一键生成增强版仪表板"""
    viz = EnhancedCausalViz(bridge)
    return viz.render(filepath, dpi=dpi)
