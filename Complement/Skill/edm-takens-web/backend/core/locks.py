"""
Core runtime locks and directory constants (debt-19).

Extracted from api.py module-level state. All concurrency primitives and
filesystem paths live here so that routes/, services/, and workers/ can
import them without circular dependencies on api.py.
"""
import os
import threading

# ── Path setup ────────────────────────────────────────────
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
DATA_DIR = os.path.join(_PROJECT_ROOT, "data")
RESULTS_DIR = os.path.join(_PROJECT_ROOT, "results")
ARCHIVE_DIR = os.path.join(_PROJECT_ROOT, "archive")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)
os.makedirs(ARCHIVE_DIR, exist_ok=True)

# ── Concurrency primitives ───────────────────────────────
# 元审计 P1 修缮 (2026-07-20): 并发度名实相符
# 之前 _ANALYSIS_LOCK=Semaphore(2) 但 _STDOUT_LOCK=Lock() 同时持有，
# 实际并发降为 1，造成"名实不符"——配置说 2 实际是 1。
# 现统一为 Semaphore(1) 并明确注释：redirect_stdout 是进程级全局替换，
# 不可并行；如需真并发，需重构为 per-job StringIO（不在本次修缮范围）。
_ANALYSIS_LOCK = threading.Semaphore(1)

# NEW-3: 串行化结果文件迁移操作。两个并发任务共享同一 cwd 和同一
# results/ 目录，_move_results_to_task 若并行执行可能把 Job A 的文件
# 移到 Job B 的目录。此锁确保"快照 + 迁移"作为临界区原子执行。
_MOVE_LOCK = threading.Lock()

# P0 修复：串行化 redirect_stdout / redirect_stderr 临界区。
# redirect_stdout 是进程级全局替换——若两个 _job_worker 线程同时进入
# redirect_stdout(stream) 块，后进入者的 stream 会覆盖前者，导致两个
# 并发 job 的 stdout 互相串台、日志归属错乱。
# 此锁确保同一时刻只有一个 worker 持有 stdout/stderr 重定向上下文。
# 元审计 P1: 与 _ANALYSIS_LOCK=Semaphore(1) 配合，名实相符。
_STDOUT_LOCK = threading.Lock()

# P1 修复：阻塞端点 /api/analyze 专用并发限流。
# 该端点会一直持有 HTTP 连接直到 job 完成（job._done.wait()），
# 若不限流，过多并发阻塞请求会耗尽 FastAPI 同步线程池。
# 容量设为 1：与 _ANALYSIS_LOCK=Semaphore(1) 一致，
# 超出的请求立即返回 429，避免无谓挂起。
# 独立于 _ANALYSIS_LOCK——后者是 worker 内部锁，若复用会造成双重 acquire 死锁。
_BLOCKING_ENDPOINT_SLOT = threading.Semaphore(1)
