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
import threading
from collections import Counter
from pathlib import Path

# 抑制第三方库 causallearn 内部的 tqdm 进度条输出，
# 这些进度条走 stderr 会被 Web UI 误显示为大量 ⚠ 噪声。
if 'TQDM_DISABLE' not in os.environ:
    os.environ['TQDM_DISABLE'] = '1'

# P2: 抑制 pandas 可选依赖版本警告 (numexpr/bottleneck)
# 这些警告不影响功能，但会在 Web UI 实时日志中显示为噪声
import warnings as _warnings
_warnings.filterwarnings('ignore', message=r".*Pandas requires version.*")
_warnings.filterwarnings('ignore', category=UserWarning, module=r"pandas\..*")

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
    # 统一 SSE 事件结构：始终输出 progress 字段（None 时为 null），
    # 避免前端因字段时有时无而产生解析分支。
    _emit({
        "type": "stage",
        "stage": stage,
        "message": message,
        "progress": round(progress, 2) if progress is not None else None,
    })


# ── 长耗时阶段心跳 ─────────────────────────────────────────────────────
# DoWhy 的 estimate_effect / refute_estimate 在 DEEP 模式下可能单次阻塞
# 1-3 分钟且不提供进度回调。后台线程每 5 秒向终端日志发射一条心跳。
def _heartbeat_log(label: str, interval: float = 5.0):
    """返回 (blocking_fn) -> blocking_fn 的包装器。

    用法:
        result = _heartbeat_log("Bootstrap 估计 ATE")(lambda: bridge.estimate())
    """
    def _wrap(blocking_fn):
        stop = threading.Event()

        def _beat():
            t0 = time.perf_counter()
            while not stop.is_set():
                elapsed = time.perf_counter() - t0
                _log("info", f"⏳ {label} — 已运行 {elapsed:.0f}s")
                stop.wait(interval)

        t = threading.Thread(target=_beat, daemon=True)
        t.start()
        try:
            return blocking_fn()
        finally:
            stop.set()
            t.join(timeout=1)
    return _wrap


# ── debt-10：结果 Schema 校验 ─────────────────────────────────────────
# 加载 schema/result_schema.json，在序列化 result 前校验必需字段。
# 校验为非阻塞式：缺失字段仅记录 warn 日志并补 _schema_missing 标记，
# 不中断已有结果输出，保证向后兼容。
_RESULT_SCHEMA = None


def _load_result_schema():
    global _RESULT_SCHEMA
    if _RESULT_SCHEMA is not None:
        return _RESULT_SCHEMA
    try:
        schema_path = Path(__file__).resolve().parent / "schema" / "result_schema.json"
        with open(schema_path, "r", encoding="utf-8") as f:
            _RESULT_SCHEMA = json.load(f)
    except Exception as e:
        _log("warn", f"加载 result_schema.json 失败，跳过结果校验: {e}")
        _RESULT_SCHEMA = {}
    return _RESULT_SCHEMA


