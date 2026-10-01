"""门店案例回流（数据飞轮）。

技师确认诊断结论 → 沉淀为案例：cases 表存档 + 以 category="case" 摄入知识库，
立即进入 kb_search 检索范围。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from backend.api.deps import DbSession, require_roles
from backend.core.agent.runner import normalize_diag
from backend.db.models import AuditLog, Case, Message, Session as ChatSession, User
from backend.rag import ingest

router = APIRouter(prefix="/api/cases", tags=["cases"])

# 诊断结论文本里的严重度前缀用中文动作词（车主/店员都不读英文等级；与前端 SEVERITY_LABEL 同口径）
SEVERITY_ZH = {"red": "需尽快检修", "yellow": "建议到店检查", "green": "正常"}


class CreateCaseIn(BaseModel):
    session_id: int = Field(gt=0)
    repair_result: str = Field(default="", max_length=2000, description="维修/验证结果（可回填）")


def _case_markdown(symptoms: str, diagnosis: str, repair: str, vehicle: str) -> str:
    parts = []
    if vehicle:
        parts.append(f"## 车辆\n{vehicle}")
    parts.append(f"## 症状\n{symptoms or '（未记录）'}")
    parts.append(f"## 诊断结论\n{diagnosis or '（未记录）'}")
    if repair:
        parts.append(f"## 维修验证\n{repair}")
    return "\n\n".join(parts)


@router.post("")
def create_case(
    body: CreateCaseIn,
    db: DbSession,
    user: User = Depends(require_roles("staff", "admin")),
) -> dict:
    session = db.get(ChatSession, body.session_id)
    if session is None or session.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在")
    dup = db.execute(select(Case.id).where(Case.session_id == session.id).limit(1)).scalar()
    if dup:
        raise HTTPException(status.HTTP_409_CONFLICT, "该会话已沉淀过案例")

    diag_msg = db.execute(
        select(Message)
        .where(Message.session_id == session.id, Message.diag_json.is_not(None))
        .order_by(Message.id.desc())
        .limit(1)
    ).scalar()
    if diag_msg is None or not diag_msg.diag_json:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "会话还没有结构化诊断结论，无法沉淀")
    diag = normalize_diag(diag_msg.diag_json)  # 旧行可能是字符串数组等未守契约形状，先归一
    first_user = db.execute(
        select(Message)
        .where(Message.session_id == session.id, Message.role == "user")
        .order_by(Message.id)
        .limit(1)
    ).scalar()
    symptoms = first_user.content if first_user else ""

    notes = session.case_notes or {}
    vehicle = str(notes.get("vehicle", "") or "")
    diagnosis_text = "\n".join(
        [f"【{SEVERITY_ZH.get(diag.get('severity', '?'), diag.get('severity', '?'))}】{diag.get('summary', '')}"]
        + [f"- {h.get('title', '')}" for h in diag.get("hypotheses", [])]
        + [f"待确认：{c}" for c in diag.get("pending_checks", [])]
    )

    case = Case(
        tenant_id=session.tenant_id,
        vehicle_id=session.vehicle_id,
        session_id=session.id,
        title=diag.get("summary", session.title)[:256],
        symptoms=symptoms,
        diagnosis=diagnosis_text,
        repair_result=body.repair_result,
        confirmed_by=user.id,
    )
    db.add(case)
    db.flush()

    # 数据飞轮：案例以 category="case" 摄入知识库，立即进入 kb_search 检索范围
    # min_chunk_chars=1：案例各节普遍很短，禁用最小块长过滤，否则整篇会被丢成 0 块
    doc, chunks = ingest.ingest_document(
        db,
        title=f"案例：{case.title}"[:256],
        category="case",
        source_note=f"会话 #{session.id} 技师确认沉淀",
        markdown_text=_case_markdown(symptoms, diagnosis_text, body.repair_result, vehicle),
        min_chunk_chars=1,
    )

    db.add(
        AuditLog(
            tenant_id=session.tenant_id,
            user_id=user.id,
            action="case_create",
            detail={"case_id": case.id, "session_id": session.id, "kb_document_id": doc.id},
            ip="",
        )
    )
    db.commit()
    return {"id": case.id, "kb_document_id": doc.id, "chunks": len(chunks), "created_at": case.created_at.isoformat()}


@router.get("")
def list_cases(
    db: DbSession,
    user: User = Depends(require_roles("staff", "admin")),
) -> dict:
    rows = db.execute(
        select(Case)
        .where(Case.tenant_id == user.tenant_id)
        .order_by(Case.created_at.desc())
        .limit(100)
    ).scalars().all()
    return {
        "cases": [
            {
                "id": c.id,
                "session_id": c.session_id,
                "vehicle_id": c.vehicle_id,
                "title": c.title,
                "symptoms": c.symptoms,
                "diagnosis": c.diagnosis,
                "repair_result": c.repair_result,
                "confirmed_by": c.confirmed_by,
                "created_at": c.created_at.isoformat() if isinstance(c.created_at, datetime) else None,
            }
            for c in rows
        ]
    }
