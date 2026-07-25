"""
项目管理器 (Project Manager)
============================
管理多个因果分析项目的创建、选择、切换。

项目结构:
  projects/
  ├── _index.json              # 项目注册表
  ├── default/                 # 默认项目
  │   └── narrative_meta_trajectories.csv
  └── {project_name}/          # 自定义项目
      └── narrative_meta_trajectories.csv

用法:
  from project_manager import ProjectManager
  pm = ProjectManager()
  pm.create("信息茧房追踪")
  pm.activate("信息茧房追踪")
  print(pm.current_csv)  # → projects/信息茧房追踪/narrative_meta_trajectories.csv
"""

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from config import PROJECT_ROOT, VERBOSE

PROJECTS_DIR = PROJECT_ROOT / "projects"
INDEX_FILE = PROJECTS_DIR / "_index.json"


def _load_index() -> Dict:
    """加载项目注册表"""
    if not INDEX_FILE.exists():
        return {
            "active": "default",
            "projects": {
                "default": {
                    "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "description": "默认项目",
                    "rows": 0,
                }
            }
        }
    with open(INDEX_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_index(index: Dict):
    """保存项目注册表"""
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


class ProjectManager:
    """
    项目管理器 — 多项目隔离的数据管理。

    每个项目有独立的轨迹 CSV，互不干扰。
    """

    def __init__(self):
        self._index = _load_index()
        self._ensure_dirs()

    def _ensure_dirs(self):
        """确保所有已注册项目的目录存在"""
        for name in self._index["projects"]:
            (PROJECTS_DIR / name).mkdir(parents=True, exist_ok=True)

    def _csv_path(self, name: str) -> Path:
        return PROJECTS_DIR / name / "narrative_meta_trajectories.csv"

    def _project_dir(self, name: str) -> Path:
        return PROJECTS_DIR / name

    def _ensure_project_dirs(self, name: str):
        """确保项目内所有子目录存在"""
        pd = self._project_dir(name)
        for sub in ["inputs", "outputs", "cache"]:
            (pd / sub).mkdir(parents=True, exist_ok=True)

    # ── 查询 ────────────────────────────────────────────

    @property
    def active(self) -> str:
        return self._index.get("active", "default")

    @property
    def current_csv(self) -> Path:
        return self._csv_path(self.active)

    @property
    def current_dir(self) -> Path:
        return self._project_dir(self.active)

    @property
    def current_cache_dir(self) -> Path:
        return self._project_dir(self.active) / "cache"

    def list_projects(self) -> List[Dict]:
        """列出所有项目"""
        result = []
        for name, meta in self._index["projects"].items():
            csv_path = self._csv_path(name)
            rows = 0
            if csv_path.exists():
                import csv
                try:
                    with open(csv_path, "r", encoding="utf-8") as f:
                        rows = sum(1 for _ in f) - 1  # 减表头
                except Exception as e:
                    # debt-12.13: 行数统计失败不阻断列表，但需记录
                    if VERBOSE:
                        print(f"[PM] 警告: 统计 {name} 行数失败: {e}")

            result.append({
                "name": name,
                "active": name == self.active,
                "created": meta.get("created", ""),
                "description": meta.get("description", ""),
                "rows": max(rows, meta.get("rows", 0)),
                "csv_path": str(csv_path),
                "project_dir": str(self._project_dir(name)),
                "inputs_dir": str(self._project_dir(name) / "inputs"),
            })
        return result

    def get_project(self, name: str) -> Optional[Dict]:
        for p in self.list_projects():
            if p["name"] == name:
                return p
        return None

    # ── 操作 ────────────────────────────────────────────

    def create(self, name: str, description: str = "", template: bool = False) -> bool:
        """创建新项目 (自包含目录结构)。

        每个项目包含:
          projects/{name}/
          ├── project.json           # 项目元数据
          ├── narrative_meta_trajectories.csv  # 轨迹数据
          ├── inputs/                # 项目专属输入
          ├── outputs/               # 项目专属输出
          └── cache/                 # 项目专属缓存 (PCA, vectors)
        """
        if not name or "/" in name or "\\" in name:
            print(f"[PM] 无效的项目名: {name}")
            return False
        if name in self._index["projects"]:
            print(f"[PM] 项目已存在: {name}")
            return False

        project_dir = self._project_dir(name)
        project_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_project_dirs(name)

        # 写入 project.json
        meta = {
            "name": name,
            "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "description": description or f"项目: {name}",
            "rows": 0,
        }
        with open(project_dir / "project.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        # 从模板复制示例输入文件 (可选)
        if template:
            template_dir = PROJECT_ROOT / "data" / "inputs"
            if template_dir.exists():
                import shutil
                for f in template_dir.glob("example_*.csv"):
                    shutil.copy2(f, project_dir / "inputs" / f.name)

        self._index["projects"][name] = {
            "created": meta["created"],
            "description": meta["description"],
            "rows": 0,
        }
        _save_index(self._index)

        if VERBOSE:
            print(f"[PM] 创建项目: {name} → {project_dir}")
        return True

    def activate(self, name: str) -> bool:
        """切换到指定项目"""
        if name not in self._index["projects"]:
            print(f"[PM] 项目不存在: {name}")
            return False
        self._index["active"] = name
        _save_index(self._index)
        if VERBOSE:
            print(f"[PM] 激活项目: {name}")
        # P0-02 修复：项目切换后主动重置 bridge 的 L2/L3 单例，
        # 避免复用旧项目的 sacred_vectors / pca_state cache。
        try:
            import bridge as _bridge
            if hasattr(_bridge, "reset_semantic_singletons"):
                _bridge.reset_semantic_singletons()
        except Exception as e:
            # debt-12.13: 不再静默吞错，至少在 VERBOSE 模式下记录原因
            if VERBOSE:
                print(f"[PM] 警告: 重置 bridge 单例失败: {e}")
        # P1-d 修缮：项目切换后重新加载该项目的活动模型配置
        # _active_model.txt 现已按项目隔离（projects/<name>/cache/_active_model.txt）
        # 需重置 L3 内存状态以匹配新项目的模型选择
        try:
            import layer3_sacred as _l3
            _l3._load_model_config()  # 从新项目的 _active_model.txt 重新加载
            _l3._MODEL = None          # 清除旧模型实例
            _l3._TOKENIZER = None
            _l3._SACRED_VECTORS = None  # 清除旧八正道向量缓存
            if VERBOSE:
                print(f"[PM] 已重置 L3 模型为项目 {name} 的配置: {_l3._ACTIVE_MODEL}")
        except Exception as e:
            if VERBOSE:
                print(f"[PM] ⚠ 切换项目后重置 L3 模型失败: {e}")
        return True

    def delete(self, name: str) -> bool:
        """删除项目及其所有数据 (自动处理活动项目和文件锁定)"""
        if name == "default":
            print("[PM] 不能删除默认项目")
            return False
        if name not in self._index["projects"]:
            print(f"[PM] 项目不存在: {name}")
            return False

        # 如果要删的是活动项目, 先切到 default
        if self._index["active"] == name:
            self._index["active"] = "default"
            _save_index(self._index)

        # 从索引移除 (即使目录删除失败也要移除)
        del self._index["projects"][name]
        _save_index(self._index)

        # 尝试删除目录 (忽略文件锁定错误)
        project_dir = PROJECTS_DIR / name
        if project_dir.exists():
            try:
                shutil.rmtree(project_dir)
            except PermissionError:
                print(f"[PM] ⚠ 部分文件被占用, 跳过: {name}")
                # Windows 下文件可能被 Node.js 锁定, 尽力删除
                import os as _os
                for root, dirs, files in _os.walk(str(project_dir), topdown=False):
                    for f in files:
                        try: _os.unlink(_os.path.join(root, f))
                        except: pass
                    for d in dirs:
                        try: _os.rmdir(_os.path.join(root, d))
                        except: pass
                try: project_dir.rmdir()
                except: pass

        if VERBOSE:
            print(f"[PM] 删除项目: {name}")
        return True

    def rename(self, old_name: str, new_name: str) -> bool:
        """重命名项目"""
        if old_name not in self._index["projects"]:
            return False
        if new_name in self._index["projects"]:
            return False

        old_dir = PROJECTS_DIR / old_name
        new_dir = PROJECTS_DIR / new_name
        if old_dir.exists():
            old_dir.rename(new_dir)

        self._index["projects"][new_name] = self._index["projects"].pop(old_name)
        if self._index["active"] == old_name:
            self._index["active"] = new_name
        _save_index(self._index)
        return True

    def update_row_count(self, name: str = None):
        """更新项目的行数统计 (同时更新 project.json 和 _index.json)"""
        if name is None:
            name = self.active
        csv_path = self._csv_path(name)
        project_json = self._project_dir(name) / "project.json"
        if csv_path.exists():
            import csv
            try:
                with open(csv_path, "r", encoding="utf-8") as f:
                    rows = sum(1 for _ in f) - 1
                rows = max(0, rows)
                if name in self._index["projects"]:
                    self._index["projects"][name]["rows"] = rows
                    _save_index(self._index)
                # 同步 project.json
                if project_json.exists():
                    with open(project_json, "r", encoding="utf-8") as f:
                        pmeta = json.load(f)
                    pmeta["rows"] = rows
                    with open(project_json, "w", encoding="utf-8") as f:
                        json.dump(pmeta, f, ensure_ascii=False, indent=2)
            except Exception as e:
                # debt-12.13: 行数同步失败不影响主流程，但需记录以便排查
                if VERBOSE:
                    print(f"[PM] 警告: 同步行数到 _index/project.json 失败: {e}")


# ── 全局单例 ────────────────────────────────────────────────
_pm_instance = None


def get_project_manager() -> ProjectManager:
    global _pm_instance
    if _pm_instance is None:
        _pm_instance = ProjectManager()
    return _pm_instance


# ── 自检 ────────────────────────────────────────────────────
if __name__ == "__main__":
    pm = ProjectManager()
    print("当前项目:", pm.active)
    print("当前 CSV:", pm.current_csv)
    print("\n所有项目:")
    for p in pm.list_projects():
        marker = "← 当前" if p["active"] else ""
        print(f"  [{p['rows']}行] {p['name']} {marker}")
        print(f"         创建: {p['created']} | {p['description']}")
