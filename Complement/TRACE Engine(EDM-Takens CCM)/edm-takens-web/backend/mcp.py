"""
edm-takens-web MCP 适配模块
============================
为 edm-takens-web 补齐 MCP (Model Context Protocol) 协议端点。
端点: POST /mcp  (JSON-RPC 2.0)

工具映射:
  list_datasets     → GET  /api/datasets
  run_analysis      → POST /api/analyze
  get_job           → GET  /api/analyze/jobs/{job_id}
  list_history      → GET  /api/history
  get_history_detail→ GET  /api/history/{task_id}
  health            → GET  /api/health

设计原则:
  1. 不侵入现有路由代码 — MCP 模块完全独立，可插拔
  2. 复用现有路由逻辑 — 通过 localhost urllib 调用，继承校验/鉴权
  3. 无新依赖 — 仅用 Python 标准库 urllib

P1 修缮（2026-08-03）: MCP 端点鉴权落地
  病灶: 原版 @router.post("/mcp") 未声明 dependencies=[Depends(require_auth)],
        导致 MCP 端点完全绕过 core/auth.py 的鉴权链。
        - 本地模式: 远程客户端可直接 POST /mcp 触发分析耗尽资源
        - 生产模式: 即使设置了 EDM_API_KEY, MCP 仍可匿名调用
  修复:
    1. POST /mcp 与 GET /mcp 均添加 Depends(require_auth)
    2. 内部 _local_fetch 透传 X-API-Key 头, 确保生产模式下 /api/* 调用通过鉴权
    3. 与 trace-engine-web/middleware/auth.js 和 trace-to-edm/server.js 的 MCP 鉴权对齐
"""

import json
import urllib.request

from fastapi import APIRouter, Depends, Request, Response

from core.auth import require_auth

