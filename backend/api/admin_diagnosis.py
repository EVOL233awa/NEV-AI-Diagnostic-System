"""管理员「诊断质控」接口：阶段时间线、假设↔证据映射、受控原文。

- 全部接口 require_roles("admin")，按 tenant_id 隔离。
- 对话原文仅在车主 privacy_share_dialog=true 时返回；未授权时 query 脱敏、
  网页证据只显示域名，避免车牌/VIN/症状原文泄漏。
- 证据链只读 retrieval_traces，不回填、不猜测；模型未输出编号的假设标记「未关联证据」。
"""
from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import distinct, func, or_, select

from backend.api.deps import DbSession, require_roles
from backend.core.agent.runner import VALID_STAGES, normalize_diag
from backend.db.models import (
    AuditLog,
    Message,
    RetrievalTrace,
    Session as ChatSession,
    User,
    VehicleProfile,
)

router = APIRouter(prefix="/api/admin/diagnosis", tags=["admin-diagnosis"])

STAGE_ORDER = {"intake": 0, "hypothesis": 1, "verification": 2, "conclusion": 3}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value else None


def _domain(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower()
    except ValueError:
        return ""


def _stage_info(db, session: ChatSession) -> dict:
    """模型记录优先；没记录时按消息形状确定性回退，并标注 inferred。"""
    notes = session.case_notes if isinstance(session.case_notes, dict) else {}
    recorded = notes.get("stage")
    history = notes.get("stage_history")
    if not isinstance(history, list):
        history = []
    if recorded in VALID_STAGES:
        return {"stage": recorded, "stage_history": history, "stage_inferred": False}

    has_diag = db.execute(
        select(Message.id)
        .where(Message.session_id == session.id, Message.diag_json.is_not(None))
        .limit(1)
    ).scalar() is not None
    has_tool = db.execute(
        select(Message.id)
        .where(Message.session_id == session.id, Message.role == "tool")
        .limit(1)
    ).scalar() is not None
    has_tool_calls = db.execute(
        select(Message.id)
        .where(Message.session_id == session.id, Message.tool_calls.is_not(None))
        .limit(1)
    ).scalar() is not None
    has_assistant = db.execute(
        select(Message.id)
        .where(Message.session_id == session.id, Message.role == "assistant", Message.content != "")
        .limit(1)
    ).scalar() is not None

    if has_diag:
        stage = "conclusion"
    elif has_tool or has_tool_calls or has_assistant:
        stage = "verification"
    else:
        stage = "intake"
    return {"stage": stage, "stage_history": history, "stage_inferred": True}


def _latest_diag(db, session_id: int) -> dict | None:
    row = db.execute(
        select(Message.diag_json)
        .where(Message.session_id == session_id, Message.diag_json.is_not(None))
        .order_by(Message.id.desc())
        .limit(1)
    ).scalar()
    return normalize_diag(row) if isinstance(row, dict) else None


def _session_row(db, session: ChatSession, owner: User | None, vehicle: VehicleProfile | None,
                 stage: dict, diag: dict | None) -> dict:
    return {
        "id": session.id,
        "title": session.title,
        "status": session.status,
        "channel": session.channel,
        "owner": {
            "id": owner.id if owner else None,
            "username": (owner.display_name or owner.username) if owner else "",
            "privacy_share_admin": bool(owner.privacy_share_dialog) if owner else False,
        },
        "vehicle": {
            "id": vehicle.id,
            "brand": vehicle.brand,
            "model_name": vehicle.model_name,
            "plate_no": vehicle.plate_no or "",
            "vin": vehicle.vin or "",
            "mileage": vehicle.mileage,
        } if vehicle else None,
        "severity": (diag or {}).get("severity", ""),
        "summary": (diag or {}).get("summary", ""),
        "message_count": int(db.execute(
            select(func.count(Message.id)).where(Message.session_id == session.id)
        ).scalar() or 0),
        "evidence_count": int(db.execute(
            select(func.count(RetrievalTrace.id)).where(RetrievalTrace.session_id == session.id)
        ).scalar() or 0),
        "stage": stage["stage"],
        "stage_inferred": stage["stage_inferred"],
        "has_conclusion": diag is not None,
        "updated_at": _iso(session.updated_at),
        "created_at": _iso(session.created_at),
    }


@router.get("/sessions")
def list_diagnosis_sessions(
    db: DbSession,
    admin: User = Depends(require_roles("admin")),
    status_filter: str | None = Query(default=None, alias="status"),
    severity: str | None = None,
    stage: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    if stage is not None and stage not in VALID_STAGES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "诊断阶段不合法")
    if limit < 1 or limit > 200:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "limit 需在 1~200 之间")
    if offset < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "offset 不能为负")

    query = (
        select(ChatSession, User, VehicleProfile)
        .join(User, ChatSession.user_id == User.id)
        .outerjoin(VehicleProfile, ChatSession.vehicle_id == VehicleProfile.id)
        .where(ChatSession.tenant_id == admin.tenant_id)
    )
    if status_filter in ("active", "closed"):
        query = query.where(ChatSession.status == status_filter)
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.where(or_(
            ChatSession.title.like(like),
            User.username.like(like),
            User.display_name.like(like),
            VehicleProfile.plate_no.like(like),
            VehicleProfile.vin.like(like),
            VehicleProfile.brand.like(like),
            VehicleProfile.model_name.like(like),
        ))
    rows = db.execute(query.order_by(ChatSession.updated_at.desc()).limit(500)).all()

    items: list[dict] = []
    for session, owner, vehicle in rows:
        info = _stage_info(db, session)
        if stage and info["stage"] != stage:
            continue
        diag = _latest_diag(db, session.id)
        if severity and (diag or {}).get("severity") != severity:
            continue
        items.append(_session_row(db, session, owner, vehicle, info, diag))

    total = len(items)
    return {"total": total, "items": items[offset:offset + limit]}


