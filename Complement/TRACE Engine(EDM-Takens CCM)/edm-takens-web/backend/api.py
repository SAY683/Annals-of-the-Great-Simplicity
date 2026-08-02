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

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

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
# debt-12.13 收窄: allow_headers 从通配符 ["*"] 改为显式白名单，
# 避免非预期自定义头（如 X-Forwarded-For 注入）穿透 CORS 检查。
# debt-12.15 隧道支持: 自动读取 tunnel_url.txt，把 trycloudflare 域名加入白名单
#
# SEC-01 修复: allow_credentials=True 与 allow_origins=["*"] 同时使用是
# 危险的配置错误（浏览器会拒绝，且语义上等价于"任意源可携带凭证访问"）。
# 此处显式列出允许的源，并对环境变量输入做通配符过滤，确保即便运维
# 误配 EDM_CORS_ORIGINS="*"，也不会与 allow_credentials=True 形成危险组合。
def _load_tunnel_origins():
    """从 tunnel_url.txt 读取隧道域名，加入 CORS 白名单。
    隧道模式下前端与 API 同源（都在 https://xxx.trycloudflare.com），
    同源请求不触发 CORS，但显式加入白名单可支持未来跨子域调用。
    """
    try:
        from pathlib import Path
        tunnel_file = Path(__file__).resolve().parent.parent / "tunnel_url.txt"
        if tunnel_file.exists():
            url = tunnel_file.read_text(encoding="utf-8").strip()
            if url and "trycloudflare.com" in url:
                return [url]
    except Exception:
        pass
    return []


def _filter_cors_origins(raw_origins):
    """SEC-01: 过滤掉通配符 origin，防止 allow_credentials=True 与通配符共存。

    浏览器规范禁止 allow_credentials=True 与 allow_origins=["*"] 同时使用，
    且通配符 origin 在凭证模式下语义危险（任意站点可携带 Cookie 访问 API）。
    本函数剔除 "*" 及其它通配模式，仅保留明确的具体源。
    """
    filtered = []
    for origin in raw_origins:
        origin = origin.strip()
        if not origin:
            continue
        # 剔除纯通配符 "*"
        if origin == "*":
            print(f"[CORS] SEC-01: 拒绝通配符 origin '*' (与 allow_credentials=True 不兼容)")
            continue
        # 剔除含通配符的 origin（如 "*.example.com"）
        if "*" in origin:
            print(f"[CORS] SEC-01: 拒绝含通配符的 origin '{origin}'")
            continue
        filtered.append(origin)
    return filtered


# SEC-01: 默认仅允许本地开发源；生产环境通过 EDM_CORS_ORIGINS 显式配置。
# 即便环境变量误配为 "*"，_filter_cors_origins 也会将其剔除。
_EDM_CORS_ORIGINS = _filter_cors_origins(
    os.environ.get(
        "EDM_CORS_ORIGINS",
        "http://localhost:5173,http://localhost:8000,http://127.0.0.1:5173,http://127.0.0.1:8000",
    ).split(",")
    + _load_tunnel_origins()
)
_EDM_ALLOWED_HEADERS = [
    "Content-Type",
    "Authorization",
    "X-Trace-Id",
    "X-Request-Id",
    "Accept",
    "Accept-Language",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_EDM_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=_EDM_ALLOWED_HEADERS,
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
    get_history_detail,
    preview_archive,
)

# ── Static frontend serving (debt-Q9):
#   - 生产环境：优先服务 frontend/dist 构建产物。
#   - 开发环境：若没有 dist，访问根路径自动重定向到 Vite 开发服务器
#     (http://127.0.0.1:5173)，避免用户直接打开 8000 看到未构建的源码。
#   - API 路由已在上方注册并优先匹配；未匹配路径才落到此处。
_FRONTEND_DIR = os.path.join(_BACKEND_DIR, "..", "frontend")
_DIST_DIR = os.path.join(_FRONTEND_DIR, "dist")

if os.path.isdir(_DIST_DIR):
    app.mount("/", StaticFiles(directory=_DIST_DIR, html=True), name="static")
elif os.path.isdir(_FRONTEND_DIR):
    @app.get("/")
    def _redirect_to_vite_dev(request: Request):
        return RedirectResponse("http://127.0.0.1:5173")

    @app.get("/{path:path}")
    def _redirect_spa_paths_to_vite(path: str):
        return RedirectResponse(f"http://127.0.0.1:5173/{path}")

