"""预约闭环（§8 商用核心）：车主一键预约 → 店员接单/改约 → 回填结果 → 取消。

- 预约时间精确到时间点（2026-09-26 用户裁定）；店员接单时可改约。
- summary_card 诊断摘要卡不受隐私开关影响、始终对店员可见（决策 #15）；
  对话原文仅在车主 privacy_share_dialog 开启时可经 /{id}/dialog 查看（用户裁定）。
- 全查询按 tenant_id 过滤（多店隔离开启，决策 #4）。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from backend.api.deps import DbSession, require_roles
from backend.core.agent.runner import normalize_diag
from backend.db.models import Appointment, AuditLog, Message, OwnerVehicle, Session as ChatSession, User, VehicleProfile

router = APIRouter(prefix="/api/appointments", tags=["appointments"])

ACTIVE_STATUSES = ("pending", "accepted")


def _naive(dt: datetime) -> datetime:
    """前端可能发带时区的 ISO 串（aware），库内一律 naive 本地时间——比较/入库前归一。"""
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _summary_card(diag: dict | None) -> dict | None:
    """diag_json → 预约摘要卡（快照，店员接单依据；不含检索引用）。"""
    if not diag:
        return None
    # 历史行可能存着模型未守契约的原始形状（如 hypotheses 为字符串数组），先归一
    diag = normalize_diag(diag)
    return {
        "severity": diag.get("severity", "?"),
        "summary": diag.get("summary", ""),
        "hypotheses": [h.get("title", "") for h in diag.get("hypotheses", []) if isinstance(h, dict)],
        "steps": [s for s in diag.get("steps", []) if isinstance(s, str)],
        "pending_checks": [c for c in diag.get("pending_checks", []) if isinstance(c, str)],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def _vehicle_line(vehicle: VehicleProfile | None) -> str:
    if vehicle is None:
        return ""
    bits = [vehicle.brand, vehicle.model_name, vehicle.model_year, vehicle.plate_no or ""]
    return " ".join(b for b in bits if b)


def _appointment_row(db, a: Appointment) -> dict:
    owner = db.get(User, a.owner_id)
    vehicle = db.get(VehicleProfile, a.vehicle_id) if a.vehicle_id else None
    return {
        "id": a.id,
        "status": a.status,
        "appointment_time": a.appointment_time.isoformat(timespec="minutes") if a.appointment_time else None,
        "summary_card": a.summary_card,
        "shop_note": a.shop_note,
        "repair_result": a.repair_result,
        "accepted_by": a.accepted_by,
        "session_id": a.session_id,
        "created_at": a.created_at.isoformat(timespec="seconds") if a.created_at else None,
        "owner_name": (owner.display_name or owner.username) if owner else "",
        "owner_privacy_share": owner.privacy_share_dialog if owner else False,
        "vehicle": _vehicle_line(vehicle),
    }


def _get_appointment(db, appointment_id: int, user: User) -> Appointment:
    a = db.get(Appointment, appointment_id)
    if a is None or a.tenant_id != user.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "预约不存在")
    if user.role == "owner" and a.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "预约不存在")
    return a


class CreateAppointmentIn(BaseModel):
    session_id: int | None = Field(default=None, gt=0, description="来源诊断会话（一键预约时带上）")
    appointment_time: datetime = Field(description="期望到店时间（精确到分钟）")
    note: str = Field(default="", max_length=300, description="车主补充说明（并入摘要卡）")


@router.post("", status_code=status.HTTP_201_CREATED)
def create_appointment(body: CreateAppointmentIn, db: DbSession, user: User = Depends(require_roles("owner"))) -> dict:
    wanted = _naive(body.appointment_time)
    if wanted < datetime.now():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "预约时间不能早于当前时间")

    session = None
    summary_card: dict | None = None
    vehicle_id: int | None = None
    if body.session_id:
        session = db.get(ChatSession, body.session_id)
        if session is None or session.tenant_id != user.tenant_id or session.user_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在")
        diag = db.execute(
            select(Message.diag_json)
            .where(Message.session_id == session.id, Message.diag_json.is_not(None))
            .order_by(Message.id.desc())
            .limit(1)
        ).scalar()
        summary_card = _summary_card(diag)
        if body.note:
            if summary_card is None:
                summary_card = {"note": body.note, "generated_at": datetime.now().isoformat(timespec="seconds")}
            else:
                summary_card["note"] = body.note
        vehicle_id = session.vehicle_id
    if vehicle_id is None:
        vehicle_id = db.execute(
            select(OwnerVehicle.vehicle_id)
            .where(OwnerVehicle.owner_id == user.id, OwnerVehicle.is_default.is_(True))
            .limit(1)
        ).scalar()

    appt = Appointment(
        tenant_id=user.tenant_id,
        owner_id=user.id,
        vehicle_id=vehicle_id,
        session_id=session.id if session else None,
        summary_card=summary_card,
        appointment_time=wanted,
        status="pending",
    )
    db.add(appt)
    db.flush()
    db.add(AuditLog(
        tenant_id=user.tenant_id, user_id=user.id, action="appointment_create",
        detail={"appointment_id": appt.id, "session_id": body.session_id},
    ))
    db.commit()
    return {"id": appt.id, "status": appt.status}


@router.get("")
def list_appointments(
    db: DbSession,
    user: User = Depends(require_roles("owner", "staff", "admin")),
    status_filter: str | None = None,
) -> dict:
    q = select(Appointment).where(Appointment.tenant_id == user.tenant_id)
    if user.role == "owner":
        q = q.where(Appointment.owner_id == user.id)
    if status_filter in ("pending", "accepted", "completed", "cancelled"):
        q = q.where(Appointment.status == status_filter)
    rows = db.execute(q.order_by(Appointment.id.desc()).limit(100)).scalars().all()
    return {"appointments": [_appointment_row(db, a) for a in rows]}


@router.get("/{appointment_id}")
def appointment_detail(appointment_id: int, db: DbSession, user: User = Depends(require_roles("owner", "staff", "admin"))) -> dict:
    return _appointment_row(db, _get_appointment(db, appointment_id, user))


class AcceptIn(BaseModel):
    appointment_time: datetime | None = None
    shop_note: str = Field(default="", max_length=500)


@router.post("/{appointment_id}/accept")
def accept_appointment(appointment_id: int, body: AcceptIn, db: DbSession, user: User = Depends(require_roles("staff", "admin"))) -> dict:
    a = _get_appointment(db, appointment_id, user)
    if a.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, f"当前状态为 {a.status}，不能接单")
    if body.appointment_time:
        a.appointment_time = _naive(body.appointment_time)
    a.shop_note = body.shop_note
    a.status = "accepted"
    a.accepted_by = user.id
    db.add(AuditLog(
        tenant_id=a.tenant_id, user_id=user.id, action="appointment_accept",
        detail={"appointment_id": a.id},
    ))
    db.commit()
    return {"id": a.id, "status": a.status}


class CompleteIn(BaseModel):
    repair_result: str = Field(min_length=1, max_length=2000)


@router.post("/{appointment_id}/complete")
def complete_appointment(appointment_id: int, body: CompleteIn, db: DbSession, user: User = Depends(require_roles("staff", "admin"))) -> dict:
    a = _get_appointment(db, appointment_id, user)
    if a.status != "accepted":
        raise HTTPException(status.HTTP_409_CONFLICT, f"当前状态为 {a.status}，不能回填结果")
    a.repair_result = body.repair_result
    a.status = "completed"
    db.add(AuditLog(
        tenant_id=a.tenant_id, user_id=user.id, action="appointment_complete",
        detail={"appointment_id": a.id},
    ))
    db.commit()
    return {"id": a.id, "status": a.status}


class CancelIn(BaseModel):
    reason: str = Field(default="", max_length=500)


@router.post("/{appointment_id}/cancel")
def cancel_appointment(appointment_id: int, body: CancelIn, db: DbSession, user: User = Depends(require_roles("owner", "staff", "admin"))) -> dict:
    a = _get_appointment(db, appointment_id, user)
    if a.status not in ACTIVE_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, f"当前状态为 {a.status}，不能取消")
    a.status = "cancelled"
    a.shop_note = body.reason or a.shop_note
    db.add(AuditLog(
        tenant_id=a.tenant_id, user_id=user.id, action="appointment_cancel",
        detail={"appointment_id": a.id, "by": user.role},
    ))
    db.commit()
    return {"id": a.id, "status": a.status}


@router.get("/{appointment_id}/dialog")
def appointment_dialog(appointment_id: int, db: DbSession, user: User = Depends(require_roles("staff", "admin"))) -> dict:
    """店员查看预约关联会话的对话原文：仅当车主隐私开关开启（用户裁定：原文只随预约看）。"""
    a = _get_appointment(db, appointment_id, user)
    if not a.session_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "该预约没有关联诊断会话")
    owner = db.get(User, a.owner_id)
    if owner is None or not owner.privacy_share_dialog:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "车主已关闭「店员可见对话记录」，仅可查看诊断摘要卡",
        )
    rows = db.execute(
        select(Message).where(
            Message.session_id == a.session_id,
            Message.role.in_(["user", "assistant"]),
            Message.content != "",
        ).order_by(Message.id)
    ).scalars().all()
    return {
        "session_id": a.session_id,
        "messages": [{"role": m.role, "content": m.content} for m in rows],
    }
