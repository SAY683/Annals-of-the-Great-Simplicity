"""
Counterfactual Sentai — Portable Path Resolution
==================================================
对标 edm-takens/src/_paths.py 的便携路径解析。

设计原则:
  - 所有外部路径由 _config.py 统一管理，不硬编码绝对路径
  - 支持 TRACE_ROOT / GRAPHVIZ_BIN_DIR 环境变量覆盖
  - 默认从 Skill 目录向上探测项目根目录的 TRACE/ 文件夹

用法:
    from project_paths import resolve_paths
    paths = resolve_paths()
    print(paths.project_root)
    print(paths.model_dir("shehui-llama"))
"""

import os
from pathlib import Path
from dataclasses import dataclass

from _config import (
    get_skill_dir,
    get_trace_root,
    get_trace_scripts_dir,
    get_trace_models_dir,
    get_trace_data_dir,
    get_graphviz_bin_dir,
)


@dataclass
class ProjectPaths:
    """项目路径解析容器 — 自动检测项目根目录"""
    project_root: Path
    skill_dir: Path           # .skills/trace-engine/
    bridge_dir: Path          # examples/counterfactual_hybrid/
    trace_dir: Path           # TRACE/ (如果存在)
    outputs_dir: Path
    cache_dir: Path

    def model_dir(self, name: str = "shehui-llama") -> Path:
        """
        查找 TRACE 模型目录。
        候选位置（按优先级）:
          1. TRACE_ROOT/models/<name>
          2. TRACE_ROOT/<name>           （便携/成品目录布局）
          3. <project_root>/TRACE/models/<name>
        若均不存在，返回首选位置并允许调用方自行处理缺失。
        """
        normalized = name.strip().replace('_', '-')
        candidates = [
            get_trace_models_dir() / normalized,
            self.trace_dir / normalized,           # 成品目录：模型直接放在 trace-engine/ 根下
            self.project_root / "TRACE" / "models" / normalized,
        ]
        for c in candidates:
            if c.exists():
                return c
        return candidates[0]

    def data_dir(self) -> Path:
        """查找 TRACE 训练数据目录"""
        return get_trace_data_dir()

    def scripts_dir(self) -> Path:
        """查找 TRACE 脚本目录"""
        return get_trace_scripts_dir()

    @classmethod
    def auto_detect(cls, start: Path = None) -> "ProjectPaths":
        """
        自动检测项目路径。
        核心依赖由 _config.py 提供；本方法负责组装 Skill 内部目录。
        """
        if start is None:
            start = get_skill_dir()

        bridge_dir = start.resolve()
        skill_dir = bridge_dir.parent.parent
        trace_dir = get_trace_root()

        # 推断项目根目录：TRACE/ 的父目录，或 Skill 向上两层的目录
        project_root = trace_dir.parent
        if not (project_root / ".skills" / "trace-engine" / "SKILL.md").exists():
            alt = skill_dir.parent
            if (alt / ".skills" / "trace-engine" / "SKILL.md").exists():
                project_root = alt

        # 确保输出目录存在；优先使用 TRACE_WORK_DIR（与 Web 端对齐），
        # 便于沙箱/只读目录部署时将运行时产物写到可写位置。
        work_dir = os.environ.get('TRACE_WORK_DIR')
        if work_dir:
            outputs_dir = Path(work_dir) / 'engine_outputs'
        else:
            outputs_dir = bridge_dir / "outputs"
        cache_dir = outputs_dir / "cache"
        logs_dir = outputs_dir / "logs"
        for d in [outputs_dir, cache_dir, logs_dir,
                  outputs_dir / "demo", outputs_dir / "real"]:
            d.mkdir(parents=True, exist_ok=True)

        return cls(
            project_root=project_root.resolve(),
            skill_dir=skill_dir.resolve(),
            bridge_dir=bridge_dir,
            trace_dir=trace_dir.resolve(),
            outputs_dir=outputs_dir,
            cache_dir=cache_dir,
        )


def resolve_paths(start: Path = None) -> ProjectPaths:
    """一键获取所有项目路径"""
    return ProjectPaths.auto_detect(start)
