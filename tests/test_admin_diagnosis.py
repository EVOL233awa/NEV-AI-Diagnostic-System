"""管理员诊断质控：权限、阶段回退、原文授权、trace 脱敏、假设↔证据映射、审计。"""
from __future__ import annotations

from backend.db.models import AuditLog, Message, RetrievalTrace, Session as ChatSession, User
from backend.seed.seed import SUPERADMIN_ENV_VAR, reset_superadmin_password


def _owner(db) -> User:
    return db.query(User).filter(User.username == "user001").one()


def _session(db, owner: User | None = None, title: str = "质控会话", notes: dict | None = None,
             status: str = "active") -> ChatSession:
    owner = owner or _owner(db)
    session = ChatSession(
        tenant_id=owner.tenant_id, user_id=owner.id, title=title, channel="owner",
        case_notes=notes, status=status,
    )
    db.add(session)
    db.commit()
    return session


def _message(db, session: ChatSession, role: str, content: str = "", diag: dict | None = None,
             tool_calls: list | None = None) -> Message:
    row = Message(
        tenant_id=session.tenant_id, session_id=session.id, role=role,
        content=content, diag_json=diag, tool_calls=tool_calls,
    )
    db.add(row)
    db.commit()
    return row


def _trace(db, session: ChatSession, message_id: int | None, key: str = "E1", kind: str = "kb",
           query: str = "车主原话 车牌桂A12345", title: str = "动力电池知识", url: str = "",
           snippet: str = "知识库原文片段") -> RetrievalTrace:
    row = RetrievalTrace(
        tenant_id=session.tenant_id, session_id=session.id, message_id=message_id,
        evidence_key=key, kind=kind, query=query, provider="kb" if kind == "kb" else "deepseek",
        rank=1, title=title, url=url, section_path="2.1 低温衰减" if kind == "kb" else "",
        score=0.8, snippet=snippet,
    )
    db.add(row)
    db.commit()
    return row


def _diag(evidence: list[str] | None = None) -> dict:
    hypothesis: dict = {"title": "低温电池活性下降"}
    if evidence is not None:
        hypothesis["evidence_ids"] = evidence
    return {
        "severity": "yellow",
        "summary": "低温导致续航衰减",
        "hypotheses": [hypothesis],
        "steps": ["检查电池健康度"],
        "pending_checks": ["到店读 BMS"],
    }


