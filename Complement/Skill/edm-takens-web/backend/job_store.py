"""
Persistent SQLite-backed JobStore for EDM-Takens Web.

Implements the same interface as the in-memory JobStore in backend/api.py:
  create(params: dict) -> Job
  get(job_id: str) -> Optional[Job]
  spawn(job: Job) -> None
  events(job_id: str) -> AsyncIterator[dict]

When ``JOBS_DB`` is set, it is used as the SQLite database path. Otherwise a
``jobs.sqlite`` file in the project root is used.
"""
import abc
import asyncio
import json
import os
import queue
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional


# ═══════════════════════════════════════════════════════════════════════════════
# Abstract + In-memory implementations (mirrors backend/api.py)
# ═══════════════════════════════════════════════════════════════════════════════

class Job:
    """A single asynchronous analysis job."""

    def __init__(self, job_id: str, params: dict):
        self.id = job_id
        self.params = params
        self.status = "pending"
        self.logs: List[str] = []
        # P2-5: 日志总行数。活跃任务中等同于 len(logs)；
        # 从 SQLite 恢复时可能大于 len(logs)（仅持久化了尾部摘要）。
        self.log_count: int = 0
        self.result: Optional[dict] = None
        self.error: Optional[str] = None
        self.created_at = time.time()
        self.updated_at = self.created_at
        self._queue: queue.Queue = queue.Queue()
        self._done = threading.Event()
        self._on_finish: Optional[Any] = None

    def set_on_finish(self, callback):
        self._on_finish = callback

    def append_log(self, line: str):
        self.logs.append(line)
        self.log_count = len(self.logs)
        self._queue.put(("log", line))

    def finish(self, result: Optional[dict] = None, error: Optional[str] = None):
        self.result = result
        self.error = error
        self.status = "error" if error else "done"
        self.updated_at = time.time()
        if result:
            self._queue.put(("result", result))
        if error:
            self._queue.put(("error", {"detail": error}))
        self._queue.put(None)
        self._done.set()
        if self._on_finish:
            try:
                self._on_finish(self)
            except Exception:
                pass

    def to_public_dict(self, limit_logs: int = 200) -> dict:
        return {
            "job_id": self.id,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "logs": self.logs[-limit_logs:],
            "log_count": self.log_count,
            "result": self.result,
            "error": self.error,
        }


class JobStore(abc.ABC):
    """Abstract interface for job lifecycle management."""

    @abc.abstractmethod
    def create(self, params: dict) -> Job:
        """Create and persist a new job, returning its in-memory view."""
        ...

    @abc.abstractmethod
    def get(self, job_id: str) -> Optional[Job]:
        """Retrieve the latest in-memory view of a job."""
        ...

    @abc.abstractmethod
    def spawn(self, job: Job) -> None:
        """Start execution of the job in the background."""
        ...

    @abc.abstractmethod
    async def events(self, job_id: str) -> AsyncIterator[dict]:
        """Yield NDJSON-serializable events for a job."""
        ...


class InMemoryJobStore(JobStore):
    """In-memory JobStore with bounded history and thread-based workers."""

    def __init__(self, max_history: int = 50):
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()
        self._max_history = max_history

    def create(self, params: dict) -> Job:
        job_id = f"job_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        job = Job(job_id, params)
        with self._lock:
            self._jobs[job_id] = job
            if len(self._jobs) > self._max_history:
                ordered = sorted(self._jobs.items(), key=lambda kv: kv[1].created_at)
                for old_id, _ in ordered[: len(self._jobs) - self._max_history]:
                    self._jobs.pop(old_id, None)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def spawn(self, job: Job) -> None:
        # Import here to avoid a circular dependency at module load time.
        from api import _job_worker

        threading.Thread(target=_job_worker, args=(self, job), daemon=True).start()

    async def events(self, job_id: str) -> AsyncIterator[dict]:
        job = self.get(job_id)
        if not job:
            return
        async for event in _stream_from_job(job):
            yield event


async def _stream_from_job(job: Job):
    """Yield NDJSON events from a job's internal queue."""
    import json as _json

    while True:
        try:
            item = await asyncio.to_thread(job._queue.get, timeout=0.2)
        except queue.Empty:
            if job._done.is_set() and job._queue.empty():
                break
            continue
        if item is None:
            break
        typ, payload = item
        yield _json.dumps({"type": typ, "data": payload}, ensure_ascii=False) + "\n"
        if typ in ("result", "error"):
            break


# ═══════════════════════════════════════════════════════════════════════════════
# SQLite-backed persistent implementation
# ═══════════════════════════════════════════════════════════════════════════════

# P2-5: 持久化到 SQLite 的日志尾部行数。
# 完整日志仅保留在内存的 Job 对象中；这里只存最近 N 行作为摘要，
# 避免每次持久化都全量序列化上千行日志。
_PERSISTED_LOG_TAIL = 50


