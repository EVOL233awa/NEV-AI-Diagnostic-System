"""搜索 provider 包：统一结果结构与注册入口。"""
from backend.core.providers.search.base import SearchHit, SearchProvider, SearchUnavailable, sanitize_text, valid_http_url
from backend.core.providers.search.registry import (
    PROVIDER_NAMES,
    get_provider,
    is_available,
    primary_name,
    search_available,
    search_direct,
    search_with_fallback,
)

__all__ = [
    "PROVIDER_NAMES",
    "SearchHit",
    "SearchProvider",
    "SearchUnavailable",
    "get_provider",
    "is_available",
    "primary_name",
    "sanitize_text",
    "search_available",
    "search_direct",
    "search_with_fallback",
    "valid_http_url",
]
