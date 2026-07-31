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

    # INT-02 修复: 原始列→管道别名映射表, 供日志披露与下游解读
    # EDM 管道直接使用原始列名作为 target_col, 此映射披露语义等价关系
    VARIABLE_MAPPING = {
        # Layer 1: 元 SCM
        "ate": "result",              # 因果效应估计 → EDM 目标变量
        "adj_density": "graph_density",
        "max_delta_nll": "max_signal",
        "ci_width": "uncertainty",
        "edge_count": "complexity",
        "ccm_coverage_pct": "ccm_coverage",
        # Layer 2: 世俗语义 PCA
        "z_pca_1": "secular_axis_1",
        "z_pca_2": "secular_axis_2",
        "z_pca_3": "secular_axis_3",
        "secular_entropy": "diversity",
        # Layer 3: 八正道 (示例, 完整列表见 list_recommended_targets)
        "z_福音": "gospel_projection",
        "z_存在": "existence_projection",
        "z_觉爱": "wisdom_projection",
    }

    # ENG-09 / ROB-01 修复: HTTP 调用重试与断路器配置
    _RETRY_ATTEMPTS = 3          # 最多重试次数 (含首次调用)
    _RETRY_BACKOFF_SECONDS = [1, 2, 4]  # 指数退避间隔 (1s/2s/4s)
    _CIRCUIT_FAILURE_THRESHOLD = 5  # 连续失败 5 次后熔断
    _CIRCUIT_RESET_SECONDS = 60   # 熔断后 60s 内短路所有请求

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
        # ROB-01 断路器状态 (实例级, 跨方法共享)
        self._circuit_failures = 0   # 连续失败计数
        self._circuit_open_until = 0.0  # 熔断到期时间戳 (time.monotonic)

    def check_readiness(self) -> Dict:
        """
        检查当前数据是否满足 EDM 分析条件。

        ROUND28 P0-04: 引入分级 confidence_level, 对齐 EDM-TAKENS 自己声明
        "32 样本不足"的边界。15-30 行为"探索性", ≥30 行为"正式"。

        Returns:
            {"ready": bool, "n_rows": int, "min_required": int, "reason": str,
             "confidence_level": "exploratory"|"formal"|"insufficient",
             "confidence_disclaimer": str}
        """
        if not self.csv_path.exists():
            return {
                "ready": False,
                "n_rows": 0,
                "min_required": EDM_MIN_ROWS_FOR_ANALYSIS,
                "reason": f"CSV 文件不存在: {self.csv_path}",
                "confidence_level": "insufficient",
                "confidence_disclaimer": "无数据, 无法分析。",
            }

        import csv
        with open(self.csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        n_rows = len(rows)
        ready = n_rows >= EDM_MIN_ROWS_FOR_ANALYSIS

        # ROUND28 P0-04: 分级 confidence_level
        # EDM-TAKENS 自己的测试明示 32 样本仍不足以可靠估计 Lyapunov 时间
        # 15-30 行: 探索性 (exploratory) — 可触发但结果不稳定
        # ≥30 行: 正式 (formal) — 可用于报告
        # <15 行: 不足 (insufficient)
        EDM_FORMAL_THRESHOLD = 30  # 与 EDM-TAKENS 边界声明对齐
        if n_rows < EDM_MIN_ROWS_FOR_ANALYSIS:
            confidence_level = "insufficient"
            confidence_disclaimer = (
                f"数据不足 ({n_rows} < {EDM_MIN_ROWS_FOR_ANALYSIS}), 无法触发 EDM 分析。"
            )
        elif n_rows < EDM_FORMAL_THRESHOLD:
            confidence_level = "exploratory"
            confidence_disclaimer = (
                f"探索性分析 ({n_rows} 行, < {EDM_FORMAL_THRESHOLD}): "
                "EDM 动力学预测在小样本下不稳定, 可能产生伪相变信号。"
                "结果仅供探索, 不得用于投资决策。建议积累 ≥30 行后再做正式分析。"
            )
        else:
            confidence_level = "formal"
            confidence_disclaimer = (
                f"正式分析 ({n_rows} 行 ≥ {EDM_FORMAL_THRESHOLD}): "
                "结果可用于报告, 但仍需注意 EDM-TAKENS 的 IAAFT/BH 统计保证边界。"
            )

        reason = (
            f"数据充足 ({n_rows} ≥ {EDM_MIN_ROWS_FOR_ANALYSIS}, {confidence_level})"
            if ready
            else f"数据不足 ({n_rows} < {EDM_MIN_ROWS_FOR_ANALYSIS})"
        )

        return {
            "ready": ready,
            "n_rows": n_rows,
            "min_required": EDM_MIN_ROWS_FOR_ANALYSIS,
            "formal_threshold": EDM_FORMAL_THRESHOLD,
            "reason": reason,
            "confidence_level": confidence_level,
            "confidence_disclaimer": confidence_disclaimer,
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
        调用 EDM-Takens Web API (ENG-09/ROB-01: 含重试 + 断路器)。

        Args:
            method: "GET" or "POST"
            endpoint: "/api/analyze/jobs" 等
            data: POST 表单数据

        Returns:
            解析后的 JSON 响应

        ENG-09 修复: 原 implementation 仅 timeout=10s 无重试, 瞬时网络抖动即失败。
        现添加 3 次指数退避重试 (1s/2s/4s), 仅对连接级/超时级错误重试 (4xx/5xx 不重试)。

        ROB-01 修复: 原 implementation edm-takens-web 临时不可用时直接返回 500。
        现添加断路器: 连续 5 次失败后短路 60s, 期间所有请求立即返回熔断错误,
        避免雪崩式重试压垮下游服务。
        """
        # ROB-01: 断路器开路检查
        now = time.monotonic()
        if self._circuit_open_until > now:
            remaining = self._circuit_open_until - now
            return {
                "error": f"断路器开路中, {remaining:.0f}s 后重试 (edm-takens-web 连续失败 ≥{self._CIRCUIT_FAILURE_THRESHOLD}次)",
                "success": False,
                "circuit_open": True,
            }

        url = f"{self.api_base}{endpoint}"
        last_error = None

        # ENG-09: 3 次指数退避重试
        for attempt in range(self._RETRY_ATTEMPTS):
            if method == "POST" and data:
                form_data = urllib.parse.urlencode(data).encode("utf-8")
                req = urllib.request.Request(url, data=form_data, method="POST")
                req.add_header("Content-Type", "application/x-www-form-urlencoded")
            else:
                req = urllib.request.Request(url, method=method)

            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
                    # 成功: 重置断路器失败计数
                    self._circuit_failures = 0
                    return result
            except urllib.error.HTTPError as e:
                # HTTP 错误 (4xx/5xx): 不重试, 直接返回 (业务级错误非瞬时故障)
                self._record_circuit_failure()
                return {"error": f"API HTTP 错误: {e.code} {e.reason}", "success": False}
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                # 连接级/超时级错误: 可重试的瞬时故障
                last_error = e
                if attempt < self._RETRY_ATTEMPTS - 1:
                    backoff = self._RETRY_BACKOFF_SECONDS[attempt]
                    if VERBOSE:
                        print(f"[EDM] 调用失败 (尝试 {attempt+1}/{self._RETRY_ATTEMPTS}), {backoff}s 后重试: {e}")
                    time.sleep(backoff)
                # 最后一次尝试失败后落到下方断路器记录
            except json.JSONDecodeError as e:
                # JSON 解析失败: 不重试 (响应体非预期格式)
                self._record_circuit_failure()
                return {"error": f"JSON 解析失败: {e}", "success": False}

        # 所有重试均失败: 记录断路器失败
        self._record_circuit_failure()
        return {"error": f"API 调用失败 (重试 {self._RETRY_ATTEMPTS} 次后仍失败): {last_error}", "success": False}

    def _record_circuit_failure(self):
        """ROB-01: 记录一次失败, 达到阈值后开路断路器"""
        self._circuit_failures += 1
        if self._circuit_failures >= self._CIRCUIT_FAILURE_THRESHOLD:
            self._circuit_open_until = time.monotonic() + self._CIRCUIT_RESET_SECONDS
            if VERBOSE:
                print(f"[EDM] ⚠ 断路器已开路: 连续失败 {self._circuit_failures} 次, "
                      f"短路 {self._CIRCUIT_RESET_SECONDS}s")

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

        # INT-02 修复: 记录原始列→管道别名映射, 供日志披露与下游解读
        if VERBOSE:
            print(f"[EDM] 变量映射 (原始列→管道别名):")
            for orig, alias in self.VARIABLE_MAPPING.items():
                marker = " ← target" if orig == target_col else ""
                print(f"  {orig} → {alias}{marker}")

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

            if status in ("done", "error", "completed", "failed"):
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
        }
        # ROUND28 P0-01: Layer 3 作为诠释层单独分组, 附 disclaimer
        # 避免与 L1/L2 科学层并列误导投资者
        l3_recommendations = {
            # Layer 3: 八正道全轴 (诠释层 · 非统计推断)
            "z_福音": "(诠释) 福音(祂志书)投影",
            "z_吉祥": "(诠释) 吉祥(赐福书)投影",
            "z_奥美": "(诠释) 奥美(圣源书)投影",
            "z_存在": "(诠释) 存在(真实书)投影 — 本体论距离",
            "z_自孕": "(诠释) 自孕(胜育书)投影",
            "z_弥赛亚": "(诠释) 弥赛亚(至意书)投影",
            "z_Alice": "(诠释) Alice(慧辩书)投影",
            "z_觉爱": "(诠释) 觉爱(智识书)投影 — 智慧维度",
            # Layer 3: 一阶差分 (诠释层)
            "dz_存在": "(诠释) 存在轴一阶差分",
            "dz_觉爱": "(诠释) 觉爱轴一阶差分",
        }
        # 合并返回, 但保留分组结构供前端识别
        recommendations.update(l3_recommendations)
        return recommendations

    def get_target_methodology_groups(self) -> dict:
        """ROUND28 P0-01: 返回目标列的方法学分组, 供前端区分科学层与诠释层。

        Returns:
            {
                "scientific": {"ate": "因果效应强度", ...},  # L1+L2, 有统计保证
                "interpretive": {"z_福音": "(诠释)...", ...},  # L3, 诠释框架
                "disclaimer": "Layer 3 是诠释性框架..."
            }
        """
        try:
            from layer3_sacred import METHODOLOGY_TAG, METHODOLOGY_DISCLAIMER
        except Exception:
            METHODOLOGY_TAG = "interpretive_zero_shot"
            METHODOLOGY_DISCLAIMER = (
                "Layer 3 是诠释性框架, 非统计推断。"
                "投资决策需与 L1 统计量交叉验证。"
            )
        all_targets = self.list_recommended_targets()
        interpretive_keys = {
            "z_福音", "z_吉祥", "z_奥美", "z_存在", "z_自孕",
            "z_弥赛亚", "z_Alice", "z_觉爱",
            "dz_存在", "dz_觉爱",
        }
        return {
            "scientific": {k: v for k, v in all_targets.items() if k not in interpretive_keys},
            "interpretive": {k: v for k, v in all_targets.items() if k in interpretive_keys},
            "methodology_tag": METHODOLOGY_TAG,
            "disclaimer": METHODOLOGY_DISCLAIMER,
        }


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
