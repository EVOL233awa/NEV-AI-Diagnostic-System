"""API 权限矩阵与业务流离线测试：角色门禁、会话隔离、案例回流全流程。

全部走 TestClient + 临时库；案例沉淀的嵌入用 FakeEmbedder 注入，检索断言
走 BM25 内存索引（与生产同一路径，且完全离线）。
"""
from __future__ import annotations

import pytest

from backend.db.models import AuditLog, Case, Message, Session as ChatSession, User
from backend.security import hash_password
from backend.rag import ingest


class _FakeEmbedder:
    dim = 1024

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.02] * self.dim for _ in texts]


# ---------- 登录与门禁 ----------


def test_unauthenticated_requests_are_rejected(client) -> None:
    assert client.get("/api/chat/sessions").status_code == 401
    assert client.get("/api/kb/documents").status_code == 401
    assert client.get("/api/cases").status_code == 401


def test_login_wrong_password(client, owner_headers) -> None:
    r = client.post("/api/auth/login", json={"username": "user001", "password": "wrong-pass"})
    assert r.status_code == 401


def test_owner_cannot_touch_kb_or_cases(client, owner_headers) -> None:
    assert client.get("/api/kb/documents", headers=owner_headers).status_code == 403
    assert client.post("/api/cases", headers=owner_headers, json={"session_id": 1}).status_code == 403
    assert client.get("/api/cases", headers=owner_headers).status_code == 403


def test_kb_role_matrix(client, staff_headers, admin_headers) -> None:
    assert client.get("/api/kb/documents", headers=staff_headers).status_code == 200
    assert client.get("/api/kb/documents", headers=admin_headers).status_code == 200
    # 分块预览与删除是 admin 专属
    assert client.get("/api/kb/documents/999999/chunks", headers=staff_headers).status_code == 403
    assert client.get("/api/kb/documents/999999/chunks", headers=admin_headers).status_code == 404
    assert client.delete("/api/kb/documents/999999", headers=staff_headers).status_code == 403
    assert client.delete("/api/kb/documents/999999", headers=admin_headers).status_code == 404


def test_password_change_roundtrip(client, db_session) -> None:
    r = client.post("/api/auth/login", json={"username": "staff001", "password": "staff001"})
    token = r.json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    assert client.post(
        "/api/auth/change-password", headers=h,
        json={"old_password": "staff001", "new_password": "new-pass-123"},
    ).status_code == 200
    # 旧密码失效、新密码可登录
    assert client.post("/api/auth/login", json={"username": "staff001", "password": "staff001"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "staff001", "password": "new-pass-123"}).status_code == 200
    # 弱口令口径（阶段 5）：改密码不允许回到「密码 = 账号名」
    assert client.post(
        "/api/auth/change-password", headers=h,
        json={"old_password": "new-pass-123", "new_password": "staff001"},
    ).status_code == 400
    # 还原只能走库层（避免影响同会话其他用例的 staff_headers 登录）
    u = db_session.query(User).filter(User.username == "staff001").first()
    u.password_hash = hash_password("staff001")
    db_session.commit()
    assert client.post("/api/auth/login", json={"username": "staff001", "password": "staff001"}).status_code == 200


def test_session_isolation_between_users(client, owner_headers, staff_headers) -> None:
    r = client.post("/api/chat/sessions", headers=owner_headers, json={"title": "隔离测试"})
    assert r.status_code == 200
    sid = r.json()["id"]
    # 属主可见
    assert client.get(f"/api/chat/sessions/{sid}/messages", headers=owner_headers).status_code == 200
    # 其他用户（即便更高角色）按"不存在"处理，不泄露
    assert client.get(f"/api/chat/sessions/{sid}/messages", headers=staff_headers).status_code == 404


# ---------- 案例回流全流程（阶段 3 数据飞轮） ----------


def _make_diag_session(db, owner: User) -> ChatSession:
    session = ChatSession(tenant_id=1, user_id=owner.id, title="案例测试会话", channel="owner")
    db.add(session)
    db.flush()
    db.add(Message(tenant_id=1, session_id=session.id, role="user", content="车在慢充桩充不进电，充电灯闪烁"))
    db.add(Message(
        tenant_id=1, session_id=session.id, role="assistant", content="结论如下",
        diag_json={
            "severity": "yellow",
            "summary": "车载充电机或充电桩通讯故障",
            "hypotheses": [{"title": "充电桩输出异常"}, {"title": "车载充电机OBC故障"}],
            "steps": ["更换充电桩交叉验证", "读取OBC故障码"],
            "pending_checks": ["确认充电桩型号"],
        },
    ))
    db.commit()
    return session


def test_case_create_full_flow(client, staff_headers, db_session, monkeypatch) -> None:
    monkeypatch.setattr(ingest, "Embedder", _FakeEmbedder)
    owner = db_session.query(User).filter_by(username="user001").first()
    session = _make_diag_session(db_session, owner)

    # 无诊断结论的会话 → 400
    empty = ChatSession(tenant_id=1, user_id=owner.id, title="无诊断", channel="owner")
    db_session.add(empty)
    db_session.commit()
    r = client.post("/api/cases", headers=staff_headers, json={"session_id": empty.id, "repair_result": ""})
    assert r.status_code == 400
    assert client.post("/api/cases", headers=staff_headers, json={"session_id": 999999}).status_code == 404

    # 正常沉淀 → 200，且数据飞轮命中
    r = client.post(
        "/api/cases", headers=staff_headers,
        json={"session_id": session.id, "repair_result": "更换充电桩后恢复正常"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["chunks"] >= 1
    case_id, doc_id = body["id"], body["kb_document_id"]

    # 重复沉淀 → 409
    assert client.post(
        "/api/cases", headers=staff_headers, json={"session_id": session.id, "repair_result": "x"}
    ).status_code == 409

    case = db_session.get(Case, case_id)
    assert case is not None
    staff = db_session.query(User).filter_by(username="staff001").first()
    assert case.confirmed_by == staff.id
    assert "充电" in case.diagnosis
    assert case.repair_result == "更换充电桩后恢复正常"

    # 案例文档以 category=case 入库并进入 BM25 检索范围
    hits = bm25_hits(db_session, "更换充电桩后恢复正常")
    assert hits, "案例内容应可被 kb_search 检索命中"

    # 列表可见 + 审计落账
    lst = client.get("/api/cases", headers=staff_headers).json()["cases"]
    assert any(c["id"] == case_id for c in lst)
    assert db_session.query(AuditLog).filter_by(action="case_create").count() >= 1

    # 清理：删掉案例文档，避免污染同进程后续检索断言
    from backend.rag.ingest import delete_document
    delete_document(db_session, doc_id)


def bm25_hits(db, query: str) -> list[tuple[int, float]]:
    from backend.rag.bm25 import bm25_index
    return bm25_index.search(db, query, category="case", top_k=5)
