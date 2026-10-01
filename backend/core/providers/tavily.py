"""Tavily 联网检索（web_search 主力通道）。

免费额度用尽 / key 失效时返回不可用标志，Agent 层转为如实说明的工具结果，不硬失败。
权威域名优先：可信域加权上浮，内容农场下沉，零价值域（财经行情/搜索结果页/文档农场）硬剔除。
"""
from __future__ import annotations

from urllib.parse import urlparse

import httpx

from backend.config import settings

TAVILY_ENDPOINT = "https://api.tavily.com/search"

# 排序加权：车企官方/标准组织/专业站优先（权威域名优先）
DOMAIN_BOOST = {
    "gbstandard": ["std.samr.gov.cn", "openstd.samr.gov.cn"],
    "oem": ["byd.com", "tesla.com", "saicmotor.com", "geely.com", "nio.com", "nio.cn", "xpeng.com", "lixiang.com"],
    "professional": ["autohome.com.cn", "12365auto.com", "cnevpost.com", "electrek.co"],
}
# 噪声下沉：UGC 混杂域。可信内容仍可能存在（工程师长文/OEM 官方号），故不剔除，由提示词单源降格规则兜底
GENERIC_NOISE = ["zhihu.com", "baijiahao.baidu.com", "sohu.com"]
# 硬剔除：确定无诊断价值的域（实测 10 查询：财经站占 24% 且全为行情噪声）。剔后不足 2 条回退为仅下沉，防模型拿到空结果
HARD_BLOCK = ["wenku.baidu.com", "cn.investing.com", "sogou.com"]

TRUSTED_DOMAINS = [d for domains in DOMAIN_BOOST.values() for d in domains]


def _host(url: str) -> str:
    try:
        h = urlparse(url).netloc.lower()
    except Exception:
        return ""
    return h[4:] if h.startswith("www.") else h


def _match(url: str, domains: list[str]) -> bool:
    """注册域精确匹配（含子域）。替代子串匹配：nio.cn 不再误配 nio.com，仿冒域 xxx-byd.com 不再命中加成。"""
    h = _host(url)
    return any(h == d or h.endswith("." + d) for d in domains)


def _score(url: str) -> int:
    return 2 if _match(url, TRUSTED_DOMAINS) else 0


def _is_noise(url: str) -> bool:
    return _match(url, GENERIC_NOISE)


def _is_blocked(url: str) -> bool:
    return _match(url, HARD_BLOCK)


class WebSearchUnavailable(RuntimeError):
    """Tavily 不可用（key 缺失 / 额度尽 / 网络失败），由调用方转为工具结果文本。"""


def is_configured() -> bool:
    return bool(settings.tavily.get("api_key"))


async def search(query: str, max_results: int = 5) -> dict:
    """返回 {results: [{title, url, content}], unavailable: False}；不可用抛 WebSearchUnavailable。"""
    api_key = settings.tavily.get("api_key", "")
    if not api_key:
        raise WebSearchUnavailable("Tavily key 未配置")
    try:
        async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
            resp = await client.post(
                TAVILY_ENDPOINT,
                json={"api_key": api_key, "query": query, "max_results": max_results, "search_depth": "basic"},
            )
    except httpx.HTTPError as exc:
        raise WebSearchUnavailable(f"联网检索连接失败：{exc}") from exc
    if resp.status_code in (401, 403, 429, 432, 451):
        raise WebSearchUnavailable(f"Tavily 不可用（HTTP {resp.status_code}，key 失效或额度尽）")
    resp.raise_for_status()
    data = resp.json()
    items = [
        {"title": r.get("title", ""), "url": r.get("url", ""), "content": (r.get("content") or "")[:500]}
        for r in data.get("results", [])
    ]
    # 硬剔除零价值域；供给保护——剔后不足 2 条则回退为仅下沉（防模型拿到空结果）
    kept = [r for r in items if not _is_blocked(r["url"])]
    if len(kept) >= 2:
        items = kept
    # 可信域上浮、噪声下沉（稳定排序保持 Tavily 相关性为二级序）
    items.sort(key=lambda r: (_is_noise(r["url"]), -_score(r["url"])))
    return {"results": items, "unavailable": False}
