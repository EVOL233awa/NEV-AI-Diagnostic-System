"""检索状态回归：failed/parsing 文档的 chunk 不得进入证据链。"""
from __future__ import annotations

from backend.db.models import KbChunk, KbDocument
from backend.rag import retrieve
from backend.rag.bm25 import bm25_index
from backend.rag.embedder import EmbedderUnavailable


class _UnavailableEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        raise EmbedderUnavailable("offline")


def _make_doc(db, title: str, status: str, content: str) -> tuple[KbDocument, KbChunk]:
    doc = KbDocument(title=title, category="general", status=status)
    db.add(doc)
    db.flush()
    chunk = KbChunk(document_id=doc.id, seq=0, content=content, tokens=len(content))
    db.add(chunk)
    db.commit()
    bm25_index.add(chunk.id, chunk.content, doc.category)
    return doc, chunk


def test_failed_document_chunks_not_retrieved(db_session) -> None:
    marker = "ZZQFAILEDMARKER"
    ready_doc, ready_chunk = _make_doc(db_session, "ready-retrieval-doc", "ready", f"{marker} 正常知识块")
    failed_doc, failed_chunk = _make_doc(db_session, "failed-retrieval-doc", "failed", f"{marker} 失败知识块")
    try:
        bm25_index.rebuild(db_session)
        results = retrieve.search(
            db_session,
            marker,
            top_k=10,
            embedder=_UnavailableEmbedder(),
            reranker=lambda _q, chunks: chunks,
        )
        ids = {r.chunk_id for r in results}
        assert ready_chunk.id in ids
        assert failed_chunk.id not in ids
    finally:
        bm25_index.remove([ready_chunk.id, failed_chunk.id])
        db_session.delete(failed_chunk)
        db_session.delete(ready_chunk)
        db_session.delete(failed_doc)
        db_session.delete(ready_doc)
        db_session.commit()