@router.get("/overview")
def diagnosis_overview(
    db: DbSession,
    admin: User = Depends(require_roles("admin")),
) -> dict:
    tid = admin.tenant_id
    day_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    total_sessions = int(db.execute(
        select(func.count(ChatSession.id)).where(ChatSession.tenant_id == tid)
    ).scalar() or 0)
    today_sessions = int(db.execute(
        select(func.count(ChatSession.id)).where(
            ChatSession.tenant_id == tid, ChatSession.created_at >= day_start
        )
    ).scalar() or 0)
    active_sessions = int(db.execute(
        select(func.count(ChatSession.id)).where(
            ChatSession.tenant_id == tid, ChatSession.status == "active"
        )
    ).scalar() or 0)
    conclusion_sessions = int(db.execute(
        select(func.count(distinct(Message.session_id)))
        .join(ChatSession, Message.session_id == ChatSession.id)
        .where(ChatSession.tenant_id == tid, Message.diag_json.is_not(None))
    ).scalar() or 0)

    diag_rows = db.execute(
        select(Message.diag_json)
        .join(ChatSession, Message.session_id == ChatSession.id)
        .where(ChatSession.tenant_id == tid, Message.diag_json.is_not(None))
    ).scalars().all()
    hypotheses_total = 0
    hypotheses_linked = 0
    for row in diag_rows:
        if not isinstance(row, dict):
            continue
        diag = normalize_diag(row)
        for item in diag.get("hypotheses", []):
            hypotheses_total += 1
            if item.get("evidence_ids"):
                hypotheses_linked += 1

    return {
        "today_sessions": today_sessions,
        "active_sessions": active_sessions,
        "total_sessions": total_sessions,
        "conclusion_sessions": conclusion_sessions,
        "conclusion_rate": round(conclusion_sessions / total_sessions, 3) if total_sessions else 0.0,
        "hypotheses_total": hypotheses_total,
        "hypotheses_linked": hypotheses_linked,
        "evidence_link_rate": round(hypotheses_linked / hypotheses_total, 3) if hypotheses_total else 0.0,
        "evidence_total": int(db.execute(
            select(func.count(RetrievalTrace.id)).where(RetrievalTrace.tenant_id == tid)
        ).scalar() or 0),
    }


