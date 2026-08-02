"""
Core runtime state — job store singleton (debt-19).

Provides ``create_job_store()`` and the module-level ``_JOB_STORE`` instance
so that both ``routes/analyze.py`` and ``workers/analysis_worker.py`` can
access the shared job store without importing from api.py (which would
create a circular dependency).
"""
import os

from job_store import JobStore, InMemoryJobStore, PersistentJobStore


def create_job_store() -> JobStore:
    """Factory: returns the active JobStore backend.

    Uses ``PersistentJobStore`` backed by SQLite when possible. The database
    path is taken from the ``JOBS_DB`` environment variable, defaulting to
    ``jobs.sqlite`` in the project root. Falls back to ``InMemoryJobStore`` if
    the SQLite store cannot be initialized.
    """
    db_path = os.environ.get("JOBS_DB")
    try:
        return PersistentJobStore(db_path=db_path)
    except Exception as e:
        print(f"[JobStore] Persistent SQLite store unavailable ({e}); "
              "falling back to in-memory store.")
        return InMemoryJobStore(max_history=50)


_JOB_STORE: JobStore = create_job_store()

# P1-2: 启动时自动同步检查（副本一致性）
# 在模块首次导入时检查 backend/edmtakens/ 是否与 edm-takens/src/ 一致。
# 非零退出会终止服务启动（ERROR），但生产环境也可通过
# EDM_SKIP_SYNC_CHECK=1 环境变量绕过（如 CI 已验证一致性）。
def _auto_sync_check():
    import subprocess, sys
    if os.environ.get("EDM_SKIP_SYNC_CHECK") == "1":
        return
    _sync_script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sync_check.py")
    if not os.path.exists(_sync_script):
        return
    try:
        result = subprocess.run(
            [sys.executable, _sync_script, "--quiet"],
            capture_output=True, text=True, timeout=15,
            cwd=os.path.dirname(_sync_script))
        if result.returncode != 0:
            print(f"[CRITICAL] 副本同步检查失败 (exit {result.returncode}):\n{result.stdout}\n{result.stderr}")
            print("[CRITICAL] 请手动运行 python sync_check.py 查看详情。")
            print("[CRITICAL] 若确认无风险，设置环境变量 EDM_SKIP_SYNC_CHECK=1 跳过。")
            # 不主动 exit — 让调用方决定策略；仅打印 CRITICAL 级日志
        else:
            if result.stdout.strip():
                print(f"[sync_check] {result.stdout.strip()}")
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[sync_check] 自动同步检查异常: {e}")

_auto_sync_check()
