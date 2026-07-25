"""
CSV 构建器 (CSV Builder)
========================
将三层投影的结果组装为统一的 narrative_meta_trajectories.csv。

CSV 结构:
  行 (Rows): 时间步 / 事件序列
  列 (Cols): ~40 个不变的系统诊断参数 + 语义投影 + 神圣审计

列分组:
  Meta:     time_step, text_hash
  Layer 1:  ate, ci_width, refuted_count, identifiability, concept_count,
            edge_count, adj_density, max_delta_nll, concept_coverage,
            condition_number, ccm_coverage_pct, edm_rho_high, edm_rho_mid,
            havok_linear_pct, causallearn_consensus, edge_stability_mean,
            permutation_p_value, total_ms
  Layer 2:  z_pca_1, z_pca_2, z_pca_3, secular_entropy
  Layer 3:  z_福音, z_吉祥, z_奥美, z_存在, z_自孕, z_弥赛亚, z_Alice, z_觉爱,
            dz_福音, ..., d2z_福音, ...
"""

import csv
import hashlib
import os
from pathlib import Path
from typing import Dict, List, Optional

from config import TRAJECTORY_CSV, OUTPUTS_DIR, VERBOSE, LAYER1_COLUMNS, SACRED_BOOKS


def _hash_text(text: str) -> str:
    """文本 → 8 位 hex 哈希 (用于溯源)"""
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:8]


def _flatten_dict(d: Dict, prefix: str = "") -> Dict:
    """展平嵌套字典为单层 key"""
    result = {}
    for k, v in d.items():
        full_key = f"{prefix}{k}" if prefix else k
        if isinstance(v, dict):
            result.update(_flatten_dict(v, f"{full_key}_"))
        elif isinstance(v, list):
            for i, item in enumerate(v):
                result[f"{full_key}_{i}"] = item
        elif isinstance(v, bool):
            result[full_key] = 1 if v else 0
        else:
            result[full_key] = v
    return result


