"""系统级路由：健康检查（无鉴权，供前端「测试连接」与 CORS/混合内容实测）。"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

from backend.config import APP_TITLE, APP_VERSION, settings
from backend.core.providers.asr import is_available as asr_is_available, provider_name as asr_provider_name
from backend.core.providers.search import primary_name, search_available

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
            # 兼容旧前端字段：当前配置下是否存在可用搜索通道（首选或 Tavily 降级）
            "web_search": search_available(),
            "search_provider": primary_name(),
            "asr_configured": asr_is_available(),
            "asr_provider": asr_provider_name(),
        },
    }
