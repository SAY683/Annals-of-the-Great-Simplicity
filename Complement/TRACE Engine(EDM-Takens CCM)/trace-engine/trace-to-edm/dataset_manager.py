"""
数据集管理器 (Dataset Manager)
==============================
每个项目维护一个数据集注册表，追踪所有已添加的数据条目及其处理状态。

数据集是项目的核心概念 — 所有数据通过它流入：
  来源 1: TRACE 工作目录 → 扫描 → 选定 UUID → 加入数据集
  来源 2: 项目 inputs/ 中的文本 CSV → 加入数据集

处理管线统一执行：遍历数据集中所有 pending 条目，自动选择最优策略：
  - UUID 条目: 回填模式 (从 result.json 提取, ~0.1s/条)
  - 文本条目: 完整管线 (TRACE → L1+L2+L3, ~5s/条)

文件结构:
  projects/{name}/
  ├── project.json
  ├── dataset.json          ← 数据集注册表
  ├── narrative_meta_trajectories.csv
  ├── inputs/               ← 文本 CSV 放这里
  ├── outputs/
  └── cache/
"""

import json
import csv
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from config import VERBOSE


class DatasetManager:
    """
    项目数据集管理器。

    dataset.json 结构:
    {
      "entries": [
        {
          "id": "uuid-xxx" or "text-{hash}",
          "type": "replay" | "text",
          "source": "完整UUID" or "文本前80字",
          "timestamp": "2026-07-17 10:00",
          "status": "pending" | "processed" | "skipped",
          "added_at": "2026-07-17 12:00",
          "result_uuid": "仅 replay 类型"
        }
      ]
    }
    """

    def __init__(self, project_dir: Path):
        self.project_dir = Path(project_dir)
        self.dataset_path = self.project_dir / "dataset.json"
        self._data = self._load()

    def _load(self) -> Dict:
        if self.dataset_path.exists():
            with open(self.dataset_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"entries": []}

    def _save(self):
        self.project_dir.mkdir(parents=True, exist_ok=True)
        with open(self.dataset_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    # ── 查询 ────────────────────────────────────────────

    @property
    def entries(self) -> List[Dict]:
        return self._data.get("entries", [])

    @property
    def pending(self) -> List[Dict]:
        return [e for e in self.entries if e.get("status") == "pending"]

    @property
    def processed(self) -> List[Dict]:
        return [e for e in self.entries if e.get("status") == "processed"]

    @property
    def total_count(self) -> int:
        return len(self.entries)

    @property
    def pending_count(self) -> int:
        return len(self.pending)

    def summary(self) -> Dict:
        return {
            "total": self.total_count,
            "pending": self.pending_count,
            "processed": len(self.processed),
            "by_type": {
                "replay": len([e for e in self.entries if e.get("type") == "replay"]),
                "text": len([e for e in self.entries if e.get("type") == "text"]),
            },
        }

    # ── 添加 ────────────────────────────────────────────

    def add_replay_uuids(self, uuid_entries: List[Dict]) -> int:
        """
        从工作扫描器添加 UUID 条目。

        Args:
            uuid_entries: [{"uuid": "...", "mtime": "...", "text_preview": "..."}, ...]

        Returns:
            新增数量 (跳过已存在的)
        """
        added = 0
        existing_ids = {e["id"] for e in self.entries}

        for entry in uuid_entries:
            eid = entry["uuid"]
            if eid in existing_ids:
                continue

            self._data["entries"].append({
                "id": eid,
                "type": "replay",
                "source": entry.get("text_preview", "")[:80],
                "timestamp": entry.get("mtime", datetime.now().strftime("%Y-%m-%d %H:%M")),
                "status": "pending",
                "added_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "result_uuid": eid,
            })
            existing_ids.add(eid)
            added += 1

        if added > 0:
            self._save()
            if VERBOSE:
                print(f"[DS] 添加 {added} 个 replay 条目")
        return added

    def add_text_entries(self, text_rows: List[Dict]) -> int:
        """
        从文本 CSV 添加条目。

        Args:
            text_rows: [{"timestamp": "...", "text": "...", "source": "..."}, ...]

        Returns:
            新增数量
        """
        added = 0
        for row in text_rows:
            text = row.get("text") or row.get("content") or ""
            if not text.strip():
                continue

            eid = "text-" + hashlib.md5(text.encode("utf-8")).hexdigest()[:12]
            if any(e["id"] == eid for e in self.entries):
                continue

            ts = row.get("timestamp") or row.get("time_step") or datetime.now().strftime("%Y-%m-%d %H:%M")

            self._data["entries"].append({
                "id": eid,
                "type": "text",
                "source": row.get("source", "")[:40] or text[:80],
                "timestamp": ts,
                "status": "pending",
                "added_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "text": text,
            })
            added += 1

        if added > 0:
            self._save()
            if VERBOSE:
                print(f"[DS] 添加 {added} 个 text 条目")
        return added

    # ── 操作 ────────────────────────────────────────────

    def mark_processed(self, entry_id: str):
        for e in self._data["entries"]:
            if e["id"] == entry_id:
                e["status"] = "processed"
                self._save()
                return

    def mark_skipped(self, entry_id: str, reason: str = ""):
        for e in self._data["entries"]:
            if e["id"] == entry_id:
                e["status"] = "skipped"
                if reason:
                    e["skip_reason"] = reason
                self._save()
                return

    def remove_entry(self, entry_id: str):
        self._data["entries"] = [e for e in self.entries if e["id"] != entry_id]
        self._save()

    def clear_processed(self):
        """移除所有已处理的条目 (保留 pending)"""
        self._data["entries"] = [e for e in self.entries if e["status"] != "processed"]
        self._save()

    def reset_all_pending(self):
        """将所有条目重置为 pending"""
        for e in self._data["entries"]:
            e["status"] = "pending"
        self._save()

    # ── 导出 ────────────────────────────────────────────

    def export_replay_csv(self) -> Path:
        """将 replay 类型的 pending 条目导出为回填 CSV"""
        replay_pending = [e for e in self.pending if e["type"] == "replay"]
        output_path = self.project_dir / "outputs" / "_replay_pending.csv"

        with open(output_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["timestamp", "source", "result_uuid"])
            writer.writeheader()
            for e in replay_pending:
                writer.writerow({
                    "timestamp": e["timestamp"],
                    "source": e["source"][:40],
                    "result_uuid": e["result_uuid"],
                })

        return output_path

    def export_text_csv(self) -> Path:
        """将 text 类型的 pending 条目导出为文本 CSV"""
        text_pending = [e for e in self.pending if e["type"] == "text"]
        output_path = self.project_dir / "outputs" / "_text_pending.csv"

        with open(output_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["timestamp", "text", "source"])
            writer.writeheader()
            for e in text_pending:
                writer.writerow({
                    "timestamp": e["timestamp"],
                    "text": e.get("text", ""),
                    "source": e["source"][:40],
                })

        return output_path


# ── 自检 ────────────────────────────────────────────────
if __name__ == "__main__":
    import tempfile, os
    tmp = Path(tempfile.mkdtemp()) / "test_project"
    tmp.mkdir(parents=True)

    dm = DatasetManager(tmp)
    print(f"Empty: {dm.summary()}")

    dm.add_replay_uuids([
        {"uuid": "test-uuid-001", "mtime": "2026-07-17 10:00", "text_preview": "测试文本A"},
        {"uuid": "test-uuid-002", "mtime": "2026-07-17 10:01", "text_preview": "测试文本B"},
    ])
    print(f"After replay add: {dm.summary()}")

    dm.add_text_entries([
        {"timestamp": "2026-07-17 11:00", "text": "这是一段新文本", "source": "测试来源"},
    ])
    print(f"After text add: {dm.summary()}")

    replay_csv = dm.export_replay_csv()
    text_csv = dm.export_text_csv()
    print(f"Replay CSV: {replay_csv} ({os.path.getsize(replay_csv)} bytes)")
    print(f"Text CSV:   {text_csv} ({os.path.getsize(text_csv)} bytes)")

    dm.mark_processed("test-uuid-001")
    print(f"After process 1: pending={dm.pending_count}")

    import shutil; shutil.rmtree(tmp)
    print("OK")
