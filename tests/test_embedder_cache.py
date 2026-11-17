"""嵌入缓存键回归：端点/模型热切换后不得复用旧向量。"""
from __future__ import annotations

import backend.rag.embedder as embedder_mod
from backend.rag.embedder import Embedder


def _stub(embedder: Embedder, vector: float, calls: list[tuple[str, list[str]]]) -> None:
    def _request(texts: list[str]) -> list[list[float]]:
        calls.append((embedder.model, texts))
        return [[vector] for _ in texts]

    embedder._request_embeddings = _request  # type: ignore[method-assign]


def test_cache_key_includes_endpoint_and_model() -> None:
    embedder_mod._embed_cache.clear()
    calls: list[tuple[str, list[str]]] = []

    first = Embedder(base_url="http://embed-a", model="model-a")
    _stub(first, 1.0, calls)
    assert first.embed(["同一段文本"]) == [[1.0]]

    # 同端点同模型：命中缓存，不再请求
    cached = Embedder(base_url="http://embed-a", model="model-a")
    _stub(cached, 9.0, calls)
    assert cached.embed(["同一段文本"]) == [[1.0]]
    assert len(calls) == 1

    # 换模型：必须重新请求
    other_model = Embedder(base_url="http://embed-a", model="model-b")
    _stub(other_model, 2.0, calls)
    assert other_model.embed(["同一段文本"]) == [[2.0]]
    assert len(calls) == 2

    # 换端点：同样必须重新请求
    other_endpoint = Embedder(base_url="http://embed-b", model="model-a")
    _stub(other_endpoint, 3.0, calls)
    assert other_endpoint.embed(["同一段文本"]) == [[3.0]]
    assert len(calls) == 3
