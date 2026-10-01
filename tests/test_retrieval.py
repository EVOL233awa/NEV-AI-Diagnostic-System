"""检索层轻量优化单测：jieba 词典注入、嵌入 LRU 缓存（全离线，不发网络请求）。"""
from __future__ import annotations

import pytest

from backend.rag import bm25 as bm25_mod
from backend.rag import embedder as embedder_mod


@pytest.fixture(autouse=True)
def _clean_embed_cache():
    """模块级 LRU 是全局状态，测试前后清空防跨用例泄漏。"""
    embedder_mod._embed_cache.clear()
    yield
    embedder_mod._embed_cache.clear()


def _patch_request(monkeypatch: pytest.MonkeyPatch, counter: dict) -> None:
    def fake_request(self: embedder_mod.Embedder, texts: list[str]) -> list[list[float]]:
        counter["n"] += 1
        counter["batch_sizes"].append(len(texts))
        return [[0.1, 0.2] for _ in texts]

    monkeypatch.setattr(embedder_mod.Embedder, "_request_embeddings", fake_request)


class TestJiebaLexicon:
    def test_corpus_dtc_codes_extracted(self) -> None:
        codes = bm25_mod._corpus_dtc_codes()
        assert len(codes) >= 100, "码表语料应抽出 DTC 码全集（约 195 个）"

    def test_dtc_code_not_split(self) -> None:
        assert bm25_mod.tokenize("p0a80") == ["p0a80"]

    def test_domain_terms_kept_whole(self) -> None:
        for term in ("动力电池组", "快充口", "充电枪", "高压配电箱", "车载充电机", "跳枪"):
            assert bm25_mod.tokenize(term) == [term], f"{term} 被切碎"


class TestEmbedCache:
    def test_repeat_query_hits_cache(self, monkeypatch: pytest.MonkeyPatch) -> None:
        counter: dict = {"n": 0, "batch_sizes": []}
        _patch_request(monkeypatch, counter)
        emb = embedder_mod.Embedder(base_url="http://fake:1", model="m")
        first = emb.embed(["电池组故障"])
        second = emb.embed(["电池组故障"])
        assert counter["n"] == 1, "相同查询不应二次请求嵌入服务"
        assert first == second == [[0.1, 0.2]]

    def test_batch_partial_hit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        counter: dict = {"n": 0, "batch_sizes": []}
        _patch_request(monkeypatch, counter)
        emb = embedder_mod.Embedder(base_url="http://fake:1", model="m")
        emb.embed(["甲"])
        emb.embed(["甲", "乙"])
        assert counter["n"] == 2
        assert counter["batch_sizes"] == [1, 1], "第二批应只请求未命中的文本"

    def test_cache_eviction_bounded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        counter: dict = {"n": 0, "batch_sizes": []}
        _patch_request(monkeypatch, counter)
        emb = embedder_mod.Embedder(base_url="http://fake:1", model="m")
        for i in range(embedder_mod._EMBED_CACHE_MAX + 10):
            emb.embed([f"q{i}"])
        assert len(embedder_mod._embed_cache) == embedder_mod._EMBED_CACHE_MAX
