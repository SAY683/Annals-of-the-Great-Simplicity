#!/usr/bin/env python3
"""
TRACE Engine Web Bridge — Python 端
====================================
从 stdin 读取文本，提取概念并构建因果图，调用 counterfactual_bridge.py
完成识别、估计、反驳、反事实扫描。

输出格式：JSON Lines（每行一个 JSON 对象）
  {"type": "stage", "stage": "tokenize", "message": "..."}
  {"type": "log", "level": "info", "message": "..."}
  {"type": "result", "payload": {...}}
  {"type": "error", "message": "..."}

用法:
    python py_bridge.py <skill_dir> <out_dir> [light|deep] [config_json] [input_file] < <text_file>

说明:
    - 若提供 input_file，则优先从文件读取文本；否则从 stdin 读取。
    - config_json 为 JSON 字符串，可覆盖阈值、窗口大小等桥接参数。
"""

import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

# 轻量 OLS 置信区间（用于 LIGHT 模式替代 DoWhy bootstrap）
try:
    import statsmodels.api as sm
    _STATSMODELS_AVAILABLE = True
except Exception:
    _STATSMODELS_AVAILABLE = False


def _emit(obj: dict):
    """输出一行 JSON Lines 到 stdout 并立即刷新。"""
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def _log(level: str, message: str):
    _emit({"type": "log", "level": level, "message": message})


def _stage(stage: str, message: str, progress: float = None):
    obj = {"type": "stage", "stage": stage, "message": message}
    if progress is not None:
        obj["progress"] = round(progress, 2)
    _emit(obj)


class StageTimer:
    """简单的阶段计时器，用于生成执行时间剖面。"""

    def __init__(self):
        self.stage_start = {}
        self.stage_ms = []
        self.total_start = time.perf_counter()

    def start(self, stage: str):
        self.stage_start[stage] = time.perf_counter()

    def end(self, stage: str):
        t0 = self.stage_start.pop(stage, None)
        if t0 is None:
            return
        ms = int((time.perf_counter() - t0) * 1000)
        self.stage_ms.append({"stage": stage, "ms": ms})

    def total_ms(self) -> int:
        return int((time.perf_counter() - self.total_start) * 1000)

    def to_dict(self):
        return {
            "stages": self.stage_ms,
            "total_ms": self.total_ms(),
        }


class _FastEstimate:
    """LIGHT 模式下替代 DoWhy CausalEstimate 的轻量估计对象。"""

    def __init__(self, value: float, ci: list):
        self.value = float(value)
        self.confidence_interval = [float(ci[0]), float(ci[1])]

    def get_confidence_intervals(self):
        return [self.confidence_interval]


def _fast_ols_ate_ci(data_df, treatment: str, outcome: str, alpha: float = 0.05):
    """
    使用 statsmodels OLS 快速同时计算 treatment 对 outcome 的 ATE 点估计与置信区间。
    用于 LIGHT 模式完全替代 DoWhy estimate_effect，避免 bootstrap 与 DoWhy 内部开销。
    """
    if not _STATSMODELS_AVAILABLE or treatment not in data_df.columns or outcome not in data_df.columns:
        return 0.0, [float("-inf"), float("inf")]

    df = data_df.copy()
    # 构造协变量：除 treatment/outcome 外的所有数值列
    covariates = [c for c in df.columns if c not in (treatment, outcome) and np.issubdtype(df[c].dtype, np.number)]
    X = df[[treatment] + covariates]
    X = sm.add_constant(X, has_constant='add')
    y = df[outcome].astype(float)

    model = sm.OLS(y, X.astype(float), missing='drop')
    result = model.fit(cov_type='HC3')  # 异方差稳健标准误
    ate = float(result.params[treatment])
    ci = result.conf_int(alpha=alpha).loc[treatment].values
    return ate, [float(ci[0]), float(ci[1])]


