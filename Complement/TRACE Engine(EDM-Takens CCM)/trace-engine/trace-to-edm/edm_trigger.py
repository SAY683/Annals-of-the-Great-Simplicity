"""
EDM-Takens 分析触发器
=====================
当 CSV 积累到足够行数 (≥ EDM_MIN_ROWS_FOR_ANALYSIS) 时,
自动将 CSV 复制到 edm-takens-web 的 data/ 目录,
并通过 HTTP API 触发分析。

触发模式:
  1. auto: 每次新行追加后自动检查并触发
  2. manual: 仅当显式调用时触发
  3. monitor: 启动一个后台轮询线程, 监控 CSV 变化

用法:
  from edm_trigger import EDMTrigger
  trigger = EDMTrigger()
  result = trigger.run_analysis(target_col="ate", q=3)
  # → {"job_id": "job_xxx", "status": "pending", ...}
"""

import os
import time
import shutil
import json
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from typing import Dict, Optional

from config import (
    TRAJECTORY_CSV, EDM_DATA_DIR, EDM_API_URL,
    EDM_MIN_ROWS_FOR_ANALYSIS, EDM_DEFAULT_TARGET, EDM_DEFAULT_Q,
    VERBOSE,
)


class EDMTrigger:
    """
    EDM-Takens Web 分析触发器。

    负责:
      1. 检查轨迹 CSV 是否满足分析条件
      2. 复制 CSV 到 edm-takens-web/data/
      3. 调用 HTTP API 提交分析任务
      4. 轮询任务状态直到完成
      5. 返回分析结果摘要
    """

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
        self.api_base = EDM_API_URL.replace("localhost", "127.0.0.1").rstrip("/")

    def check_readiness(self) -> Dict:
        """
        检查当前数据是否满足 EDM 分析条件。

        Returns:
            {"ready": bool, "n_rows": int, "min_required": int, "reason": str}
        """
        if not self.csv_path.exists():
            return {
                "ready": False,
                "n_rows": 0,
                "min_required": EDM_MIN_ROWS_FOR_ANALYSIS,
                "reason": f"CSV 文件不存在: {self.csv_path}",
            }

        import csv
        with open(self.csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        n_rows = len(rows)
        ready = n_rows >= EDM_MIN_ROWS_FOR_ANALYSIS

        reason = (
            f"数据充足 ({n_rows} ≥ {EDM_MIN_ROWS_FOR_ANALYSIS})"
            if ready
            else f"数据不足 ({n_rows} < {EDM_MIN_ROWS_FOR_ANALYSIS})"
        )

        return {
            "ready": ready,
            "n_rows": n_rows,
            "min_required": EDM_MIN_ROWS_FOR_ANALYSIS,
            "reason": reason,
        }

    def copy_to_edm_data(self, time_start: str = None, time_end: str = None) -> Path:
        """将轨迹 CSV 复制到 edm-takens-web 的 data/ 目录。支持时间范围过滤。"""
        target_name = "narrative_meta_trajectories.csv"
        target_path = EDM_DATA_DIR / target_name
        EDM_DATA_DIR.mkdir(parents=True, exist_ok=True)

        # 如果指定了时间范围, 过滤 CSV 行
        if time_start or time_end:
            import csv as _csv
            filtered_rows = []
            with open(self.csv_path, "r", encoding="utf-8") as f:
                reader = _csv.DictReader(f)
                header = reader.fieldnames
                for row in reader:
                    ts = row.get("time_step", "")
                    if time_start and ts < time_start:
                        continue
                    if time_end and ts > time_end:
                        continue
                    filtered_rows.append(row)

            with open(target_path, "w", encoding="utf-8", newline="") as f:
                writer = _csv.DictWriter(f, fieldnames=header)
                writer.writeheader()
                for row in filtered_rows:
                    writer.writerow(row)

            if VERBOSE:
                print(f"[EDM] CSV已过滤: {len(filtered_rows)}行 (时间 {time_start or '...'} ~ {time_end or '...'})")
        else:
            shutil.copy2(self.csv_path, target_path)
            if VERBOSE:
                print(f"[EDM] CSV已复制: {target_path}")

        return target_path

    def _api_call(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Dict:
        """
        调用 EDM-Takens Web API。

        Args:
            method: "GET" or "POST"
            endpoint: "/api/analyze/jobs" 等
            data: POST 表单数据

        Returns:
            解析后的 JSON 响应
        """
        url = f"{self.api_base}{endpoint}"

        if method == "POST" and data:
            form_data = urllib.parse.urlencode(data).encode("utf-8")
            req = urllib.request.Request(url, data=form_data, method="POST")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
        else:
            req = urllib.request.Request(url, method=method)

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            return {"error": f"API 调用失败: {e}", "success": False}
        except json.JSONDecodeError as e:
            return {"error": f"JSON 解析失败: {e}", "success": False}

    def submit_job(
        self,
        target_col: str = EDM_DEFAULT_TARGET,
        q: int = EDM_DEFAULT_Q,
        auto_fix: bool = True,
        time_start: str = None,
        time_end: str = None,
    ) -> Dict:
        """
        提交 EDM 分析任务。

        Args:
            target_col: 预测目标列 (默认: "ate")
            q: 嵌入维度 (默认: 3)
            auto_fix: 是否自动修正数值问题
            time_start: 时间范围起始 (可选, 如 "2026-07-01")
            time_end: 时间范围结束 (可选)
        """
        # 先复制 CSV (可能带时间过滤)
        self.copy_to_edm_data(time_start=time_start, time_end=time_end)

        # 提交分析任务
        result = self._api_call("POST", "/api/analyze/jobs", {
            "filename": "narrative_meta_trajectories.csv",
            "target_col": target_col,
            "q": str(q),
            "auto_fix": str(auto_fix).lower(),
        })

        if "error" in result:
            print(f"[EDM] ❌ 任务提交失败: {result['error']}")
            return result

        job_id = result.get("job_id", "unknown")
        if VERBOSE:
            print(f"[EDM] ✓ 任务已提交: job_id={job_id}, target={target_col}, q={q}")

        return result

    def poll_job(self, job_id: str, timeout_sec: int = 300, interval_sec: float = 2) -> Dict:
        """
        轮询等待 EDM 分析任务完成。

        Args:
            job_id: 任务 ID
            timeout_sec: 超时时间
            interval_sec: 初始轮询间隔 (会指数退避到最大 15s)

        Returns:
            最终任务状态
        """
        start = time.time()
        current_interval = interval_sec

        while (time.time() - start) < timeout_sec:
            result = self._api_call("GET", f"/api/analyze/jobs/{job_id}")

            if "error" in result:
                return result

            status = result.get("status", "unknown")
            if VERBOSE:
                print(f"[EDM]   job={job_id} status={status} ({time.time()-start:.0f}s)")

            if status in ("completed", "failed", "error"):
                return result

            time.sleep(current_interval)
            # 指数退避: 2 → 4 → 8 → 15 (最大)
            current_interval = min(current_interval * 1.5, 15.0)

        return {"error": f"任务超时 ({timeout_sec}s)", "job_id": job_id, "status": "timeout"}

    def run_analysis(
        self,
        target_col: str = EDM_DEFAULT_TARGET,
        q: int = EDM_DEFAULT_Q,
        wait: bool = True,
        timeout_sec: int = 300,
        time_start: str = None,
        time_end: str = None,
    ) -> Dict:
        """
        一键提交 + (可选)等待完成。

        Args:
            target_col: 预测目标列
            q: 嵌入维度
            wait: 是否等待完成
            timeout_sec: 等待超时

        Returns:
            {"job_id": ..., "status": ..., "result_summary": ...}
        """
        # 检查就绪状态
        readiness = self.check_readiness()
        if not readiness["ready"]:
            return {"error": readiness["reason"], "success": False}

        # 提交任务
        submit_result = self.submit_job(target_col=target_col, q=q, time_start=time_start, time_end=time_end)
        if "error" in submit_result:
            return submit_result

        job_id = submit_result.get("job_id")

        if not wait:
            return submit_result

        # 等待完成
        final = self.poll_job(job_id, timeout_sec=timeout_sec)
        return final

    def list_recommended_targets(self) -> Dict[str, str]:
        """
        推荐适合作为 EDM 预测目标的列。

        Returns:
            {列名: 推荐理由, ...}
        """
        recommendations = {
            # Layer 1: 元SCM
            "ate": "因果效应强度",
            "adj_density": "因果图密度",
            "max_delta_nll": "最强因果信号",
            "ci_width": "因果不确定性",
            "edge_count": "显著因果边数",
            "ccm_coverage_pct": "CCM覆盖率",
            # Layer 2: 世俗语义 PCA
            "z_pca_1": "世俗PCA第1主轴 — 主流话语方向",
            "z_pca_2": "世俗PCA第2主轴",
            "z_pca_3": "世俗PCA第3主轴",
            "secular_entropy": "世俗熵 — 话语多样性",
            # Layer 3: 八正道全轴
            "z_福音": "福音(祂志书)投影",
            "z_吉祥": "吉祥(赐福书)投影",
            "z_奥美": "奥美(圣源书)投影",
            "z_存在": "存在(真实书)投影 — 本体论距离",
            "z_自孕": "自孕(胜育书)投影",
            "z_弥赛亚": "弥赛亚(至意书)投影",
            "z_Alice": "Alice(慧辩书)投影",
            "z_觉爱": "觉爱(智识书)投影 — 智慧维度",
            # Layer 3: 一阶差分
            "dz_存在": "存在轴一阶差分",
            "dz_觉爱": "觉爱轴一阶差分",
        }
        return recommendations


# ── 自检 (需要后端运行) ─────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("EDM Trigger 自检")
    print("=" * 60)

    trigger = EDMTrigger()

    # 检查就绪状态
    readiness = trigger.check_readiness()
    print(f"\n轨迹 CSV: {trigger.csv_path}")
    print(f"当前行数: {readiness['n_rows']}")
    print(f"最少需要: {readiness['min_required']}")
    print(f"就绪: {readiness['ready']}")
    print(f"原因: {readiness['reason']}")

    # 推荐目标列
    print("\n推荐的预测目标列:")
    for col, reason in trigger.list_recommended_targets().items():
        print(f"  {col:25s} — {reason}")

    # 尝试连接后端
    print(f"\n尝试连接 EDM 后端: {trigger.api_base}")
    health = trigger._api_call("GET", "/api/analyze/jobs")
    if "error" in health:
        print(f"  ⚠ 后端未运行: {health['error']}")
        print("  请先启动 edm-takens-web 后端 (python run_backend.py)")
    else:
        print(f"  ✓ 后端在线")

    print("\nEDM Trigger 自检完成 ✓")
