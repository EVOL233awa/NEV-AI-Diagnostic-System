"""bge-reranker-v2-m3 重排客户端（硅基流动 /v1/rerank，同步 urllib，与 Embedder 同风格）。

2026-10-02 实测（50 例评测集 + 12 例同义改写集，详见 work/rerank_tune.py）：
- 候选池 = top_k 直排最优：top1 命中 82%→86%（主集 +4pp）、改写集 top1 75%→83%，
  top3 均不倒退；端到端延迟 P50 +140ms（5 块）/ +256ms（15 块）。
- 分数可分性弱（命中块 P50 0.088、P10 仅 0.005）：阈值当过滤器/插队器均被证伪，
  score_threshold 默认 0（纯重排）；>0 时退化为"高分块插队、其余保持原序"的保守模式。
- rerank 服务不可达/超时/HTTP 错误/格式异常一律静默返回原序——检索不因重排中断。
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, Protocol

from backend.config import settings

logger = logging.getLogger(__name__)

# 禁用系统代理：本机代理环境变量（SOCKS）会干扰云端 API 与本地回环的直连
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
DEFAULT_MODEL = "BAAI/bge-reranker-v2-m3"
TIMEOUT_S = 10


class _ChunkLike(Protocol):
    content: str


def rerank_api(
    url: str,
    api_key: str,
    model: str,
    query: str,
    documents: list[str],
    top_n: int | None = None,
) -> list[tuple[int, float]]:
    """底层 /v1/rerank 调用：返回 [(原索引, 相关性分数)]（按分数降序）。失败抛异常。"""
    payload: dict[str, Any] = {"model": model, "query": query, "documents": documents, "return_documents": False}
    if top_n is not None:
        payload["top_n"] = top_n
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(
        f"{url.rstrip('/').removesuffix('/v1')}/v1/rerank",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
    )
    with _OPENER.open(req, timeout=TIMEOUT_S) as resp:
        data = json.load(resp)
    items = data.get("results")
    if not isinstance(items, list):
        raise ValueError(f"rerank 返回格式异常：缺少 results 数组")
    return [(int(item["index"]), float(item["relevance_score"])) for item in items]


def rerank_chunks(query: str, chunks: list[_ChunkLike]) -> list[_ChunkLike]:
    """重排检索结果。未启用/失败/空输入一律原样返回（调用方无需关心降级）。

    阈值语义：score_threshold > 0 时，分数 ≥ 阈值的块按分数排前（"插队"），
    其余块保持原相对顺序补位——防止语义相近的错误块把术语精确匹配块挤出头部
    （实测 P0A80 型伤害）；= 0 时纯按重排分数排序。
    """
    if not chunks or not query.strip():
        return chunks
    lm = settings.local_models
    if not lm.get("rerank_enabled", True):
        return chunks
    url = str(lm.get("rerank_url") or "").strip()
    if not url:
        return chunks  # 未配置 = 未启用（测试环境/离线零依赖）
    model = str(lm.get("rerank_model") or DEFAULT_MODEL)
    threshold = float(lm.get("rerank_score_threshold") or 0.0)
    try:
        t0 = time.perf_counter()
        api_key = str(lm.get("rerank_key") or lm.get("embedding_key") or "")
        ranked = rerank_api(url, api_key, model, query, [c.content for c in chunks])
        logger.info("rerank 完成：%d 块，%.0fms", len(chunks), (time.perf_counter() - t0) * 1000)
    except (urllib.error.URLError, TimeoutError, OSError, KeyError, ValueError) as exc:
        logger.warning("重排失败，保持原序降级：%s", exc)
        return chunks

    scores = [0.0] * len(chunks)
    for idx, score in ranked:
        if 0 <= idx < len(chunks):
            scores[idx] = score
    if threshold > 0.0:
        promoted = sorted((i for i in range(len(chunks)) if scores[i] >= threshold), key=lambda i: -scores[i])
        rest = [i for i in range(len(chunks)) if scores[i] < threshold]
        order = promoted + rest
    else:
        order = [i for i, _ in ranked if 0 <= i < len(chunks)]
        order += [i for i in range(len(chunks)) if i not in set(order)]
    return [chunks[i] for i in order]
