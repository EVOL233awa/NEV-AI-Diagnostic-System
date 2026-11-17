"""DeepSeek 官方联网搜索适配器（v2.1.0 默认 provider）。

接口：POST {base_url}/v1/tools/search
- 专用 api_key 为空时，仅当 base_url 指向 api.deepseek.com 才回退主模型 key；
  主模型换到别家供应商后绝不把主 key 打到其他端点。
- 中文/英文 query 自动追加 lang: 算子（search.deepseek.dynamic_language 可关）。
- 失败语义统一为 SearchUnavailable，402（余额不足）单独文案。
"""
from __future__ import annotations

import httpx

from backend.config import is_official_deepseek, settings
from backend.core.providers.search.base import SearchHit, SearchUnavailable, sanitize_text, valid_http_url
from backend.core.providers.search.language import build_query


def _endpoint(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}{path}"
    return f"{base}/v1{path}"


class DeepSeekSearch:
    name = "deepseek"

    def _cfg(self) -> dict:
        cfg = settings.search.get("deepseek")
        return cfg if isinstance(cfg, dict) else {}

    def _base_url(self) -> str:
        return str(self._cfg().get("base_url") or "").rstrip("/")

    def api_key(self) -> str:
        key = str(self._cfg().get("api_key") or "").strip()
        if key:
            return key
        base = self._base_url()
        if is_official_deepseek(base):
            return str(settings.deepseek.get("main_key") or "")
        return ""

    def is_configured(self) -> bool:
        return bool(self._base_url() and self.api_key())

    async def search(self, query: str, count: int) -> list[SearchHit]:
        if not self.is_configured():
            raise SearchUnavailable("DeepSeek 搜索未配置（base_url/api_key）", code="not_configured")
        cfg = self._cfg()
        q = build_query(query, dynamic_language=bool(cfg.get("dynamic_language", True)))
        if not q:
            return []
        body = {"query": q, "count": max(1, min(int(count or 5), 10)), "need_content": bool(cfg.get("need_content", True))}
        timeout = float(cfg.get("timeout") or 20)
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                resp = await client.post(
                    _endpoint(self._base_url(), "/tools/search"),
                    json=body,
                    headers={"Authorization": f"Bearer {self.api_key()}", "Content-Type": "application/json"},
                )
        except httpx.TimeoutException as exc:
            raise SearchUnavailable("联网检索连接超时", code="timeout") from exc
        except httpx.HTTPError as exc:
            raise SearchUnavailable(f"联网检索连接失败：{exc}", code="network") from exc

        if resp.status_code == 402:
            raise SearchUnavailable("DeepSeek 搜索账户余额不足（HTTP 402）", code="payment")
        if resp.status_code in (401, 403):
            raise SearchUnavailable(f"DeepSeek 搜索 key 无效或无权限（HTTP {resp.status_code}）", code="auth")
        if resp.status_code == 429:
            raise SearchUnavailable("DeepSeek 搜索请求过多（HTTP 429）", code="rate_limit")
        if resp.status_code >= 500:
            raise SearchUnavailable(f"DeepSeek 搜索服务异常（HTTP {resp.status_code}）", code="server")
        if resp.status_code >= 400:
            raise SearchUnavailable(f"DeepSeek 搜索请求失败（HTTP {resp.status_code}）", code="bad_request")
        try:
            data = resp.json()
        except ValueError as exc:
            raise SearchUnavailable("DeepSeek 搜索响应不是合法 JSON", code="protocol") from exc

        hits: list[SearchHit] = []
        for item in data.get("results") or []:
            if not isinstance(item, dict):
                continue
            url = valid_http_url(item.get("url"))
            if not url:
                continue
            content = item.get("content") or item.get("summary") or ""
            score_raw = item.get("rerank_score")
            try:
                score = float(score_raw) if score_raw is not None else 0.0
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
                    snippet=sanitize_text(item.get("snippet"), limit=600),
                    content=sanitize_text(content),
                    score=score,
                    authority=authority,
                    date=str(item["date"])[:40] if item.get("date") else None,
                    provider=self.name,
                )
            )
        return hits