def _load_config(arg_json: str) -> dict:
    """从环境变量 TRACE_BRIDGE_CONFIG 或命令行 JSON 加载配置。"""
    config = {}
    env = os.environ.get("TRACE_BRIDGE_CONFIG", "")
    src = arg_json or env
    if src:
        try:
            config = json.loads(src)
        except Exception:
            pass
    # 允许单独的环境变量覆盖
    for key, cast in [
        ("window_size", int),
        ("max_concepts", int),
        ("concept_min_freq", int),
        ("min_valid_tokens", int),
        ("min_concepts", int),
        ("max_edges_for_dowhy", int),
    ]:
        val = os.environ.get(f"TRACE_BRIDGE_{key.upper()}")
        if val is not None:
            try:
                config[key] = cast(val)
            except Exception:
                pass
    for key, cast in [("threshold", float)]:
        val = os.environ.get(f"TRACE_BRIDGE_{key.upper()}")
        if val is not None:
            try:
                config[key] = cast(val)
            except Exception:
                pass
    # 布尔开关（用于 LIGHT/DEEP 模式行为微调）
    for key in ("fast_ci", "run_refuters"):
        val = os.environ.get(f"TRACE_BRIDGE_{key.upper()}")
        if val is not None:
            config[key] = val.lower() in ("1", "true", "yes", "on")
    return config


def _tokenize(text: str) -> list:
    """中文分词：优先使用 jieba（加载领域词），否则回退到简单正则。"""
    try:
        import jieba
        _DOMAIN_WORDS = [
            "算法推荐", "信息茧房", "观点极化", "社会共识", "公共讨论",
            "用户行为", "算法透明", "推荐系统", "因果推断",
        ]
        for w in _DOMAIN_WORDS:
            jieba.add_word(w, freq=1000)
        return list(jieba.lcut(text))
    except ImportError:
        return re.findall(r'[\u4e00-\u9fff]{2,}', text)


def _write_error(out_dir: Path, message: str):
    """统一错误输出：日志、文件、SSE。"""
    _log("error", message)
    _stage("error", message, 1.0)
    result = {"success": False, "error": message}
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "report.md").write_text(f"# 分析失败\n\n{message}\n", encoding="utf-8")
    _emit({"type": "error", "message": message})


