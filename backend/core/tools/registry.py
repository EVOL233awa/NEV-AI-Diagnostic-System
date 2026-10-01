"""Agent 工具层：注册给主模型的工具清单与执行器。

工具是模型手里随时可调用的能力；执行器只做只读/单步动作，
决策权（查什么、查几轮、何时下结论）始终归主模型（AstrBot ADR-002 边界）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.providers import tavily
from backend.core.providers.tavily import WebSearchUnavailable
from backend.db.models import KbChunk, KbDocument, Session as ChatSession, VehicleProfile
from backend.rag import retrieve

Handler = Callable[..., Awaitable[str]]


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Handler
    # ask_user 单轮上限 3，全工具单轮上限 6 由 runner 计数
    is_interaction: bool = False


@dataclass
class ToolContext:
    """本轮会话上下文：工具按当前会话的车主/车辆取数，不查全店。"""

    session: ChatSession | None = None


def _fmt_hits(results: list[retrieve.RetrievedChunk]) -> str:
    if not results:
        return "知识库无命中。请改用更短的关键词或换措辞再试；未命中应如实告知用户。"
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"[{i}] 来源：{r.document_title} > {r.section_path}" + (f"（第{r.page_no}页）" if r.page_no else ""))
        lines.append(r.content)
    return "\n\n".join(lines)


async def _tool_kb_search(db: Session, query: str, category: str | None = None, top_k: int = 5) -> str:
    results = retrieve.search(db, query, category=category, top_k=min(top_k, 8))
    return _fmt_hits(results)


async def _tool_dtc_lookup(db: Session, code: str) -> str:
    code = code.strip().upper()
    rows = db.execute(
        select(KbChunk.content, KbDocument.title)
        .join(KbDocument, KbChunk.document_id == KbDocument.id)
        .where(KbDocument.category == "dtc", KbChunk.section_path == code)
        .limit(3)
    ).all()
    if not rows:
        return f"码表中无 {code} 的通用定义。它可能是厂商专有码（P1xxx/U1xxx 段），请查对应厂商手册或用 kb_search 模糊检索。"
    return "\n\n".join(f"来源：{t}\n{c}" for c, t in rows)


async def _tool_web_search(db: Session, query: str) -> str:
    try:
        data = await tavily.search(query, max_results=5)
    except WebSearchUnavailable as exc:
        return f"联网检索暂不可用（{exc}）。请基于知识库与码表证据作答，并如实说明未能联网核实。"
    items = data["results"]
    if not items:
        return "联网检索无结果。请改写关键词再试或如实说明。"
    lines = []
    for i, r in enumerate(items, 1):
        lines.append(f"[网{i}] {r['title']}\n链接：{r['url']}\n{r['content']}")
    return "\n\n".join(lines)


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
            f"VIN {v.vin or '未登记'}，车牌 {v.plate_no or '未登记'}）"
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


async def _tool_get_vehicle_profile(db: Session, ctx: ToolContext) -> str:
    summary = vehicle_summary_line(db, ctx.session) if ctx.session else ""
    return summary or "当前车主未绑定车辆档案。可在对话中直接询问车主车型信息。"


TOOL_LIST_REMINDER = "（工具只查资料不替代判断；结论必须引用来源）"


def build_tool_specs(ctx: ToolContext | None = None) -> list[ToolSpec]:
    """工具 schema 清单。handler 签名统一 (db, **kwargs)，interaction 类工具由 runner 特殊处理。

    ctx 携带本轮会话（车主/车辆定位）；不传时 get_vehicle_profile 降级为无上下文提示。
    """

    async def _vehicle_profile_bound(db: Session) -> str:
        return await _tool_get_vehicle_profile(db, ctx or ToolContext())

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
            handler=_tool_kb_search,
        ),
        ToolSpec(
            name="dtc_lookup",
            description="按 OBD-II 故障码精确查询码表定义（区别于 kb_search 的模糊检索，直接命中码定义）。",
            parameters={
                "type": "object",
                "properties": {"code": {"type": "string", "description": "故障码，如 P0AA6"}},
                "required": ["code"],
            },
            handler=_tool_dtc_lookup,
        ),
        ToolSpec(
            name="web_search",
            description="联网检索（车型专属资料、最新通报等知识库没有的内容）。知识库查不到时再用，结果带来源链接。",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "联网检索词"}},
                "required": ["query"],
            },
            handler=_tool_web_search,
        ),
        ToolSpec(
            name="get_vehicle_profile",
            description="读取当前车主绑定的车辆档案与历史诊断记录（车型/VIN/动力类型/车主备注/近期结论）。开始诊断前建议先调用。",
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
