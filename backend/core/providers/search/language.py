"""提问语言检测与 DeepSeek 搜索的 lang: 算子拼接。

规则（v2.1.0 定稿）：
- 中文占比 ≥ 20% → lang:zh（分母为中文+拉丁字母，避免故障码/型号把中文比例拉低）
- 英文占比 ≥ 60% → lang:en（分母为非空白字符，纯故障码 P0A80 不会被误判为英文）
- 其他语言 / 无法判断 → 不加
"""
from __future__ import annotations

import re

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_LATIN_RE = re.compile(r"[A-Za-z]")

MAX_QUERY_CHARS = 120


def detect_language(query: str) -> str | None:
    text = str(query or "")
    cjk = len(_CJK_RE.findall(text))
    latin = len(_LATIN_RE.findall(text))
    letters = cjk + latin
    visible = len([c for c in text if not c.isspace()])
    if letters == 0 or visible == 0:
        return None
    if cjk / letters >= 0.2:
        return "zh"
    if latin / visible >= 0.6:
        return "en"
    return None


def build_query(query: str, *, dynamic_language: bool = True) -> str:
    """截断到 120 字符后按需追加 `lang:xx`（总长 ≤ 128，满足接口上限）。"""
    base = str(query or "").strip()[:MAX_QUERY_CHARS]
    if not dynamic_language or not base:
        return base
    lang = detect_language(base)
    return f"{base} lang:{lang}" if lang else base
