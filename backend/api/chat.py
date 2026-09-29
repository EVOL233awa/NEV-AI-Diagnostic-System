"""诊断会话路由：会话 CRUD + 流式对话（SSE）+ ask_user 离线续答。"""
from __future__ import annotations

import asyncio
import json
from typing import Annotated, AsyncIterator, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from backend.api.deps import CurrentUser, DbSession
from backend.core.agent.extractor import extract_case_notes, generate_session_title
from backend.core.agent.runner import AgentRunner
from backend.db.base import SessionLocal
from backend.db.models import Message, OwnerVehicle, Session as ChatSession

router = APIRouter(prefix="/api/chat", tags=["chat"])

# 历史里工具结果全文保留的最近轮数（§6.1：当轮全文 + 2 轮后历史瘦身）
SLIM_TOOL_ROUNDS = 2


class CreateSessionIn(BaseModel):
    title: str = Field(default="新诊断会话", max_length=128)


class SendIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class AnswerIn(BaseModel):
    answers: list[dict] = Field(min_length=1)  # [{id, value}]


def _get_session(db: DbSession, session_id: int, user: CurrentUser) -> ChatSession:
    session = db.get(ChatSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在")
    return session


def build_history(db: DbSession, session: ChatSession) -> list[dict]:
    """messages 表 → OpenAI 消息序列。

    工具结果按 tool_call_id 与 assistant.tool_calls 严格配对重放（§6.1：超过 2 轮的
    检索结果瘦身为一行摘要；ask_user 的车主回答不瘦身——那是诊断事实，丢了压缩也补不回）。
    模型端要求每个 tool_call 都有配对的 tool 消息：用户跳过提问直接发新消息、ask_user
    超限、同批并行调用未执行、中途异常等留下的无响应调用一律补合成存根，
    否则下一轮请求会被 API 以 400 拒收。
    每条带 "_id" 内部键供压缩边界定位（发送前由 compressor._strip_internal 剥除；
    合成行沿用所属 assistant 的 _id，保证压缩边界不拆散配对）。
    """
    rows = db.execute(
        select(Message).where(Message.session_id == session.id).order_by(Message.id)
    ).scalars().all()
    tool_results = {
        m.tool_call_id: m.content
        for m in rows
        if m.role == "tool" and m.tool_call_id
    }
    history: list[dict] = []
    tool_round = 0
    for m in rows:
        if m.role == "user":
            history.append({"_id": m.id, "role": "user", "content": m.content})
        elif m.role == "assistant":
            calls = m.tool_calls or []
            if calls:
                # ask_user 的调用同样重放：OpenAI 格式要求后续 tool 消息有配对的 assistant tool_calls
                tool_round += 1
                history.append(
                    {
                        "_id": m.id,
                        "role": "assistant",
                        "content": m.content,
                        "tool_calls": [
                            {"id": c["id"], "type": "function",
                             "function": {"name": c["name"], "arguments": c["arguments"]}}
                            for c in calls
                        ],
                    }
                )
                for c in calls:
                    content = tool_results.get(c["id"])
                    if content is None:
                        content = "（该调用未执行或未回答，用户已跳过）"
                    elif tool_round > SLIM_TOOL_ROUNDS and c.get("name") != "ask_user":
                        content = "（已查证并引用，原文已瘦身）"
                    history.append({"_id": m.id, "role": "tool", "tool_call_id": c["id"], "content": content})
            elif m.content:
                history.append({"_id": m.id, "role": "assistant", "content": m.content})
        # role == "tool"：已按 tool_call_id 并入上方 assistant 的配对输出，不再单独重放
    return history


@router.post("/sessions")
def create_session(body: CreateSessionIn, user: CurrentUser, db: DbSession) -> dict:
    # 新会话自动绑定车主默认车辆（§6 记忆层 2：按车归档，历史诊断跨会话可查）
    default_vehicle_id = db.execute(
        select(OwnerVehicle.vehicle_id)
        .where(OwnerVehicle.owner_id == user.id, OwnerVehicle.is_default.is_(True))
        .limit(1)
    ).scalar()
    session = ChatSession(
        tenant_id=user.tenant_id, user_id=user.id, title=body.title, channel="owner",
        vehicle_id=default_vehicle_id,
    )
    db.add(session)
    db.commit()
    return {"id": session.id, "title": session.title}


@router.get("/sessions")
def list_sessions(user: CurrentUser, db: DbSession) -> dict:
    rows = db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == user.id)
        .order_by(ChatSession.updated_at.desc())
        .limit(50)
    ).scalars().all()
    return {
        "sessions": [
            {"id": s.id, "title": s.title, "status": s.status, "has_pending": bool(s.pending_questions)}
            for s in rows
        ]
    }


