"""应用工厂：单体应用（学 AstrBot）——一个 FastAPI 进程同时提供 /api/* 与前端静态页。"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.api import admin_diagnosis as admin_diagnosis_api
from backend.api import asr as asr_api
from backend.api import auth as auth_api
from backend.api import cases as cases_api
from backend.api import dtc as dtc_api
from backend.api import chat as chat_api
from backend.api import kb as kb_api
from backend.api import appointments as appointments_api
from backend.api import stats as stats_api
from backend.api import admin_users as admin_users_api
from backend.api import superadmin as superadmin_api
from backend.api import system as system_api
from backend.api import vehicles as vehicles_api
from backend.config import APP_TITLE, APP_VERSION, FRONTEND_DIST, settings
from backend.db.base import init_db
from backend.seed.seed import ensure_seed


def _mount_frontend(app: FastAPI) -> None:
    """托管前端构建产物 frontend/dist；dist 不存在时仅提供 API 并提示。"""
    index_html = FRONTEND_DIST / "index.html"
    if not index_html.exists():
        print(f"[startup] 未找到前端构建产物 {FRONTEND_DIST}，当前仅提供 API；"
              f"请先在 frontend/ 目录执行 npm install && npm run build")
        return

    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="接口不存在")
        candidate = (FRONTEND_DIST / full_path).resolve()
        # 防 目录穿越：只允许 dist 内的真实文件，其余回退 index.html（history 路由）
        if full_path and candidate.is_file() and candidate.is_relative_to(FRONTEND_DIST):
            return FileResponse(candidate)
        # index.html 不缓存：assets 文件名带 hash，html 必须每次重拉才能拿到新版本
        return FileResponse(index_html, headers={"Cache-Control": "no-cache"})


def create_app() -> FastAPI:
    app = FastAPI(title=APP_TITLE, version=APP_VERSION)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        """安全响应头 + CSP（D24）：SPA 只加载同源脚本，样式允许 Element Plus 内联。"""
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "microphone=(self), camera=(), geolocation=()"
        )
        # Swagger/ReDoc 依赖 CDN 脚本与内联引导，CSP 会使其不可用；文档页单独豁免
        if not (
            request.url.path.startswith("/docs")
            or request.url.path.startswith("/redoc")
            or request.url.path == "/openapi.json"
        ):
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: blob:; "
                "font-src 'self' data:; "
                "media-src 'self' blob:; "
                # 跨源 API base（superadmin 本机设置/HTTPS 部署）需放行；本地调试仅放回环
                "connect-src 'self' https: http://localhost:* http://127.0.0.1:*; "
                "worker-src 'self' blob:; "
                "manifest-src 'self'; "
                "object-src 'none'; "
                "base-uri 'self'; "
                "form-action 'self'; "
                "frame-ancestors 'none'",
            )
        is_https = request.url.scheme == "https" or request.headers.get(
            "x-forwarded-proto", ""
        ).lower() == "https"
        if is_https:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

    init_db()
    ensure_seed()

    app.include_router(system_api.router)
    app.include_router(auth_api.router)
    app.include_router(asr_api.router)
    app.include_router(dtc_api.router)
    app.include_router(admin_diagnosis_api.router)
    app.include_router(kb_api.router)
    app.include_router(chat_api.router)
    app.include_router(cases_api.router)
    app.include_router(appointments_api.router)
    app.include_router(vehicles_api.router)
    app.include_router(admin_users_api.router)
    app.include_router(superadmin_api.router)
    app.include_router(stats_api.router)
    _mount_frontend(app)
    return app
