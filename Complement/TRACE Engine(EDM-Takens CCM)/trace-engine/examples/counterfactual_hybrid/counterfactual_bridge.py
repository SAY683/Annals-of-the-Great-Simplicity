"""
TRACE → DoWhy Counterfactual Bridge v2
=======================================
将 TRACE 引擎的因果发现结果桥接到 DoWhy 的正式因果推断框架。
v2 新增: DoWhy 0.14 兼容 + causallearn (PC/GES) + Graphviz 可视化。

六合一架构:
  Layer 1-2: TRACE Auditor (环境+配置)     ← trace_plus.py
  Layer 3:   CCM Cross-Validation          ← ccm_causality.py
  Layer 4:   DoWhy 识别 + 三层反驳          ← 本模块
  Layer 5:   Counterfactual 反事实查询      ← 本模块
  Layer 6:   causallearn 独立验证           ← 本模块 (NEW)

用法:
    from counterfactual_bridge import TRACE2DoWhy

    bridge = TRACE2DoWhy(adj_matrix, token_list)
    bridge.build_model()
    bridge.identify()
    bridge.estimate()
    bridge.refute()
    bridge.counterfactual_scan(n_top_edges=5)
    bridge.causallearn_validate()  # NEW: PC/GES 独立验证
    bridge.visualize("causal_graph")  # NEW: DAG 可视化
    print(bridge.report())

模拟模式（DoWhy 未安装时自动启用）:
    bridge = TRACE2DoWhy(adj_matrix, token_list, simulation=True)
"""

import functools
import sys
import warnings
from collections import Counter
from typing import Optional

import numpy as np

from _token_filters import is_valid_concept, classify_bpe_type, is_unk_token

# ── 可用性探测函数（debt-05: lru_cache 缓存，避免重复 import 开销）────────
# 将原模块级全局状态 _X_AVAILABLE 改为带缓存的探测函数；
# 旧变量名作为兼容别名保留（见文件末尾 _X_AVAILABLE = is_X_available()）。
@functools.lru_cache(maxsize=1)
def is_dowhy_available() -> bool:
    """探测 DoWhy 是否可用（带缓存）。"""
    try:
        import dowhy  # noqa: F401
        from dowhy import CausalModel  # noqa: F401
        return True
    except ImportError:
        return False


@functools.lru_cache(maxsize=1)
def is_causallearn_available() -> bool:
    """探测 causallearn 是否可用（带缓存）。"""
    try:
        import causallearn  # noqa: F401
        from causallearn.search.ConstraintBased.PC import pc  # noqa: F401
        from causallearn.search.ScoreBased.GES import ges  # noqa: F401
        return True
    except ImportError:
        return False


@functools.lru_cache(maxsize=1)
def is_graphviz_available() -> bool:
    """探测 graphviz 是否可用（带缓存）。"""
    try:
        import graphviz  # noqa: F401
        return True
    except ImportError:
        return False


@functools.lru_cache(maxsize=1)
def is_pandas_available() -> bool:
    """探测 pandas 是否可用（带缓存）。"""
    try:
        import pandas  # noqa: F401
        return True
    except ImportError:
        return False


# ── 模块级导入（惰性化 — P1-A 优化：避免 LIGHT 模式被 DoWhy/causallearn 导入拖慢 60-70s）───
# 原 implementation 在模块加载时无条件 import dowhy/pandas/graphviz/networkx,
# 即使 LIGHT 模式不需要这些库,也会触发 ~60-70s 的重导入开销。
# 优化策略:不声明模块级变量,实际导入延迟到首次属性访问时（通过 __getattr__）。
# 注意:不能写 CausalModel = None,否则 __getattr__ 不会触发（属性已存在为 None）。
# 兼容性:is_dowhy_available() 等探测函数已带 lru_cache,首次调用时才触发 import。


def __getattr__(name):
    """模块级惰性导入（Python 3.7+）。

    当外部代码访问 counterfactual_bridge.CausalModel / pd / graphviz / nx 时,
    才触发实际 import。LIGHT 模式不访问这些名称,完全跳过 DoWhy/causallearn 加载,
    将 LIGHT 模式延迟从 ~84s 降低到 ~10-15s（仅 jieba + statsmodels + 基础库）。

    注意:模块级不能声明同名变量(如 CausalModel=None),否则 __getattr__ 不触发。
    """
    if name == "CausalModel":
        try:
            from dowhy import CausalModel
            globals()["CausalModel"] = CausalModel  # 缓存到模块字典,后续访问直接命中
            return CausalModel
        except ImportError:
            globals()["CausalModel"] = None  # 缓存 None,避免重复尝试
            return None
    if name == "pd":
        import pandas
        globals()["pd"] = pandas
        return pandas
    if name == "graphviz":
        try:
            import graphviz
            globals()["graphviz"] = graphviz
            return graphviz
        except ImportError:
            globals()["graphviz"] = None
            return None
    if name == "nx":
        try:
            import networkx
            globals()["nx"] = networkx
            return networkx
        except ImportError:
            globals()["nx"] = None
            return None
    # _X_AVAILABLE 兼容:首次访问时触发惰性探测
    if name == "_DOWHY_AVAILABLE":
        _resolve_availability_flags()
        return globals()["_DOWHY_AVAILABLE"]
    if name == "_CAUSALLEARN_AVAILABLE":
        _resolve_availability_flags()
        return globals()["_CAUSALLEARN_AVAILABLE"]
    if name == "_GRAPHVIZ_AVAILABLE":
        _resolve_availability_flags()
        return globals()["_GRAPHVIZ_AVAILABLE"]
    if name == "_PANDAS_AVAILABLE":
        _resolve_availability_flags()
        return globals()["_PANDAS_AVAILABLE"]
    raise AttributeError(f"module 'counterfactual_bridge' has no attribute {name!r}")


# ── 兼容别名（保持 _DOWHY_AVAILABLE 等旧名可用,debt-05 双轨）──────────
# P1-A 优化:不在此处赋值,通过 __getattr__ 惰性解析。
# 旧代码访问 _DOWHY_AVAILABLE 时,触发 __getattr__ → _resolve_availability_flags()。
# 注意:不能写 _DOWHY_AVAILABLE = None,否则 __getattr__ 不触发。


def _resolve_availability_flags():
    """首次访问 _X_AVAILABLE 时调用,触发惰性探测并缓存结果。"""
    if "_DOWHY_AVAILABLE" not in globals() or globals().get("_DOWHY_AVAILABLE") is None and "_AVAILABILITY_RESOLVED" not in globals():
        globals()["_DOWHY_AVAILABLE"] = is_dowhy_available()
        globals()["_CAUSALLEARN_AVAILABLE"] = is_causallearn_available()
        globals()["_GRAPHVIZ_AVAILABLE"] = is_graphviz_available()
        globals()["_PANDAS_AVAILABLE"] = is_pandas_available()
        globals()["_AVAILABILITY_RESOLVED"] = True


