"""
trace-to-edm 全局配置
====================
三层元因果控制论桥接系统的统一配置中心。

三层架构:
  Layer 1 — Meta-SCM Parameters: 从 TRACE result.json 提取系统诊断不变量
  Layer 2 — Secular Semantic Projection: PCA 驱动的世俗语义流形投影
  Layer 3 — Sacred Axis Audit: 八正道神圣坐标轴的零样本探针对齐
"""

import os
from pathlib import Path

# ── 路径配置 ────────────────────────────────────────────────
PROJECT_ROOT = Path(os.path.dirname(os.path.abspath(__file__)))

# 便携式布局自动探测
# ----------------------------------------------------------
# 便携式目录结构:
#   Complement/
#     Skill/edm-takens-web/         (跨父目录的兄弟)
#     TRACE Engine(EDM-Takens CCM)/
#       Models/Qwen2.5-X-Instruct/  (Qwen 模型，便携式专属)
#       trace-engine-web/           (同级，开发布局也正确)
#       trace-to-edm/                (本项目 = PROJECT_ROOT)
#
# 开发布局:
#   .skills/
#     trace-engine-web/             (同级)
#     edm-takens-web/               (同级)
#     trace-to-edm/                 (本项目 = PROJECT_ROOT)
#   Qwen2.5-X-Instruct/             (PROJECT_ROOT.parent.parent)
#
# 探测信号: PROJECT_ROOT.parent / "Models" 存在且包含 Qwen2.5-1.5B-Instruct
_PORTABLE_MODELS_DIR = PROJECT_ROOT.parent / "Models"
_IS_PORTABLE_LAYOUT = (
    _PORTABLE_MODELS_DIR.exists()
    and (_PORTABLE_MODELS_DIR / "Qwen2.5-1.5B-Instruct").exists()
)

# TRACE 引擎路径（两种布局下都是同级，无须分支）
TRACE_ENGINE_WEB_DIR = PROJECT_ROOT.parent / "trace-engine-web"
TRACE_BRIDGE_SCRIPT = TRACE_ENGINE_WEB_DIR / "py_bridge.py"
TRACE_WORK_DIR = TRACE_ENGINE_WEB_DIR / "work" / "outputs"

# EDM-Takens Web 路径
if _IS_PORTABLE_LAYOUT:
    # 便携式: edm-takens-web 在 Skill/ 下，跨父目录
    EDM_TAKENS_DIR = PROJECT_ROOT.parent.parent / "Skill" / "edm-takens-web"
else:
    # 开发布局: 同级目录
    EDM_TAKENS_DIR = PROJECT_ROOT.parent / "edm-takens-web"
EDM_DATA_DIR = EDM_TAKENS_DIR / "data"
EDM_API_URL = "http://localhost:8000"

# Qwen 模型路径
# 优先级: 环境变量 > 便携式布局探测 > 开发布局 fallback
if _IS_PORTABLE_LAYOUT:
    _DEFAULT_QWEN_1_5B = str(_PORTABLE_MODELS_DIR / "Qwen2.5-1.5B-Instruct")
    _DEFAULT_QWEN_3B = str(_PORTABLE_MODELS_DIR / "Qwen2.5-3B-Instruct")
else:
    _DEFAULT_QWEN_1_5B = str(PROJECT_ROOT.parent.parent / "Qwen2.5-1.5B-Instruct")
    _DEFAULT_QWEN_3B = str(PROJECT_ROOT.parent.parent / "Qwen2.5-3B-Instruct")

QWEN_MODEL_PATH = Path(os.environ.get("QWEN_MODEL_PATH_1_5B", _DEFAULT_QWEN_1_5B))
QWEN_MODEL_PATH_3B = Path(os.environ.get("QWEN_MODEL_PATH_3B", _DEFAULT_QWEN_3B))

# TRACE LLaMA 模型路径（便携式 Models/ 目录或开发布局的 sibling Models/）
if _IS_PORTABLE_LAYOUT:
    _DEFAULT_SHEHUI = str(_PORTABLE_MODELS_DIR / "shehui-llama")
    _DEFAULT_SHENJI = str(_PORTABLE_MODELS_DIR / "shenji-llama")
else:
    _DEFAULT_SHEHUI = str(PROJECT_ROOT.parent.parent / "Models" / "shehui-llama")
    _DEFAULT_SHENJI = str(PROJECT_ROOT.parent.parent / "Models" / "shenji-llama")

SHEHUI_MODEL_PATH = Path(os.environ.get("SHEHUI_MODEL_PATH", _DEFAULT_SHEHUI))
SHENJI_MODEL_PATH = Path(os.environ.get("SHENJI_MODEL_PATH", _DEFAULT_SHENJI))

# 便携式布局标志（供外部模块查询当前布局）
IS_PORTABLE_LAYOUT = _IS_PORTABLE_LAYOUT

# 本项目的输入/输出目录 (重组后)
DATA_DIR = PROJECT_ROOT / "data"
INPUTS_DIR = DATA_DIR / "inputs"
OUTPUTS_DIR = DATA_DIR / "outputs"
CACHE_DIR = DATA_DIR / "cache"
ARCHIVE_DIR = PROJECT_ROOT / "archive"
SACRED_TEXTS_DIR = PROJECT_ROOT / "sacred_texts"

