"""聊天流异常脱敏：客户端只收到通用错误 + 编号，不暴露内部异常文本。"""
from __future__ import annotations

import asyncio

import backend.api.chat as chat_api
from backend.db.models import Session as ChatSession, User


def test_stream_turn_hides_internal_exception(client, db_session, monkeypatch) -> None:
    owner = db_session.query(User).filter_by(username="user001").one()
    session = ChatSession(tenant_id=1, user_id=owner.id, title="异常脱敏", channel="owner")
    db_session.add(session)
    db_session.commit()

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("sqlite:///D:/nev-diag/data/data.db 内部路径")

    monkeypatch.setattr(chat_api.AgentRunner, "run_turn", _boom)

    async def _collect() -> str:
        return "".join([
            chunk async for chunk in chat_api._stream_turn(
                db_session, session, [], "你好", None
            )
        ])

    text = asyncio.run(_collect())
    assert "服务内部错误" in text
    assert "编号" in text
    assert "sqlite:///" not in text
    assert "内部路径" not in text
    assert "event: stream_end" in text
