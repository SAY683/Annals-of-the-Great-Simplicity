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