@router.get("/sessions/{session_id}")
def diagnosis_detail(
    session_id: int,
    db: DbSession,
    admin: User = Depends(require_roles("admin")),
) -> dict:
    session = db.get(ChatSession, session_id)
    if session is None or session.tenant_id != admin.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在")
    owner = db.get(User, session.user_id)
    vehicle = db.get(VehicleProfile, session.vehicle_id) if session.vehicle_id else None
    raw_included = bool(owner and owner.privacy_share_dialog)
    stage = _stage_info(db, session)

    rows = db.execute(
        select(Message)
        .where(Message.session_id == session.id, Message.role.in_(("user", "assistant")))
        .order_by(Message.id)
    ).scalars().all()

    messages: list[dict] = []
    for row in rows:
        diag = normalize_diag(row.diag_json) if isinstance(row.diag_json, dict) else None
        messages.append({
            "id": row.id,
            "role": row.role,
            "created_at": _iso(row.created_at),
            "content": row.content if raw_included else "[车主未授权查看原文]",
            "diag": diag,
            "raw_included": raw_included,
        })

    trace_rows = db.execute(
        select(RetrievalTrace)
        .where(RetrievalTrace.session_id == session.id)
        .order_by(RetrievalTrace.id)
    ).scalars().all()

    traces: list[dict] = []
    trace_by_key: dict[str, dict] = {}
    for trace in trace_rows:
        item = {
            "id": trace.id,
            "message_id": trace.message_id,
            "evidence_key": trace.evidence_key,
            "kind": trace.kind,
            "provider": trace.provider,
            "rank": trace.rank,
            "domain": _domain(trace.url),
            "doc_id": trace.doc_id,
            "chunk_id": trace.chunk_id,
            "score": round(float(trace.score or 0.0), 6),
            "created_at": _iso(trace.created_at),
        }
        if raw_included:
            item.update({
                "query": trace.query,
                "title": trace.title,
                "url": trace.url,
                "section_path": trace.section_path,
                "snippet": trace.snippet,
            })
        elif trace.kind == "kb":
            # 知识库标题/章节/分数可给管理员复核；片段与 query 可能含车主原话，脱敏
            item.update({
                "query": "（车主未授权）",
                "title": trace.title,
                "url": "",
                "section_path": trace.section_path,
                "snippet": "",
            })
        else:
            item.update({
                "query": "（车主未授权）",
                "title": "",
                "url": "",
                "section_path": "",
                "snippet": "",
            })
        traces.append(item)
        if trace.evidence_key:
            trace_by_key[trace.evidence_key] = item

    evidence_map: list[dict] = []
    for message in messages:
        diag = message.get("diag")
        if not diag:
            continue
        for hypothesis in diag.get("hypotheses", []):
            ids = hypothesis.get("evidence_ids", [])
            linked = [trace_by_key[key] for key in ids if key in trace_by_key]
            evidence_map.append({
                "message_id": message["id"],
                "title": hypothesis.get("title", ""),
                "evidence": linked,
                "linked": bool(linked),
            })

    db.add(AuditLog(
        tenant_id=admin.tenant_id, user_id=admin.id,
        action="admin_view_diagnosis",
        detail={"session_id": session.id, "raw_included": raw_included},
    ))
    db.commit()

    return {
        "session": {
            "id": session.id,
            "title": session.title,
            "status": session.status,
            "channel": session.channel,
            "vehicle_id": session.vehicle_id,
            "case_notes": session.case_notes or {},
            "created_at": _iso(session.created_at),
            "updated_at": _iso(session.updated_at),
            "stage": stage["stage"],
            "stage_history": stage["stage_history"],
            "stage_inferred": stage["stage_inferred"],
        },
        "owner": {
            "id": owner.id if owner else None,
            "username": (owner.display_name or owner.username) if owner else "",
            "privacy_share_admin": raw_included,
        },
        "vehicle": {
            "id": vehicle.id,
            "brand": vehicle.brand,
            "model_name": vehicle.model_name,
            "model_year": vehicle.model_year,
            "plate_no": vehicle.plate_no or "",
            "vin": vehicle.vin or "",
            "mileage": vehicle.mileage,
        } if vehicle else None,
        "messages": messages,
        "traces": traces,
        "evidence_map": evidence_map,
        "raw_included": raw_included,
        "counts": {
            "kb_hits": sum(1 for trace in traces if trace["kind"] == "kb"),
            "web_hits": sum(1 for trace in traces if trace["kind"] == "web"),
            "hypotheses": len(evidence_map),
            "linked_hypotheses": sum(1 for item in evidence_map if item["linked"]),
        },
    }
