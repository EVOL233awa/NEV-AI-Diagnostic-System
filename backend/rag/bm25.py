"""关键词检索路：jieba 分词 + rank-bm25（§3.2 底层，专治故障码/术语字面命中）。

索引在内存单例中维护：进程启动或检索 miss 时从 kb_chunks 全量加载，
新增/删除知识块时增量更新。数据量为单店万级块内，Python 层 BM25 毫秒级。
"""
from __future__ import annotations

import threading

import jieba
from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models import KbChunk, KbDocument

# 领域词进 jieba 词典，避免被切碎（电池管理系统/BMS/P0A1F 等）
for _w in (
    "电池管理系统", "电机控制器", "整车控制器", "动力电池", "充电桩", "快充", "慢充",
    "续航里程", "绝缘故障", "高压互锁", "热管理", "热失控", "SOC", "SOH", "BMS", "MCU",
    "VCU", "OBC", "DCDC", "IGBT", "CAN", "DTC", "P0A1F", "预充", "继电器", "编码器",
    "续航衰减", "低温衰减", "回收失效", "充电中断", "充电跳枪", "绝缘电阻",
):
    jieba.add_word(_w, freq=1000)

_TOKEN_CACHE: dict[str, list[str]] = {}


def tokenize(text: str) -> list[str]:
    cached = _TOKEN_CACHE.get(text)
    if cached is not None:
        return cached
    lowered = text.lower()
    tokens = [t for t in jieba.lcut(lowered) if t.strip()]
    if len(_TOKEN_CACHE) > 20_000:
        _TOKEN_CACHE.clear()
    _TOKEN_CACHE[text] = tokens
    return tokens


class Bm25Index:
    """kb_chunks 的内存 BM25 索引（含类别过滤所需的元数据）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._corpus_ids: list[int] = []
        self._corpus_meta: dict[int, tuple[str, str]] = {}  # id -> (category, doc_title)
        self._engine: BM25Okapi | None = None
        self._doc_tokens: dict[int, list[str]] = {}

    def rebuild(self, db: Session) -> None:
        rows = db.execute(
            select(KbChunk.id, KbChunk.content, KbDocument.category)
            .join(KbDocument, KbChunk.document_id == KbDocument.id)
        ).all()
        with self._lock:
            self._corpus_ids = []
            self._doc_tokens = {}
            self._corpus_meta = {}
            token_lists: list[list[str]] = []
            for chunk_id, content, category in rows:
                tokens = tokenize(content)
                self._corpus_ids.append(int(chunk_id))
                self._doc_tokens[int(chunk_id)] = tokens
                token_lists.append(tokens)
                self._corpus_meta[int(chunk_id)] = (category or "general", "")
            self._engine = BM25Okapi(token_lists) if token_lists else None

    def _ensure_loaded(self, db: Session) -> None:
        if self._engine is None:
            self.rebuild(db)

    def add(self, chunk_id: int, content: str, category: str) -> None:
        """增量加入新块（重建整表对万级数据也够快，但增量写路径更平滑）。"""
        with self._lock:
            if self._engine is None:
                return  # 未初始化时留给 rebuild
            tokens = tokenize(content)
            self._corpus_ids.append(int(chunk_id))
            self._doc_tokens[int(chunk_id)] = tokens
            self._corpus_meta[int(chunk_id)] = (category or "general", "")
            self._engine = BM25Okapi([self._doc_tokens[cid] for cid in self._corpus_ids])

    def remove(self, chunk_ids: list[int]) -> None:
        with self._lock:
            drop = set(chunk_ids)
            self._corpus_ids = [cid for cid in self._corpus_ids if cid not in drop]
            for cid in drop:
                self._doc_tokens.pop(cid, None)
                self._corpus_meta.pop(cid, None)
            self._engine = (
                BM25Okapi([self._doc_tokens[cid] for cid in self._corpus_ids])
                if self._corpus_ids
                else None
            )

    def search(
        self,
        db: Session,
        query: str,
        category: str | None = None,
        top_k: int = 10,
    ) -> list[tuple[int, float]]:
        """返回 [(chunk_id, bm25_score)]，按分数降序。"""
        self._ensure_loaded(db)
        with self._lock:
            engine = self._engine
            if engine is None:
                return []
            scores = engine.get_scores(tokenize(query.lower()))
            pairs = sorted(
                zip(self._corpus_ids, scores), key=lambda p: p[1], reverse=True
            )
        if category:
            pairs = [p for p in pairs if self._corpus_meta.get(p[0], ("general", ""))[0] == category]
        return [(cid, float(s)) for cid, s in pairs[:top_k] if s > 0]


bm25_index = Bm25Index()