def main():
    if len(sys.argv) < 3:
        _emit({"type": "error", "message": "用法: python py_bridge.py <skill_dir> <out_dir> [light|deep]"})
        sys.exit(1)

    skill_dir = Path(sys.argv[1]).resolve()
    out_dir = Path(sys.argv[2]).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    mode = (sys.argv[3] if len(sys.argv) > 3 else "light").lower().strip()
    if mode not in ("light", "deep"):
        mode = "light"

    # 可配置参数：环境变量 > 命令行第4位（JSON）> 默认值
    config = _load_config(sys.argv[4] if len(sys.argv) > 4 else "")

    # 参数基本校验
    window_size = config.get("window_size", 8)
    threshold = config.get("threshold", 0.5)
    concept_min_freq = config.get("concept_min_freq", 1)
    max_concepts = config.get("max_concepts", 12)
    if not (2 <= window_size <= 128):
        _write_error(out_dir, f"window_size 必须在 [2, 128] 之间，当前为 {window_size}")
        return
    if not (0 <= threshold <= 10):
        _write_error(out_dir, f"threshold 必须在 [0, 10] 之间，当前为 {threshold}")
        return
    if not (1 <= max_concepts <= 128):
        _write_error(out_dir, f"max_concepts 必须在 [1, 128] 之间，当前为 {max_concepts}")
        return

    # 输入文件路径（第5位），便于在 Windows/PowerShell 等 stdin 重定向受限环境直接调用
    input_file = sys.argv[5] if len(sys.argv) > 5 else None
    min_valid_tokens = config.get("min_valid_tokens", 10)
    min_concepts = config.get("min_concepts", 3)
    max_edges_for_dowhy = config.get("max_edges_for_dowhy")
    fast_ci = config.get("fast_ci")
    run_refuters = config.get("run_refuters")

    # 按模式给出默认策略：LIGHT 求快，DEEP 求全
    if mode == "light":
        if max_edges_for_dowhy is None:
            max_edges_for_dowhy = 12
        if fast_ci is None:
            fast_ci = True
        if run_refuters is None:
            run_refuters = False
    else:
        if max_edges_for_dowhy is None:
            max_edges_for_dowhy = 20
        if fast_ci is None:
            fast_ci = False
        if run_refuters is None:
            run_refuters = True

    sys.path.insert(0, str(skill_dir))

    timer = StageTimer()

    try:
        from _token_filters import is_valid_concept
        from counterfactual_bridge import TRACE2DoWhy, DoWhy14Adapter
    except Exception as e:
        _emit({"type": "error", "message": f"导入 Skill 模块失败: {e}"})
        sys.exit(1)

    # Web 端额外停用词兜底（即使 Skill 的 _token_filters 未同步更新也能保证概念质量）
    _EXTRA_STOP_CHARS = set(
        "它他她你我咱这那哪什怎为对中个种样"
        "么呢吧啊哦嗯哟哈嘛哩呐哇喽兮哉乎邪"
        "将不地来去上下左右前后里外内间旁过"
        "着过得好累真太比较更最很极已正曾"
    )
    _EXTRA_STOP_WORDS = {
        "这种", "那种", "就是", "不是", "而是", "还是", "或是",
        "之中", "之间", "之内", "之外", "之前", "之后", "以上", "以下",
        "的话", "来说", "而言", "看来", "说来", "起来", "下去", "出来",
        "我们", "你们", "他们", "她们", "它们", "咱们", "自己", "人家",
        "那么", "这么", "成为", "作为", "以为", "认为",
        "可以", "可能", "能够", "已经", "曾经", "正在",
        # 低信息含量通用词（在哲学/政治文本中高频但因果价值低）
        "东西", "事情", "情况", "问题", "意义", "作用", "方面", "部分",
        "存在", "进一步", "真正", "完全", "全部", "整体", "整个",
        "所有", "一切", "一种", "一个", "一些", "许多", "各种",
        "不断", "逐渐", "日益", "越来越", "更加", "极为", "非常",
        "似乎", "好像", "大概", "其实", "实际上", "事实上",
        "因此", "因而", "从而", "于是", "所以", "因为", "由于",
        "但是", "然而", "不过", "只是", "尽管", "虽然",
        "如果", "那么", "假如", "即使", "哪怕", "无论",
        "不仅", "不但", "而且", "并且", "同时", "另外", "此外",
        "对于", "关于", "至于", "根据", "按照", "通过", "经过",
        "进行", "做出", "得到", "形成", "产生", "发生", "出现",
        "具有", "拥有", "具备", "含有", "包含着", "充满",
        "使得", "导致", "造成", "引起", "带来", "产生",
        "需要", "必须", "应当", "应该", "只能", "只好", "不得不",
        "人们", "人类", "有人", "他人", "别人", "某人",
    }

    def _is_valid_concept_web(name):
        if not is_valid_concept(name):
            return False
        stripped = name.strip()
        if len(stripped) == 1 and stripped in _EXTRA_STOP_CHARS:
            return False
        if stripped in _EXTRA_STOP_WORDS:
            return False
        return True

    # DEEP 模式下默认保留更多概念，以支撑 HAVOK / causallearn 等需要更大矩阵的战士
    if mode == "deep" and "max_concepts" not in config:
        max_concepts = 24

    timer.start("read")
    _stage("read", "正在读取输入文本...", 0.05)
    if input_file:
        try:
            text = Path(input_file).read_text(encoding="utf-8")
        except Exception as e:
            _write_error(out_dir, f"无法读取输入文件 {input_file}: {e}")
            return
    else:
        text = sys.stdin.read()
    timer.end("read")

    if not text.strip():
        _write_error(out_dir, "输入文本为空。")
        return

    timer.start("tokenize")
    _stage("tokenize", "正在进行中文分词与概念过滤...", 0.12)
    tokens = _tokenize(text)
    valid_tokens = [t for t in tokens if _is_valid_concept_web(t)]
    _log("info", f"原始 token 数: {len(tokens)}, 有效概念 token 数: {len(valid_tokens)}")
    timer.end("tokenize")

    if len(valid_tokens) < min_valid_tokens:
        _write_error(out_dir, f"有效词数不足（仅 {len(valid_tokens)} 个，至少 {min_valid_tokens} 个），无法构建因果图。")
        return

    timer.start("concepts")
    _stage("concepts", "正在提取高频概念...", 0.22)
    freq = Counter(valid_tokens)
    concept_names = [w for w, _ in freq.most_common(max_concepts)]
    concept_frequencies = {w: int(freq[w]) for w in concept_names}
    ccm_eligible = [w for w, c in freq.items() if c >= 3 and w in concept_names]
    _log("info", f"提取概念: {concept_names} (CCM eligible: {ccm_eligible})")
    timer.end("concepts")

    if len(concept_names) < min_concepts:
        _write_error(out_dir, f"有效概念不足（仅 {len(concept_names)} 个，至少 {min_concepts} 个），无法构建因果图。")
        return

    concept_idx = {name: i for i, name in enumerate(concept_names)}

    timer.start("graph")
    _stage("graph", "正在基于窗口共现构建概念因果图...", 0.32)
    adj = np.zeros((len(concept_names), len(concept_names)))
    directed_count = np.zeros((len(concept_names), len(concept_names)))

    token_ids = [concept_idx.get(t) for t in tokens if t in concept_idx]

    for i in range(len(token_ids)):
        for j in range(i + 1, min(i + window_size, len(token_ids))):
            a = token_ids[i]
            b = token_ids[j]
            if a is None or b is None or a == b:
                continue
            adj[a, b] += 1.0
            directed_count[a, b] += 1.0

    for i in range(len(concept_names)):
        for j in range(i + 1, len(concept_names)):
            if directed_count[i, j] > directed_count[j, i]:
                adj[j, i] = 0
            elif directed_count[j, i] > directed_count[i, j]:
                adj[i, j] = 0

    if adj.max() > 0:
        adj = adj / adj.max() * 8.0

    n_edges = int((adj > threshold).sum())
    _log("info", f"概念数: {len(concept_names)}, 候选边数: {n_edges}")
    timer.end("graph")

    timer.start("bridge")
    _stage("bridge", "正在调用 TRACE2DoWhy 桥接器...", 0.42)
    bridge = TRACE2DoWhy(adj, concept_names, threshold=threshold,
                         concept_min_freq=concept_min_freq, simulation=False,
                         max_edges_for_dowhy=max_edges_for_dowhy)
    bridge.build_model()
    _log("info", f"聚合后概念节点: {len(bridge.concept_names)}, 显著边: {len(bridge.significant_edges)}")
    timer.end("bridge")

    if bridge.significant_edges:
        treatment, outcome, strength = bridge.significant_edges[0]
    else:
        treatment, outcome = concept_names[0], concept_names[-1]
        strength = 0.0
    _log("info", f"选定 treatment/outcome: {treatment} → {outcome} (strength={strength:.2f})")

    timer.start("identify")
    _stage("identify", "正在识别因果效应...", 0.52)
    bridge.identify(treatment=treatment, outcome=outcome)
    identifiable = DoWhy14Adapter.is_identifiable(bridge.identified_estimand)
    _log("info", f"可识别性: {identifiable}")
    timer.end("identify")

    timer.start("estimate")
    _stage("estimate", "正在估计因果效应 (ATE)...", 0.68)
    if fast_ci and _STATSMODELS_AVAILABLE and not bridge.simulation:
        # LIGHT 模式：完全跳过 DoWhy estimate_effect，使用 OLS 解析解估计 ATE + CI
        ate, ci = _fast_ols_ate_ci(bridge.data_df, bridge.treatment, bridge.outcome)
        estimate = _FastEstimate(ate, ci)
        bridge.estimate_result = estimate  # 保证 bridge.report() 可用
        confidence_method = "OLS-analytic"
        _log("info", f"ATE={ate:.4f}, 95% CI=[{ci[0]:.4f}, {ci[1]:.4f}] (fast OLS)")
    else:
        estimate = bridge.estimate()
        ci = DoWhy14Adapter.get_confidence_interval(estimate)
        confidence_method = "bootstrap" if not bridge.simulation else "SEM-analytic"
        _log("info", f"ATE={estimate.value:.4f}, 95% CI=[{ci[0]:.4f}, {ci[1]:.4f}]")
    timer.end("estimate")

    refutations = {}
    if run_refuters:
        timer.start("refute")
        _stage("refute", "正在运行反驳测试 (3 refuters)...", 0.80)
        refutations = bridge.refute()
        n_refuted = sum(1 for r in refutations.values()
                        if bool(getattr(getattr(r, '_check', None), 'refuted',
                                        getattr(r, 'refuted', False))))
        _log("info", f"反驳测试完成: {n_refuted}/{len(refutations)} 被反驳")
        timer.end("refute")
    else:
        _log("info", "LIGHT 模式跳过反驳测试以保障响应速度")

    timer.start("counterfactual")
    _stage("counterfactual", "正在执行反事实扫描...", 0.90)
    scan = bridge.counterfactual_scan(n_top_edges=min(5, len(bridge.significant_edges)))
    _log("info", f"反事实扫描完成: {len(scan)} 条边")
    timer.end("counterfactual")

    # ── 深度模式：六战士完整诊断 ──
    six_warriors = {}
    if mode == "deep":
        timer.start("six_warriors")
        _stage("six_warriors", "正在执行六战士深度诊断 (CCM/EDM/HAVOK/causallearn)...", 0.94)
        try:
            from six_warriors import assemble_all_six
            # 使用 bridge 中的概念级邻接矩阵和 token_list
            # 注意：必须传入原始 token 序列（而非 bridge.token_list 概念名列表），
            # 否则 CCM/EDM 等依赖频率的战士会误判为每个概念只出现 1 次。
            cards = assemble_all_six(
                bridge.concept_adj if bridge.concept_adj is not None else adj,
                tokens,
                bridge=bridge,
                text=text[:500],
                concept_names=bridge.concept_names,
            )
            # Web 桥接未加载 LLaMA TRACE 模型，TRACE 战士实际基于共现近似
            if "trace" in cards:
                cards["trace"].findings.append(
                    "Web 桥接：使用 jieba 共现近似，未调用 LLaMA TRACE 模型"
                )
            six_warriors = {k: _card_to_dict(card) for k, card in cards.items()}
            deployed = sum(1 for c in six_warriors.values() if c.get("status") == "deployed")
            _log("info", f"六战士诊断完成: {deployed}/{len(six_warriors)} deployed")
        except Exception as e:
            _log("warn", f"六战士诊断部分失败: {e}")
        timer.end("six_warriors")

    timer.start("report")
    _stage("report", "正在生成 Markdown 报告与 JSON 结果...", 0.98)
    report = bridge.report()
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    timer.end("report")

    ref_list = []
    for name, r in refutations.items():
        check = getattr(r, '_check', None)
        ref_list.append({
            "method": name,
            "new_effect": float(r.new_effect),
            "refuted": bool(check['refuted']) if check else bool(getattr(r, 'refuted', False)),
            "display_metric": float(check['display_metric']) if check and check.get('display_metric') is not None else None,
            "display_label": check.get('display_label') if check else None,
        })

    scan_list = [
        {
            "source": r["source"],
            "target": r["target"],
            "trace_dnl": float(r["trace_dnl"]),
            "ite": float(r["ite"]),
            "observed": float(r["observed"]),
            "counterfactual": float(r["counterfactual"]),
        }
        for r in scan
    ]

    # 提取可识别性细节
    identifiability = _extract_identifiability(bridge, DoWhy14Adapter)

    # 数据与模型诊断
    data_diagnostics = _extract_data_diagnostics(bridge, tokens, valid_tokens, concept_names, adj)
    data_diagnostics["trace_source"] = "cooccurrence-web"
    data_diagnostics["analysis_mode"] = mode

    # 稳定性分析（DEEP 模式）
    stability_analysis = {}
    if mode == "deep":
        timer.start("stability")
        _stage("stability", "正在执行稳定性与鲁棒性分析 (bootstrap / permutation / CV)...", 0.955)
        _log("info", f"稳定性分析启动: n_bootstrap=30, n_permutation=20, n_folds=3")
        try:
            stability_analysis = _run_stability_analysis(
                bridge, tokens, concept_names, window_size, threshold, max_concepts, estimate,
                valid_filter=_is_valid_concept_web,
            )
            _log("info", f"稳定性分析完成: edge_stability_mean={stability_analysis.get('edge_stability_mean'):.3f}")
        except Exception as e:
            _log("warn", f"稳定性分析部分失败: {e}")
        timer.end("stability")

    result = {
        "success": True,
        "mode": bridge.mode_name,
        "analysis_mode": mode,
        "concepts": concept_names,
        "concept_frequencies": concept_frequencies,
        "ccm_eligible_concepts": ccm_eligible,
        "adjacency_matrix": adj.tolist(),
        "treatment": treatment,
        "outcome": outcome,
        "identifiable": identifiable,
        "identifiability": identifiability,
        "ate": float(estimate.value),
        "confidence_interval": [float(ci[0]), float(ci[1])],
        "confidence_method": confidence_method,
        "refutations": ref_list,
        "counterfactual_scan": scan_list,
        "n_significant_edges": len(bridge.significant_edges),
        "top_edges": [
            {"source": s, "target": t, "strength": float(v), "direction": "→"}
            for s, t, v in bridge.significant_edges[:8]
        ],
        "threshold": threshold,
        "window_size": window_size,
        "concept_min_freq": concept_min_freq,
        "max_concepts": max_concepts,
        "max_edges_for_dowhy": max_edges_for_dowhy,
        "n_samples": bridge.data_df.shape[0] if hasattr(bridge.data_df, 'shape') else len(bridge.data_df),
        "backend": "DoWhy" if not bridge.simulation else "SimulationModel(SEM)",
        "simulation": bool(bridge.simulation),
        "dowhy_available": bool(getattr(sys.modules.get("counterfactual_bridge"), "_DOWHY_AVAILABLE", False)),
        "causallearn_available": bool(getattr(sys.modules.get("counterfactual_bridge"), "_CAUSALLEARN_AVAILABLE", False)),
        "estimand_type": identifiability.get("estimand_type", "N/A"),
        "data_diagnostics": data_diagnostics,
        "execution_profile": timer.to_dict(),
        "six_warriors": six_warriors,
        "stability_analysis": stability_analysis,
    }

    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    _stage("done", "分析完成。", 1.0)
    _emit({"type": "result", "payload": result})


