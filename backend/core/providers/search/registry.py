"""搜索 provider 注册表：主备选择、失败降级、统一治理与截断。

- `search.provider` 是首选；`fallback_to_tavily` 仅在首选抛 SearchUnavailable 时降级
  （且 Tavily key 可用）。首选返回 0 条默认不降级，避免双倍计费；
  `fallback_on_empty=true` 才降级。
- 日志只记 provider/耗时/条数/降级原因，不记 query 原文与结果正文。
- 不做多级链、不做结果缓存（检索结果缓存已被证伪）。
"""
from __future__ import annotations

import logging
import time

from backend.config import settings
from backend.core.providers.search import governance
from backend.core.providers.search.base import SearchHit, SearchProvider, SearchUnavailable
from backend.core.providers.search.custom import CustomSearch
from backend.core.providers.search.deepseek import DeepSeekSearch
from backend.core.providers.search.tavily import TavilySearch

logger = logging.getLogger(__name__)

PROVIDER_NAMES = ("deepseek", "tavily", "custom")


def get_provider(name: str | None = None) -> SearchProvider:
    selected = (name or str(settings.search.get("provider") or "deepseek")).strip().lower()
    if selected == "deepseek":
        return DeepSeekSearch()
    if selected == "tavily":
        return TavilySearch()
    if selected == "custom":
        return CustomSearch()
    raise SearchUnavailable(f"未知搜索 provider：{selected}", code="bad_config")


def primary_name() -> str:
    return str(settings.search.get("provider") or "deepseek").strip().lower()


def is_available(name: str | None = None) -> bool:
    try:
        return get_provider(name).is_configured()
    except SearchUnavailable:
        return False


def search_available() -> bool:
    """当前配置下是否至少有一条可用的搜索通道（首选或 Tavily 降级）。"""
    if is_available():
        return True
    return bool(settings.search.get("fallback_to_tavily")) and is_available("tavily")


def _truncate(hits: list[SearchHit]) -> list[SearchHit]:
    from dataclasses import replace

    max_chars = int(settings.search.get("content_max_chars") or 1200)
    return [replace(hit, content=hit.content[:max_chars]) for hit in hits]


async def _search_one(provider: SearchProvider, query: str, count: int) -> list[SearchHit]:
    hits = await provider.search(query, count)
    hits = governance.apply(hits)
    return _truncate(hits)


async def search_with_fallback(query: str, count: int | None = None) -> list[SearchHit]:
    """按配置执行一次搜索（含降级与治理）；不可用抛 SearchUnavailable。"""
    cfg = settings.search
    effective_count = int(count or cfg.get("count") or 5)
    provider = get_provider()
    started = time.perf_counter()
    fallback_reason = ""
    try:
        hits = await _search_one(provider, query, effective_count)
    except SearchUnavailable as exc:
        tavily = TavilySearch()
        if (
            provider.name != "tavily"
            and bool(cfg.get("fallback_to_tavily"))
            and tavily.is_configured()
        ):
            logger.warning("search_fallback primary=%s secondary=tavily reason=%s", provider.name, exc)
            try:
                hits = await _search_one(tavily, query, effective_count)
            except SearchUnavailable as exc2:
                raise SearchUnavailable(
                    f"联网检索不可用（{provider.name}：{exc}；tavily：{exc2}）", code="fallback_failed"
                ) from exc2
            fallback_reason = str(exc)
        else:
            raise
    else:
        if (
            not hits
            and provider.name != "tavily"
            and bool(cfg.get("fallback_on_empty"))
            and bool(cfg.get("fallback_to_tavily"))
            and TavilySearch().is_configured()
        ):
            logger.info("search_fallback primary=%s secondary=tavily reason=empty", provider.name)
            hits = await _search_one(TavilySearch(), query, effective_count)
            fallback_reason = "empty"

    logger.info(
        "search_done provider=%s hits=%d ms=%.0f fallback=%s",
        provider.name if not fallback_reason else "tavily",
        len(hits),
        (time.perf_counter() - started) * 1000,
        fallback_reason or "-",
    )
    return hits


async def search_direct(name: str, query: str, count: int = 3) -> list[SearchHit]:
    """指定 provider 直连（superadmin 连通性测试用），不走降级。"""
    return await _search_one(get_provider(name), query, count)
