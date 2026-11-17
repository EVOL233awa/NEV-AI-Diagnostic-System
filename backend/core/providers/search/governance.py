"""搜索结果统一治理：域名加权、噪声下沉、零价值域硬剔除、URL 去重。

所有 provider 的输出都走这里，保证切换供应商时行为一致：
1. 硬剔除 HARD_BLOCK；剔后不足 2 条回退为只下沉（防模型拿到空结果）。
2. 按规范化 URL 去重，保留最高分。
3. 稳定排序：噪声域下沉 → 权威域上浮 → 相关分降序。
"""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

from backend.core.providers.search.base import SearchHit, valid_http_url

# 排序加权：车企官方/标准组织/专业站优先（权威域名优先）
DOMAIN_BOOST = {
    "gbstandard": ["std.samr.gov.cn", "openstd.samr.gov.cn"],
    "oem": ["byd.com", "tesla.com", "saicmotor.com", "geely.com", "nio.com", "nio.cn", "xpeng.com", "lixiang.com"],
    "professional": ["autohome.com.cn", "12365auto.com", "cnevpost.com", "electrek.co"],
}
# 噪声下沉：UGC 混杂域。可信内容仍可能存在（工程师长文/OEM 官方号），故不剔除，由提示词单源降格规则兜底
GENERIC_NOISE = ["zhihu.com", "baijiahao.baidu.com", "sohu.com"]
# 硬剔除：确定无诊断价值的域（实测 10 查询：财经站占 24% 且全为行情噪声）。剔后不足 2 条回退为仅下沉
HARD_BLOCK = ["wenku.baidu.com", "cn.investing.com", "sogou.com"]

TRUSTED_DOMAINS = [d for domains in DOMAIN_BOOST.values() for d in domains]


def _host(url: str) -> str:
    try:
        h = urlparse(url).netloc.lower()
    except ValueError:
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


def normalize_url(url: str) -> str:
    """去 #fragment、去 utm_* 参数、主机与协议小写、路径末斜杠归一。"""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def _dedupe(hits: list[SearchHit]) -> list[SearchHit]:
    best: dict[str, SearchHit] = {}
    order: list[str] = []
    for hit in hits:
        key = normalize_url(hit.url)
        if key not in best:
            best[key] = hit
            order.append(key)
        elif hit.score > best[key].score:
            best[key] = hit
    return [best[key] for key in order]


def apply(hits: list[SearchHit]) -> list[SearchHit]:
    """输入原始命中，输出去重、治理、排序后的列表（内容截断由 registry 统一做）。"""
    cleaned = [hit for hit in hits if valid_http_url(hit.url)]
    kept = [hit for hit in cleaned if not _is_blocked(hit.url)]
    if len(kept) >= 2:
        cleaned = kept
    deduped = _dedupe(cleaned)
    # 硬剔除不足以保底时退化为“只下沉”：被 block 的域排在最后，仍给模型留结果
    return sorted(
        deduped,
        key=lambda h: (_is_blocked(h.url), _is_noise(h.url), -_score(h.url), -h.score),
    )
