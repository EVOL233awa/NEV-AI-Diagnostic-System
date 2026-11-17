"""DTC 速查：角色隔离、码表搜索、大小写归一、知识块兜底、相关案例。"""
from __future__ import annotations

from backend.db.models import Case
from backend.rag import ingest


class _Embedder:
    dim = 1024

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.02] * self.dim for _ in texts]


def test_role_isolation(client, owner_headers, staff_headers, admin_headers):
    assert client.get("/api/dtc/search", params={"q": "P0A"}).status_code == 401
    assert client.get("/api/dtc/search", params={"q": "P0A"}, headers=owner_headers).status_code == 403
    assert client.get("/api/dtc/P0A80", headers=owner_headers).status_code == 403
    assert client.get("/api/dtc/search", params={"q": "P0A"}, headers=staff_headers).status_code == 200
    assert client.get("/api/dtc/P0A80", headers=admin_headers).status_code == 200


def test_search_by_prefix_and_chinese(client, staff_headers):
    body = client.get("/api/dtc/search", params={"q": "P0A8"}, headers=staff_headers).json()
    assert body["results"] and body["results"][0]["code"] == "P0A80"
    assert "混合动力电池组" in body["results"][0]["zh"]

    body = client.get("/api/dtc/search", params={"q": "失火"}, headers=staff_headers).json()
    codes = [item["code"] for item in body["results"]]
    assert "P0300" in codes

    body = client.get("/api/dtc/search", params={"q": "   "}, headers=staff_headers).json()
    assert body["results"] == []

    assert client.get("/api/dtc/search", params={"q": "P0", "limit": 0},
                      headers=staff_headers).status_code == 400


def test_detail_normalizes_case(client, staff_headers):
    upper = client.get("/api/dtc/P0A80", headers=staff_headers).json()
    lower = client.get("/api/dtc/p0a80", headers=staff_headers).json()
    assert lower == upper
    assert upper["zh"] == "更换混合动力电池组"
    assert "单体压差" in upper["note"]
    assert upper["chunks"] == []  # 种子库未灌 DTC 语料时不影响码表解释

    assert client.get("/api/dtc/12345", headers=staff_headers).status_code == 400
    assert client.get("/api/dtc/P9F99", headers=staff_headers).status_code == 404


def test_detail_from_kb_chunk_when_catalog_missing(client, db_session, staff_headers):
    ingest.ingest_document(
        db_session, title="测试 DTC 文档", category="dtc",
        markdown_text="## C1ABC\n[C1ABC] 测试专用故障\n说明：仅用于测试的知识块兜底。\n",
        embedder=_Embedder(), min_chunk_chars=1,
    )
    body = client.get("/api/dtc/C1ABC", headers=staff_headers).json()
    assert body["zh"] == "测试专用故障"
    assert body["note"] == "仅用于测试的知识块兜底。"
    assert body["doc_title"] == "测试 DTC 文档"
    assert body["chunks"] and body["chunks"][0]["section_path"] == "C1ABC"


def test_detail_includes_related_cases(client, db_session, staff_headers):
    db_session.add(Case(
        tenant_id=1, title="P0300 失火检修", symptoms="怠速抖动",
        diagnosis="点火线圈故障", repair_result="更换点火线圈",
    ))
    db_session.commit()
    body = client.get("/api/dtc/P0300", headers=staff_headers).json()
    assert any(case["title"] == "P0300 失火检修" for case in body["cases"])