def _validate_result(result: dict) -> dict:
    """按 result_schema.json 校验必需字段，缺失字段记 warn 并补标记。"""
    schema = _load_result_schema()
    required = schema.get("required") if schema else None
    if not required:
        return result
    missing = [f for f in required if result.get(f) is None]
    if missing:
        _log("warn", f"结果缺少 Schema 必需字段: {', '.join(missing)}（已标记，结果仍输出）")
        result["_schema_missing"] = missing
    else:
        result["_schema_validated"] = True
    return result


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
    """中文分词：使用 jieba（加载领域词）。

    P0 修缮 (2026-07-25 元审计 Round 12.12):
    原实现将 jieba 标记为"可选依赖"，缺失时静默回退到
    `re.findall(r'[\\u4e00-\\u9fff]{2,}', text)`。该回退有两个致命缺陷:
      1. 只匹配连续中文字符，英文/数字/标点全部被丢弃
      2. 中文连续片段被当成单个 token，无法正确切词
    导致中英混排文本的"有效概念数"严重低估，触发
    "有效词数不足"错误——历史上 0/2/3/5/6/7/8/9 个有效词的
    失败任务全部源于此。

    修复: jieba 是核心依赖（非可选），缺失时明确报错并提示安装。
    """
    try:
        import jieba
        import logging
        jieba.setLogLevel(logging.WARNING)  # 抑制词典加载的 INFO 日志
        _DOMAIN_WORDS = [
            # 原有：算法推荐系统领域
            "算法推荐", "信息茧房", "观点极化", "社会共识", "公共讨论",
            "用户行为", "算法透明", "推荐系统", "因果推断",
            # ROUND27: 商业/新闻领域通用词（提升新闻文本分词质量）
            "供应链", "股价", "高管", "收购", "裁员", "监管", "审计",
            "财报", "营收", "毛利率", "产能", "供应商", "客户", "订单",
            "董事会", "股东大会", "敌意收购", "资本运作", "股权结构",
            "战略评估", "机构投资者", "大宗交易", "看空报告", "评级下调",
            "流动性危机", "资产剥离", "业务重组", "公司治理",
        ]
        for w in _DOMAIN_WORDS:
            jieba.add_word(w, freq=1000)
        return list(jieba.lcut(text))
    except ImportError as e:
        # P0 修缮: 不再静默回退到无效的正则模式
        raise RuntimeError(
            "jieba 是核心依赖（用于中文分词），但未安装。"
            "请运行: pip install jieba  "
            "（正则回退模式无法处理中英混排文本，会导致有效概念数严重不足）"
        ) from e


