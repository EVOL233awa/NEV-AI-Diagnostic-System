"""build_history 工具调用配对回归（2026-09-27 验收修复锁定）。

背景：模型端要求 assistant.tool_calls 的每个调用都有配对 tool 消息。
用户跳过提问直接发新消息、ask_user 超限、同批并行调用未执行、中途异常，
都会在库里留下无响应的 tool_call——重放历史必须补合成存根，否则下一轮请求 400。
另锁定：检索结果超 2 轮瘦身、ask_user 车主回答不瘦身（那是诊断事实）。
"""
from __future__ import annotations

from sqlalchemy import select

from backend.api.chat import build_history
from backend.db.models import Message, Session as ChatSession, User


def _mk_session(db, user_id: int) -> ChatSession:
    s = ChatSession(tenant_id=1, user_id=user_id, title="配对测试")
    db.add(s)
    db.commit()
    return s


def _add(db, session_id: int, **kw) -> None:
    db.add(Message(tenant_id=1, session_id=session_id, **kw))
    db.commit()


def _call(cid: str, name: str) -> dict:
    return {"id": cid, "name": name, "arguments": "{}"}


def test_dangling_tool_call_gets_stub(db_session) -> None:
    user = db_session.scalar(select(User).where(User.username == "user001"))
    s = _mk_session(db_session, user.id)
    _add(db_session, s.id, role="user", content="车充不进电")
    # assistant 发起 kb_search 后异常中断：tool 结果行缺失
    _add(db_session, s.id, role="assistant", content="", tool_calls=[_call("c1", "kb_search")])

    history = build_history(db_session, s)
    tool_msgs = [m for m in history if m["role"] == "tool"]
    assert [t["tool_call_id"] for t in tool_msgs] == ["c1"]
    assert "未执行或未回答" in tool_msgs[0]["content"]
    # 合成行沿用 assistant 的 _id，压缩边界不会拆散配对
    asst = next(m for m in history if m["role"] == "assistant")
    assert tool_msgs[0]["_id"] == asst["_id"]


def test_ask_user_answer_not_slimmed_but_retrieval_is(db_session) -> None:
    user = db_session.scalar(select(User).where(User.username == "user001"))
    s = _mk_session(db_session, user.id)
    # 第 1 轮检索（应瘦身：tool_round=1 不 slim，再造第 3 轮触发）
    _add(db_session, s.id, role="user", content="冬天续航掉得快")
    _add(db_session, s.id, role="assistant", content="", tool_calls=[_call("c1", "kb_search")])
    _add(db_session, s.id, role="tool", content="A" * 500, tool_call_id="c1")
    # 第 2 轮提问 + 回答（车主回答永不清瘦）
    _add(db_session, s.id, role="assistant", content="", tool_calls=[_call("c2", "ask_user")])
    _add(db_session, s.id, role="tool", content="车主已补充回答：\n- 充电频率：每天一充", tool_call_id="c2")
    # 第 3 轮检索（tool_round=3 > 2 → 瘦身）
    _add(db_session, s.id, role="user", content="每天一充")
    _add(db_session, s.id, role="assistant", content="", tool_calls=[_call("c3", "kb_search")])
    _add(db_session, s.id, role="tool", content="B" * 500, tool_call_id="c3")

    by_id = {m["tool_call_id"]: m["content"] for m in build_history(db_session, s) if m["role"] == "tool"}
    # c1 属第 1 轮（tool_round=1 ≤ 2）不瘦身；c3 第 3 轮瘦身；c2 车主回答永不瘦身
    assert by_id["c1"] == "A" * 500
    assert by_id["c3"].startswith("（已查证并引用")
    assert "每天一充" in by_id["c2"]


def test_parallel_calls_paired_in_call_order(db_session) -> None:
    user = db_session.scalar(select(User).where(User.username == "user001"))
    s = _mk_session(db_session, user.id)
    _add(db_session, s.id, role="user", content="查一下")
    _add(
        db_session, s.id, role="assistant", content="",
        tool_calls=[_call("x1", "kb_search"), _call("x2", "dtc_lookup")],
    )
    _add(db_session, s.id, role="tool", content="码表结果", tool_call_id="x2")
    _add(db_session, s.id, role="tool", content="知识库结果", tool_call_id="x1")

    tools = [m for m in build_history(db_session, s) if m["role"] == "tool"]
    assert [(t["tool_call_id"], t["content"]) for t in tools] == [
        ("x1", "知识库结果"),
        ("x2", "码表结果"),
    ]
