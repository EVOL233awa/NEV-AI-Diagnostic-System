"""检索：向量路为主路，关键词路为降级保底 → 带引用返回（§3.2 底层）。

- 云端 bge-m3 实测纯向量路显著优于双路 RRF 融合（eval_gate：vec_only 100% vs 融合 85%），
  BM25 在当前语料上是负贡献，故健康路径只走向量路（eval_gate.py 同批注释）。
- 向量路不可达（嵌入服务挂 / 扩展缺失）或零召回时，自动退化为 BM25 关键词路，服务不中断（§4）。
- 重排默认关（bge-reranker-base 复测不合格，§13-①），预留 rerank 钩子。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import KbChunk, KbDocument
from backend.rag import vecstore
from backend.rag.bm25 import bm25_index
from backend.rag.embedder import Embedder, EmbedderUnavailable

# RRF_K：TREC 缺省 60 适用于大候选池；本系统单店万级块内，K 取小值
# 拉大头部排名差距——避免单路 rank0 被另一路 rank9+ 的噪声块淹没（实测教训）
RRF_K = 10
# 数量漏斗（§6.1 参数经验）：两路各召回候选，融合后取 top_k 注入
CANDIDATE_PER_LEG = 10


@dataclass
class RetrievedChunk:
    chunk_id: int
    document_id: int
    document_title: str
    category: str
    section_path: str
    page_no: int | None
    content: str
    score: float
    legs: list[str]  # 命中来源：vec / bm25


def _rrf_fuse(
    ranked_lists: dict[str, list[tuple[int, float]]],
    top_k: int,
) -> list[tuple[int, float, list[str]]]:
    scores: dict[int, float] = {}
    legs: dict[int, list[str]] = {}
    for leg, ranking in ranked_lists.items():
        for rank, (chunk_id, _raw) in enumerate(ranking):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank + 1)
            legs.setdefault(chunk_id, []).append(leg)
    fused = sorted(scores.items(), key=lambda p: p[1], reverse=True)[:top_k]
    return [(cid, s, legs[cid]) for cid, s in fused]


def search(
    db: Session,
    query: str,
    category: str | None = None,
    top_k: int = 5,
    embedder: Embedder | None = None,
    reranker: Callable[[str, list[RetrievedChunk]], list[RetrievedChunk]] | None = None,
) -> list[RetrievedChunk]:
    """单次混合检索。category 过滤在候选层做（向量路 KNN 取足量再过滤）。"""
    query = query.strip()
    if not query:
        return []
    ranked: dict[str, list[tuple[int, float]]] = {}

    # 语义向量路（主路，可退化）
    embedder = embedder or Embedder()
    try:
        if vecstore.ensure_vec_table(db):
            qvec = embedder.embed([query])[0]
            ranked["vec"] = vecstore.knn_search(db, qvec, CANDIDATE_PER_LEG * 3)
    except EmbedderUnavailable:
        ranked.pop("vec", None)  # 降级：纯关键词（§4）

    # 关键词路保底：向量路不可用或零召回时才启用（主路切换依据见模块 docstring）
    if not ranked.get("vec"):
        ranked["bm25"] = bm25_index.search(db, query, category=None, top_k=CANDIDATE_PER_LEG * 3)

    fused = _rrf_fuse(ranked, top_k=top_k * 3)
    if not fused:
        return []

    ids = [cid for cid, _s, _l in fused]
    rows = db.execute(
        select(
            KbChunk.id,
            KbChunk.document_id,
            KbDocument.category,
            KbChunk.section_path,
            KbChunk.page_no,
            KbChunk.content,
            KbDocument.title,
        )
        .join(KbDocument, KbChunk.document_id == KbDocument.id)
        .where(KbChunk.id.in_(ids))
    ).all()
    by_id = {int(r[0]): r for r in rows}

    results: list[RetrievedChunk] = []
    for cid, score, legs in fused:
        row = by_id.get(cid)
        if row is None:
            continue
        if category and row[2] != category:
            continue
        results.append(
            RetrievedChunk(
                chunk_id=cid,
                document_id=int(row[1]),
                document_title=str(row[6]),
                category=row[2],
                section_path=row[3],
                page_no=row[4],
                content=row[5],
                score=round(score, 6),
                legs=legs,
            )
        )
        if len(results) >= top_k:
            break

    if reranker is not None:
        results = reranker(query, results)
    return results
