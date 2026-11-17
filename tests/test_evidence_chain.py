"""诊断阶段与证据链：编号分配、trace 落库、假设映射、车主可见性剥除。"""
from __future__ import annotations

import asyncio
import json

from backend.core.agent.runner import AgentRunner, normalize_diag, public_diag
from backend.core.providers.llm import ToolCall
from backend.core.tools.registry import EvidenceAllocator, ToolContext
from backend.db.models import Message, RetrievalTrace, Session as ChatSession, User
from backend.rag.retrieve import RetrievedChunk

FINAL_JSON = {
    "severity": "yellow",
    "summary": "低温导致续航衰减",
    "hypotheses": [{"title": "低温电池活性下降", "evidence": ["E1"]}],
    "steps": ["检查电池健康度"],
    "pending_checks": ["到店读 BMS 数据"],
}


class _FakeProvider:
    model = "fake-main"
    base_url = "https://api.deepseek.com"

    def __init__(self, script: list[list[dict]]):
        self.script = script
        self.calls = 0

    async def chat_stream(self, messages, tools=None, **params):
        index = min(self.calls, len(self.script) - 1)
        self.calls += 1
        for event in self.script[index]:
            yield event


def _tool_round(name: str, args: dict) -> list[dict]:
    return [{
        "type": "finish",
        "reason": "tool_calls",
        "tool_calls": [ToolCall(id=f"call_{name}", name=name, arguments=json.dumps(args, ensure_ascii=False))],
        "usage": {},
    }]


def _final_round(diag: dict) -> list[dict]:
    content = "解释文字。\n```json\n" + json.dumps(diag, ensure_ascii=False) + "\n```"
    return [
        {"type": "delta", "content": content},
        {"type": "finish", "reason": "stop", "tool_calls": [], "usage": {}},
    ]


def _new_session(db) -> ChatSession:
    owner = db.query(User).filter(User.username == "user001").one()
    session = ChatSession(tenant_id=1, user_id=owner.id, title="证据链测试", channel="owner")
    db.add(session)
    db.commit()
    return session


def _chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=1, document_id=2, document_title="动力电池知识",
        category="battery", section_path="低温衰减", page_no=None,
        content="低温环境下锂电池活性下降，续航会明显衰减。",
        score=0.91, legs=["vec"],
    )


class TestNormalize:
    def test_evidence_ids_kept_and_public_strips(self):
        diag = normalize_diag({
            "severity": "red",
            "hypotheses": [
                {"title": "A", "evidence": ["E1", "e2", "bad", "E1"]},
                {"title": "B", "evidence_ids": ["E3"]},
                "C",
            ],
        })
        assert diag["hypotheses"][0]["evidence_ids"] == ["E1", "E2"]
        assert diag["hypotheses"][1]["evidence_ids"] == ["E3"]
        assert diag["hypotheses"][2] == {"title": "C"}
        public = public_diag(diag)
        assert public["hypotheses"] == [{"title": "A"}, {"title": "B"}, {"title": "C"}]


class TestStage:
    def test_stage_transitions_record_history(self, db_session):
        session = _new_session(db_session)
        runner = AgentRunner(provider=_FakeProvider([_final_round(FINAL_JSON)]))
        runner._merge_case_notes(session, {"stage": "intake"})
        runner._merge_case_notes(session, {"stage": "verification", "symptoms": ["冬天掉电"]})
        runner._merge_case_notes(session, {"stage": "verification"})  # 重复阶段不追加
        notes = session.case_notes or {}
        assert notes["stage"] == "verification"
        assert [item["stage"] for item in notes["stage_history"]] == ["intake", "verification"]
        assert notes["symptoms"] == ["冬天掉电"]

    def test_tail_block_hides_stage_history(self, db_session):
        session = _new_session(db_session)
        session.case_notes = {
            "stage": "verification",
            "stage_history": [{"stage": "intake", "at": "2026-01-01T00:00:00"}],
            "symptoms": ["抖动"],
        }
        db_session.commit()
        runner = AgentRunner(provider=_FakeProvider([_final_round(FINAL_JSON)]))
        block = runner._build_tail_block(db_session, session)
        assert "stage_history" not in block
        assert "verification" in block


class TestRunnerEvidence:
    def _run_turn(self, db, session, provider, user_content="电池低温"):
        events: list[tuple[str, dict]] = []

        async def emit(name: str, payload: dict) -> None:
            events.append((name, payload))

        result = asyncio.run(provider_run(db, session, provider, user_content, emit))
        return result, events

    def test_evidence_persisted_and_mapped(self, db_session, monkeypatch):
        monkeypatch.setattr("backend.rag.retrieve.search", lambda *args, **kwargs: [_chunk()])
        session = _new_session(db_session)
        provider = _FakeProvider([
            _tool_round("kb_search", {"query": "低温 续航"}),
            _final_round(FINAL_JSON),
        ])
        result, events = self._run_turn(db_session, session, provider)
        assert result == "done"

        traces = db_session.query(RetrievalTrace).filter_by(session_id=session.id).all()
        assert len(traces) == 1
        trace = traces[0]
        assert trace.evidence_key == "E1"
        assert trace.kind == "kb"
        assert trace.provider == "kb"
        assert trace.query == "低温 续航"
        assert trace.message_id is not None

        message = db_session.get(Message, trace.message_id)
        assert message is not None and message.role == "assistant"
        assert message.diag_json["hypotheses"][0]["evidence_ids"] == ["E1"]

        diag_events = [payload for name, payload in events if name == "diag_final"]
        assert diag_events and "evidence_ids" not in diag_events[0]["hypotheses"][0]

        # 会话内编号继续递增（ask_user 续答/下一轮不冲突）
        provider2 = _FakeProvider([
            _tool_round("kb_search", {"query": "低温 续航"}),
            _final_round({**FINAL_JSON, "hypotheses": [{"title": "低温电池活性下降", "evidence": ["E2"]}]}),
        ])
        result2, _ = self._run_turn(db_session, session, provider2, user_content="继续")
        assert result2 == "done"
        traces = db_session.query(RetrievalTrace).filter_by(session_id=session.id).order_by(RetrievalTrace.id).all()
        assert [trace.evidence_key for trace in traces] == ["E1", "E2"]

    def test_allocator_shares_across_tools(self):
        allocator = EvidenceAllocator()
        ctx = ToolContext(evidence=allocator)
        assert [ctx.evidence.next(), ctx.evidence.next()] == ["E1", "E2"]


async def provider_run(db, session, provider, user_content, emit):
    runner = AgentRunner(provider=provider)
    return await runner.run_turn(db, session, [], user_content, emit)
