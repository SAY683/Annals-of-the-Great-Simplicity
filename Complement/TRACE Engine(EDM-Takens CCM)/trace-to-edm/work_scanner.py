"""
工作目录扫描器 (Work Scanner)
=============================
扫描 trace-engine-web/work/ 目录，列出所有 UUID 的状态，
支持预览、筛选、选择和清理无效数据。

功能:
  1. 扫描: 发现所有 UUID，报告状态 (result.json? input.txt? 大小? 时间?)
  2. 预览: 读取原始文本的前 N 字作为预览
  3. 筛选: 按状态筛选 (完整/仅JSON/仅文本/损坏)
  4. 选择: 交互式或编程式选择 UUID 加入回填
  5. 清理: 删除无效/不完整的 TRACE 输出

用法:
  from work_scanner import WorkScanner
  ws = WorkScanner()
  entries = ws.scan()
  # → [{"uuid": "...", "has_json": True, "has_text": True, "preview": "...", ...}]
  ws.delete_invalid()  # 删除只有 input 没有 result.json 的目录
"""

import os
import shutil
import csv
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from config import TRACE_WORK_DIR, VERBOSE


class WorkScanner:
    """
    TRACE 工作目录扫描器。

    scan() 返回所有 UUID 条目的完整状态报告。
    """

    def __init__(self, work_dir: Optional[Path] = None):
        self.work_dir = Path(work_dir) if work_dir else TRACE_WORK_DIR
        self.inputs_dir = self.work_dir.parent / "inputs"

    def scan(self) -> List[Dict]:
        """
        扫描工作目录，返回所有条目的状态。

        同时扫描 outputs/ 和 inputs/ 目录，确保只存在于 inputs/ 的孤儿也能被发现。

        Returns:
            按时间倒序排列的条目列表:
            [{
                "uuid": str,
                "has_json": bool,       # result.json 存在?
                "has_text": bool,       # 原始文本存在?
                "json_size": int,       # result.json 字节数
                "text_size": int,       # 原始文本字节数
                "text_preview": str,    # 前 80 字预览
                "mtime": str,           # 修改时间
                "status": "complete" | "json_only" | "text_only" | "empty",
                "json_error": str,      # JSON 是否可解析 (空=正常)
            }, ...]
        """
        entries = []
        if not self.work_dir.exists() and not self.inputs_dir.exists():
            return entries

        # 收集所有 UUID：来自 outputs/ 目录和 inputs/ 中的 .txt 文件
        uuid_set = set()
        if self.work_dir.exists():
            for task_dir in self.work_dir.iterdir():
                if task_dir.is_dir():
                    uuid_set.add(task_dir.name)
        if self.inputs_dir.exists():
            for txt_file in self.inputs_dir.glob("*.txt"):
                uuid_set.add(txt_file.stem)

        for uuid_str in sorted(uuid_set, reverse=True):
            task_dir = self.work_dir / uuid_str
            result_json = task_dir / "result.json"
            input_txt = self.inputs_dir / f"{uuid_str}.txt"

            has_json = result_json.exists()
            has_text = input_txt.exists()

            json_size = result_json.stat().st_size if has_json else 0
            text_size = input_txt.stat().st_size if has_text else 0

            # 状态判定
            if has_json and has_text:
                status = "complete"
            elif has_json and not has_text:
                status = "json_only"
            elif not has_json and has_text:
                status = "text_only"
            else:
                status = "empty"

            # JSON 有效性检查
            json_error = ""
            if has_json:
                import json
                try:
                    with open(result_json, "r", encoding="utf-8") as f:
                        json.load(f)
                except Exception as e:
                    json_error = str(e)[:100]

            # 文本预览
            text_preview = ""
            if has_text:
                try:
                    with open(input_txt, "r", encoding="utf-8") as f:
                        text_preview = f.read(200).replace("\n", " ").strip()
                        if len(text_preview) > 80:
                            text_preview = text_preview[:80] + "..."
                except Exception:
                    text_preview = "(读取失败)"

            # 修改时间
            mtime = ""
            if has_json:
                mtime = datetime.fromtimestamp(result_json.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            elif has_text:
                mtime = datetime.fromtimestamp(input_txt.stat().st_mtime).strftime("%Y-%m-%d %H:%M")

            entries.append({
                "uuid": uuid_str,
                "has_json": has_json,
                "has_text": has_text,
                "json_size": json_size,
                "text_size": text_size,
                "text_preview": text_preview,
                "mtime": mtime,
                "status": status,
                "json_error": json_error,
            })

        # 按时间倒序
        entries.sort(key=lambda e: e["mtime"], reverse=True)
        return entries

    def scan_summary(self) -> Dict:
        """扫描摘要统计 (包含磁盘用量和孤儿文件数)"""
        entries = self.scan()
        counts = {"complete": 0, "json_only": 0, "text_only": 0, "empty": 0}
        for e in entries:
            counts[e["status"]] = counts.get(e["status"], 0) + 1

        return {
            "total": len(entries),
            "counts": counts,
            "disk_mb": round(self.disk_usage_mb(), 2),
            "orphans": counts.get("text_only", 0),
            "complete_entries": [e for e in entries if e["status"] == "complete"],
            "incomplete_entries": [e for e in entries if e["status"] != "complete"],
        }

    def get_complete_uuids(self) -> List[str]:
        """获取所有状态为 'complete' 的 UUID"""
        return [e["uuid"] for e in self.scan() if e["status"] == "complete"]

    def get_replay_entries(self, uuids: Optional[List[str]] = None) -> List[Dict]:
        """
        获取可用于回填的条目。
        如果指定 uuids，只返回这些 UUID (需状态为 complete 或 json_only)。
        否则返回所有 complete 条目。
        """
        all_entries = {e["uuid"]: e for e in self.scan()}

        if uuids:
            result = []
            for u in uuids:
                entry = all_entries.get(u)
                if entry and entry["has_json"]:
                    result.append(entry)
                else:
                    print(f"[WS] ⚠ UUID 不可用: {u}")
            return result

        return [e for e in self.scan() if e["status"] == "complete"]

    def export_replay_csv(self, uuids: List[str], output_path: Path) -> int:
        """
        将选定的 UUID 导出为回填 CSV 格式。

        Args:
            uuids: UUID 列表
            output_path: 输出 CSV 路径

        Returns:
            导出的条目数
        """
        entries = self.get_replay_entries(uuids)
        if not entries:
            return 0

        with open(output_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["timestamp", "source", "result_uuid"])
            writer.writeheader()
            for e in entries:
                writer.writerow({
                    "timestamp": e["mtime"],
                    "source": e["text_preview"][:40],
                    "result_uuid": e["uuid"],
                })

        if VERBOSE:
            print(f"[WS] 导出 {len(entries)} 个 UUID → {output_path}")
        return len(entries)

    def delete_uuids(self, uuids: List[str], dry_run: bool = True) -> Dict:
        """
        删除指定 UUID 的工作目录和输入文件。

        Args:
            uuids: 要删除的 UUID 列表
            dry_run: True=仅预览, False=实际执行

        Returns:
            {"deleted": int, "freed_bytes": int, "errors": [...]}
        """
        freed = 0
        deleted = 0
        errors = []

        for uuid_str in uuids:
            task_dir = self.work_dir / uuid_str
            input_file = self.inputs_dir / f"{uuid_str}.txt"

            try:
                # 删除 outputs/{uuid} 目录（孤儿可能没有此目录，属正常情况）
                if task_dir.exists():
                    for f in task_dir.rglob("*"):
                        if f.is_file():
                            freed += f.stat().st_size
                    if not dry_run:
                        shutil.rmtree(task_dir)
                    deleted += 1

                # 删除 inputs/{uuid}.txt（孤儿的主要清理目标）
                if input_file.exists():
                    freed += input_file.stat().st_size
                    if not dry_run:
                        input_file.unlink()
                    # 若 task_dir 不存在（text_only 孤儿），仅删 input 也算删除成功
                    if not task_dir.exists():
                        deleted += 1

            except Exception as e:
                errors.append(f"{uuid_str}: {e}")

        action = "将删除" if dry_run else "已删除"
        if VERBOSE:
            print(f"[WS] {action} {deleted} 个 UUID, 释放 {freed/1024:.1f} KB")

        return {
            "deleted": deleted,
            "freed_bytes": freed,
            "errors": errors,
            "dry_run": dry_run,
        }

    def delete_invalid(self, dry_run: bool = True) -> Dict:
        """
        删除所有无效条目 (text_only, empty, 或 json_error 非空)。

        Args:
            dry_run: True=仅预览

        Returns:
            删除结果字典
        """
        entries = self.scan()
        invalid = []
        for e in entries:
            if e["status"] in ("text_only", "empty") or e["json_error"]:
                invalid.append(e["uuid"])

        if VERBOSE:
            print(f"[WS] 发现 {len(invalid)} 个无效条目 (共 {len(entries)} 个)")

        return self.delete_uuids(invalid, dry_run=dry_run)

    def delete_orphans(self, dry_run: bool = True) -> Dict:
        """
        删除孤儿文件: inputs/ 中有 .txt 但 outputs/ 中没有对应 result.json 的条目。

        这些通常是不完整 TRACE 运行的残留 (只有输入文本, 没有输出结果)。
        清理它们不会丢失任何已完成的分析数据。

        Args:
            dry_run: True=仅预览

        Returns:
            删除结果字典
        """
        entries = self.scan()
        orphans = [e["uuid"] for e in entries if e["status"] == "text_only"]

        # 也检查 outputs/ 中的空目录
        for e in entries:
            if e["status"] == "empty":
                orphans.append(e["uuid"])

        if VERBOSE:
            print(f"[WS] 发现 {len(orphans)} 个孤儿/空条目")

        return self.delete_uuids(orphans, dry_run=dry_run)

    def disk_usage_mb(self) -> float:
        """计算工作目录总磁盘占用 (MB)"""
        total = 0
        if self.work_dir.exists():
            for f in self.work_dir.rglob("*"):
                if f.is_file():
                    total += f.stat().st_size
        if self.inputs_dir.exists():
            for f in self.inputs_dir.rglob("*.txt"):
                if f.is_file():
                    total += f.stat().st_size
        return total / (1024 * 1024)

    def print_report(self):
        """打印工作目录状态报告 (人类可读)"""
        summary = self.scan_summary()
        c = summary["counts"]

        print(f"\n{'='*60}")
        print(f"TRACE 工作目录: {self.work_dir}")
        print(f"总条目: {summary['total']}")
        print(f"  ✓ 完整 (json+text): {c['complete']}")
        print(f"  ⚡ 仅JSON (缺文本): {c['json_only']}")
        print(f"  📄 仅文本 (缺JSON): {c['text_only']}")
        print(f"  ❌ 空目录:          {c['empty']}")
        print(f"{'='*60}")

        if c["complete"] > 0:
            print("\n可回填条目 (完整):")
            for e in summary["complete_entries"][:10]:
                print(f"  {e['uuid'][:12]}... | {e['mtime']} | {e['text_preview'][:50]}")

        if summary["incomplete_entries"]:
            print(f"\n不完整条目 ({len(summary['incomplete_entries'])} 个):")
            for e in summary["incomplete_entries"][:5]:
                print(f"  {e['uuid'][:12]}... | status={e['status']} | json_error={e['json_error'][:40]}")


# ── 自检 ────────────────────────────────────────────────────
if __name__ == "__main__":
    ws = WorkScanner()
    ws.print_report()