def _card_to_dict(card):
    """将 WarriorCard 转换为可序列化的字典，并保留更丰富的原始指标。"""
    raw = card.raw
    if raw is not None and not isinstance(raw, (dict, list, str, int, float, bool, type(None))):
        # 对非原生类型尝试抽取属性；失败则回退到空 dict，避免重复异常
        try:
            raw = _extract_raw(card)
        except Exception:
            raw = {}
    elif raw is None:
        # 默认用 metrics + findings 填充 raw，确保前端可展开质谱级详情
        raw = _extract_raw(card)
    return {
        "warrior_id": card.warrior_id,
        "name": card.name,
        "instrument": card.instrument,
        "status": card.status,
        "color": card.color,
        "findings": card.findings,
        "metrics": card.metrics,
        "verdict": card.verdict,
        "raw": raw,
    }


def _extract_raw(card):
    """从 WarriorCard 或其关联对象中提取可序列化的原始指标。"""
    # 默认：metrics + findings 的详情版本
    detail = dict(card.metrics or {})
    if card.findings:
        detail["findings_full"] = card.findings
    if card.verdict:
        detail["verdict"] = card.verdict
    return detail


def _extract_identifiability(bridge, adapter):
    """从 DoWhy estimand 中提取可识别性细节。"""
    estimand = bridge.identified_estimand
    info = {
        "identifiable": False,
        "estimand_type": "N/A",
        "backdoor_paths": "N/A",
        "adjustment_set": [],
    }
    if estimand is None:
        return info

    # 可识别性
    info["identifiable"] = adapter.is_identifiable(estimand)

    # estimand_type
    if hasattr(estimand, "estimand_type"):
        info["estimand_type"] = str(estimand.estimand_type)

    # backdoor / adjustment
    if hasattr(estimand, "backdoor_variables") and estimand.backdoor_variables:
        info["adjustment_set"] = list(estimand.backdoor_variables)
    elif hasattr(estimand, "identifier"):
        ident = estimand.identifier
        if isinstance(ident, dict):
            info["backdoor_paths"] = ident.get("backdoor", "N/A")
            info["estimand_type"] = ident.get("estimand_type", info["estimand_type"])
        else:
            info["backdoor_paths"] = str(ident)

    return info


