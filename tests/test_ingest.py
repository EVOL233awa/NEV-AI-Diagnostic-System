"""知识库摄取离线测试：结构感知分块、块长约束、双路入库、删除。嵌入用假向量。"""
from __future__ import annotations

import pytest

from backend.db.models import KbChunk, KbDocument
from backend.rag import ingest
from backend.rag.bm25 import bm25_index


class _FakeEmbedder:
    """定值 1024 维向量（bge-m3 维度），sqlite-vec 可用与否都不影响断言。"""

    dim = 1024

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.01] * self.dim for _ in texts]


LONG_PARA = "新能源汽车在低温环境下动力电池的可用容量会出现明显衰减，续航里程随之下降，" * 10  # 280字


def test_split_long_respects_limit() -> None:
    text = "电池管理系统会监控电芯温度。电池管理系统会监控单体电压。电池管理系统会均衡充电电流。" * 15
    pieces = ingest._split_long(text)
    assert all(len(p) <= ingest.MAX_CHUNK_CHARS for p in pieces)
    assert len(pieces) >= 2
    assert sum(len(p) for p in pieces) >= len(text) - 5


def test_parse_markdown_section_paths() -> None:
    md = (
        "# 第一章 总则\n"
        f"{LONG_PARA}\n"
        "## 1.1 充电规范\n"
        f"{LONG_PARA}\n"
        "### 1.1.1 直流快充\n"
        f"{LONG_PARA}\n"
        "## 1.2 存放要求\n"
        f"{LONG_PARA}\n"
    )
    chunks = ingest.parse_markdown(md)
    paths = [c.section_path for c in chunks]
    assert "第一章 总则" in paths
    assert "第一章 总则 > 1.1 充电规范" in paths
    assert "第一章 总则 > 1.1 充电规范 > 1.1.1 直流快充" in paths
    assert "第一章 总则 > 1.2 存放要求" in paths
    assert all(c.page_no is None for c in chunks)


def test_parse_markdown_drops_tiny_blocks() -> None:
    md = "# 标题\n太短\n"
    assert ingest.parse_markdown(md) == []


def test_parse_markdown_splits_long_body() -> None:
    body = LONG_PARA * 3
    md = f"# 长文\n{body}\n"
    chunks = ingest.parse_markdown(md)
    assert len(chunks) >= 2
    assert all(len(c.content) <= ingest.MAX_CHUNK_CHARS for c in chunks)


def test_parse_plain_merges_and_keeps_source_note() -> None:
    text = f"{LONG_PARA}\n\n{LONG_PARA}\n\n短段\n"
    chunks = ingest.parse_plain(text, "附录A")
    assert len(chunks) >= 1
    assert all("附录A" in c.section_path for c in chunks)


def test_ingest_document_full_flow(db_session) -> None:
    md = f"# 诊断手册\n{LONG_PARA}\n"
    doc, chunks = ingest.ingest_document(
        db_session, title="测试文档", category="dtc", markdown_text=md, embedder=_FakeEmbedder()
    )
    assert doc.status == "ready"
    assert doc.chunk_count == len(chunks) >= 1
    rows = db_session.query(KbChunk).filter(KbChunk.document_id == doc.id).all()
    assert len(rows) == len(chunks)
    # 关键词路（BM25 内存索引增量）可命中
    hits = bm25_index.search(db_session, "低温环境下动力电池", category="dtc", top_k=5)
    assert any(h[0] == chunks[0].id for h in hits)

    # 删除：文档/块清理且 BM25 不再命中
    assert ingest.delete_document(db_session, doc.id) is True
    assert db_session.query(KbChunk).filter(KbChunk.document_id == doc.id).count() == 0
    assert db_session.get(KbDocument, doc.id) is None
    assert not any(h[0] == chunks[0].id for h in bm25_index.search(db_session, "低温环境下动力电池", top_k=5))


def test_ingest_rejects_unknown_type(db_session) -> None:
    with pytest.raises(ValueError):
        ingest.ingest_document(
            db_session, title="x", category="general", file_bytes=b"a", file_kind=".exe",
            embedder=_FakeEmbedder(),
        )
