"""系统级路由：健康检查（无鉴权，供 Pages 前端「测试连接」与 CORS/混合内容实测）。"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

from backend.config import APP_TITLE, APP_VERSION, settings

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "app": APP_TITLE,
        "version": APP_VERSION,
        "time": datetime.now().isoformat(timespec="seconds"),
        # 前端据此显示供应商就绪状态（key 只在服务端，不回传）
        "providers": {
            "main_model": settings.deepseek.get("main_model", ""),
            "web_search": bool(settings.tavily.get("api_key")),
        },
    }
