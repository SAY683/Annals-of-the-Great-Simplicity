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
import logging
import os
import sys
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

# ── P3 修复 (Round 29 §11.4): 日志可追踪 (维度5) ────────
# edm-takens-web 原全仓零日志, 故障排查几乎不可能.
# 本模块配置结构化 logger, trace_id 通过 BaseHTTPMiddleware 注入.
_LOG_FORMAT = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
logging.basicConfig(
    level=os.environ.get("EDM_LOG_LEVEL", "INFO"),
    format=_LOG_FORMAT,
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("edm_takens_web")

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


# ── P3 修复 (Round 29 §11.4): trace_id + 缓存控制 (维度5 + 维度6) ──
# 维度5 (日志可追踪): trace_id 贯穿请求全生命周期, 通过 X-Trace-Id 头传入或生成.
# 维度6 (缓存策略): /api/ GET 端点 no-cache, 静态资源短 TTL.
# 两项债务在同一中间件内修复, 避免多重中间件开销.
from starlette.middleware.base import BaseHTTPMiddleware


class TraceIdAndCacheMiddleware(BaseHTTPMiddleware):
    """注入 trace_id 到 request.state 并设置 Cache-Control 响应头.

    - trace_id 来源: 客户端 X-Trace-Id 头 > X-Request-Id 头 > 服务端生成 UUID4
    - Cache-Control:
        * /api/ 路径 GET 请求: no-store (防止敏感数据/实时数据被缓存)
        * /api/analyze/jobs/{id}/stream: no-store (SSE 流不可缓存)
        * 静态资源 (?v=xxx): public, max-age=300 (5分钟, 配合缓存戳失效)
        * 其他: no-cache (默认保守)
    """

    async def dispatch(self, request: Request, call_next):
        # --- trace_id 注入 ---
        trace_id = (
            request.headers.get("x-trace-id")
            or request.headers.get("x-request-id")
            or f"edm-{uuid.uuid4().hex[:16]}"
        )
        request.state.trace_id = trace_id

        # --- 请求日志 ---
        start_ts = datetime.now(timezone.utc)
        client_ip = request.client.host if request.client else "unknown"
        logger.info(
            f"[{trace_id}] -> {request.method} {request.url.path} "
            f"from={client_ip} ua={request.headers.get('user-agent', '-')[:60]}"
        )

        # --- 调用下游 ---
        try:
            response = await call_next(request)
        except Exception as e:
            duration_ms = (datetime.now(timezone.utc) - start_ts).total_seconds() * 1000
            logger.error(
                f"[{trace_id}] !! {request.method} {request.url.path} "
                f"duration={duration_ms:.1f}ms error={type(e).__name__}: {e}"
            )
            raise

        # --- 响应日志 ---
        duration_ms = (datetime.now(timezone.utc) - start_ts).total_seconds() * 1000
        logger.info(
            f"[{trace_id}] <- {response.status_code} "
            f"duration={duration_ms:.1f}ms"
        )

        # --- Cache-Control 设置 ---
        path = request.url.path
        method = request.method

        if method == "GET" and path.startswith("/api/"):
            # API GET 端点: 严格不缓存 (数据实时性 + 鉴权敏感)
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        elif "/stream" in path:
            # SSE 流: 不可缓存
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["X-Accel-Buffering"] = "no"
        elif "v=" in request.url.query:
            # 静态资源带缓存戳: 允许中间缓存 5 分钟
            response.headers["Cache-Control"] = "public, max-age=300"
        else:
            # 其他: 默认保守
            response.headers["Cache-Control"] = "no-cache"

        # --- 透传 trace_id 到响应头 (便于客户端排查) ---
        response.headers["X-Trace-Id"] = trace_id

        return response


app.add_middleware(TraceIdAndCacheMiddleware)

# ── Mount routers (debt-19) ──────────────────────────────
from routes.datasets import router as _datasets_router
from routes.analyze import router as _analyze_router
from routes.history import router as _history_router

app.include_router(_datasets_router)
app.include_router(_analyze_router)
app.include_router(_history_router)

# ROUND29 MCP: 补齐 MCP 协议端点 (JSON-RPC 2.0 over HTTP)
from mcp import create_mcp_router
app.include_router(create_mcp_router(8000))

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

