"""
EDM-Takens Web Backend — FastAPI application (debt-19 拆分后的入口).

api.py 现在只负责:
  1. sys.path 设置
  2. FastAPI app 创建 + CORS 中间件
  3. 路由挂载（通过 APIRouter include）
  4. 向后兼容的重新导出（extract+re-export 策略）

所有业务逻辑已提取到:
  - core/       : 锁、目录常量、job store 单例
  - services/   : 文件管理、变量选择、摘要构建
  - workers/    : 后台分析 worker
  - routes/     : APIRouter 路由模块（datasets / analyze / history）
"""
import os
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ── sys.path 设置 ─────────────────────────────────────────
# debt-17: 推荐通过 `pip install -e .`（edm-takens/pyproject.toml）
# 安装可编辑包，使模块在全局可导入。此处 sys.path.append 仅作为
# 未安装时的回退机制——使用 append 而非 insert(0) 确保已安装的
# 可编辑包具有更高导入优先级，副本目录不覆盖全局安装。
# Make the bundled edmtakens package importable.
# We append the edmtakens directory itself so the copied src modules can keep
# their sibling-style imports (e.g. `from _paths import data_path`).
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(_BACKEND_DIR, "edmtakens"))

import _paths
from pipeline import PipelineConfig, run_full_analysis
from analysis_profiles import recommend_profile
from data_quality import evaluate_dataframe
from _usability import is_usable_for_edm  # debt-22: 共享可用性检查

# Job lifecycle: in-memory fallback or SQLite-backed persistent store.
# debt-17: 同样使用 append 而非 insert(0)，保持与 editable install 优先级一致。
sys.path.append(_BACKEND_DIR)
from job_store import Job, JobStore, InMemoryJobStore, PersistentJobStore

# debt-22: os.chdir(_PROJECT_ROOT) 已移至 run_backend.py 入口点，
# 避免库模块（api.py）在导入时产生进程级副作用。run_backend.py 在
# 启动 uvicorn 前统一切换 cwd，确保 pipeline 内部硬编码的相对路径
# results/ 能正确解析。若直接通过 `uvicorn api:app` 启动（绕过
# run_backend.py），调用方需自行确保 cwd 为项目根目录。

# ── Core: locks, directories, job store ──────────────────
from core.locks import (
    _ANALYSIS_LOCK,
    _MOVE_LOCK,
    _STDOUT_LOCK,
    _BLOCKING_ENDPOINT_SLOT,
    DATA_DIR,
    RESULTS_DIR,
    ARCHIVE_DIR,
    _PROJECT_ROOT,
)
from core.runtime import create_job_store, _JOB_STORE

# ── Services: file management + summary builder ──────────
from services.file_management import (
    _list_uploaded_csvs,
    _ID_LIKE,
    _is_id_like,
    _recommend_target,
    _read_csv_robust,
    _prepare_dataset,
    _select_variables,
    _check_target_quality,
    _prepare_pipeline_data,
    _make_config,
    _resolve_analysis_params,
    _collect_images,
    _safe_task_path,
    _zip_task,
    _sanitize_project_name,
    _move_results_to_task,
    _total_size_mb,
    _MAX_UPLOAD_BYTES,
    _SNIFF_BYTES,
)
from services.summary_builder import _build_summary, _task_summary

# debt-22: 保留别名以兼容现有调用点
_is_usable_for_edm = is_usable_for_edm

# ── Workers: analysis job execution ──────────────────────
from workers.analysis_worker import _JobStream, _job_worker, _stream_from_job

# ── App creation + CORS ─────────────────────────────────
app = FastAPI(title="EDM-Takens Web", version="0.1.0")

# P2 修复: CORS 生产环境收窄，通过 EDM_CORS_ORIGINS 环境变量配置
_EDM_CORS_ORIGINS = os.environ.get("EDM_CORS_ORIGINS", "http://localhost:5173,http://localhost:8000,http://127.0.0.1:5173,http://127.0.0.1:8000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_EDM_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# ── Mount routers (debt-19) ──────────────────────────────
from routes.datasets import router as _datasets_router
from routes.analyze import router as _analyze_router
from routes.history import router as _history_router

app.include_router(_datasets_router)
app.include_router(_analyze_router)
app.include_router(_history_router)

# ── Re-export route handlers for backward compatibility ──
from routes.datasets import (
    health,
    list_datasets,
    upload_file,
    get_columns,
    recommend_analysis,
    data_quality,
    embed_curve,
)
from routes.analyze import (
    create_analysis_job,
    get_job_status,
    stream_job,
    analyze,
    analyze_stream,
    get_image,
)
from routes.history import (
    list_history,
    archive_task,
    download_task,
    delete_task,
    cleanup_history,
    list_archives,
    restore_archive,
    delete_archive,
    batch_history,
    compare_tasks,
    export_task_json,
    export_task_csv,
)