@router.get("/sessions/{session_id}/messages")
def list_messages(session_id: int, user: CurrentUser, db: DbSession) -> dict:
    """历史消息回放：assistant 条目附带 tools 轨迹（工具调用+结果摘要），
    前端重开会话时才能还原查证时间线。ask_user 由前端渲染为提问卡片，不进轨迹。
    """
    session = _get_session(db, session_id, user)
    rows = db.execute(
        select(Message).where(Message.session_id == session.id).order_by(Message.id)
    ).scalars().all()
    tool_results = {
        m.tool_call_id: m.content
        for m in rows
        if m.role == "tool" and m.tool_call_id
    }

    def _traces(calls: list[dict] | None) -> list[dict]:
        return [
            {
                "name": c.get("name", ""),
                "arguments": c.get("arguments", ""),
                # 结果只回传前 200 字（前端只用完成态做展示），整段结果留库
                "result": (tool_results.get(c.get("id", "")) or "")[:200],
            }
            for c in (calls or [])
            if c.get("name") != "ask_user"
        ]

    messages: list[dict] = []
    pending_traces: list[dict] = []

    def _flush() -> None:
        # 纯工具轮（正文为空）也要回传轨迹，否则重开后查证过程消失
        if pending_traces:
            messages.append({"id": 0, "role": "assistant", "content": "", "diag": None, "tools": list(pending_traces)})
            pending_traces.clear()

    for m in rows:
        if m.role == "user":
            _flush()
            if m.content:
                messages.append({"id": m.id, "role": "user", "content": m.content, "diag": None, "tools": []})
        elif m.role == "assistant":
            pending_traces.extend(_traces(m.tool_calls))
            if m.content or m.diag_json:
                messages.append({
                    "id": m.id,
                    "role": "assistant",
                    "content": m.content,
                    "diag": m.diag_json,
                    "tools": list(pending_traces),
                })
                pending_traces.clear()
    _flush()
    return {"messages": messages, "pending_questions": session.pending_questions}


def _spawn_case_notes_extraction(session_id: int, content: str) -> None:
    """新会话首条描述 → 本地小模型异步抽取状态卡初稿（§6.1：不阻塞主对话，失败留空）。"""

    async def _run() -> None:
        notes = await extract_case_notes(content)
        if not notes:
            return
        db = SessionLocal()
        try:
            session = db.get(ChatSession, session_id)
            if session is not None and not session.case_notes:
                session.case_notes = notes
                db.commit()
        finally:
            db.close()

    asyncio.create_task(_run())


def _spawn_title_generation(session_id: int, content: str) -> None:
    """新会话首条描述 → 本地小模型异步生成会话标题。

    只覆盖默认标题「新诊断会话」；用户建会话时自定义的名字不覆盖。失败静默保留原标题。
    """

    async def _run() -> None:
        db = SessionLocal()
        try:
            session = db.get(ChatSession, session_id)
            if session is None or session.title != "新诊断会话":
                return
        finally:
            db.close()
        title = await generate_session_title(content)
        if not title:
            return
        db = SessionLocal()
        try:
            session = db.get(ChatSession, session_id)
            # 双检：等待模型期间用户可能已手动改名，不再覆盖
            if session is not None and session.title == "新诊断会话":
                session.title = title
                db.commit()
        finally:
            db.close()

    asyncio.create_task(_run())


@router.post("/sessions/{session_id}/send")
async def send_message(session_id: int, body: SendIn, user: CurrentUser, db: DbSession) -> StreamingResponse:
    session = _get_session(db, session_id, user)
    first_user_message = not db.execute(
        select(Message.id)
        .where(Message.session_id == session.id, Message.role == "user")
        .limit(1)
    ).scalar()
    if first_user_message and not session.case_notes:
        _spawn_case_notes_extraction(session.id, body.content)
    if first_user_message:
        _spawn_title_generation(session.id, body.content)
    history = build_history(db, session)
    return StreamingResponse(
        _stream_turn(db, session, history, body.content, None),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/sessions/{session_id}/answers")
async def answer_questions(session_id: int, body: AnswerIn, user: CurrentUser, db: DbSession) -> StreamingResponse:
    """ask_user 离线续答：回答作为工具结果回填，Agent 循环继续出结论。"""
    session = _get_session(db, session_id, user)
    pending = session.pending_questions
    if not pending:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "当前没有待回答的问题")

    pending_ids = {p.get("id"): p for p in pending}
    lines = []
    for a in body.answers:
        q = pending_ids.get(a.get("id"))
        if q is None:
            continue
        lines.append(f"- {q.get('question', a.get('id'))}：{a.get('value', '')}")
    if not lines:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "回答与问题不匹配")
    tool_text = "车主已补充回答：\n" + "\n".join(lines) + "\n请结合这些信息继续诊断。"

    # 找到挂起的 ask_user 调用 id（最近一条含 ask_user 的 assistant 消息）
    ask_msg = db.execute(
        select(Message)
        .where(Message.session_id == session.id, Message.role == "assistant")
        .order_by(Message.id.desc())
        .limit(10)
    ).scalars().all()
    tool_call_id = ""
    for m in ask_msg:
        for c in m.tool_calls or []:
            if c.get("name") == "ask_user":
                tool_call_id = c["id"]
                break
        if tool_call_id:
            break
    if not tool_call_id:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "找不到挂起的提问调用")

    session.pending_questions = None
    db.add(Message(tenant_id=session.tenant_id, session_id=session.id, role="tool",
                   content=tool_text, tool_call_id=tool_call_id))
    db.commit()

    history = build_history(db, session)
    return StreamingResponse(
        _stream_turn(db, session, history, None, None),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _stream_turn(
    db: DbSession,
    session: ChatSession,
    history: list[dict],
    user_content: str | None,
    prefill: list[dict] | None,
) -> AsyncIterator[str]:
    """把 AgentRunner 的事件经队列桥接为 SSE 字节流。"""
    queue: asyncio.Queue = asyncio.Queue()
    runner = AgentRunner()

    async def emit(event: str, payload: dict) -> None:
        await queue.put((event, payload))

    async def run() -> None:
        try:
            final = await runner.run_turn(db, session, history, user_content, emit)
            await queue.put(("stream_end", {"status": final}))
        except Exception as exc:  # noqa: BLE001  兜底转 SSE 错误事件
            await queue.put(("error", {"message": f"服务内部错误：{exc}"}))
            await queue.put(("stream_end", {"status": "error"}))

    task = asyncio.create_task(run())
    try:
        while True:
            event, payload = await queue.get()
            if event == "stream_end":
                yield f"event: stream_end\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                break
            yield f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
    finally:
        task.cancel()
