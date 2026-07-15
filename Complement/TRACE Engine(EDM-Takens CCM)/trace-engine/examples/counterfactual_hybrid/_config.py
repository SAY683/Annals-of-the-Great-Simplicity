"""
Counterfactual Sentai — Environment Configuration
==================================================
集中管理 Skill 运行所需的外部路径与可选依赖。

设计原则:
  - 不硬编码绝对路径
  - 优先环境变量，其次相对路径探测
  - 缺失必要路径时给出明确错误，而非静默失败
"""

import os
from pathlib import Path


def _env_path(name: str) -> Path | None:
    """从环境变量读取路径并验证存在性。"""
    val = os.environ.get(name)
    if val:
        p = Path(val)
        if p.exists():
            return p
    return None


def _is_portable_trace_root(path: Path) -> bool:
    """判断是否为成品/便携版 TRACE 根目录（模型直接放在根下）。

    使用全小写目录名（shehui-llama / shenji-llama），与当前模型目录命名约定一致。
    """
    return (
        (path / "shehui-llama" / "model.safetensors").exists()
        and (path / "shenji-llama" / "model.safetensors").exists()
    )


def _is_nested_engine_trace_root(path: Path) -> bool:
    """判断是否为层级目录布局：模型放在 path/trace-engine/models/ 下。"""
    return (
        (path / "trace-engine" / "models" / "shehui-llama" / "model.safetensors").exists()
        or (path / "trace-engine" / "models" / "shenji-llama" / "model.safetensors").exists()
    )


def _find_trace_root(skill_dir: Path) -> Path | None:
    """
    从 Skill 目录向上探测 TRACE 项目根目录。
    识别特征（按优先级）:
      1. 工作副本: <project_root>/TRACE/README.md
      2. 工作副本: <project_root>/.skills/trace-engine/SKILL.md
      3. 层级副本: <dir>/trace-engine/models/<model>/model.safetensors
      4. 成品/便携副本: <dir>/shehui-llama/model.safetensors 等（全小写目录名）
    """
    current = skill_dir.resolve()
    for _ in range(10):
        # 工作副本: 项目根目录下的 TRACE/ 文件夹
        if (current / "TRACE" / "README.md").exists():
            return current / "TRACE"
        if (current / ".skills" / "trace-engine" / "SKILL.md").exists():
            # .skills 目录位于项目根下，真正的 TRACE 数据/模型目录在项目根/TRACE
            return current.parent / "TRACE"
        # 层级副本: trace-engine-web 与 trace-engine 处于同一父目录，模型在 trace-engine/models
        if _is_nested_engine_trace_root(current):
            return current / "trace-engine"
        # 成品/便携副本: 模型直接放在当前目录
        if _is_portable_trace_root(current):
            return current
        if current.parent == current:
            break
        current = current.parent
    return None


def get_skill_dir() -> Path:
    """返回本文件所在 Skill 目录（examples/counterfactual_hybrid/）。"""
    return Path(__file__).resolve().parent


def get_trace_root() -> Path:
    """
    返回 TRACE 项目根目录（含 scripts/、models/、date/）。
    解析顺序:
      1. TRACE_ROOT 环境变量
      2. 从 Skill 目录向上探测 TRACE/
    缺失时抛出 FileNotFoundError。
    """
    # 1. 环境变量
    env = _env_path("TRACE_ROOT")
    if env is not None:
        return env

    # 2. 相对探测
    skill_dir = get_skill_dir()
    discovered = _find_trace_root(skill_dir)
    if discovered is not None:
        return discovered

    raise FileNotFoundError(
        "未找到 TRACE 项目根目录。请设置 TRACE_ROOT 环境变量，"
        "或确保项目根目录存在 TRACE/ 文件夹。"
    )


def get_trace_scripts_dir() -> Path:
    """返回 TRACE/scripts/ 目录。"""
    return get_trace_root() / "scripts"


def get_trace_models_dir() -> Path:
    """返回 TRACE/models/ 目录。"""
    return get_trace_root() / "models"


def get_trace_data_dir() -> Path:
    """返回 TRACE/date/ 目录（训练数据）。"""
    return get_trace_root() / "date"


def get_graphviz_bin_dir() -> Path | None:
    """
    返回 Graphviz bin 目录（仅通过环境变量）。
    不扫描磁盘绝对路径，保持可移植性。
    """
    return _env_path("GRAPHVIZ_BIN_DIR")


def ensure_trace_scripts_in_sys_path() -> None:
    """将 TRACE/scripts 加入 sys.path，供动态导入使用。"""
    import sys
    scripts_dir = str(get_trace_scripts_dir())
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)


def ensure_edm_takens_in_sys_path() -> None:
    """将 edm-takens/src 加入 sys.path（若存在）。"""
    import sys
    skill_dir = get_skill_dir()
    # 从 Skill 目录向上探测 .skills/edm-takens/src
    current = skill_dir
    for _ in range(10):
        edm_src = current.parent / ".skills" / "edm-takens" / "src"
        if edm_src.exists():
            if str(edm_src) not in sys.path:
                sys.path.insert(0, str(edm_src))
            return
        if current.parent == current:
            break
        current = current.parent