class TestAuthz:
    def test_anonymous_rejected(self, client):
        assert client.get("/api/admin/diagnosis/sessions").status_code == 401
        assert client.get("/api/admin/diagnosis/overview").status_code == 401

    def test_owner_and_staff_forbidden(self, client, owner_headers, staff_headers):
        for headers in (owner_headers, staff_headers):
            assert client.get("/api/admin/diagnosis/sessions", headers=headers).status_code == 403
            assert client.get("/api/admin/diagnosis/overview", headers=headers).status_code == 403
            assert client.get("/api/admin/diagnosis/sessions/1", headers=headers).status_code == 403

    def test_superadmin_forbidden(self, client, monkeypatch):
        monkeypatch.delenv(SUPERADMIN_ENV_VAR, raising=False)
        password = reset_superadmin_password()
        token = client.post("/api/auth/login", json={"username": "superadmin", "password": password}).json()["token"]
        r = client.get("/api/admin/diagnosis/sessions", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403


class TestStageFallback:
    def test_inferred_from_message_shape(self, client, db_session, admin_headers):
        session = _session(db_session, title="阶段回退-仅用户")
        _message(db_session, session, "user", "车放了一周打不着火")
        detail = client.get(f"/api/admin/diagnosis/sessions/{session.id}", headers=admin_headers).json()
        assert detail["session"]["stage"] == "intake"
        assert detail["session"]["stage_inferred"] is True

        tool_msg = _message(db_session, session, "tool", "检索结果")
        detail = client.get(f"/api/admin/diagnosis/sessions/{session.id}", headers=admin_headers).json()
        assert detail["session"]["stage"] == "verification"

        _message(db_session, session, "assistant", "结论", diag=_diag(["E1"]))
        detail = client.get(f"/api/admin/diagnosis/sessions/{session.id}", headers=admin_headers).json()
        assert detail["session"]["stage"] == "conclusion"
        assert tool_msg.id  # 使用一次，保留变量语义

    def test_recorded_stage_wins(self, client, db_session, admin_headers):
        session = _session(db_session, title="阶段回退-模型记录", notes={
            "stage": "hypothesis",
            "stage_history": [{"stage": "intake", "at": "2026-01-01T00:00:00"},
                              {"stage": "hypothesis", "at": "2026-01-01T00:01:00"}],
        })
        _message(db_session, session, "user", "抖动")
        detail = client.get(f"/api/admin/diagnosis/sessions/{session.id}", headers=admin_headers).json()
        assert detail["session"]["stage"] == "hypothesis"
        assert detail["session"]["stage_inferred"] is False
        assert len(detail["session"]["stage_history"]) == 2


class TestDetailPrivacy:
    def test_unauthorized_redacts_content_and_query(self, client, db_session, admin_headers):
        owner = _owner(db_session)
        owner.privacy_share_dialog = False
        db_session.commit()
        session = _session(db_session, owner=owner, title="质控隐私-未授权")
        _message(db_session, session, "user", "我的车牌桂A12345，电池故障")
        assistant = _message(db_session, session, "assistant", "诊断结果", diag=_diag(["E1", "E9"]))
        _trace(db_session, session, assistant.id, key="E1", kind="kb")
        _trace(db_session, session, assistant.id, key="E2", kind="web",
               title="含症状的网页标题", url="https://www.autohome.com.cn/a/1", query="桂A12345 电池")

        detail = client.get(f"/api/admin/diagnosis/sessions/{session.id}", headers=admin_headers).json()
        assert detail["raw_included"] is False
        user_msg = next(m for m in detail["messages"] if m["role"] == "user")
        assert user_msg["content"] == "[车主未授权查看原文]"
        trace = next(t for t in detail["traces"] if t["evidence_key"] == "E1")
        assert trace["query"] == "（车主未授权）"
        assert trace["title"] == "动力电池知识"  # 知识库标题仍可见
        assert trace["snippet"] == ""
        web = next(t for t in detail["traces"] if t["evidence_key"] == "E2")
        assert web["query"] == "（车主未授权）"
        assert web["title"] == "" and web["url"] == ""
        assert web["domain"] == "www.autohome.com.cn"

        # 假设↔证据映射：E1 已关联，E9 未关联
        mapping = {item["title"]: item for item in detail["evidence_map"]}
        assert mapping["低温电池活性下降"]["linked"] is True
        assert [e["evidence_key"] for e in mapping["低温电池活性下降"]["evidence"]] == ["E1"]
        assert detail["counts"]["hypotheses"] == 1
        assert detail["counts"]["linked_hypotheses"] == 1

        audit = (db_session.query(AuditLog)
                 .filter_by(action="admin_view_diagnosis")
                 .order_by(AuditLog.id.desc()).first())
        assert audit is not None
        assert audit.detail["session_id"] == session.id
        assert audit.detail["raw_included"] is False

    def test_authorized_shows_raw_text(self, client, db_session, admin_headers):
        owner = _owner(db_session)
        owner.privacy_share_dialog = True
        db_session.commit()
        session = _session(db_session, owner=owner, title="质控隐私-已授权")
        _message(db_session, session, "user", "我的车牌桂A12345，电池故障")
        assistant = _message(db_session, session, "assistant", "诊断结果", diag=_diag(["E1"]))
        _trace(db_session, session, assistant.id, key="E1", kind="kb")

        detail = client.get(f"/api/admin/diagnosis/sessions/{session.id}", headers=admin_headers).json()
        assert detail["raw_included"] is True
        user_msg = next(m for m in detail["messages"] if m["role"] == "user")
        assert "桂A12345" in user_msg["content"]
        trace = detail["traces"][0]
        assert "桂A12345" in trace["query"]
        assert trace["snippet"] == "知识库原文片段"
        owner.privacy_share_dialog = False
        db_session.commit()


class TestListAndOverview:
    def test_filters(self, client, db_session, admin_headers):
        owner = _owner(db_session)
        red_session = _session(db_session, owner=owner, title="筛选样本-红", notes={"stage": "conclusion"})
        green_session = _session(db_session, owner=owner, title="筛选样本-绿", status="closed")
        _message(db_session, red_session, "assistant", "结论", diag={**_diag(["E1"]), "severity": "red"})
        _message(db_session, green_session, "user", "咨询")

        body = client.get(
            "/api/admin/diagnosis/sessions",
            headers=admin_headers,
            params={"q": "筛选样本", "severity": "red"},
        ).json()
        assert body["total"] == 1 and body["items"][0]["id"] == red_session.id

        body = client.get(
            "/api/admin/diagnosis/sessions",
            headers=admin_headers,
            params={"q": "筛选样本", "stage": "conclusion"},
        ).json()
        assert body["total"] == 1 and body["items"][0]["id"] == red_session.id

        body = client.get(
            "/api/admin/diagnosis/sessions",
            headers=admin_headers,
            params={"q": "筛选样本", "status": "closed"},
        ).json()
        assert body["total"] == 1 and body["items"][0]["id"] == green_session.id

        body = client.get(
            "/api/admin/diagnosis/sessions",
            headers=admin_headers,
            params={"q": "筛选样本", "stage": "bad-stage"},
        )
        assert body.status_code == 400

    def test_overview_fields(self, client, admin_headers):
        body = client.get("/api/admin/diagnosis/overview", headers=admin_headers).json()
        for key in ("today_sessions", "active_sessions", "total_sessions", "conclusion_sessions",
                    "conclusion_rate", "hypotheses_total", "hypotheses_linked",
                    "evidence_link_rate", "evidence_total"):
            assert key in body
        assert 0 <= body["evidence_link_rate"] <= 1
