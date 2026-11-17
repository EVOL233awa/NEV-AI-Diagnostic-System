"""搜索 provider 公共契约：统一结果结构、异常与 Protocol。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_TAG_RE = re.compile(r"<[^>]{0,2000}>")


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    snippet: str
    content: str
    score: float
    authority: int | None
    date: str | None
    provider: str


class SearchUnavailable(RuntimeError):
    """搜索不可用（key 缺失 / 额度尽 / 网络失败），由调用方转为说明文本。"""

    def __init__(self, message: str, *, code: str = "") -> None:
        super().__init__(message)
        self.code = code


class SearchProvider(Protocol):
    name: str

    def is_configured(self) -> bool: ...

    async def search(self, query: str, count: int) -> list[SearchHit]: ...


def sanitize_text(text: object, *, limit: int = 4000) -> str:
    """网页文本去 HTML 标签与控制字符（网页内容是不可信数据，进模型前先削尖）。"""
    raw = str(text or "")
    raw = _CONTROL_RE.sub("", raw)
    raw = _TAG_RE.sub(" ", raw)
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    return raw.strip()[:limit]


def valid_http_url(url: object) -> str:
    """只保留 http/https URL；其余返回空串（模型上下文不接受 javascript:/data: 之类）。"""
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except ValueError:
        return ""
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        return ""
    return raw[:1024]
