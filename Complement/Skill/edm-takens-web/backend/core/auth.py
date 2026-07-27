"""
鉴权依赖 (D-P0-4 修复, Round 21 §P0-A)
=====================================
edm-takens-web 原全端点零鉴权, 任意网络可达客户端可触发分析/删除/归档操作.
本模块提供 FastAPI Depends 链, 通过环境变量 EDM_API_KEY 控制:

  - EDM_API_KEY 未设置 (本地开发默认): 仅允许 127.0.0.1 / localhost / ::1
  - EDM_API_KEY 设置 (生产/隧道): 客户端必须提供 X-API-Key 头匹配

使用方式:
    from core.auth import require_auth
    @router.post("/api/...", dependencies=[Depends(require_auth)])
    def handler(...): ...

    # 或在路由函数签名中:
    def handler(_: None = Depends(require_auth)): ...

设计权衡:
  - 不强制全局 middleware, 让每个端点显式声明鉴权依赖 (审计可见)
  - 本地模式自动放行, 避免 dev 体验退化
  - 生产模式返回 401 + 错误码, 不暴露内部细节
"""
import os
import hmac
from typing import Optional

from fastapi import Header, HTTPException, Request


_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _client_ip(request: Request) -> str:
    """获取客户端 IP. 优先取 X-Forwarded-For 首段 (反代场景), 否则取 client.host."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def require_auth(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> None:
    """FastAPI 依赖: 校验客户端访问权限.

    - 无 EDM_API_KEY: 仅允许本地环回地址
    - 有 EDM_API_KEY: 客户端必须提供匹配的 X-API-Key 头
      (本地环回也需要提供, 防止隧道穿透后的本机滥用)

    失败时抛 401, 错误码 UNAUTHORIZED, 不返回内部细节.
    """
    api_key = os.environ.get("EDM_API_KEY")

    if not api_key:
        # 本地开发模式: 仅允许环回地址
        ip = _client_ip(request)
        if ip not in _LOCAL_HOSTS:
            raise HTTPException(
                status_code=401,
                detail={
                    "error": "UNAUTHORIZED",
                    "message": "Remote access requires EDM_API_KEY environment variable.",
                },
            )
        return

    # 生产模式: 必须提供 X-API-Key 且匹配
    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "UNAUTHORIZED",
                "message": "Missing X-API-Key header.",
            },
        )
    # 用 hmac.compare_digest 防止时序攻击
    if not hmac.compare_digest(str(x_api_key), api_key):
        raise HTTPException(
            status_code=401,
            detail={
                "error": "UNAUTHORIZED",
                "message": "Invalid API key.",
            },
        )


def require_auth_optional(
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> None:
    """弱鉴权: 用于只读端点 (GET /api/health, GET /api/datasets 等).

    与 require_auth 相同逻辑, 但命名上让审计清晰区分读/写鉴权.
    """
    return require_auth(request, x_api_key)