def _run_stability_analysis(bridge, tokens, concept_names, window_size, threshold, max_concepts, estimate, valid_filter=None):
    """执行轻量稳定性与鲁棒性分析（bootstrap 边稳定性、ATE 置换检验、K-fold CV）。"""
    from _token_filters import is_valid_concept
    from counterfactual_bridge import TRACE2DoWhy

    if valid_filter is None:
        valid_filter = is_valid_concept

    rng = np.random.default_rng(42)
    n_bootstrap = 30
    edge_stability = {}
    ate_bootstrap = []

    # 原始显著边集合
    original_edges = {(s, t) for s, t, _ in bridge.significant_edges}

    token_arr = np.asarray(tokens)
    T = len(tokens)
    for b in range(n_bootstrap):
        # 对 token 序列做 bootstrap resample（保持顺序）
        idx = rng.integers(0, T, size=T)
        boot_tokens = token_arr[idx].tolist()
        valid_boot = [t for t in boot_tokens if valid_filter(t)]
        if len(valid_boot) < 10:
            continue
        freq = Counter(valid_boot)
        boot_concepts = [w for w, _ in freq.most_common(max_concepts)]
        if len(boot_concepts) < 3:
            continue
        ci = {name: i for i, name in enumerate(boot_concepts)}
        boot_adj = np.zeros((len(boot_concepts), len(boot_concepts)))
        boot_ids = [ci.get(t) for t in boot_tokens if t in ci]
        for i in range(len(boot_ids)):
            for j in range(i + 1, min(i + window_size, len(boot_ids))):
                a, bb = boot_ids[i], boot_ids[j]
                if a is None or bb is None or a == bb:
                    continue
                boot_adj[a, bb] += 1.0
        if boot_adj.max() > 0:
            boot_adj = boot_adj / boot_adj.max() * 8.0
        # 记录与原始概念重合的边
        for s, t in original_edges:
            if s in ci and t in ci:
                key = f"{s} → {t}"
                edge_stability.setdefault(key, []).append(
                    float(boot_adj[ci[s], ci[t]] > threshold)
                )
    # 准备数据列名（供 bootstrap / permutation / CV 复用）
    df = None
    treatment_col = bridge.treatment if hasattr(bridge, "treatment") else bridge.concept_names[0]
    outcome_col = bridge.outcome if hasattr(bridge, "outcome") else bridge.concept_names[-1]
    try:
        df = bridge.data_df.copy()
    except Exception:
        pass

    # 数据重采样 bootstrap ATE：直接在原始数据行上 bootstrap，估计 ATE 的抽样波动
    if df is not None and treatment_col in df.columns and outcome_col in df.columns:
        try:
            n_rows = df.shape[0]
            covariates = [c for c in df.columns if c not in (treatment_col, outcome_col)]
            for _ in range(n_bootstrap):
                idx = rng.integers(0, n_rows, size=n_rows)
                boot_df = df.iloc[idx]
                X = boot_df[[treatment_col] + covariates].values
                y = boot_df[outcome_col].values
                coef = np.linalg.lstsq(X, y, rcond=None)[0][0]
                ate_bootstrap.append(float(coef))
        except Exception:
            pass

    # 置换检验（Permutation test）：打乱 treatment 列看 ATE 是否显著
    permutation_ates = []
    if df is not None and treatment_col in df.columns and outcome_col in df.columns:
        orig_ate = float(estimate.value)
        for _ in range(20):
            perm_df = df.copy()
            perm_df[treatment_col] = rng.permutation(perm_df[treatment_col].values)
            try:
                # 快速线性回归估计
                X = perm_df[[treatment_col] + [c for c in df.columns if c not in (treatment_col, outcome_col)]].values
                y = perm_df[outcome_col].values
                coef = np.linalg.lstsq(X, y, rcond=None)[0][0]
                permutation_ates.append(float(coef))
            except Exception:
                pass
        p_value = np.mean([abs(a) >= abs(orig_ate) for a in permutation_ates]) if permutation_ates else None
    else:
        p_value = None

    # K-fold CV 估计 ATE 稳定性
    cv_ates = []
    n_folds = 3
    n_rows = df.shape[0] if df is not None else 0
    if df is not None and n_rows >= n_folds * 2:
        fold_size = n_rows // n_folds
        for fold in range(n_folds):
            mask = np.ones(n_rows, dtype=bool)
            mask[fold * fold_size:(fold + 1) * fold_size] = False
            try:
                train_df = df.iloc[mask]
                X = train_df[[treatment_col] + [c for c in df.columns if c not in (treatment_col, outcome_col)]].values
                y = train_df[outcome_col].values
                coef = np.linalg.lstsq(X, y, rcond=None)[0][0]
                cv_ates.append(float(coef))
            except Exception:
                pass

    per_edge = {k: float(np.mean(v)) for k, v in edge_stability.items() if v}
    return {
        "edge_stability_mean": float(np.mean(list(per_edge.values()))) if per_edge else 0.0,
        "edge_stability_std": float(np.std(list(per_edge.values()))) if per_edge else 0.0,
        "edge_stability_per_edge": per_edge,
        "ate_bootstrap_std": float(np.std(ate_bootstrap)) if ate_bootstrap else None,
        "permutation_p_value": float(p_value) if p_value is not None else None,
        "cv_folds": n_folds,
        "cv_ate_mean": float(np.mean(cv_ates)) if cv_ates else None,
        "cv_ate_std": float(np.std(cv_ates)) if cv_ates else None,
    }


