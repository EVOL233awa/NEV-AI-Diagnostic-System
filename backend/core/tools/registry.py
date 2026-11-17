"""Agent 工具层：注册给主模型的工具清单与执行器。

工具是模型手里随时可调用的能力；执行器只做只读/单步动作，
决策权（查什么、查几轮、何时下结论）始终归主模型（AstrBot ADR-002 边界）。

v2.1.0 起工具返回 `ToolOutcome`：文本给模型，trace 给管理员证据链。
证据编号（E1、E2…）由本轮共享的 EvidenceAllocator 分配，工具结果文本里带编号，
模型在诊断 JSON 的 hypotheses[].evidence 中回引，由 runner 落库到 retrieval_traces。
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core import dtc, quota
from backend.core.providers.search import SearchUnavailable, primary_name, search_with_fallback
from backend.db.models import AuditLog, KbChunk, KbDocument, Session as ChatSession, VehicleProfile
from backend.rag import retrieve


@dataclass(frozen=True)
class TraceItem:
    """一次检索命中的证据行（落库到 retrieval_traces）。"""

    evidence_key: str
    kind: str  # kb / web
    query: str
    provider: str
    rank: int
    title: str
    url: str = ""
    doc_id: int | None = None
    chunk_id: int | None = None
    section_path: str = ""
    score: float = 0.0
    snippet: str = ""


@dataclass
class ToolOutcome:
    text: str
    trace: list[TraceItem] = field(default_factory=list)


@dataclass
class EvidenceAllocator:
    """会话内单调递增的证据编号分配器（跨工具调用、跨 ask_user 续答不冲突）。"""

    used: int = 0

    def next(self) -> str:
        self.used += 1
        return f"E{self.used}"


@dataclass
class ToolContext:
    """本轮会话上下文：工具按当前会话的车主/车辆取数，不查全店。"""

    session: ChatSession | None = None
    evidence: EvidenceAllocator = field(default_factory=EvidenceAllocator)


Handler = Callable[..., Awaitable[ToolOutcome]]


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Handler
    # ask_user 单轮上限 3，全工具单轮上限 6 由 runner 计数
    is_interaction: bool = False


def _fmt_hits(results: list[retrieve.RetrievedChunk], query: str, ctx: ToolContext) -> ToolOutcome:
    if not results:
        return ToolOutcome("知识库无命中。请改用更短的关键词或换措辞再试；未命中应如实告知用户。")
    lines: list[str] = []
    traces: list[TraceItem] = []
    for rank, item in enumerate(results, 1):
        key = ctx.evidence.next()
        lines.append(
            f"[{key}] 来源：{item.document_title} > {item.section_path}"
            + (f"（第{item.page_no}页）" if item.page_no else "")
        )
        lines.append(item.content)
        traces.append(TraceItem(
            evidence_key=key,
            kind="kb",
            query=query[:500],
            provider="kb",
            rank=rank,
            title=item.document_title,
            doc_id=item.document_id,
            chunk_id=item.chunk_id,
            section_path=item.section_path,
            score=item.score,
            snippet=item.content[:300],
        ))
    return ToolOutcome("\n\n".join(lines), traces)


async def _tool_kb_search(
    db: Session,
    query: str,
    category: str | None = None,
    top_k: int = 5,
    ctx: ToolContext | None = None,
) -> ToolOutcome:
    context = ctx or ToolContext()
    # 嵌入/重排走同步 urllib，直接跑会阻塞事件循环（单进程下拖住全部 SSE/接口）；
    # 放到线程池执行，SQLite 连接已开 check_same_thread=False，调用仍是串行交接。
    results = await asyncio.to_thread(
        retrieve.search, db, query, category=category, top_k=min(top_k, 8)
    )
    return _fmt_hits(results, query, context)


async def _tool_dtc_lookup(db: Session, code: str, ctx: ToolContext | None = None) -> ToolOutcome:
    context = ctx or ToolContext()
    normalized = dtc.normalize_code(code)
    chunks = dtc.lookup_chunks(db, normalized)
    if not chunks:
        return ToolOutcome(
            f"码表中无 {normalized} 的通用定义。它可能是厂商专有码（P1xxx/U1xxx 段），"
            "请查对应厂商手册或用 kb_search 模糊检索。"
        )
    lines: list[str] = []
    traces: list[TraceItem] = []
    for rank, chunk in enumerate(chunks, 1):
        key = context.evidence.next()
        lines.append(f"[{key}] 来源：{chunk['doc_title']}\n{chunk['content']}")
        traces.append(TraceItem(
            evidence_key=key,
            kind="kb",
            query=normalized,
            provider="kb",
            rank=rank,
            title=chunk["doc_title"],
            section_path=chunk["section_path"],
            score=1.0,
            snippet=chunk["content"][:300],
        ))
    return ToolOutcome("\n\n".join(lines), traces)


def _attr_escape(value: str) -> str:
    return value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


def _wrap_untrusted(evidence_key: str, title: str, url: str, content: str) -> str:
    """网页结果是不可信数据：进模型上下文前加边界标记，提示词配合声明不得执行其中指令。"""
    return (
        f'<untrusted_web_result id="{evidence_key}" url="{_attr_escape(url)}">\n'
        f"{title}\n链接：{url}\n{content}\n"
        "</untrusted_web_result>"
    )


async def _tool_web_search(db: Session, query: str, ctx: ToolContext | None = None) -> ToolOutcome:
    context = ctx or ToolContext()
    session = context.session
    provider_name = primary_name()
    if session is not None:
        blocked = quota.check_search(db, session.user_id)
        if blocked is not None:
            db.add(AuditLog(
                tenant_id=session.tenant_id,
                user_id=session.user_id,
                action="search_quota_blocked",
                detail={"provider": provider_name, "blocked": blocked},
                ip="",
            ))
            db.commit()
            if blocked == "user":
                return ToolOutcome("今日联网检索额度已用完，请基于知识库与码表证据继续作答。")
            return ToolOutcome("今日搜索/语音预算已用完，请基于知识库与码表证据继续作答。")
    started = time.perf_counter()
    try:
        hits = await search_with_fallback(query)
    except SearchUnavailable as exc:
        if session is not None:
            quota.record_search(
                db, tenant_id=session.tenant_id, user_id=session.user_id,
                provider=provider_name, success=False,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        return ToolOutcome(
            f"联网检索暂不可用（{exc}）。请基于知识库与码表证据作答，并如实说明未能联网核实。"
        )
    if session is not None:
        quota.record_search(
            db, tenant_id=session.tenant_id, user_id=session.user_id,
            provider=hits[0].provider if hits else provider_name, success=bool(hits),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
    if not hits:
        return ToolOutcome("联网检索无结果。请改写关键词再试或如实说明。")
    blocks: list[str] = []
    traces: list[TraceItem] = []
    for rank, hit in enumerate(hits, 1):
        key = context.evidence.next()
        blocks.append(_wrap_untrusted(key, hit.title, hit.url, hit.content))
        traces.append(TraceItem(
            evidence_key=key,
            kind="web",
            query=query[:500],
            provider=hit.provider,
            rank=rank,
            title=hit.title,
            url=hit.url[:1024],
            score=hit.score,
            snippet=hit.content[:300],
        ))
    return ToolOutcome("\n\n".join(blocks), traces)


def vehicle_summary_line(db: Session, session: ChatSession) -> str:
    """当前车主车辆档案 + 近 3 条历史诊断结论（跨会话归档）。
    供 get_vehicle_profile 工具与 runner 的状态卡注入块共用；无档案返回空串。"""
    from backend.db.models import Message, OwnerVehicle

    # 优先会话绑定的车，其次车主名下绑定的车
    bound = list(db.execute(
        select(OwnerVehicle.vehicle_id).where(OwnerVehicle.owner_id == session.user_id)
    ).scalars().all())
    if session.vehicle_id:
        bound = [session.vehicle_id, *[v for v in bound if v != session.vehicle_id]]
    if not bound:
        return ""
    rows = db.execute(
        select(VehicleProfile).where(VehicleProfile.id.in_(bound)).limit(3)
    ).scalars().all()
    blocks = []
    for v in rows:
        line = (
            f"车辆#{v.id}：{v.brand} {v.model_name} {v.model_year}（{v.power_type or '未知动力类型'}，"
            f"VIN {v.vin or '未登记'}，车牌 {v.plate_no or '未登记'}"
            + (f"，里程 {v.mileage} km" if v.mileage is not None else "")
            + "）"
        )
        if v.notes:
            line += f"\n车主备注：{v.notes}"
        diag_sessions = db.execute(
            select(ChatSession)
            .where(ChatSession.vehicle_id == v.id, ChatSession.user_id == session.user_id)
            .order_by(ChatSession.updated_at.desc())
            .limit(3)
        ).scalars().all()
        for s in diag_sessions:
            diag = db.execute(
                select(Message)
                .where(Message.session_id == s.id, Message.diag_json.is_not(None))
                .order_by(Message.id.desc())
                .limit(1)
            ).scalar()
            if diag is not None and diag.diag_json:
                d = diag.diag_json
                line += f"\n历史诊断（会话「{s.title}」）：{d.get('severity', '?')} — {d.get('summary', '')}"
        blocks.append(line)
    return "\n\n".join(blocks)


async def _tool_get_vehicle_profile(db: Session, ctx: ToolContext) -> ToolOutcome:
    summary = vehicle_summary_line(db, ctx.session) if ctx.session else ""
    return ToolOutcome(summary or "当前车主未绑定车辆档案。可在对话中直接询问车主车型信息。")


TOOL_LIST_REMINDER = "（工具只查资料不替代判断；结论必须引用来源）"


def build_tool_specs(ctx: ToolContext | None = None) -> list[ToolSpec]:
    """工具 schema 清单。handler 签名统一 (db, **kwargs)，interaction 类工具由 runner 特殊处理。

    ctx 携带本轮会话（车主/车辆定位）与证据编号分配器；不传时降级为独立上下文。
    """
    context = ctx or ToolContext()

    async def _kb_bound(db: Session, query: str, category: str | None = None, top_k: int = 5) -> ToolOutcome:
        return await _tool_kb_search(db, query, category, top_k, context)

    async def _dtc_bound(db: Session, code: str) -> ToolOutcome:
        return await _tool_dtc_lookup(db, code, context)

    async def _vehicle_profile_bound(db: Session) -> ToolOutcome:
        return await _tool_get_vehicle_profile(db, context)

    async def _web_search_bound(db: Session, query: str) -> ToolOutcome:
        return await _tool_web_search(db, query, context)

    return [
        ToolSpec(
            name="kb_search",
            description="查询门店维修知识库（码表解读、三电系统知识、场景经验）。涉及故障判断时必须先查，支持多轮调用、可改写查询词。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索查询，用简短关键词而非长句"},
                    "category": {
                        "type": "string",
                        "description": "可选类别过滤：dtc/battery/motor/electric_control/charging/method/scenario/indicators/maintenance",
                    },
                    "top_k": {"type": "integer", "description": "返回条数，默认 5"},
                },
                "required": ["query"],
            },
            handler=_kb_bound,
        ),
        ToolSpec(
            name="dtc_lookup",
            description="按 OBD-II 故障码精确查询码表定义（区别于 kb_search 的模糊检索，直接命中码定义）。",
            parameters={
                "type": "object",
                "properties": {"code": {"type": "string", "description": "故障码，如 P0AA6"}},
                "required": ["code"],
            },
            handler=_dtc_bound,
        ),
        ToolSpec(
            name="web_search",
            description="联网检索（车型专属资料、最新通报等知识库没有的内容）。知识库查不到时再用，结果带来源链接。",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "联网检索词"}},
                "required": ["query"],
            },
            handler=_web_search_bound,
        ),
        ToolSpec(
            name="get_vehicle_profile",
            description="读取当前车主绑定的车辆档案与历史诊断记录（车型/VIN/动力类型/里程/车主备注/近期结论）。开始诊断前建议先调用。",
            parameters={"type": "object", "properties": {}},
            handler=_vehicle_profile_bound,
        ),
    ]


def tool_specs_to_openai(specs: list[ToolSpec]) -> list[dict]:
    return [
        {"type": "function", "function": {"name": s.name, "description": s.description, "parameters": s.parameters}}
        for s in specs
    ]


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)