# 确保目录存在
for _d in [DATA_DIR, INPUTS_DIR, OUTPUTS_DIR, CACHE_DIR, ARCHIVE_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

# 主输出 CSV (通过项目管理器动态获取)
# 使用 project_manager.get_project_manager().current_csv 获取当前项目路径
# 此处保留默认值用于向后兼容和模块导入
def _get_default_csv():
    from pathlib import Path
    return OUTPUTS_DIR / "narrative_meta_trajectories.csv"

TRAJECTORY_CSV = OUTPUTS_DIR / "narrative_meta_trajectories.csv"  # 向后兼容

# 项目目录
PROJECTS_DIR = PROJECT_ROOT / "projects"
MODEL_CACHE_DIR = CACHE_DIR
PCA_CACHE_FILE = CACHE_DIR / "_pca_state.pkl"

# ── 输入 CSV 列名 ───────────────────────────────────────────
INPUT_COL_TIMESTAMP = "timestamp"
INPUT_COL_TEXT = "text"
INPUT_COL_SOURCE = "source"

# ── Layer 1: 元 SCM 参数列定义 ──────────────────────────────
# (列名, result.json 路径, 默认值, 描述)
LAYER1_COLUMNS = [
    # DoWhy 因果效应
    ("ate",                  "ate",                  0.0,    "平均处理效应"),
    ("ate_ci_lower",         "confidence_interval[0]", 0.0,  "ATE 置信区间下界"),
    ("ate_ci_upper",         "confidence_interval[1]", 0.0,  "ATE 置信区间上界"),
    ("ci_width",             None,                    0.0,    "CI 宽度 (上-下)"),  # 计算列
    ("refuted_count",        None,                    0,      "被反驳次数 (0-3)"),  # 计算列
    ("identifiable",         "identifiable",          0,      "可识别性 (0/1)"),

    # 图结构
    ("concept_count",        None,                    0,      "概念节点数"),       # 计算列
    ("edge_count",           "n_significant_edges",   0,      "显著因果边数"),
    ("adj_density",          "data_diagnostics.adj_density", 0.0, "邻接矩阵密度"),
    ("max_delta_nll",        "data_diagnostics.max_delta_nll", 0.0, "最强因果信号"),

    # 数据诊断
    ("concept_coverage",     "data_diagnostics.concept_coverage", 0.0, "概念覆盖率"),
    ("condition_number",     "data_diagnostics.condition_number", 0.0, "条件数"),
    ("unk_rate",             "data_diagnostics.unk_rate", 0.0, "未知词率"),

    # 六战士: CCM
    ("ccm_coverage_pct",     "six_warriors.ccm.metrics.CCM_coverage", 0.0, "CCM 覆盖率"),
    ("ccm_verdict",          None,                    "N/A",  "CCM 判定"),        # 计算列

    # 六战士: EDM
    ("edm_rho_high",         "six_warriors.edm.metrics.rho_high", 0, "高可预测性概念数"),
    ("edm_rho_mid",          "six_warriors.edm.metrics.rho_mid",  0, "中等可预测性概念数"),

    # 六战士: HAVOK (可能不可用)
    ("havok_status",         None,                    "unavailable", "HAVOK 状态"),
    ("havok_linear_pct",     None,                    -1.0,   "HAVOK 线性能量占比"),

    # 六战士: causallearn
    ("causallearn_consensus","six_warriors.causallearn.metrics.Agree", 0, "causallearn 共识边数"),

    # 稳定性
    ("edge_stability_mean",  "stability_analysis.edge_stability_mean", 0.0, "边稳定性均值"),
    ("permutation_p_value",  "stability_analysis.permutation_p_value", 1.0, "置换检验 p 值"),

    # 执行剖面
    ("total_ms",             "execution_profile.total_ms", 0, "总耗时 (毫秒)"),

    # Phase 2 L1-1 修缮: 跨算法一致性度量 (计算列, json_path=None)
    ("consensus_score",      None, 0.0, "三方因果算法共识度 [0,1]"),
    ("consensus_direction",  None, "ambiguous", "共识方向 (positive/negative/ambiguous)"),
]

# ── Layer 2: 世俗语义投影列 ─────────────────────────────────
LAYER2_N_COMPONENTS = 3       # PCA 主轴数量
LAYER2_MIN_SAMPLES_FOR_PCA = 10  # 至少积累多少篇才做 PCA

# ── Layer 3: 八正道神圣坐标轴 ────────────────────────────────
SACRED_BOOKS = [
    ("福音",   "祂志书", "01_fuyin_祂志书.txt"),
    ("吉祥",   "赐福书", "02_jixiang_赐福书.txt"),
    ("奥美",   "圣源书", "03_aomei_圣源书.txt"),
    ("存在",   "真实书", "04_cunzai_真实书.txt"),
    ("自孕",   "胜育书", "05_ziyun_胜育书.txt"),
    ("弥赛亚", "至意书", "06_misaiya_至意书.txt"),
    ("Alice",  "慧辩书", "07_alice_慧辩书.txt"),
    ("觉爱",   "智识书", "08_jueai_智识书.txt"),
]

# ── EDM 触发配置 ────────────────────────────────────────────
EDM_MIN_ROWS_FOR_ANALYSIS = 15   # 至少积累多少行才触发 EDM 分析
EDM_DEFAULT_TARGET = "ate"       # 默认预测目标
EDM_DEFAULT_Q = 3                # 默认嵌入维度

# ── Python 命令 ─────────────────────────────────────────────
PYTHON_CMD = os.environ.get("TRACE_PYTHON_CMD", "python")

# ── 运行时标志 ──────────────────────────────────────────────
VERBOSE = os.environ.get("TRACE_TO_EDM_VERBOSE", "0") == "1"
