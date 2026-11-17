"""Tavily 联网检索适配器（v2.1.0 保留为可切换 provider 与可选降级通道）。

域名治理统一由 governance 处理；这里只负责请求与字段映射。
"""
from __future__ import annotations

import httpx

from backend.config import settings
from backend.core.providers.search.base import SearchHit, SearchUnavailable, sanitize_text, valid_http_url

TAVILY_ENDPOINT = "https://api.tavily.com/search"


class TavilySearch:
    name = "tavily"

    def _cfg(self) -> dict:
        cfg = settings.search.get("tavily")
        return cfg if isinstance(cfg, dict) else {}

    def api_key(self) -> str:
        return str(self._cfg().get("api_key") or "").strip()

    def is_configured(self) -> bool:
        return bool(self.api_key())

    async def search(self, query: str, count: int) -> list[SearchHit]:
        if not self.is_configured():
            raise SearchUnavailable("Tavily api_key 未配置", code="not_configured")
        cfg = self._cfg()
        max_results = int(cfg.get("max_results") or count or 5)
        body = {
            "api_key": self.api_key(),
            "query": query[:400],
            "max_results": max(1, min(int(count or 5), max_results, 10)),
            "search_depth": str(cfg.get("search_depth") or "basic"),
        }
        timeout = float(cfg.get("timeout") or 20)
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                resp = await client.post(TAVILY_ENDPOINT, json=body)
        except httpx.TimeoutException as exc:
            raise SearchUnavailable("Tavily 检索连接超时", code="timeout") from exc
        except httpx.HTTPError as exc:
            raise SearchUnavailable(f"联网检索连接失败：{exc}", code="network") from exc

        if resp.status_code in (401, 403, 429, 432, 451):
            raise SearchUnavailable(
                f"Tavily 不可用（HTTP {resp.status_code}，key 失效或额度尽）", code="auth"
            )
        if resp.status_code >= 500:
            raise SearchUnavailable(f"Tavily 服务异常（HTTP {resp.status_code}）", code="server")
        if resp.status_code >= 400:
            raise SearchUnavailable(f"Tavily 请求失败（HTTP {resp.status_code}）", code="bad_request")
        try:
            data = resp.json()
        except ValueError as exc:
            raise SearchUnavailable("Tavily 响应不是合法 JSON", code="protocol") from exc

        hits: list[SearchHit] = []
        for item in data.get("results") or []:
            if not isinstance(item, dict):
                continue
            url = valid_http_url(item.get("url"))
            if not url:
                continue
            content = sanitize_text(item.get("content"))
            try:
                score = float(item.get("score") or 0.0)
            except (TypeError, ValueError):
                score = 0.0
            hits.append(
                SearchHit(
                    title=sanitize_text(item.get("title"), limit=300),
                    url=url,
                    snippet=content[:600],
                    content=content,
                    score=score,
                    authority=None,
                    date=str(item["published_date"])[:40] if item.get("published_date") else None,
                    provider=self.name,
                )
            )
        return hits
