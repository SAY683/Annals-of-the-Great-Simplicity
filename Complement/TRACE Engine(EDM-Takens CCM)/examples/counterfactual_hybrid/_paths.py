"""
Counterfactual Sentai — Portable Path Resolution
==================================================
对标 edm-takens/src/_paths.py 的便携路径解析。

用法:
    from _paths import resolve_paths
    paths = resolve_paths()
    print(paths.project_root)
    print(paths.model_dir("shehui-llama"))
"""

import os
from pathlib import Path
from dataclasses import dataclass


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
        """查找 TRACE 模型目录（扫描多个可能位置）"""
        candidates = [
            self.trace_dir / "models" / name,
            self.project_root / "models" / name,
            # 便携副本
            self.project_root.parent / "Complement" / "TRACE Engine(EDM-Takens CCM)" / name.capitalize().replace('-', '-'),
        ]
        # 也尝试检查上级目录
        for ancestor in self.project_root.parents:
            c = ancestor / "Complement" / "TRACE Engine(EDM-Takens CCM)" / name.capitalize().replace('-', '-')
            if c not in candidates:
                candidates.append(c)

        for c in candidates:
            if c.exists():
                return c
        return candidates[0]  # 返回首选位置（即使不存在）

    def data_dir(self) -> Path:
        """查找 TRACE 训练数据目录"""
        for d in [self.trace_dir / "date", self.project_root / "TRACE" / "date"]:
            if d.exists():
                return d
        return self.trace_dir / "date"

    @classmethod
    def auto_detect(cls, start: Path = None) -> "ProjectPaths":
        """自动检测项目根目录（兼容工作副本和便携副本两种环境）"""
        if start is None:
            start = Path(__file__).resolve().parent

        # 向上查找，识别环境类型
        current = start
        project_root = current
        is_portable = False

        for _ in range(10):
            # 便携副本特征: SKILL.md + Shehui-LLaMA/ 在同级
            if ((current / "SKILL.md").exists() and
                (current / "Shehui-LLaMA").exists()):
                project_root = current
                is_portable = True
                break
            # 工作副本特征: .skills/trace-engine/SKILL.md
            if (current / ".skills" / "trace-engine" / "SKILL.md").exists():
                project_root = current
                break
            # 工作副本特征: TRACE/README.md
            if (current / "TRACE" / "README.md").exists():
                project_root = current
                break
            current = current.parent
        else:
            # 遍历 10 层都没找到特征 → 信任起始位置
            project_root = start.parent if start.name == 'counterfactual_hybrid' else start

        # ── 根据环境类型解析路径 ──
        if is_portable:
            skill_dir = project_root
            bridge_dir = project_root / "examples" / "counterfactual_hybrid"
            if not bridge_dir.exists():
                bridge_dir = start  # 当前目录就是 bridge
            # TRACE/ 可能在上级（工作副本）或不存在
            trace_dir = project_root.parent.parent / "TRACE" if (project_root.parent.parent / "TRACE").exists() else project_root / "TRACE"
        else:
            skill_dir = project_root / ".skills" / "trace-engine"
            bridge_dir = skill_dir / "examples" / "counterfactual_hybrid"
            if not bridge_dir.exists():
                bridge_dir = start
            trace_dir = project_root / "TRACE"

        # 确保输出目录存在
        outputs_dir = bridge_dir / "outputs"
        cache_dir = outputs_dir / "cache"
        for d in [outputs_dir, cache_dir,
                  outputs_dir / "demo", outputs_dir / "real"]:
            d.mkdir(parents=True, exist_ok=True)

        return cls(
            project_root=project_root,
            skill_dir=skill_dir,
            bridge_dir=bridge_dir,
            trace_dir=trace_dir.resolve(),
            outputs_dir=outputs_dir,
            cache_dir=cache_dir,
        )


def resolve_paths(start: Path = None) -> ProjectPaths:
    """一键获取所有项目路径"""
    return ProjectPaths.auto_detect(start)
