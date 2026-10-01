"""车辆档案：车主双通道维护 + 店员到店档案检索。

- 车主可添加/修改自己名下车辆（双通道的"车主自填"一路，2026-09-26 裁定）。
- 店员档案检索：按车牌/VIN/品牌车型模糊查，返回档案 + 历史诊断摘要，
  不含对话原文（2026-09-26 裁定：原文只随预约看）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from backend.api.deps import DbSession, require_roles
from backend.db.models import AuditLog, Message, OwnerVehicle, Session as ChatSession, User, VehicleProfile

router = APIRouter(prefix="/api/vehicles", tags=["vehicles"])

POWER_TYPES = ("EV", "PHEV", "REEV", "ICE", "")


def _diag_briefs(db, vehicle_id: int, limit: int = 5) -> list[dict]:
    """某车的历史诊断摘要（severity + summary + 会话标题），不含对话原文。"""
    rows = db.execute(
        select(Message.diag_json, Message.created_at, ChatSession.title)
        .join(ChatSession, Message.session_id == ChatSession.id)
        .where(ChatSession.vehicle_id == vehicle_id, Message.diag_json.is_not(None))
        .order_by(Message.id.desc())
        .limit(limit)
    ).all()
    return [
        {
            "severity": diag.get("severity", "?") if diag else "?",
            "summary": diag.get("summary", "") if diag else "",
            "session_title": title,
            "created_at": created.isoformat(timespec="minutes") if created else None,
        }
        for diag, created, title in rows
    ]


def _profile_row(v: VehicleProfile, include_history: bool = False, db=None) -> dict:
    row = {
        "id": v.id,
        "vin": v.vin or "",
        "plate_no": v.plate_no or "",
        "brand": v.brand,
        "model_name": v.model_name,
        "model_year": v.model_year,
        "power_type": v.power_type,
        "notes": v.notes,
        "is_default": False,
    }
    if include_history and db is not None:
        row["history"] = _diag_briefs(db, v.id)
    return row


class UpsertVehicleIn(BaseModel):
    brand: str = Field(default="", max_length=64)
    model_name: str = Field(default="", max_length=64)
    model_year: str = Field(default="", max_length=16)
    power_type: str = Field(default="EV")
    vin: str = Field(default="", max_length=32)
    plate_no: str = Field(default="", max_length=16)
    notes: str = Field(default="", max_length=500)


def _validate(body: UpsertVehicleIn) -> None:
    if body.power_type not in POWER_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "能源类型不合法")
    if not (body.brand or body.model_name or body.vin or body.plate_no):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "至少填写品牌/车型/VIN/车牌其一")


@router.get("")
def my_vehicles(db: DbSession, user: User = Depends(require_roles("owner"))) -> dict:
    binds = db.execute(
        select(OwnerVehicle, VehicleProfile)
        .join(VehicleProfile, OwnerVehicle.vehicle_id == VehicleProfile.id)
        .where(OwnerVehicle.owner_id == user.id, OwnerVehicle.tenant_id == user.tenant_id)
        .order_by(OwnerVehicle.id)
    ).all()
    vehicles = []
    for bind, profile in binds:
        row = _profile_row(profile, include_history=True, db=db)
        row["is_default"] = bool(bind.is_default)
        vehicles.append(row)
    return {"vehicles": vehicles}


@router.post("", status_code=status.HTTP_201_CREATED)
def add_vehicle(body: UpsertVehicleIn, db: DbSession, user: User = Depends(require_roles("owner"))) -> dict:
    _validate(body)
    count = len(
        db.execute(select(OwnerVehicle.id).where(OwnerVehicle.owner_id == user.id)).all()
    )
    profile = VehicleProfile(
        tenant_id=user.tenant_id,
        vin=body.vin.strip() or None,
        plate_no=body.plate_no.strip() or None,
        brand=body.brand.strip(),
        model_name=body.model_name.strip(),
        model_year=body.model_year.strip(),
        power_type=body.power_type,
        notes=body.notes.strip(),
    )
    db.add(profile)
    db.flush()
    db.add(OwnerVehicle(owner_id=user.id, vehicle_id=profile.id, is_default=count == 0))
    db.add(AuditLog(
        tenant_id=user.tenant_id, user_id=user.id, action="vehicle_add",
        detail={"vehicle_id": profile.id},
    ))
    db.commit()
    return {"id": profile.id}


class PatchVehicleIn(BaseModel):
    brand: str | None = Field(default=None, max_length=64)
    model_name: str | None = Field(default=None, max_length=64)
    model_year: str | None = Field(default=None, max_length=16)
    power_type: str | None = None
    plate_no: str | None = Field(default=None, max_length=16)
    notes: str | None = Field(default=None, max_length=500)
    is_default: bool | None = None


@router.patch("/{vehicle_id}")
def patch_vehicle(vehicle_id: int, body: PatchVehicleIn, db: DbSession, user: User = Depends(require_roles("owner"))) -> dict:
    bind = db.execute(
        select(OwnerVehicle)
        .where(OwnerVehicle.owner_id == user.id, OwnerVehicle.vehicle_id == vehicle_id)
        .limit(1)
    ).scalar()
    if bind is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "车辆不存在或不在你名下")
    profile = db.get(VehicleProfile, vehicle_id)
    assert profile is not None
    if body.power_type is not None and body.power_type not in POWER_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "能源类型不合法")
    for field in ("brand", "model_name", "model_year", "power_type", "plate_no", "notes"):
        value = getattr(body, field)
        if value is not None:
            setattr(profile, field, str(value).strip())
    if body.is_default:
        for other in db.execute(
            select(OwnerVehicle).where(OwnerVehicle.owner_id == user.id)
        ).scalars():
            other.is_default = False
        bind.is_default = True
    db.add(AuditLog(
        tenant_id=user.tenant_id, user_id=user.id, action="vehicle_update",
        detail={"vehicle_id": vehicle_id},
    ))
    db.commit()
    return {"ok": True}


@router.delete("/{vehicle_id}")
def delete_vehicle(vehicle_id: int, db: DbSession, user: User = Depends(require_roles("owner"))) -> dict:
    """车主删除自己名下车辆：解绑；档案无其他绑定时一并删除；删默认车则首辆自动补位。

    历史会话/预约/案例里的 vehicle_id 引用不回填（SQLite 默认不强制 FK），展示端按缺失处理。
    """
    bind = db.execute(
        select(OwnerVehicle)
        .where(OwnerVehicle.owner_id == user.id, OwnerVehicle.vehicle_id == vehicle_id)
        .limit(1)
    ).scalar()
    if bind is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "车辆不存在或不在你名下")
    was_default = bind.is_default
    db.delete(bind)
    db.flush()  # SessionLocal autoflush=False：不 flush 的话下面的查询仍会看到已删的绑定行
    if db.execute(
        select(OwnerVehicle.id).where(OwnerVehicle.vehicle_id == vehicle_id).limit(1)
    ).scalar() is None:
        profile = db.get(VehicleProfile, vehicle_id)
        if profile is not None:
            db.delete(profile)
    if was_default:
        first = db.execute(
            select(OwnerVehicle)
            .where(OwnerVehicle.owner_id == user.id)
            .order_by(OwnerVehicle.id)
            .limit(1)
        ).scalar()
        if first is not None:
            first.is_default = True
    db.add(AuditLog(
        tenant_id=user.tenant_id, user_id=user.id, action="vehicle_delete",
        detail={"vehicle_id": vehicle_id},
    ))
    db.commit()
    return {"ok": True}


@router.get("/search")
def search_vehicles(db: DbSession, user: User = Depends(require_roles("staff", "admin")), q: str = "") -> dict:
    """到店档案检索：车牌/VIN/品牌/车型模糊查 → 档案 + 历史诊断摘要（不含对话原文）。"""
    keyword = q.strip()
    if not keyword:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "请输入车牌/VIN/品牌车型关键词")
    like = f"%{keyword}%"
    rows = db.execute(
        select(VehicleProfile).where(
            VehicleProfile.tenant_id == user.tenant_id,
            or_(
                VehicleProfile.plate_no.like(like),
                VehicleProfile.vin.like(like),
                VehicleProfile.brand.like(like),
                VehicleProfile.model_name.like(like),
            ),
        ).limit(20)
    ).scalars().all()
    return {"vehicles": [_profile_row(v, include_history=True, db=db) for v in rows]}