class TrajectoryCSV:
    """
    叙事元轨迹 CSV 管理器。

    负责:
      1. 创建/加载 CSV 文件
      2. 追加新行 (所有列自动对齐)
      3. 维护列顺序 (即使新行缺少某些列也能正确处理)
      4. CSV 统计信息

    Usage:
      csv_mgr = TrajectoryCSV()
      row = {
          "time_step": "2026-07-16 10:00",
          "text_hash": "28f0c14b",
          "ate": 28.13,
          "z_存在": 0.03,
          ...
      }
      csv_mgr.append_row(row)
    """

    # 列顺序定义 (类常量, 所有实例共享引用但每个实例独立维护 KNOWN_COLUMNS)
    # P1-g 修缮：Layer 1 列名从 config.LAYER1_COLUMNS 动态构建，消除三处独立硬编码
    COLUMN_ORDER = [
        # ── Meta ──
        "time_step", "text_hash", "source_label",
    ] + [
        # ── Layer 1: 元 SCM（从 config.LAYER1_COLUMNS 程序化绑定） ──
        c[0] for c in LAYER1_COLUMNS
    ] + [
        # ── Layer 2: 世俗语义 ──
        "z_pca_1", "z_pca_2", "z_pca_3",
        "secular_entropy",
    ] + [
        # ── Layer 3: 八正道审计 (绝对投影) ──
        f"z_{short}" for short, _, _ in SACRED_BOOKS
    ] + [
        # ── Layer 3: 八正道审计 (一阶差分) ──
        f"dz_{short}" for short, _, _ in SACRED_BOOKS
    ] + [
        # ── Layer 3: 八正道审计 (二阶差分) ──
        f"d2z_{short}" for short, _, _ in SACRED_BOOKS
    ]

    def __init__(self, csv_path: Optional[Path] = None):
        # 优先使用传入路径, 否则从项目管理器获取当前项目 CSV
        if csv_path:
            self.csv_path = Path(csv_path)
        else:
            try:
                from project_manager import get_project_manager
                self.csv_path = get_project_manager().current_csv
            except Exception:
                self.csv_path = TRAJECTORY_CSV
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)

        # 实例级别的已知列集合 (修复: 之前是类变量, 多实例共享导致污染)
        self._known_columns = set(self.COLUMN_ORDER)
        self._rows: List[Dict] = []

        # 加载现有数据
        if self.csv_path.exists():
            self._load_existing()

    def _load_existing(self):
        """加载已有 CSV，保留所有行（跳过以 _ 开头的内部元数据列，清理历史污染）"""
        with open(self.csv_path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # 过滤以 _ 开头的内部元数据字段（历史污染清理）
                clean_row = {
                    k: v for k, v in row.items()
                    if not k.startswith(self._INTERNAL_FIELD_PREFIX)
                }
                self._rows.append(clean_row)
                # 更新实例级已知列（同样跳过 _ 前缀）
                for key in clean_row.keys():
                    self._known_columns.add(key)

        if VERBOSE:
            print(f"[CSV] 加载已有轨迹: {len(self._rows)} 行, {len(self._known_columns)} 列")

    # 内部元数据字段前缀（不写入 CSV，防止污染 54 列规范）
    # 例如 layer3_sacred.py 返回的 _orthogonality_report / _method
    _INTERNAL_FIELD_PREFIX = "_"

    def append_row(self, row: Dict, auto_write: bool = True):
        """
        追加一行到 CSV。

        Args:
            row: 包含各列值的字典 (键可以是不完整子集)
            auto_write: 是否自动写入磁盘

        Note:
            以 ``_`` 开头的键视为内部元数据（如 ``_orthogonality_report``、
            ``_method``），不会作为新列追加，从而保持 54 列规范不被污染。
            若需保留此类字段，应在调用方先重命名为正式列名。
        """
        # 确保所有已知列都存在
        normalized = {}
        for col in self._known_columns:
            normalized[col] = row.get(col, "")

        # 添加新列（跳过以 _ 开头的内部元数据字段）
        for key, value in row.items():
            if key.startswith(self._INTERNAL_FIELD_PREFIX):
                continue
            if key not in self._known_columns:
                self._known_columns.add(key)
            normalized[key] = value

        self._rows.append(normalized)

        if auto_write:
            self._write()

    def _write(self):
        """写入 CSV 文件"""
        # 构建列顺序: 预定义顺序 + 动态添加的列（双保险：排除 _ 前缀内部字段）
        ordered_cols = [c for c in self.COLUMN_ORDER if c in self._known_columns]
        extra_cols = sorted(
            c for c in self._known_columns
            if c not in self.COLUMN_ORDER
            and not c.startswith(self._INTERNAL_FIELD_PREFIX)
        )
        all_cols = ordered_cols + extra_cols

        with open(self.csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=all_cols, extrasaction="ignore")
            writer.writeheader()

            for row in self._rows:
                writer.writerow(row)

    @property
    def n_rows(self) -> int:
        return len(self._rows)

    @property
    def latest_row(self) -> Optional[Dict]:
        return self._rows[-1] if self._rows else None

    def get_columns_by_layer(self) -> Dict[str, List[str]]:
        """按层分组返回列名"""
        groups = {
            "meta": [],
            "layer1": [],
            "layer2": [],
            "layer3": [],
            "other": [],
        }

        layer1_prefixes = (
            "ate", "ci_", "refuted", "identifiable", "concept_", "edge_",
            "adj_", "max_", "ccm_", "edm_", "havok_", "causallearn_",
            "edge_stability", "permutation", "total_ms",
        )
        layer3_prefixes = ("z_", "dz_", "d2z_")

        for col in self._known_columns:
            if col in ("time_step", "text_hash", "source_label"):
                groups["meta"].append(col)
            elif col.startswith("z_pca") or col == "secular_entropy":
                groups["layer2"].append(col)
            elif any(col.startswith(p) for p in layer3_prefixes) and "pca" not in col:
                groups["layer3"].append(col)
            elif any(col.startswith(p) for p in layer1_prefixes):
                groups["layer1"].append(col)
            else:
                groups["other"].append(col)

        return groups

    def print_summary(self):
        """打印 CSV 当前状态摘要"""
        groups = self.get_columns_by_layer()
        print(f"\n{'='*60}")
        print(f"轨迹文件: {self.csv_path}")
        print(f"总行数: {self.n_rows}")
        print(f"总列数: {len(self._known_columns)}")
        print(f"  Meta:  {len(groups['meta'])} 列")
        print(f"  L1:    {len(groups['layer1'])} 列 (元 SCM)")
        print(f"  L2:    {len(groups['layer2'])} 列 (世俗语义)")
        print(f"  L3:    {len(groups['layer3'])} 列 (八正道审计)")
        print(f"  其他:  {len(groups['other'])} 列")
        print(f"{'='*60}")

        # 显示最近 3 行的核心列
        if self.n_rows > 0:
            print("\n最近记录预览:")
            key_cols = ["time_step", "ate", "adj_density", "z_pca_1", "z_存在", "z_觉爱"]
            for i, row in enumerate(self._rows[-3:]):
                vals = {k: row.get(k, "") for k in key_cols if k in row}
                print(f"  [{i+1}] {vals}")


# ── 自检 ────────────────────────────────────────────────────
if __name__ == "__main__":
    import tempfile

    print("=" * 60)
    print("CSV Builder 自检")
    print("=" * 60)

    # 使用临时文件
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
        tmp_path = Path(f.name)

    try:
        mgr = TrajectoryCSV(csv_path=tmp_path)

        # 模拟追加数据
        for i in range(5):
            row = {
                "time_step": f"2026-07-{15+i:02d} 10:00",
                "text_hash": _hash_text(f"test text {i}"),
                "ate": 20.0 + i * 2.0,
                "adj_density": 0.5 - i * 0.05,
                "z_pca_1": 0.1 * i,
                "z_存在": 0.03 - i * 0.005,
            }
            mgr.append_row(row)

        mgr.print_summary()

        # 验证数据完整性
        assert mgr.n_rows == 5
        print("\n✓ 所有断言通过")

    finally:
        tmp_path.unlink(missing_ok=True)

    print("\nCSV Builder 自检完成 ✓")