def _write_error(out_dir: Path, message: str):
    """统一错误输出：日志、文件、SSE。
    文件 I/O 失败不阻断 SSE 错误事件——即使磁盘满，
    前端仍能收到错误消息而非静默超时。
    """
    _log("error", message)
    _stage("error", message, 1.0)
    result = {"success": False, "error": message}
    try:
        (out_dir / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (out_dir / "report.md").write_text(f"# 分析失败\n\n{message}\n", encoding="utf-8")
    except OSError as e:
        _log("warn", f"写入错误文件失败（磁盘满/权限不足）: {e}")
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
    if not (2 <= window_size <= 256):
        _write_error(out_dir, f"window_size 必须在 [2, 256] 之间，当前为 {window_size}")
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
        "进而", "指出", "表示", "显示", "表明", "说明", "强调",
        "报道", "获悉", "透露", "证实", "否认", "回应",
        "当日", "此前", "近期", "届时", "目前", "随后", "此后",
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
    try:
        tokens = _tokenize(text)
    except RuntimeError as e:
        _write_error(out_dir, str(e))
        return
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

    # P0 fix (Round 22 §3b): 保存归一化前的原始 max_delta_nll,
    # 否则归一化后 adj.max() 恒为 8.0, 导致所有轨迹行的 max_delta_nll 列完全相同,
    # 失去区分度. 原始值通过 _extract_data_diagnostics 的 raw_max_delta_nll 参数传入.
    raw_max_delta_nll = float(adj.max()) if adj.size > 0 else 0.0
    if adj.max() > 0:
        adj = adj / adj.max() * 8.0

    n_edges = int((adj > threshold).sum())
    _log("info", f"概念数: {len(concept_names)}, 候选边数: {n_edges}")
    timer.end("graph")

    timer.start("bridge")
    _stage("bridge", "正在调用 TRACE2DoWhy 桥接器...", 0.42)
    bridge = TRACE2DoWhy(adj, concept_names, threshold=threshold,
                         concept_min_freq=concept_min_freq, simulation=False,
                         max_edges_for_dowhy=max_edges_for_dowhy,
                         filter_mode=config.get("filter_mode", "topn"),
                         filter_percentile=config.get("filter_percentile", 85),
                         random_state=config.get("random_state", 42),
                         classical_mode=config.get("classical_mode", False),
                         max_concepts=max_concepts)
    # 注入已聚合的概念级数据，避免 bridge.build_model() 内部对概念名列表
    # 重新执行 aggregate_concepts()（概念名列表每个元素只出现一次，会被
    # concept_min_freq=2 全部过滤掉，导致 "概念节点不足（<2）" 错误）。
    bridge.concept_adj = adj
    bridge.concept_names = concept_names
    bridge.concept_idx = concept_idx
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
        # DEEP 模式：DoWhy bootstrap 估计可能耗时 1-5 分钟，
        # 后台线程每 5 秒向终端日志发射心跳 "⏳ ... 已运行 Ns"
        estimate = _heartbeat_log("Bootstrap 估计 ATE")(lambda: bridge.estimate())
        ci = DoWhy14Adapter.get_confidence_interval(estimate)
        confidence_method = "bootstrap" if not bridge.simulation else "SEM-analytic"
        _log("info", f"ATE={estimate.value:.4f}, 95% CI=[{ci[0]:.4f}, {ci[1]:.4f}]")
    timer.end("estimate")

    refutations = {}
    if run_refuters:
        timer.start("refute")
        _stage("refute", "正在运行反驳测试 (3 refuters)...", 0.80)
        refutations = _heartbeat_log("反驳测试 (3 refuters)")(lambda: bridge.refute())
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
    try:
        (out_dir / "report.md").write_text(report, encoding="utf-8")
    except OSError as e:
        _log("warn", f"写入 report.md 失败: {e}")
    timer.end("report")

    ref_list = []
    for name, r in refutations.items():
        check = getattr(r, '_check', None)
        ne = float(r.new_effect)
        dm = check.get('display_metric') if isinstance(check, dict) else None
        ref_list.append({
            "method": name,
            "new_effect": ne if np.isfinite(ne) else None,
            "refuted": bool(check.get('refuted', False)) if isinstance(check, dict) else bool(getattr(r, 'refuted', False)),
            "display_metric": float(dm) if dm is not None and np.isfinite(float(dm)) else None,
            "display_label": check.get('display_label') if isinstance(check, dict) else None,
        })

    scan_list = []
    for r in scan:
        def _safe_float(v):
            f = float(v)
            return None if np.isnan(f) else f
        item = {
            "source": r["source"],
            "target": r["target"],
            "trace_dnl": _safe_float(r["trace_dnl"]),
            "ite": _safe_float(r.get("ite", float('nan'))),
            "observed": _safe_float(r.get("observed", float('nan'))),
            "counterfactual": _safe_float(r.get("counterfactual", float('nan'))),
        }
        if "error" in r:
            item["error"] = r["error"]
        scan_list.append(item)

    # 提取可识别性细节
    identifiability = _extract_identifiability(bridge, DoWhy14Adapter)

    # 数据与模型诊断
    # P0 fix (Round 22 §3b): 传入 raw_max_delta_nll, 避免使用归一化后的 adj.max().
    data_diagnostics = _extract_data_diagnostics(bridge, tokens, valid_tokens, concept_names, adj, raw_max_delta_nll)
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
        "ate": float(estimate.value) if np.isfinite(estimate.value) else None,
        "confidence_interval": [
            float(ci[0]) if np.isfinite(ci[0]) else None,
            float(ci[1]) if np.isfinite(ci[1]) else None,
        ],
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

    try:
        (out_dir / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as e:
        _log("warn", f"写入 result.json 失败: {e}")

    _stage("done", "分析完成。", 1.0)
    _validate_result(result)
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
        # P0修复: 同步 WarriorCard.tier 字段（six_warriors.py P0-1 修缮）
        # tier: "A"=真算法层(可追溯因果证据), "B"=启发式诊断层(文本特征启发式)
        "tier": getattr(card, "tier", "A"),
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


def _bca_bootstrap_ci(bootstrap_estimates, original_estimate, jackknife_estimates,
                      confidence_level=0.95):
    """BCa (Bias-Corrected and accelerated) bootstrap 置信区间。

    ROUND26 算法审视 P1-1 修复: 百分位法→BCa, 小样本下减少偏差。

    百分位法 CI 在以下情况下有偏 (Efron & Tibshirani 1993, Ch. 14):
      1. 偏差: bootstrap 分布中心 ≠ 原始估计量时,百分位法不修正偏差
      2. 偏度: 统计量抽样分布偏斜时,百分位法不对称覆盖
      3. 小样本: N < 50 时偏差与偏度影响被放大

    BCa 通过两个校正系数修正:
      - z0: 偏差校正,基于 bootstrap 估计 < 原始估计的比例
      - a:  加速度系数,基于 jackknife 估计的影响函数

    Args:
        bootstrap_estimates: bootstrap 重采样得到的统计量序列 (ate_bootstrap)
        original_estimate:   原始样本上的统计量 (theta_hat),必须与 bootstrap
                             使用同一统计量定义
        jackknife_estimates: leave-one-out jackknife 估计序列,用于计算加速度 a
        confidence_level:    置信水平,默认 0.95

    Returns:
        [ci_lo, ci_hi] 列表;若无法计算 (样本不足/退化) 返回 None。
    """
    from scipy.stats import norm

    boot = np.asarray(bootstrap_estimates, dtype=float)
    n_boot = len(boot)
    if n_boot < 2:
        return None

    # ── z0: 偏差修正 ──
    # Phi^-1( (#{boot < theta_hat} + 0.5*#{boot == theta_hat}) / n_boot )
    n_less = float(np.sum(boot < original_estimate))
    n_eq = float(np.sum(boot == original_estimate))
    prop = (n_less + 0.5 * n_eq) / n_boot
    # 边界保护: prop=0 → norm.ppf(0)=-inf, prop=1 → norm.ppf(1)=+inf
    # 用 0.5/n_boot 的极小偏移避免退化 (Efron & Tibshirani 1993 §14.3 推荐)
    if prop <= 0:
        prop = 0.5 / n_boot
    elif prop >= 1:
        prop = 1.0 - 0.5 / n_boot
    z0 = norm.ppf(prop)

    # ── a: 加速度因子 (jackknife) ──
    # a = sum((theta_dot - theta_(i))^3) / (6 * (sum((theta_dot - theta_(i))^2))^1.5)
    jack = np.asarray(jackknife_estimates, dtype=float)
    jack_mean = np.mean(jack)
    diff = jack_mean - jack
    denom = 6.0 * (np.sum(diff ** 2) ** 1.5)
    if denom == 0 or not np.isfinite(denom):
        # 退化: jackknife 估计全一致 (常数数据) → a=0, 退化为 BC (仅偏差修正)
        a = 0.0
    else:
        a = float(np.sum(diff ** 3) / denom)

    # ── 调整分位数 ──
    alpha = 1.0 - confidence_level
    z_lo = norm.ppf(alpha / 2.0)
    z_hi = norm.ppf(1.0 - alpha / 2.0)

    def _adjust(z_alpha):
        denom_adj = 1.0 - a * (z0 + z_alpha)
        if denom_adj == 0 or not np.isfinite(denom_adj):
            # 退化: 回退到百分位法分位数
            return None
        return norm.cdf(z0 + (z0 + z_alpha) / denom_adj)

    alpha1 = _adjust(z_lo)
    alpha2 = _adjust(z_hi)
    # 任一端无法调整 → 回退到未校正的百分位 (仍优于报错)
    if alpha1 is None or alpha2 is None:
        alpha1, alpha2 = alpha / 2.0, 1.0 - alpha / 2.0
    # 裁剪到 [0, 1] 防止 norm.cdf 数值溢出导致越界
    alpha1 = max(0.0, min(1.0, alpha1))
    alpha2 = max(0.0, min(1.0, alpha2))

    ci_lo = float(np.percentile(boot, alpha1 * 100.0))
    ci_hi = float(np.percentile(boot, alpha2 * 100.0))
    return [ci_lo, ci_hi]


def _run_stability_analysis(bridge, tokens, concept_names, window_size, threshold, max_concepts, estimate, valid_filter=None):
    """执行轻量稳定性与鲁棒性分析（bootstrap 边稳定性、ATE 置换检验、K-fold CV）。"""
    from _token_filters import is_valid_concept
    from counterfactual_bridge import TRACE2DoWhy

    if valid_filter is None:
        valid_filter = is_valid_concept


    rng = np.random.default_rng(42)
    n_bootstrap = 1000  # P0修复: 30→1000, 确保百分位法 CI 可靠 (Efron & Tibshirani 1993)
    n_permutation = 1000  # P0修复: 20→1000, 确保置换检验 p 值精度
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
    # P1修复: 增加 intercept 列，避免非中心化数据的系数偏差
    if df is not None and treatment_col in df.columns and outcome_col in df.columns:
        try:
            n_rows = df.shape[0]
            covariates = [c for c in df.columns if c not in (treatment_col, outcome_col)]
            for _ in range(n_bootstrap):
                idx = rng.integers(0, n_rows, size=n_rows)
                boot_df = df.iloc[idx]
                X = boot_df[[treatment_col] + covariates].values
                y = boot_df[outcome_col].values
                # P1修复: 添加 intercept 列 (全1)，treatment 系数索引变为 1
                X_intercept = np.hstack([np.ones((X.shape[0], 1)), X])
                coef = np.linalg.lstsq(X_intercept, y, rcond=None)[0][1]
                ate_bootstrap.append(float(coef))
        except Exception:
            pass

    # 置换检验（Permutation test）：打乱 treatment 列看 ATE 是否显著
    # P0修复: (1) 次数 20→1000 (2) p值 +1 修正避免 p=0 (Phipson & Smyth 2010) (3) 加 intercept
    permutation_ates = []
    if df is not None and treatment_col in df.columns and outcome_col in df.columns:
        orig_ate = float(estimate.value)
        for _ in range(n_permutation):
            perm_df = df.copy()
            perm_df[treatment_col] = rng.permutation(perm_df[treatment_col].values)
            try:
                # 快速线性回归估计 (P1修复: 加 intercept 列)
                X = perm_df[[treatment_col] + [c for c in df.columns if c not in (treatment_col, outcome_col)]].values
                y = perm_df[outcome_col].values
                X_intercept = np.hstack([np.ones((X.shape[0], 1)), X])
                coef = np.linalg.lstsq(X_intercept, y, rcond=None)[0][1]
                permutation_ates.append(float(coef))
            except Exception:
                pass
        # P0修复: +1 修正公式 (count+1)/(n+1)，避免 p=0 且确保零假设下 p 均匀分布
        if permutation_ates:
            count_extreme = int(np.sum([abs(a) >= abs(orig_ate) for a in permutation_ates]))
            p_value = (count_extreme + 1) / (len(permutation_ates) + 1)
        else:
            p_value = None
    else:
        p_value = None

    # K-fold CV 估计 ATE 稳定性
    # P0修复: (1) 用 array_split 避免漏样本 (2) 加 intercept (3) 在测试折上评估 ATE
    cv_ates = []
    n_folds = 3
    n_rows = df.shape[0] if df is not None else 0
    if df is not None and n_rows >= n_folds * 2:
        all_indices = np.arange(n_rows)
        fold_indices = np.array_split(all_indices, n_folds)  # P0修复: 不漏样本
        for test_idx in fold_indices:
            mask = np.ones(n_rows, dtype=bool)
            mask[test_idx] = False
            try:
                train_df = df.iloc[mask]
                test_df = df.iloc[~mask]
                X_train = train_df[[treatment_col] + [c for c in df.columns if c not in (treatment_col, outcome_col)]].values
                y_train = train_df[outcome_col].values
                # P1修复: 加 intercept 列
                X_train_int = np.hstack([np.ones((X_train.shape[0], 1)), X_train])
                coef = np.linalg.lstsq(X_train_int, y_train, rcond=None)[0]
                # P0修复: 在测试折上计算 ATE (out-of-fold 评估)
                X_test = test_df[[treatment_col] + [c for c in df.columns if c not in (treatment_col, outcome_col)]].values
                y_test = test_df[outcome_col].values
                X_test_int = np.hstack([np.ones((X_test.shape[0], 1)), X_test])
                # P0修复: ATE = E[Y|do(T=1)] - E[Y|do(T=0)]
                # 对线性模型 Y = β0 + β1·T + Σγ·X，ATE = β1（treatment 系数）
                # 原代码 np.mean(y_pred) 计算的是 Y 预测均值，非 ATE
                # 显式反事实: 对测试折设置 T=1 和 T=0，取预测差均值
                X_test_t1 = X_test.copy()
                X_test_t1[:, 0] = 1.0  # treatment=1
                X_test_t0 = X_test.copy()
                X_test_t0[:, 0] = 0.0  # treatment=0
                X_test_t1_int = np.hstack([np.ones((X_test_t1.shape[0], 1)), X_test_t1])
                X_test_t0_int = np.hstack([np.ones((X_test_t0.shape[0], 1)), X_test_t0])
                y1_pred = X_test_t1_int @ coef
                y0_pred = X_test_t0_int @ coef
                cv_ates.append(float(np.mean(y1_pred - y0_pred)))
            except Exception:
                pass

    per_edge = {k: float(np.mean(v)) for k, v in edge_stability.items() if v}
    # ROUND26 算法审视 P1-1 修复: 百分位法→BCa, 小样本下减少偏差
    # 原 P0 修复使用百分位法 (np.percentile 2.5%/97.5%) 构建 95% CI;
    # 当 bootstrap 分布有偏/偏斜时 (treatment 为计数变量时常见),
    # 百分位法覆盖率偏离名义 95%。BCa 通过 z0 (偏差修正) + a (加速度,
    # jackknife) 校正两端分位数。若 BCa 无法计算 (退化数据/jackknife
    # 不可用), 回退到百分位法以保持向后兼容。
    ate_bootstrap_ci = None
    ate_bootstrap_method = None
    if ate_bootstrap:
        ate_bootstrap_method = "percentile"  # 默认回退值
        ate_bootstrap_ci = [
            float(np.percentile(ate_bootstrap, 2.5)),
            float(np.percentile(ate_bootstrap, 97.5)),
        ]
        # 尝试升级到 BCa: 需要原始 OLS 估计 + jackknife 估计
        # 使用与 bootstrap 相同的统计量定义 (未调整 OLS treatment 系数),
        # 而非 DoWhy estimate.value (语义不同, 见下方 ate_bootstrap_type 注释)
        try:
            covariates_full = [c for c in df.columns
                               if c not in (treatment_col, outcome_col)]
            X_full = df[[treatment_col] + covariates_full].values
            y_full = df[outcome_col].values
            X_full_int = np.hstack([np.ones((X_full.shape[0], 1)), X_full])
            theta_hat = float(np.linalg.lstsq(X_full_int, y_full, rcond=None)[0][1])
            # Jackknife: leave-one-out OLS treatment 系数
            n_rows_jk = df.shape[0]
            jack_estimates = []
            for i in range(n_rows_jk):
                mask_jk = np.ones(n_rows_jk, dtype=bool)
                mask_jk[i] = False
                X_jk = df.loc[mask_jk, [treatment_col] + covariates_full].values
                y_jk = df.loc[mask_jk, outcome_col].values
                X_jk_int = np.hstack([np.ones((X_jk.shape[0], 1)), X_jk])
                # 至少需要 (协变量数+2) 行才能求解; 行数不足跳过该 jackknife 点
                if X_jk_int.shape[0] < X_jk_int.shape[1] + 1:
                    continue
                coef_jk = np.linalg.lstsq(X_jk_int, y_jk, rcond=None)[0][1]
                jack_estimates.append(float(coef_jk))
            if len(jack_estimates) >= 3:
                bca_ci = _bca_bootstrap_ci(ate_bootstrap, theta_hat,
                                           jack_estimates, confidence_level=0.95)
                if bca_ci is not None:
                    ate_bootstrap_ci = bca_ci
                    ate_bootstrap_method = "bca"
        except Exception:
            # BCa 计算失败时静默回退到百分位法 (保持向后兼容)
            pass
    return {
        "edge_stability_mean": float(np.mean(list(per_edge.values()))) if per_edge else 0.0,
        "edge_stability_std": float(np.std(list(per_edge.values()))) if per_edge else 0.0,
        "edge_stability_per_edge": per_edge,
        "ate_bootstrap_std": float(np.std(ate_bootstrap)) if ate_bootstrap else None,
        "ate_bootstrap_ci": ate_bootstrap_ci,  # ROUND26 P1-1: BCa 95% CI (回退百分位法)
        "ate_bootstrap_method": ate_bootstrap_method,
        # P1修复: 标注 bootstrap 估计的语义类型
        # "unadjusted_ols" = 未调整 OLS 系数 (dY/dT)，与 DoWhy backdoor 调整后 ATE 语义不同
        # 两者符号可相反（Simpson 悖论），数值差异反映混杂偏倚
        "ate_bootstrap_type": "unadjusted_ols" if ate_bootstrap else None,
        "permutation_p_value": float(p_value) if p_value is not None else None,
        "permutation_n": n_permutation,  # P0修复: 记录置换次数供诊断
        "cv_folds": n_folds,
        "cv_ate_mean": float(np.mean(cv_ates)) if cv_ates else None,
        "cv_ate_std": float(np.std(cv_ates)) if cv_ates else None,
    }


def _extract_data_diagnostics(bridge, tokens, valid_tokens, concept_names, adj, raw_max_delta_nll=None):
    """生成数据与模型级诊断指标。

    P0 fix (Round 22 §3b): raw_max_delta_nll 为归一化前的原始 ΔNLL 最大值.
    若未提供 (旧调用方), 回退到 adj.max() (归一化后, 恒为 8.0).
    """
    if raw_max_delta_nll is None:
        raw_max_delta_nll = float(adj.max()) if adj.size > 0 else 0.0
    # P0 fix (Round 23 §1): 添加 signal_type 字段区分信号语义.
    # py_bridge.py (LIGHT/DEEP) 的 adj 由共现计数构建 (adj[a,b] += 1.0),
    # raw_max_delta_nll 实为 "最大共现计数" 而非真实 ΔNLL.
    # 保留字段名 max_delta_nll 以维持下游 (trace-to-edm config.py /
    # csv_builder.py) 兼容, 但通过 signal_type="co_occurrence" 显式标注语义,
    # 避免数学审计时的语义混淆.
    # SUPER 模式 (llama_worker.py) 的 adj 来自 LLaMA counterfactual probing,
    # 为真实 ΔNLL, signal_type="delta_nll".
    # simulation 标志只影响 data_df 来源 (SEM 生成 vs 真实观测), 不影响 adj
    # 构建方式, 因此 LIGHT/DEEP 下始终为 co_occurrence.
    diagnostics = {
        "raw_tokens": len(tokens),
        "valid_concept_tokens": len(valid_tokens),
        "unique_tokens": len(set(tokens)),
        "unique_concepts": len(concept_names),
        "concept_coverage": round(len(valid_tokens) / max(len(tokens), 1), 4),
        "adj_density": round(float((adj > 0).sum()) / max(adj.size, 1), 4),
        "max_delta_nll": round(float(raw_max_delta_nll), 3),
        "signal_type": "co_occurrence",
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
