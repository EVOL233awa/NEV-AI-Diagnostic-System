"""检索重排与 superadmin 新配置项回归：降级链、阈值插队、PUT 校验、连通性测试槽位。

rerank_chunks 全程 mock rerank_api/网络——测试完全离线；未配置 rerank_url 必须零网络依赖。
"""
from __future__ import annotations

import urllib.error
from types import SimpleNamespace

import pytest

import backend.rag.reranker as reranker_mod
from backend.rag.reranker import rerank_chunks
from backend.rag.retrieve import RetrievedChunk
from backend.seed.seed import reset_superadmin_password


@pytest.fixture
def superadmin_headers(client):
    """重置 superadmin 密码 → 登录拿 token（与 test_superadmin 同款）。"""
    password = reset_superadmin_password()
    r = client.post("/api/auth/login", json={"username": "superadmin", "password": password})
    assert r.status_code == 200, f"superadmin 登录失败: HTTP {r.status_code}"
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _chunks(*contents: str) -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            chunk_id=i, document_id=1, document_title=f"doc{i}", category="dtc",
            section_path=f"doc{i} > sec", page_no=None, content=c, score=1.0 - i * 0.1, legs=["vec"],
        )
        for i, c in enumerate(contents)
    ]


@pytest.fixture
def lm(monkeypatch: pytest.MonkeyPatch):
    """可换桩的 local_models 配置。"""
    state = {"local_models": {}}
    monkeypatch.setattr(reranker_mod, "settings", SimpleNamespace(local_models=state["local_models"]))
    return state["local_models"]


class TestRerankChunks:
    def test_no_url_keeps_order(self, lm):
        chunks = _chunks("a", "b")
        assert rerank_chunks("query", chunks) is chunks

    def test_disabled_keeps_order(self, lm):
        lm.update({"rerank_url": "http://fake", "rerank_enabled": False})
        chunks = _chunks("a", "b")
        assert rerank_chunks("query", chunks) is chunks

    def test_rerank_reorders_by_score(self, lm, monkeypatch: pytest.MonkeyPatch):
        lm.update({"rerank_url": "http://fake", "rerank_model": "m", "embedding_key": "sk-x"})
        chunks = _chunks("低分块", "高分块", "中分块")
        monkeypatch.setattr(
            reranker_mod, "rerank_api",
            lambda *a, **k: [(1, 0.9), (2, 0.5), (0, 0.1)],
        )
        out = rerank_chunks("q", chunks)
        assert [c.content for c in out] == ["高分块", "中分块", "低分块"]

    def test_api_failure_degrades_to_original(self, lm, monkeypatch: pytest.MonkeyPatch):
        lm.update({"rerank_url": "http://fake"})
        chunks = _chunks("a", "b", "c")

        def _boom(*a, **k):
            raise urllib.error.URLError("refused")

        monkeypatch.setattr(reranker_mod, "rerank_api", _boom)
        assert rerank_chunks("q", chunks) is chunks

    def test_threshold_promotes_only_high_scores(self, lm, monkeypatch: pytest.MonkeyPatch):
        lm.update({"rerank_url": "http://fake", "rerank_score_threshold": 0.5})
        chunks = _chunks("原第一", "高分块", "插队块")
        monkeypatch.setattr(
            reranker_mod, "rerank_api",
            lambda *a, **k: [(2, 0.9), (0, 0.3), (1, 0.7)],
        )
        out = rerank_chunks("q", chunks)
        # ≥0.5 的按分数排前（插队块0.9 → 高分块0.7），其余保持原相对序（原第一0.3）
        assert [c.content for c in out] == ["插队块", "高分块", "原第一"]

    def test_threshold_zero_pure_rerank(self, lm, monkeypatch: pytest.MonkeyPatch):
        lm.update({"rerank_url": "http://fake", "rerank_score_threshold": 0.0})
        chunks = _chunks("a", "b", "c")
        monkeypatch.setattr(
            reranker_mod, "rerank_api",
            lambda *a, **k: [(2, 0.05), (1, 0.03), (0, 0.01)],
        )
        out = rerank_chunks("q", chunks)
        assert [c.content for c in out] == ["c", "b", "a"]

    def test_empty_query_keeps_order(self, lm):
        lm.update({"rerank_url": "http://fake"})
        chunks = _chunks("a")
        assert rerank_chunks("  ", chunks) is chunks


class TestSuperadminRerankConfig:
    def test_put_rerank_hot_effective(self, client, superadmin_headers):
        r = client.put(
            "/api/superadmin/config",
            headers=superadmin_headers,
            json={"providers": {"rerank": {"enabled": True, "url": "https://api.siliconflow.cn",
                                           "model": "BAAI/bge-reranker-v2-m3", "score_threshold": 0.3}}},
        )
        assert r.status_code == 200
        assert "rerank_url" in r.json()["updated"]
        cfg = client.get("/api/superadmin/config", headers=superadmin_headers).json()
        assert cfg["providers"]["rerank"]["enabled"] is True
        assert cfg["providers"]["rerank"]["url"] == "https://api.siliconflow.cn"
        assert cfg["providers"]["rerank"]["score_threshold"] == 0.3
        # 热生效：rerank_chunks 直读 settings
        assert reranker_mod.settings.local_models["rerank_url"] == "https://api.siliconflow.cn"

    def test_put_rerank_threshold_rejected_out_of_range(self, client, superadmin_headers):
        r = client.put(
            "/api/superadmin/config",
            headers=superadmin_headers,
            json={"providers": {"rerank": {"score_threshold": 1.5}}},
        )
        assert r.status_code == 400
        assert reranker_mod.settings.local_models.get("rerank_score_threshold") != 1.5

    def test_put_small_model_params_and_validation(self, client, superadmin_headers):
        r = client.put(
            "/api/superadmin/config",
            headers=superadmin_headers,
            json={"providers": {"small_model": {"base_url": "https://api.siliconflow.cn",
                                                "model": "Qwen/Qwen3.5-4B",
                                                "title_temperature": 0.4, "title_max_tokens": 80}}},
        )
        assert r.status_code == 200
        cfg = client.get("/api/superadmin/config", headers=superadmin_headers).json()
        sm = cfg["providers"]["small_model"]
        assert sm["base_url"] == "https://api.siliconflow.cn"
        assert sm["model"] == "Qwen/Qwen3.5-4B"
        assert sm["title_temperature"] == 0.4
        assert sm["title_max_tokens"] == 80
        assert sm["fallback"]  # 视图回显 background 槽位模型名（回退说明）
        # 越界拒绝
        r = client.put(
            "/api/superadmin/config",
            headers=superadmin_headers,
            json={"providers": {"small_model": {"title_max_tokens": 99999}}},
        )
        assert r.status_code == 400

    def test_test_slot_rerank_requires_url(self, client, superadmin_headers):
        # 先清空 rerank_url（settings.raw 全 session 共享，防其他用例写入残留）
        client.put("/api/superadmin/config", headers=superadmin_headers,
                   json={"providers": {"rerank": {"url": ""}}})
        r = client.post("/api/superadmin/config/test", headers=superadmin_headers, json={"slot": "rerank"})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False and "未配置" in body["error"]