# ── 工具定义 ──────────────────────────────────────────────
TOOLS = [
    {
        "name": "list_datasets",
        "description": "列出已上传的 CSV 数据集文件名列表。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "run_analysis",
        "description": "运行 EDM-Takens 分析（从拓扑重建动力学）。需要先选择数据集和目标列。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dataset": {"type": "string", "description": "数据集文件名（如 game_log.csv）"},
                "target_col": {"type": "string", "description": "目标列名"},
                "variables": {"type": "string", "description": "分析变量（逗号分隔，留空自动选前6个）"},
                "q": {"type": "integer", "description": "嵌入维度（留空自动检测，范围2-64）"},
                "profile": {"type": "string", "enum": ["auto", "light", "medium", "heavy"], "default": "auto"},
            },
            "required": ["dataset", "target_col"],
        },
    },
    {
        "name": "get_job",
        "description": "查询 EDM 分析任务的状态和结果。",
        "inputSchema": {
            "type": "object",
            "properties": {"job_id": {"type": "string", "description": "任务 ID"}},
            "required": ["job_id"],
        },
    },
    {
        "name": "list_history",
        "description": "列出历史分析记录。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_history_detail",
        "description": "获取历史任务的详情（含结果摘要）。",
        "inputSchema": {
            "type": "object",
            "properties": {"task_id": {"type": "string", "description": "历史任务 ID"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "health",
        "description": "检查 EDM-Takens 服务健康状态。",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

# ── 内部 HTTP 调用 ────────────────────────────────────────
def _local_fetch(port: int, method: str, path: str, body: dict = None,
                 fwd_headers: dict = None):
    """通过 localhost urllib 调用现有 API（无新依赖）。

    P1 修缮（2026-08-03）: 新增 fwd_headers 参数, 透传鉴权头 (X-API-Key)。
    生产模式下 EDM_API_KEY 已设置, /api/* 端点会校验 X-API-Key,
    若不透传则 MCP → /api/* 的内部调用会被 401 拒绝。
    """
    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(body).encode("utf-8") if body else None
    headers = {"Content-Type": "application/json"} if body else {}
    # P1 修缮: 透传鉴权头到内部 localhost 调用
    if fwd_headers:
        for k, v in fwd_headers.items():
            headers[k] = v
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(raw), raw
            except json.JSONDecodeError:
                return resp.status, None, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8") if e.fp else ""
        try:
            return e.code, json.loads(raw), raw
        except json.JSONDecodeError:
            return e.code, None, raw


# ── 工具调用分发 ──────────────────────────────────────────
async def call_tool(name: str, args: dict, port: int, fwd_headers: dict = None):
    a = args or {}
    if name == "list_datasets":
        return await _fetch_async(port, "GET", "/api/datasets", fwd_headers=fwd_headers)
    elif name == "run_analysis":
        body = {
            "dataset": a.get("dataset"),
            "target_col": a.get("target_col"),
            "profile": a.get("profile", "auto"),
        }
        if a.get("variables"):
            body["variables"] = a["variables"]
        if a.get("q"):
            body["q"] = a["q"]
        return await _fetch_async(port, "POST", "/api/analyze", body, fwd_headers=fwd_headers)
    elif name == "get_job":
        return await _fetch_async(port, "GET", f"/api/analyze/jobs/{a['job_id']}", fwd_headers=fwd_headers)
    elif name == "list_history":
        return await _fetch_async(port, "GET", "/api/history", fwd_headers=fwd_headers)
    elif name == "get_history_detail":
        return await _fetch_async(port, "GET", f"/api/history/{a['task_id']}", fwd_headers=fwd_headers)
    elif name == "health":
        return await _fetch_async(port, "GET", "/api/health", fwd_headers=fwd_headers)
    else:
        raise ValueError(f"Unknown tool: {name}")


async def _fetch_async(port, method, path, body=None, fwd_headers=None):
    """异步包装（用 anyio.to_thread.run_sync 在 FastAPI 中不阻塞事件循环）"""
    import anyio
    return await anyio.to_thread.run_sync(_local_fetch, port, method, path, body, fwd_headers)


# ── MCP 路由 ─────────────────────────────────────────────
def create_mcp_router(port: int) -> APIRouter:
    router = APIRouter()

    # P1 修缮（2026-08-03）: POST /mcp 添加 Depends(require_auth) 鉴权。
    # 原版无 dependencies 声明, 导致 MCP 端点完全绕过 core/auth.py 鉴权链。
    @router.post("/mcp", dependencies=[Depends(require_auth)])
    async def mcp_endpoint(request: Request):
        body = await request.json()
        jsonrpc = body.get("jsonrpc")
        method = body.get("method")
        params = body.get("params")
        req_id = body.get("id")

        # P1 修缮: 提取鉴权头, 透传给内部 localhost 调用。
        # 生产模式 (EDM_API_KEY 已设置) 下 /api/* 端点会校验 X-API-Key,
        # 若不透传则 MCP → /api/* 内部调用会被 401 拒绝。
        fwd_headers = {}
        for h in ("x-api-key", "authorization"):
            v = request.headers.get(h)
            if v:
                fwd_headers[h] = v

        # JSON-RPC 2.0 协议校验
        if jsonrpc != "2.0":
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32600, "message": 'Invalid Request: jsonrpc must be "2.0"'}}

        # initialize
        if method == "initialize":
            return {
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "edm-takens-web-mcp", "version": "0.1.0"},
                },
            }

        # tools/list
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}

        # tools/call
        if method == "tools/call":
            name = (params or {}).get("name")
            args = (params or {}).get("arguments", {})
            if not name:
                return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": "params.name is required"}}
            try:
                status, j, text = await call_tool(name, args, port, fwd_headers=fwd_headers)
                content = json.dumps(j, ensure_ascii=False, indent=2) if j is not None else text
                return {
                    "jsonrpc": "2.0", "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": content}],
                        "isError": status >= 400,
                    },
                }
            except Exception as e:
                return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32603, "message": f"Tool execution failed: {e}"}}

        # 未知方法
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}

    # P1 修缮（2026-08-03）: GET /mcp 同样添加鉴权。
    # 该端点返回服务信息和工具列表, 未鉴权会泄露内部能力清单给匿名探测者。
    @router.get("/mcp", dependencies=[Depends(require_auth)])
    async def mcp_info():
        return {
            "service": "edm-takens-web-mcp",
            "version": "0.1.0",
            "protocolVersion": "2024-11-05",
            "endpoint": "POST /mcp",
            "methods": ["initialize", "tools/list", "tools/call"],
            "toolCount": len(TOOLS),
            "tools": [t["name"] for t in TOOLS],
        }

    return router