# ══════════════════════════════════════════════════════════════════════
# 抽取模块再导出 (debt-01: 职责拆分)
# ══════════════════════════════════════════════════════════════════════
# 以下公共名称已移入独立职责模块，此处 re-import 以保持向后兼容:
#   from counterfactual_bridge import TRACE2DoWhy, DoWhy14Adapter, ...
#   from counterfactual_bridge import _DOWHY_AVAILABLE, ...
# 新模块不维护依赖检查块；可用性标志由本文件统一探测并通过参数下传。
from dowhy_adapter import DoWhy14Adapter
from pearl_counterfactual import PearlCounterfactual, estimate_sem_from_data
from causallearn_validator import CausalLearnValidator
from minimal_dataframe import _MinimalDataFrame, _ILocIndexer, _MinimalRow
from simulation_model import (
    SimulationEstimand,
    SimulationEstimate,
    SimulationRefutation,
    SimulationModel,
)

__all__ = [
    "TRACE2DoWhy",
    "DoWhy14Adapter",
    "PearlCounterfactual",
    "estimate_sem_from_data",
    "CausalLearnValidator",
    "_MinimalDataFrame",
    "_ILocIndexer",
    "_MinimalRow",
    "SimulationEstimand",
    "SimulationEstimate",
    "SimulationRefutation",
    "SimulationModel",
    "from_trace_output",
    "quick_analysis",
    "is_dowhy_available",
    "is_causallearn_available",
    "is_graphviz_available",
    "is_pandas_available",
    "_DOWHY_AVAILABLE",
    "_CAUSALLEARN_AVAILABLE",
    "_GRAPHVIZ_AVAILABLE",
    "_PANDAS_AVAILABLE",
]


# ══════════════════════════════════════════════════════════════════════
# 核心桥接类 v2
# ══════════════════════════════════════════════════════════════════════