class PersistentJobStore(JobStore):
    """SQLite-backed JobStore with in-memory active-job cache."""

    def __init__(self, db_path: Optional[str] = None, max_history: int = 200):
        if db_path is None:
            project_root = Path(__file__).resolve().parent.parent
            db_path = str(project_root / "jobs.sqlite")
        self._db_path = db_path
        self._max_history = max_history
        self._lock = threading.Lock()
        self._active_jobs: Dict[str, Job] = {}
        self._ensure_schema()

    # NEW-4: 统一的 SQLite 连接工厂。timeout=30 让 SQLite 在遇到 BUSY
    # 锁时内部等待最多 30 秒；若仍超时则进入 _busy_retry 的指数退避重试。
    _BUSY_RETRY_MAX = 5
    _BUSY_RETRY_BASE = 0.1

    def _connect(self) -> sqlite3.Connection:
        """创建带 timeout 和 busy 重试的 SQLite 连接。"""
        last_err = None
        for attempt in range(self._BUSY_RETRY_MAX):
            try:
                return sqlite3.connect(self._db_path, timeout=30)
            except sqlite3.OperationalError as e:
                last_err = e
                time.sleep(self._BUSY_RETRY_BASE * (2 ** attempt))
        raise last_err  # type: ignore[misc]

    def _ensure_schema(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    params TEXT,
                    logs TEXT,
                    result TEXT,
                    error TEXT,
                    created_at REAL,
                    updated_at REAL
                )
                """
            )
            # P2-5: 新增 log_count 列，记录日志总行数；
            # logs 列改为只保留尾部摘要（最后 _PERSISTED_LOG_TAIL 行），
            # 完整日志仅保留在内存的 Job 对象中，避免每次全量 JSON 持久化。
            try:
                conn.execute(
                    "ALTER TABLE jobs ADD COLUMN log_count INTEGER DEFAULT 0"
                )
            except sqlite3.OperationalError:
                pass  # 列已存在（旧库迁移幂等）
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_updated_at ON jobs(updated_at)"
            )
            conn.commit()

    def _insert_job(self, job: Job):
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO jobs
                (job_id, status, params, logs, result, error,
                 created_at, updated_at, log_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.id,
                    job.status,
                    json.dumps(job.params, ensure_ascii=False),
                    # P2-5: 仅持久化日志尾部摘要，完整日志保留在内存。
                    json.dumps(job.logs[-_PERSISTED_LOG_TAIL:], ensure_ascii=False),
                    json.dumps(job.result, ensure_ascii=False) if job.result else None,
                    job.error,
                    job.created_at,
                    job.updated_at,
                    len(job.logs),
                ),
            )
            conn.commit()

    def _persist(self, job: Job):
        self._insert_job(job)
        with self._lock:
            if job.status in ("done", "error"):
                self._active_jobs.pop(job.id, None)

    def _load_job(self, job_id: str) -> Optional[Job]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT status, params, logs, result, error, created_at, "
                "updated_at, log_count FROM jobs WHERE job_id = ?",
                (job_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        # P2-5: log_count 可能为 None（旧库未迁移行）；logs 仅含尾部摘要。
        (status, params_json, logs_json, result_json, error,
         created_at, updated_at, log_count) = row
        job = Job(job_id, json.loads(params_json or "{}"))
        job.status = status
        # 仅恢复持久化的尾部摘要；完整日志只在内存的活跃 Job 中可用。
        job.logs = json.loads(logs_json or "[]")
        # 记录日志总行数，便于 UI 提示“仅显示最近 N / 共 M 行”。
        job.log_count = log_count if log_count is not None else len(job.logs)
        job.result = json.loads(result_json or "null")
        if job.result is None:
            job.result = None
        job.error = error
        job.created_at = created_at
        job.updated_at = updated_at
        # Completed jobs have no live queue; mark done so event loops exit cleanly.
        if status in ("done", "error"):
            job._done.set()
        return job

    def create(self, params: dict) -> Job:
        job_id = f"job_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        job = Job(job_id, params)
        job.set_on_finish(self._persist)
        self._insert_job(job)
        with self._lock:
            self._active_jobs[job_id] = job
            # Prune oldest completed jobs if we exceed max_history.
            completed = sorted(
                [
                    (jid, j)
                    for jid, j in self._active_jobs.items()
                    if j.status in ("done", "error")
                ],
                key=lambda kv: kv[1].updated_at,
            )
            if len(self._active_jobs) > self._max_history:
                for jid, _ in completed[: len(self._active_jobs) - self._max_history]:
                    self._active_jobs.pop(jid, None)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            job = self._active_jobs.get(job_id)
        if job is not None:
            return job
        return self._load_job(job_id)

    def spawn(self, job: Job) -> None:
        from api import _job_worker

        def _worker_wrapper(store, j):
            try:
                _job_worker(store, j)
            finally:
                self._persist(j)

        threading.Thread(target=_worker_wrapper, args=(self, job), daemon=True).start()

    async def events(self, job_id: str) -> AsyncIterator[dict]:
        job = self.get(job_id)
        if not job:
            return
        async for event in _stream_from_job(job):
            yield event