def _extract_data_diagnostics(bridge, tokens, valid_tokens, concept_names, adj):
    """生成数据与模型级诊断指标。"""
    diagnostics = {
        "raw_tokens": len(tokens),
        "valid_concept_tokens": len(valid_tokens),
        "unique_tokens": len(set(tokens)),
        "unique_concepts": len(concept_names),
        "concept_coverage": round(len(valid_tokens) / max(len(tokens), 1), 4),
        "adj_density": round(float((adj > 0).sum()) / max(adj.size, 1), 4),
        "max_delta_nll": round(float(adj.max()), 3),
        "bpe_type": getattr(bridge, "bpe_type", "unknown"),
        "unk_rate": round(float(getattr(bridge, "unk_rate", 0.0)), 4),
        "n_concepts_after_aggregate": len(bridge.concept_names),
        "n_significant_edges": len(bridge.significant_edges),
        "max_edges_for_dowhy": bridge.max_edges_for_dowhy,
        "filter_mode": bridge.filter_mode,
        "sem_regularization": bridge.sem_regularization or "none",
    }
    # 数值稳定性指标
    try:
        df = bridge.data_df
        numeric = df.select_dtypes(include=[np.number]).values
        if numeric.shape[1] > 1:
            corr = np.corrcoef(numeric, rowvar=False)
            eigvals = np.linalg.eigvalsh(corr)
            diagnostics["condition_number"] = round(float(np.max(np.abs(eigvals)) / max(np.min(np.abs(eigvals)), 1e-12)), 2)
            diagnostics["max_correlation"] = round(float(np.max(np.abs(corr[np.triu_indices_from(corr, k=1)]))), 3)
            diagnostics["min_eigenvalue"] = round(float(np.min(eigvals)), 4)
    except Exception:
        pass
    return diagnostics


if __name__ == "__main__":
    main()