class TRACE2DoWhy:
    """
    将 TRACE 因果邻接矩阵转换为 DoWhy 因果模型，
    提供识别、估计、反驳、反事实查询的完整管线。

    v2 新增:
    - DoWhy 0.14 API 兼容层
    - causallearn (PC/GES) 独立验证
    - Graphviz DAG 可视化
    - Pearl 三步反事实推理（独立实现，不依赖 dowhy-gcm）
    """

    def __init__(
        self,
        adj_matrix: np.ndarray,
        token_list: list,
        tokenizer=None,
        threshold: float = 0.03,
        concept_min_freq: int = 2,
        simulation: bool = False,
        random_state: int = 42,
        max_edges_for_dowhy: int = 8,
        filter_mode: str = "top_n",
        # P1-C 修复 (ROUND27 12维度核对): filter_percentile 默认值与 bridge_schema.json (85) 对齐
        filter_percentile: float = 85,
        sem_regularization: Optional[str] = None,
        sem_alpha: float = 0.01,
        min_concept_len: Optional[int] = None,
        classical_mode: bool = False,
        # P1-D 修复 (ROUND27 12维度核对): max_concepts 默认值与 bridge_schema.json (12) 对齐
        max_concepts: int = 12,
        # SYNC-4 修复 (2026-07-30 审计): 反驳偏差阈值，与 presets.yaml 对齐
        refutation_deviation_threshold: float = 0.3,
    ):
        self.adj_matrix = np.asarray(adj_matrix)
        if isinstance(token_list, str):
            raise TypeError("token_list 必须是列表/数组，不能是字符串")
        self.token_list = list(token_list)
        # 形状校验：adj_matrix 必须是 (T, T) 方阵且与 token_list 长度一致
        if self.adj_matrix.ndim != 2 or self.adj_matrix.shape[0] != self.adj_matrix.shape[1]:
            raise ValueError(f"adj_matrix 必须是 2D 方阵，得到 shape={self.adj_matrix.shape}")
        if self.adj_matrix.shape[0] != len(self.token_list):
            raise ValueError(
                f"adj_matrix shape ({self.adj_matrix.shape[0]}, {self.adj_matrix.shape[1]}) 与 token_list 长度 ({len(self.token_list)}) 不匹配"
            )
        # P1-7 修复 (Round 27 审计): 空矩阵语义统一。
        # 原实现接受 np.zeros((0,0))（形状校验通过），但下游 build_model 会抛 ValueError，
        # 与 six_warriors._deploy_trace 的 EMPTY_MATRIX 语义冲突。此处显式拒绝。
        if self.adj_matrix.size == 0:
            raise ValueError(
                "adj_matrix 不能为空（size==0）。上游 TRACE 未产生任何 token，"
                "请检查输入文本或模型 tokenizer 输出。"
            )
        # NaN/Inf 清理：避免在后续聚合/估计中静默传播
        if not np.all(np.isfinite(self.adj_matrix)):
            warnings.warn("adj_matrix 含 NaN/Inf，已替换为 0.0", RuntimeWarning)
            self.adj_matrix = np.nan_to_num(self.adj_matrix, nan=0.0, posinf=0.0, neginf=0.0)
        # P0 fix: ΔNLL 数学上必须非负（掩码后 NLL ≥ 原 NLL）。
        # 上游计算异常可能产生负值，传播到 concept_adj / SEM 系数会导致因果方向反转。
        self.adj_matrix = np.maximum(self.adj_matrix, 0.0)
        self.tokenizer = tokenizer
        self.threshold = threshold
        self.concept_min_freq = concept_min_freq
        # SYNC-4: 反驳偏差阈值（与 presets.yaml dowhy.refutation_deviation_threshold 对齐）
        self.refutation_deviation_threshold = float(refutation_deviation_threshold)
        # P1-A 优化:首次实例化 TRACE2DoWhy 时触发惰性可用性探测。
        # 这确保 _DOWHY_AVAILABLE 等变量在使用前被解析,同时避免模块加载时的 import 开销。
        _resolve_availability_flags()
        self.simulation = simulation or not _DOWHY_AVAILABLE
        self.rng = np.random.default_rng(random_state)

        # v3: 自适应过滤参数
        self.max_edges_for_dowhy = max_edges_for_dowhy
        # 统一 filter_mode 命名：presets.yaml / Web 使用 'topn'，bridge 内部使用 'top_n'
        self.filter_mode = "top_n" if filter_mode == "topn" else filter_mode
        self.filter_percentile = filter_percentile

        # v9: 最大概念数上限（0 表示不限制）。用于 SUPER 模式 token-level 图防止概念爆炸。
        self.max_concepts = max(0, int(max_concepts))

        # v3.5: SEM 正则化参数
        self.sem_regularization = sem_regularization
        self.sem_alpha = sem_alpha

        # v7: 概念最小长度（自动探测：字级 BPE 保留单字，词级 BPE 过滤单字碎片）
        self.min_concept_len = min_concept_len

        # v8: 古汉语模式（Shenji 古文保留之/乎/者/也等虚词）
        self.classical_mode = classical_mode

        # 管线状态
        self.concept_map: dict = {}
        self.concept_adj: np.ndarray = None
        self.concept_names: list = []
        self.concept_idx: dict = {}
        self.causal_graph = None
        self.model = None
        self.identified_estimand = None
        self.estimate_result = None
        self.refutation_results: dict = {}
        self.counterfactual_result = None
        self.scan_results: list = []
        self.significant_edges: list = []

        # v2 新增状态
        self.sem_coeff: np.ndarray = None       # 线性 SEM 系数矩阵
        self.pearl_cf: PearlCounterfactual = None
        self.cl_validator: CausalLearnValidator = None
        self.cl_comparison: dict = {}
        self.bpe_type: str = "unknown"           # v6: BPE 类型检测
        self.unk_rate: float = 0.0               # v6: UNK 率

        # 诊断日志
        self.log: list[str] = []

        # 六战士诊断卡片（外部通过 set_six_warriors_cards 注入后，
        # report() 会在末尾追加一致性检查章节）
        self.six_warriors_cards: dict = {}

    def _log(self, msg: str):
        self.log.append(msg)

    def set_six_warriors_cards(self, cards: dict):
        """注入六战士诊断卡片，供 report() 输出一致性检查章节。

        Parameters
        ----------
        cards : dict
            键为战士标识（如 'trace'/'ccm'/'dowhy_cf'/'causallearn'），
            值为含 ``status`` 与 ``verdict`` 属性的卡片对象（如 six_warriors.WarriorCard）。
        """
        self.six_warriors_cards = cards or {}

    @property
    def mode_name(self) -> str:
        if self.simulation:
            return "模拟模式 (SEM)"
        return "DoWhy 0.14 正式 do-calculus"

    # ── 步骤 0: Token → Concept 聚合 ─────────────────────────────────

    def aggregate_concepts(self) -> dict:
        """
        将 token 级因果图聚合到概念级。

        策略:
        1. 出现 >= concept_min_freq → 独立概念节点
        2. 低频 token → 归入 "<other>"
        3. token 间 ΔNLL → 概念间聚合 ΔNLL
        4. 单字 BPE 碎片过滤：词级 BPE 默认只保留长度 >= 2 的概念
        """
        T = len(self.token_list)
        token_counter = Counter(self.token_list)

        # ── v7: BPE 类型与最小概念长度自动探测 ──
        self.bpe_type = classify_bpe_type(self.token_list)
        if self.min_concept_len is not None:
            min_len = self.min_concept_len
        else:
            # 启发式：即使 BPE 被判定为字级，只要有效 token 中有一定比例多字词，
            # 也按词级处理（过滤单字碎片）。这能避免词级模型在跨域文本上产生
            # 大量 "永"/"恒"/"目" 等无意义单字概念。
            valid_tokens = [t for t in self.token_list if is_valid_concept(t, classical_mode=self.classical_mode)]
            total_valid = max(len(valid_tokens), 1)
            multi_char_ratio = sum(1 for t in valid_tokens if len(t.strip()) >= 2) / total_valid
            if multi_char_ratio > 0.15:
                min_len = 2
                self._log(f"BPE类型: {self.bpe_type}, 多字词占比={multi_char_ratio:.1%} -> 按词级过滤单字碎片")
            elif self.bpe_type == "character":
                min_len = 1
                self._log("BPE类型: 字级. 概念将以单字为主. 建议: Instant TRACE 训练词级 BPE.")
            else:
                min_len = 2
                self._log(f"BPE类型: {self.bpe_type} -> 过滤单字碎片")


        high_freq = {t for t, c in token_counter.items()
                     if c >= self.concept_min_freq
                     and is_valid_concept(t, classical_mode=self.classical_mode)
                     and len(t.strip()) >= min_len}

        # v9: 如果概念数超过上限，仅保留频率最高的前 N 个 token 作为独立概念
        if self.max_concepts > 0 and len(high_freq) > self.max_concepts:
            sorted_tokens = sorted(
                high_freq,
                key=lambda t: token_counter[t],
                reverse=True,
            )
            high_freq = set(sorted_tokens[:self.max_concepts])
            self._log(f"概念数超过上限 {self.max_concepts}，已按频率截断至 {len(high_freq)} 个高频概念")

        concept_map = {}
        for i, tok in enumerate(self.token_list):
            if tok in high_freq:
                concept_map[i] = tok
            elif is_valid_concept(tok, classical_mode=self.classical_mode):
                # 有效但低频的 token 归入 <other> 聚合桶
                concept_map[i] = "<other>"
            else:
                # 无效 token（标点、BPE 碎片、虚词、<other> token 本身）直接丢弃，不参与概念图
                continue

        unique_concepts = sorted(set(concept_map.values()))
        C = len(unique_concepts)
        concept_idx = {name: j for j, name in enumerate(unique_concepts)}

        self.concept_adj = np.zeros((C, C))
        concept_counts = np.zeros((C, C))

        for i in range(T):
            if i not in concept_map:
                continue
            for j in range(i + 1, T):
                if j not in concept_map:
                    continue
                ci = concept_idx[concept_map[i]]
                cj = concept_idx[concept_map[j]]
                if ci == cj:
                    continue
                self.concept_adj[ci, cj] += self.adj_matrix[i, j]
                concept_counts[ci, cj] += 1
                # P0-1修复: 同时聚合反向因果边 adj_matrix[j, i] → concept_adj[cj, ci]
                self.concept_adj[cj, ci] += self.adj_matrix[j, i]
                concept_counts[cj, ci] += 1

        mask = concept_counts > 0
        self.concept_adj[mask] /= concept_counts[mask]

        self.concept_map = concept_map
        self.concept_names = unique_concepts
        self.concept_idx = concept_idx

        # ── v6: UNK 率感知 + 阈值自适应建议 ──
        unk_count = sum(1 for t in self.token_list if is_unk_token(t))
        unk_rate = unk_count / max(T, 1)
        n_unique = len(set(self.token_list))
        self.unk_rate = unk_rate
        self._log(f"Token {T} → Concept {C} "
                  f"(高频={len(high_freq)}, "
                  f"低频={sum(1 for i, t in enumerate(self.token_list) if t not in high_freq and is_valid_concept(t, classical_mode=self.classical_mode))})")

        if unk_rate > 0.3:
            # SYNC-3 修复 (2026-07-30 审计): 与 ALGORITHM_AUDIT.md §3.1
            # "UNK 率 > 30% → ΔNLL 信号失真" 文档对齐。
            self._log(f"⚠⚠ UNK rate={unk_rate:.1%} (>30%, ΔNLL 信号失真). "
                      f"TRACE 因果边可能不可靠, 结果需人工复核. "
                      f"强烈建议: 使用 Instant TRACE 训练专属模型.")
        elif unk_rate > 0.2:
            self._log(f"⚠ UNK rate={unk_rate:.1%} (严重跨域). "
                      f"强烈建议: 使用 Instant TRACE 训练专属模型. "
                      f"当前 τ={self.threshold} 可能过高, 建议 τ≤0.05.")
        elif unk_rate > 0.05:
            self._log(f"⚠ UNK rate={unk_rate:.1%} (中度跨域). "
                      f"建议: 降低阈值 τ≤0.1 以捕获弱信号.")
        elif unk_rate > 0.01:
            self._log(f"UNK rate={unk_rate:.1%} (正常).")

        # 叙事文启发式: token 种类少 + 段落多 → 叙事文 → 建议低 τ
        if n_unique < T * 0.15 and T > 500:
            self._log(f"文本类型推测: 叙事文 (unique tokens={n_unique}/{T}={n_unique/T:.1%}). "
                      f"建议 τ=0.05-0.15.")

        return concept_map

    # ── 步骤 1: 构建因果模型 ─────────────────────────────────────────

    def build_model(self, data_df=None):
        """
        从概念邻接矩阵构建因果模型。
        如果 DoWhy 可用，创建正式的 CausalModel；
        否则使用模拟模式。
        """
        # P0 修复 (2026-07-29): 模块级 __getattr__ 不对模块内部代码生效,
        # 必须在方法内部显式 import 才能让 'CausalModel' 名称解析成功.
        # P0 修复 (2026-07-30): 函数内 `from X import Y` 会让 Y 在整个函数作用域内
        # 成为局部变量。即使 import 在 if 块内，后续 Y() 调用在 if 未进入时也会
        # 报 UnboundLocalError（如第二次调用时 Y 已缓存到 globals()）。
        # 解决方案：使用别名 import 避免遮蔽，再通过 globals() 取出绑定到局部别名。
        if "CausalModel" not in globals():
            try:
                from dowhy import CausalModel as _CM
                globals()["CausalModel"] = _CM
            except ImportError:
                globals()["CausalModel"] = None
        _CausalModel = globals().get("CausalModel")
        # v2 改进: 同时估计线性 SEM 系数，用于 Pearl 反事实推理。
        if self.concept_adj is None:
            self.aggregate_concepts()

        C = len(self.concept_names)

        if C == 0:
            raise ValueError("无有效概念节点：所有 token 均被过滤（标点/BPE碎片/虚词）。请提供更长或更多元的文本。")

        if C < 2:
            raise ValueError("概念节点不足（<2），因果分析无意义")

        # 阈值校验：负数 threshold 会产生自环和零权边
        if self.threshold < 0:
            raise ValueError("threshold 不能为负数")

        # 提取显著边（跳过自环 ci == cj）
        edges = []
        for ci in range(C):
            for cj in range(C):
                if ci == cj:
                    continue
                if self.concept_adj[ci, cj] > self.threshold:
                    edges.append((self.concept_names[ci],
                                  self.concept_names[cj],
                                  self.concept_adj[ci, cj]))
        edges.sort(key=lambda e: e[2], reverse=True)

        # ── v3: 自适应边过滤 ──
        # 真实 TRACE 数据可能有数千条边，DoWhy 无法处理。
        # 策略: 过滤 BPE 碎片 + top-N 最强边
        # (is_valid_concept 统一从 _token_filters 导入)

        edges_filtered = [e for e in edges if is_valid_concept(e[0], classical_mode=self.classical_mode) and is_valid_concept(e[1], classical_mode=self.classical_mode)]

        n_total = len(edges_filtered)
        if n_total > self.max_edges_for_dowhy:
            if self.filter_mode == "percentile":
                threshold_val = np.percentile(
                    [e[2] for e in edges_filtered], self.filter_percentile)
                edges_filtered = [e for e in edges_filtered if e[2] >= threshold_val]
            elif self.filter_mode == "adaptive":
                # adaptive: 根据图密度自动选择 percentile 或 top-N
                density = n_total / max(C * (C - 1), 1)
                if density > 0.3:
                    threshold_val = np.percentile(
                        [e[2] for e in edges_filtered], self.filter_percentile)
                    edges_filtered = [e for e in edges_filtered if e[2] >= threshold_val]
                    self._log(f"adaptive 模式: 图密度 {density:.1%} > 30%, 使用 percentile 过滤")
                else:
                    edges_filtered = edges_filtered[:self.max_edges_for_dowhy]
                    self._log(f"adaptive 模式: 图密度 {density:.1%} ≤ 30%, 使用 top-N 过滤")
            else:
                # Default: top-N
                edges_filtered = edges_filtered[:self.max_edges_for_dowhy]

        if n_total > self.max_edges_for_dowhy:
            self._log(f"边过滤: {n_total} → {len(edges_filtered)} "
                      f"(mode={self.filter_mode}, max={self.max_edges_for_dowhy})")
        self.significant_edges = edges_filtered
        self._log(f"显著边: {len(edges_filtered)}/{C*C} (ΔNLL > {self.threshold})")

        # DOT 图 — 只包含有效边中出现的节点（否则 DoWhy 在大图上极慢/崩溃）
        dot_nodes = set()
        for src, dst, _ in edges_filtered:
            if is_valid_concept(src, classical_mode=self.classical_mode) and is_valid_concept(dst, classical_mode=self.classical_mode):
                dot_nodes.add(src)
                dot_nodes.add(dst)
        dot_lines = ["digraph {"]
        for node in sorted(dot_nodes):
            dot_lines.append(f'  "{node}";')
        for src, dst, _ in edges_filtered:
            dot_lines.append(f'  "{src}" -> "{dst}";')
        dot_lines.append("}")
        self.dot_graph = "\n".join(dot_lines)

        # 数据矩阵
        if data_df is None:
            data_df = self._simulate_data(C)

        # 估计 SEM 系数（用于 Pearl 反事实）
        raw_data = data_df.values if hasattr(data_df, 'values') else np.asarray(data_df)
        # 构建二值邻接矩阵
        bin_adj = np.zeros((C, C))
        for src, dst, _ in edges_filtered:
            si = self.concept_idx.get(src)
            di = self.concept_idx.get(dst)
            if si is not None and di is not None:
                bin_adj[si, di] = 1
        self.sem_coeff = estimate_sem_from_data(
            bin_adj, raw_data, self.concept_names,
            regularization=self.sem_regularization,
            alpha=self.sem_alpha,
            log_fn=self._log,
        )

        # 初始化 Pearl 反事实引擎
        name_to_idx = {n: i for i, n in enumerate(self.concept_names)}
        self.pearl_cf = PearlCounterfactual(self.sem_coeff, name_to_idx, self.rng)

        # 构建模型 — v6: 概念规模自适应降级
        DOT_NODES = len(dot_nodes)
        if not self.simulation and DOT_NODES > 50:
            self.simulation = True
            self._log(f"⚠ 概念节点过多 ({DOT_NODES} > 50), DoWhy do-calculus 极慢 → 自动降级为模拟模式")
        elif not self.simulation and DOT_NODES > 30:
            self._log(f"⚠ 概念节点较多 ({DOT_NODES} > 30), DoWhy 可能较慢. 建议降低 max_edges_for_dowhy.")

        if self.simulation:
            self.model = SimulationModel(
                graph_edges=[(e[0], e[1]) for e in edges_filtered],
                concept_names=self.concept_names,
                data=data_df,
                rng=self.rng,
                refutation_deviation_threshold=self.refutation_deviation_threshold,
            )
            self._log(f"模型: SimulationMode")
        else:
            # DoWhy 0.14: 使用最强边的 source→target（保证有有向路径）
            if edges_filtered:
                default_treatment = edges_filtered[0][0]
                default_outcome = edges_filtered[0][1]
            else:
                valid_names = [n for n in self.concept_names
                              if n != "<other>" and len(n) > 1]
                if valid_names:
                    default_treatment = valid_names[0]
                    default_outcome = valid_names[-1]
                else:
                    non_other = [n for n in self.concept_names if n != "<other>"]
                    default_treatment = non_other[0] if non_other else self.concept_names[0]
                    default_outcome = non_other[-1] if len(non_other) > 1 else default_treatment

            # 精简数据: 只包含 DOT 图中出现的列（否则 DoWhy 在大数据上失败）
            dot_cols = sorted(dot_nodes)
            reduced_data = data_df[dot_cols] if hasattr(data_df, '__getitem__') else data_df

            self.model = _CausalModel(
                data=reduced_data,
                treatment=default_treatment,
                outcome=default_outcome,
                graph=self.dot_graph,
            )
            self._log(f"模型: DoWhy 0.14 CausalModel (精简图: {len(dot_cols)} 节点)")

        self.data_df = data_df
        return self.model

    def _simulate_data(self, n_concepts: int, n_samples: int = 1000):
        """
        从邻接矩阵模拟生成观测数据（SEM 数据生成过程）。

        使用拓扑排序确保按 DAG 结构生成数据，避免原实现中
        'for i in range(j)' 对任意排序邻接矩阵的索引错误。
        如果检测到环，则使用 5 次迭代近似。
        """
        # P0 修复 (2026-07-29): 模块级 __getattr__ 不对模块内部代码生效,
        # 必须显式 import pandas 才能让 'pd' 名称解析成功.
        if "pd" not in globals():
            import pandas
            globals()["pd"] = pandas
        data = np.zeros((n_samples, n_concepts))
        # σ=1.0 增强外生噪声，避免 OLS 设计矩阵接近奇异
        noise = self.rng.normal(0, 1.0, (n_samples, n_concepts))
        data[:] = noise[:]

        # 收集所有显著边 (父节点 -> 子节点)，跳过自环
        edges = []
        for i in range(n_concepts):
            for j in range(n_concepts):
                if i == j:
                    continue
                if self.concept_adj[i, j] > self.threshold:
                    edges.append((i, j, self.concept_adj[i, j] / 10.0))

        # 尝试拓扑排序
        in_degree = [0] * n_concepts
        adjacency = [[] for _ in range(n_concepts)]
        for i, j, eff in edges:
            adjacency[i].append((j, eff))
            in_degree[j] += 1

        queue = [i for i in range(n_concepts) if in_degree[i] == 0]
        topo_order = []
        while queue:
            node = queue.pop(0)
            topo_order.append(node)
            for child, _ in adjacency[node]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        if len(topo_order) == n_concepts:
            # 无环：按拓扑顺序应用父节点效应
            generated = set()
            for node in topo_order:
                generated.add(node)
                for child, eff in adjacency[node]:
                    data[:, child] += eff * data[:, node]
        else:
            # P0-1 修复 (2026-07-30): 有环使用 Jacobi 风格迭代（非累加），
            # 限制总能量避免爆炸；原实现是 5 次累加，eff>0.5 时数据爆炸。
            self._log(f"模拟数据: 检测到环 ({len(topo_order)}/{n_concepts} 节点可拓扑排序)，使用 Jacobi 迭代近似。")
            # 截断过大效应避免数值爆炸
            edges_clamped = [(i, j, float(np.clip(eff, -0.5, 0.5))) for i, j, eff in edges]
            for _ in range(5):
                delta = np.zeros_like(data)
                for i, j, eff in edges_clamped:
                    delta[:, j] += eff * data[:, i]
                data += delta
                # 收敛判定：增量能量 < 1e-6 * 数据能量
                if np.linalg.norm(delta) < 1e-6 * max(np.linalg.norm(data), 1.0):
                    break

        if _PANDAS_AVAILABLE:
            return pd.DataFrame(data, columns=self.concept_names)
        return _MinimalDataFrame(data, self.concept_names)

    # ── 步骤 2: 识别因果效应 ─────────────────────────────────────────

    def identify(self, treatment: str = None, outcome: str = None):
        """
        使用 do-calculus 识别因果效应是否可以从观测数据中估计。

        DoWhy 0.14 兼容: 使用 estimand_type 判断可识别性。
        """
        if self.model is None:
            self.build_model()

        # 选择有效的 treatment/outcome（排除 <other> 和单字语法 token）
        # 默认使用最强边的 source→target（保证有向路径）
        if treatment is None and self.significant_edges:
            treatment = self.significant_edges[0][0]
        if outcome is None and self.significant_edges:
            outcome = self.significant_edges[0][1]

        if treatment is None or outcome is None:
            valid_names = [n for n in self.concept_names
                           if n != "<other>" and len(n) > 1]
            if not valid_names:
                valid_names = [n for n in self.concept_names if n != "<other>"]
            if treatment is None:
                treatment = valid_names[0] if valid_names else self.concept_names[0]
            if outcome is None:
                outcome = valid_names[-1] if len(valid_names) > 1 else treatment

        self.treatment = treatment
        self.outcome = outcome

        try:
            self.identified_estimand = self.model.identify_effect(
                proceed_when_unidentifiable=True,
            )
            identifiable = DoWhy14Adapter.is_identifiable(self.identified_estimand)
        except Exception as e:
            self._log(f"识别失败: {e}")
            self.identified_estimand = SimulationEstimand(treatment, outcome, identifiable=False)
            identifiable = False

        self._log(f"识别: {treatment} → {outcome}")
        if hasattr(self.identified_estimand, 'identifier'):
            method = (self.identified_estimand.identifier
                      if isinstance(self.identified_estimand.identifier, str)
                      else str(self.identified_estimand.identifier))
            self._log(f"  估计方法: {method}")
        self._log(f"  可识别: {identifiable}")
        return self.identified_estimand

    # ── 步骤 3: 估计因果效应 ─────────────────────────────────────────

    def estimate(self, method: str = "backdoor.linear_regression",
                 confidence_intervals: bool = True, **kwargs):
        """
        估计因果效应的大小和置信区间。

        Parameters
        ----------
        method : str
            DoWhy 估计方法名。
        confidence_intervals : bool
            是否计算置信区间。关闭可显著加速 LIGHT 模式。
        **kwargs
            透传给 model.estimate_effect，例如 method_params={'num_simulations': 200}
            用于在 SUPER 模式减少 bootstrap 次数、提升响应速度。

        DoWhy 0.14 兼容: 使用 get_confidence_intervals() 获取 CI。
        注意: 如果 identify() 回退到 SimulationEstimand，estimate() 也会
        自动回退到 SimulationModel，保证管线不会中断。
        """
        if self.identified_estimand is None:
            self.identify()

        # Fallback: 如果 DoWhy identify 失败导致 estimand 是模拟的，
        # 需要同步切换 model 为 SimulationModel
        if isinstance(self.identified_estimand, SimulationEstimand) and not isinstance(self.model, SimulationModel):
            self._log("DoWhy 识别失败，自动回退到模拟模式")
            self.simulation = True
            self.model = SimulationModel(
                graph_edges=[(e[0], e[1]) for e in self.significant_edges],
                concept_names=self.concept_names,
                data=self.data_df,
                rng=self.rng,
                refutation_deviation_threshold=self.refutation_deviation_threshold,
            )

        # 过滤 statsmodels 在条件数计算中产生的无害 divide-by-zero warning
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                category=RuntimeWarning,
                message="divide by zero encountered in scalar divide",
                module="statsmodels.regression.linear_model",
            )
            # P0 修复 (2026-07-30): SimulationModel.estimate_effect 不接受
            # method_params（DoWhy 0.14 仅 CausalModel 透传到 method 实现）。
            # 仅对真正的 CausalModel 透传 **kwargs，避免 TypeError。
            if isinstance(self.model, SimulationModel):
                self.estimate_result = self.model.estimate_effect(
                    self.identified_estimand,
                    method_name=method,
                    confidence_intervals=confidence_intervals,
                )
            else:
                self.estimate_result = self.model.estimate_effect(
                    self.identified_estimand,
                    method_name=method,
                    confidence_intervals=confidence_intervals,
                    **kwargs,
                )

        ci = DoWhy14Adapter.get_confidence_interval(self.estimate_result)
        # P1修复: 设置 confidence_method 字段，标识 CI 计算方式
        # P1 修复 (2026-07-30 审计): 统一 method.lower()，避免大小写敏感导致匹配失败。
        method_lower = method.lower() if isinstance(method, str) else ""
        if "linear_regression" in method_lower:
            self.confidence_method = "OLS-analytic"
        elif "sem" in method_lower:
            self.confidence_method = "SEM-analytic"
        else:
            self.confidence_method = "bootstrap"
        self._log(f"估计方法: {method}")
        self._log(f"  效应量: {self.estimate_result.value:.4f}")
        self._log(f"  95% CI: [{ci[0]:.4f}, {ci[1]:.4f}]")
        return self.estimate_result

    # ── 步骤 4: 反驳测试 ─────────────────────────────────────────────

    def refute(self, progress_callback=None, **kwargs) -> dict:
        """
        三层反驳测试。DoWhy 0.14 兼容: 用偏差度判断 refuted。

        Parameters
        ----------
        progress_callback : callable or None
            可选的进度回调，签名为 callback(idx: int, total: int, label: str)。
            在每次反驳测试前调用，用于 Web UI 实时进度显示。
        **kwargs
            透传给 model.refute_estimate，例如 num_simulations=200
            用于在 SUPER 模式减少重采样次数、提升响应速度。
        """
        if self.estimate_result is None:
            self.estimate()

        self.refutation_results = {}
        refuters = [
            ("random_common_cause", "随机共因"),
            ("placebo_treatment_refuter", "安慰剂处理"),
            ("data_subset_refuter", "数据子集"),
        ]

        # 过滤 statsmodels 在 bootstrap/refuter 内部产生的无害 warning
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                category=RuntimeWarning,
                message="divide by zero encountered in scalar divide",
                module="statsmodels.regression.linear_model",
            )
            warnings.filterwarnings(
                "ignore",
                category=RuntimeWarning,
                message="invalid value encountered in scalar divide",
                module="statsmodels.regression.linear_model",
            )

            for idx, (method_name, label) in enumerate(refuters):
                if progress_callback:
                    progress_callback(idx + 1, len(refuters), label)
                try:
                    result = self.model.refute_estimate(
                        self.identified_estimand,
                        self.estimate_result,
                        method_name=method_name,
                        **kwargs,
                    )
                    check = DoWhy14Adapter.check_refuted(
                        self.estimate_result, result, method_name=method_name,
                        threshold=self.refutation_deviation_threshold)
                    result._check = check  # 附加自定义判断
                    self.refutation_results[label] = result
                    self._log(f"反驳-{label}: 新效应={result.new_effect:.4f}, "
                              f"偏差={check['deviation']:.1%}, "
                              f"{'⚠️ 反驳' if check['refuted'] else '✓ 稳健'}")
                except Exception as e:
                    self._log(f"反驳-{label}: 失败 ({e})")

        return self.refutation_results

    # ── 步骤 5: 反事实查询 ───────────────────────────────────────────

    def counterfactual(
        self,
        observed_sample: np.ndarray = None,
        treatment_var: str = None,
        control_value: float = 0.0,
        treatment_value: float = 1.0,
        outcome_var: str = None,
    ) -> dict:
        """
        Pearl 三步反事实推理。

        v2: 使用独立的 PearlCounterfactual 引擎（基于估计的 SEM 系数），
        不依赖 DoWhy 的 counterfactual 方法（DoWhy 0.14 base 版无此方法）。
        """
        if treatment_var is None:
            treatment_var = self.treatment
        if outcome_var is None:
            outcome_var = self.outcome
        if observed_sample is None:
            observed_sample = self.data_df.iloc[0].values

        self._log(f"反事实查询: do({treatment_var}={treatment_value}) "
                  f"vs do({treatment_var}={control_value}) → {outcome_var}")

        # 使用 PearlCounterfactual 引擎
        result = self.pearl_cf.query(
            observed=observed_sample,
            treatment_var=treatment_var,
            outcome_var=outcome_var,
            control_value=control_value,
            treatment_value=treatment_value,
        )

        self.counterfactual_result = result
        # P0-3 修复 (Round 27 审计): pearl_counterfactual.py 在 NaN 时返回
        # observed_outcome=None 且无 'error' 字段，原守卫 'error' not in result 会放行，
        # 紧接着 None:.4f 抛 TypeError 中断整个 counterfactual_scan。
        # 新守卫：必须同时满足无 error 且 observed_outcome 非 None 才格式化。
        if not result.get('error') and result.get('observed_outcome') is not None:
            self._log(f"  观测结果: {result['observed_outcome']:.4f}")
            # counterfactual_outcome / causal_effect 也可能为 None，单独守护
            cf_val = result.get('counterfactual_outcome')
            ite_val = result.get('causal_effect')
            if cf_val is not None:
                self._log(f"  反事实结果: {cf_val:.4f}")
            if ite_val is not None:
                self._log(f"  个体因果效应 (ITE): {ite_val:+.4f}")
        elif 'error' in result:
            self._log(f"  错误: {result['error']}")
        else:
            self._log("  观测结果: N/A (NaN 或 None) — 跳过格式化输出")

        return result

    # ── 批量反事实扫描 ────────────────────────────────────────────────

    def counterfactual_scan(self, n_top_edges: int = 5) -> list[dict]:
        """对 ΔNLL 最强的 N 条边逐个执行反事实查询"""
        if self.concept_adj is None:
            self.build_model()

        results = []
        for src, dst, strength in self.significant_edges[:n_top_edges]:
            try:
                cf = self.counterfactual(
                    treatment_var=src,
                    outcome_var=dst,
                    control_value=0.0,
                    treatment_value=1.0,
                )
                results.append({
                    "source": src,
                    "target": dst,
                    "trace_dnl": strength,
                    "ite": cf.get("causal_effect"),
                    "observed": cf.get("observed_outcome"),
                    "counterfactual": cf.get("counterfactual_outcome"),
                })
            except Exception as e:
                self._log(f"反事实扫描 [{src}→{dst}]: 失败 ({e})")
                # P0-3 修复: 异常分支用 None 而非 float('nan')，避免 JSON 输出 "NaN"
                results.append({
                    "source": src,
                    "target": dst,
                    "trace_dnl": strength,
                    "ite": None,
                    "observed": None,
                    "counterfactual": None,
                    "error": str(e),
                })

        self.scan_results = results
        return results

    # ── v2 新增: causallearn 独立验证 ─────────────────────────────────

    def causallearn_validate(self, run_pc: bool = True, run_ges: bool = True,
                             compare: bool = True) -> dict:
        """
        使用 causallearn 的 PC 和 GES 算法进行独立因果发现，
        并与 TRACE 的结果交叉验证。

        这是六合一架构中的第六验证维度:
        - TRACE (探照灯): token 级因果发现
        - CCM (测谎仪): 非线性交叉映射
        - EDM (节拍器): 时间结构骨架
        - HAVOK (X光机): 隐藏驱动力
        - DoWhy (第五维): 识别+估计+反驳
        - causallearn (第六维): 独立图搜索算法验证

        Returns
        -------
        dict: 比较结果
        """
        if self.concept_adj is None:
            self.build_model()

        # 准备数据（排除 <other> 列）
        raw_data = self.data_df.values if hasattr(self.data_df, 'values') else np.asarray(self.data_df)

        # 只使用非 <other> 的概念
        valid_idx = [i for i, n in enumerate(self.concept_names) if n != "<other>"]
        valid_names = [self.concept_names[i] for i in valid_idx]
        valid_data = raw_data[:, valid_idx]

        if len(valid_names) < 3:
            self._log("causallearn 验证跳过: 有效概念 < 3")
            return {'error': 'too few concepts', 'n_concepts': len(valid_names)}

        self.cl_validator = CausalLearnValidator(
            valid_data, valid_names, causallearn_available=_CAUSALLEARN_AVAILABLE)

        if run_pc:
            result_pc = self.cl_validator.run_pc(alpha=0.05)
            n = result_pc.get('n_edges', 0)
            err = result_pc.get('error', '')
            self._log(f"causallearn PC: {'失败' if err else f'{n} edges'}")

        if run_ges:
            result_ges = self.cl_validator.run_ges()
            n = result_ges.get('n_edges', 0)
            err = result_ges.get('error', '')
            self._log(f"causallearn GES: {'失败' if err else f'{n} edges'}")

        if compare:
            # 只比较非 <other> 概念之间的边
            trace_valid_edges = [
                (s, d, w) for s, d, w in self.significant_edges
                if s != "<other>" and d != "<other>"
            ]
            self.cl_comparison = self.cl_validator.compare_with_trace(trace_valid_edges)

        return self.cl_comparison

    # ── v2 新增: DAG 可视化 ────────────────────────────────────────────

    def visualize(self, filename: str = "causal_graph", format: str = "png",
                  view: bool = False, graphviz_bin_dir: str = None) -> str:
        """
        使用 graphviz 渲染因果 DAG。

        Windows 上需要指定 graphviz 二进制路径。

        Parameters
        ----------
        filename : str
            输出文件名（不含扩展名）
        format : str
            输出格式 (png, pdf, svg, dot)
        view : bool
            是否自动打开查看
        graphviz_bin_dir : str or None
            graphviz bin 目录路径。如果为 None，使用 _config.get_graphviz_bin_dir()。
            不再扫描任何磁盘绝对路径，保持可移植性。

        Returns
        -------
        str: 输出文件路径，或错误信息
        """
        # P0 修复 (2026-07-29): 模块级 __getattr__ 不对模块内部代码生效,
        # 必须显式 import graphviz 才能让 'graphviz' 名称解析成功.
        if "graphviz" not in globals():
            try:
                import graphviz
                globals()["graphviz"] = graphviz
            except ImportError:
                globals()["graphviz"] = None
        if not _GRAPHVIZ_AVAILABLE:
            return "[graphviz 未安装] pip install graphviz"

        if not self.significant_edges:
            self.build_model()

        # Windows: 确保 graphviz bin 在 PATH 中（委托给 _config.setup_graphviz，
        # debt-05: PATH 配置逻辑集中到 _config.py）
        from _config import setup_graphviz
        setup_graphviz(graphviz_bin_dir)

        try:
            dot = graphviz.Digraph(
                name='TRACE_DoWhy_Causal_Graph',
                comment='Causal DAG discovered by TRACE + DoWhy',
            )
            dot.attr(rankdir='LR')
            dot.attr('node', shape='ellipse', style='filled',
                     fillcolor='#E8F0FE', fontname='SimHei')
            dot.attr('edge', fontname='SimHei', fontsize='10')

            for src, dst, strength in self.significant_edges:
                if src == "<other>" or dst == "<other>":
                    continue
                # 边宽度与因果强度成正比
                penwidth = max(0.5, min(5.0, strength / 3.0))
                dot.edge(src, dst, label=f'{strength:.1f}',
                        penwidth=str(penwidth))

            output_path = dot.render(filename=filename, format=format,
                                     cleanup=True, view=view)
            self._log(f"DAG 可视化: {output_path}")
            return output_path
        except Exception as e:
            self._log(f"DAG 可视化失败: {e}")
            return f"[可视化失败] {e}"

    # ── 综合报告 ─────────────────────────────────────────────────────

    def report(self) -> str:
        """生成 Markdown 格式的六合一（+六维）诊断报告"""
        n_edges = len(self.significant_edges)
        n_concepts = len(self.concept_names)
        # _check 是 dict 而非对象，需用键访问而非 getattr
        n_refuted = 0
        for r in self.refutation_results.values():
            check = getattr(r, '_check', None)
            refuted = check['refuted'] if isinstance(check, dict) else getattr(r, 'refuted', False)
            if refuted:
                n_refuted += 1

        lines = [
            "# TRACE + DoWhy + Counterfactual 综合诊断报告",
            "",
        ]
        # 降级透明化: 模拟模式下 ATE/CI 是合成值，需显著警告避免误读
        if self.simulation:
            lines.extend([
                "> ⚠ 模拟模式 — ATE/CI 是合成值（SimulationModel），不代表真实 do-calculus 结论",
                "",
            ])
        lines.extend([
            "## 1. 因果图摘要",
            f"- 概念节点: {n_concepts}",
            f"- 显著边 (ΔNLL > {self.threshold}): {n_edges}",
            f"- 运行模式: {self.mode_name}",
            f"- causallearn: {'可用' if _CAUSALLEARN_AVAILABLE else '未安装'}",
            f"- Graphviz: {'可用' if _GRAPHVIZ_AVAILABLE else '未安装'}",
            "",
        ])

        if self.significant_edges:
            lines.append("### Top-5 因果边 (TRACE ΔNLL)")
            lines.append("| 原因 | 结果 | ΔNLL |")
            lines.append("|------|------|------|")
            for src, dst, strength in self.significant_edges[:5]:
                lines.append(f"| {src} | {dst} | {strength:.2f} |")
            lines.append("")

        if self.identified_estimand is not None:
            identifiable = DoWhy14Adapter.is_identifiable(self.identified_estimand)
            lines.append("## 2. 因果效应识别")
            lines.append(f"- 处理变量: {self.treatment}")
            lines.append(f"- 结果变量: {self.outcome}")
            lines.append(f"- 可识别: {identifiable}")
            if hasattr(self.identified_estimand, 'identifier'):
                ident_str = str(self.identified_estimand.identifier)
                lines.append(f"- 识别方法: {ident_str}")
            lines.append("")

        if self.estimate_result is not None:
            ci = DoWhy14Adapter.get_confidence_interval(self.estimate_result)
            lines.append("## 3. 因果效应估计")
            lines.append(f"- 效应量 (ATE): {self.estimate_result.value:.4f}")
            lines.append(f"- 95% CI: [{ci[0]:.4f}, {ci[1]:.4f}]")
            lines.append("")

        if self.refutation_results:
            lines.append("## 4. 反驳测试")
            # P1-2 修复: 分母用实际反驳测试数，避免异常路径下硬编码 "3" 误导
            n_total_refuters = len(self.refutation_results)
            # P1 修复 (2026-07-30 审计): 阈值硬编码 2 在 n_total_refuters<2 时误导。
            # 改为与总数成比例: 至少 2 票或半数以上才判定不稳定。
            n_unstable_threshold = max(2, n_total_refuters // 2)
            lines.append(f"- 结论: {n_refuted}/{n_total_refuters} 被反驳 "
                         f"({'⚠️ 效应不稳定' if n_refuted >= n_unstable_threshold else '✓ 效应稳健'})")
            lines.append("")
            lines.append("| 反驳方法 | 原始效应 | 新效应 | 指标 | 判定 |")
            lines.append("|---------|---------|--------|------|------|")
            orig = self.estimate_result.value if self.estimate_result else 0
            for name, result in self.refutation_results.items():
                new_eff = result.new_effect
                check = getattr(result, '_check', None)
                refuted = check['refuted'] if check else False
                deviation = check['deviation'] if check else abs(new_eff - orig) / (abs(orig) + 1e-10)
                display_metric = check['display_metric'] if check else deviation
                display_label = check['display_label'] if check else "偏差"

                # 安慰剂反驳: 新效应接近 0 是支持因果性的证据
                if name == "安慰剂处理":
                    if refuted:
                        verdict = "⚠️ 安慰剂仍有效应"
                    else:
                        verdict = "✓ 安慰剂效应消失（支持因果性）"
                else:
                    verdict = "⚠️ 反驳" if refuted else "✓ 稳健"

                lines.append(f"| {name} | {orig:.4f} | {new_eff:.4f} "
                             f"| {display_label}={display_metric:.1%} | {verdict} |")
            lines.append("")

        if self.counterfactual_result:
            cf = self.counterfactual_result
            lines.append("## 5. 反事实查询")
            lines.append(f"- 观测结果: {cf.get('observed_outcome', 'N/A')}")
            lines.append(f"- 反事实结果: {cf.get('counterfactual_outcome', 'N/A')}")
            lines.append(f"- 个体因果效应 (ITE): {cf.get('causal_effect', 'N/A')}")
            lines.append("")

        if self.scan_results:
            lines.append("## 6. 反事实扫描（Top 边）")
            lines.append("| 原因 → 结果 | TRACE ΔNLL | ITE | 观测 | 反事实 |")
            lines.append("|------------|-----------|-----|------|--------|")
            for r in self.scan_results:
                # P1 修复 (ROUND31 阶段C): 反事实扫描异常分支会写入 None,
                # 直接用 :+.4f 格式化 None 会触发 TypeError 中断整个 report()。
                # 改为辅助函数, None 时显示 "N/A" 保持表格完整。
                _dnl = r.get('trace_dnl')
                _ite = r.get('ite')
                _obs = r.get('observed')
                _cf  = r.get('counterfactual')
                _s_dnl = f"{_dnl:.2f}" if _dnl is not None else "N/A"
                _s_ite = f"{_ite:+.4f}" if _ite is not None else "N/A"
                _s_obs = f"{_obs:.4f}" if _obs is not None else "N/A"
                _s_cf  = f"{_cf:.4f}"  if _cf  is not None else "N/A"
                lines.append(
                    f"| {r['source']} → {r['target']} "
                    f"| {_s_dnl} | {_s_ite} | {_s_obs} | {_s_cf} |"
                )
            lines.append("")

        if self.cl_comparison:
            lines.append("## 7. causallearn 独立验证")
            lines.append("| 算法 | TRACE 边 | CL 边 | 一致 | 一致率 |")
            lines.append("|------|---------|-------|------|--------|")
            for algo_key, comp in self.cl_comparison.items():
                lines.append(
                    f"| {comp['algorithm']} "
                    f"| {comp['trace_n_edges']} "
                    f"| {comp['cl_n_edges']} "
                    f"| {comp['agree']} "
                    f"| {comp['agreement_rate']:.0%} |"
                )
            lines.append("")

        lines.append("## 诊断日志")
        for log_entry in self.log:
            lines.append(f"- {log_entry}")

        # 六战士一致性检查（如果 cards 已外部计算并附加到 bridge）
        if self.six_warriors_cards:
            lines.append("")
            lines.append("## 六战士一致性检查")
            for key, card in self.six_warriors_cards.items():
                status = getattr(card, 'status', '')
                verdict = getattr(card, 'verdict', '')
                warrior_id = getattr(card, 'warrior_id', key)
                # 兼容 WarriorCard (deployed/fallback/unavailable) 与 ok/warn 语义
                if status in ("ok", "deployed"):
                    status_icon = "✓"
                elif status in ("warn", "fallback", "ready"):
                    status_icon = "⚠"
                else:
                    status_icon = "✗"
                lines.append(f"- {status_icon} {warrior_id}: {verdict}")

            # 复合诊断引擎：跨战士聚合判定文本类型
            try:
                from compound_diagnostic import CompoundDiagnosticEngine, render_compound_diagnosis
                engine = CompoundDiagnosticEngine()
                compound_result = engine.diagnose(self.six_warriors_cards)
                lines.append("")
                lines.append(render_compound_diagnosis(compound_result))
            except Exception as e:
                lines.append(f"\n(复合诊断引擎不可用: {e})")

        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════
# 模拟模式类已移至 simulation_model.py（debt-01），通过文件顶部 re-import 提供
# ══════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════
# 便捷工厂函数
# ══════════════════════════════════════════════════════════════════════

def from_trace_output(trace_result: dict, threshold: float = 0.03,
                      concept_min_freq: int = 2, **kwargs) -> TRACE2DoWhy:
    """从 TRACE 引擎的标准输出字典创建桥接实例"""
    return TRACE2DoWhy(
        adj_matrix=trace_result["adj_matrix"],
        token_list=trace_result["token_list"],
        tokenizer=trace_result.get("tokenizer"),
        threshold=threshold,
        concept_min_freq=concept_min_freq,
        **kwargs,
    )


def quick_analysis(adj_matrix, token_list, threshold=0.03):
    """一键运行完整的六合一管线并返回 bridge"""
    bridge = TRACE2DoWhy(adj_matrix, token_list, threshold=threshold)
    bridge.build_model()
    bridge.identify()
    bridge.estimate()
    bridge.refute()
    bridge.counterfactual_scan(n_top_edges=5)
    return bridge
