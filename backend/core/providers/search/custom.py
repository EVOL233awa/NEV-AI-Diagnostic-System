"""自定义搜索接口适配器（契约见 docs/技术架构设计.md）。

POST {base_url}
请求：{"query": "...", "count": 5}
响应：{"results": [{"title", "url", "snippet", "content", "score", "authority", "date"}]}
缺失字段按空处理；该适配位用于接入第三家供应商，不新增内置实现。
"""
from __future__ import annotations

import httpx

from backend.config import settings
from backend.core.providers.search.base import SearchHit, SearchUnavailable, sanitize_text, valid_http_url


class CustomSearch:
    name = "custom"

    def _cfg(self) -> dict:
        cfg = settings.search.get("custom")
        return cfg if isinstance(cfg, dict) else {}

    def _base_url(self) -> str:
        return str(self._cfg().get("base_url") or "").strip()

    def api_key(self) -> str:
        return str(self._cfg().get("api_key") or "").strip()

    def is_configured(self) -> bool:
        return bool(self._base_url())

    async def search(self, query: str, count: int) -> list[SearchHit]:
        if not self.is_configured():
            raise SearchUnavailable("自定义搜索 base_url 未配置", code="not_configured")
        cfg = self._cfg()
        headers = {"Content-Type": "application/json"}
        if self.api_key():
            headers["Authorization"] = f"Bearer {self.api_key()}"
        timeout = float(cfg.get("timeout") or 20)
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                resp = await client.post(
                    self._base_url(), json={"query": query[:400], "count": int(count or 5)}, headers=headers
                )
        except httpx.TimeoutException as exc:
            raise SearchUnavailable("自定义搜索连接超时", code="timeout") from exc
        except httpx.HTTPError as exc:
            raise SearchUnavailable(f"自定义搜索连接失败：{exc}", code="network") from exc

        if resp.status_code in (401, 403, 429):
            raise SearchUnavailable(f"自定义搜索不可用（HTTP {resp.status_code}）", code="auth")
        if resp.status_code >= 500:
            raise SearchUnavailable(f"自定义搜索服务异常（HTTP {resp.status_code}）", code="server")
        if resp.status_code >= 400:
            raise SearchUnavailable(f"自定义搜索请求失败（HTTP {resp.status_code}）", code="bad_request")
        try:
            data = resp.json()
        except ValueError as exc:
            raise SearchUnavailable("自定义搜索响应不是合法 JSON", code="protocol") from exc

        hits: list[SearchHit] = []
        for item in data.get("results") or []:
            if not isinstance(item, dict):
                continue
            url = valid_http_url(item.get("url"))
            if not url:
                continue
            snippet = sanitize_text(item.get("snippet"), limit=600)
            content = sanitize_text(item.get("content")) or snippet
            try:
                score = float(item.get("score") or 0.0)
            except (TypeError, ValueError):
                score = 0.0
            authority_raw = item.get("authority")
            try:
                authority = int(authority_raw) if authority_raw is not None else None
            except (TypeError, ValueError):
                authority = None
            hits.append(
                SearchHit(
                    title=sanitize_text(item.get("title"), limit=300),
                    url=url,
                    snippet=snippet,
                    content=content,
                    score=score,
                    authority=authority,
                    date=str(item["date"])[:40] if item.get("date") else None,
                    provider=self.name,
                )
            )
        return hits
