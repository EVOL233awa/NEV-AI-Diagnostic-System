"""成员与角色管理（admin 专属）：建号 / 停用启用 / 重置密码 / 改角色。

初始密码 = 账号名（2026-09-26 用户裁定，与种子账号一致）；
禁自停与自降权，防止管理员把自己锁在门外。
superadmin 调试账号不在管辖范围：列表不显示、禁改禁停禁重置（2026-09-29 用户裁定，
公网环境 admin 不应能触到 superadmin 的凭据与状态）。
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from backend.api.auth import ensure_password_strength
from backend.api.deps import DbSession, require_roles
from backend.db.models import AuditLog, OwnerVehicle, User, VehicleProfile
from backend.security import hash_password
from backend.seed.seed import SUPERADMIN_USERNAME

router = APIRouter(prefix="/api/admin/users", tags=["admin-users"])

USERNAME_PAT = re.compile(r"^[a-zA-Z0-9_]{3,32}$")
VALID_ROLES = ("owner", "staff", "admin")


class CreateUserIn(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    display_name: str = Field(default="", max_length=64)
    role: str = Field(default="owner")
    # admin 建号时代填车辆（双通道维护的"店端"一路，可省略）
    vehicle_brand: str = Field(default="", max_length=64)
    vehicle_model: str = Field(default="", max_length=64)
    vehicle_year: str = Field(default="", max_length=16)
    vehicle_power_type: str = Field(default="", max_length=16)
    vehicle_vin: str = Field(default="", max_length=32)
    vehicle_plate: str = Field(default="", max_length=16)
    vehicle_notes: str = Field(default="", max_length=500)


class UpdateUserIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=64)
    role: str | None = None
    disabled: bool | None = None


def _user_row(u: User, vehicle: str = "") -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "role": u.role,
        "display_name": u.display_name or u.username,
        "disabled": u.disabled,
        "privacy_share_dialog": u.privacy_share_dialog,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
        "vehicle": vehicle,
    }


@router.get("")
def list_users(db: DbSession, admin: User = Depends(require_roles("admin"))) -> dict:
    rows = db.execute(
        select(User)
        .where(User.tenant_id == admin.tenant_id, User.role != "superadmin")
        .order_by(User.id)
    ).scalars().all()
    vehicle_map: dict[int, str] = {}
    binds = db.execute(
        select(OwnerVehicle.owner_id, VehicleProfile.brand, VehicleProfile.model_name)
        .join(VehicleProfile, OwnerVehicle.vehicle_id == VehicleProfile.id)
        .where(OwnerVehicle.tenant_id == admin.tenant_id, VehicleProfile.tenant_id == admin.tenant_id)
    ).all()
    for owner_id, brand, model in binds:
        vehicle_map.setdefault(owner_id, f"{brand} {model}".strip())
    return {"users": [_user_row(u, vehicle_map.get(u.id, "")) for u in rows]}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(body: CreateUserIn, db: DbSession, admin: User = Depends(require_roles("admin"))) -> dict:
    username = body.username.strip()
    if not USERNAME_PAT.match(username):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "账号须为 3~32 位字母/数字/下划线")
    if body.role not in VALID_ROLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "角色不合法")
    dup = db.execute(select(User.id).where(User.username == username).limit(1)).scalar()
    if dup:
        raise HTTPException(status.HTTP_409_CONFLICT, "该账号已存在")

    user = User(
        tenant_id=admin.tenant_id,
        username=username,
        password_hash=hash_password(username),  # 初始密码 = 账号名（裁定）
        role=body.role,
        display_name=body.display_name.strip() or username,
    )
    db.add(user)
    db.flush()

    if body.vehicle_brand or body.vehicle_model or body.vehicle_vin or body.vehicle_plate:
        vehicle = VehicleProfile(
            tenant_id=admin.tenant_id,
            vin=body.vehicle_vin.strip() or None,
            plate_no=body.vehicle_plate.strip() or None,
            brand=body.vehicle_brand.strip(),
            model_name=body.vehicle_model.strip(),
            model_year=body.vehicle_year.strip(),
            power_type=body.vehicle_power_type.strip(),
            notes=body.vehicle_notes.strip(),
        )
        db.add(vehicle)
        db.flush()
        db.add(OwnerVehicle(owner_id=user.id, vehicle_id=vehicle.id, is_default=True))

    db.add(AuditLog(
        tenant_id=admin.tenant_id, user_id=admin.id, action="user_create",
        detail={"username": username, "role": body.role},
    ))
    db.commit()
    return {"id": user.id, "username": user.username, "role": user.role}


def _forbid_superadmin(user: User) -> None:
    """superadmin 账号不受成员管理管辖：admin 不可见、不可改、不可重置。"""
    if user.role == "superadmin" or user.username == SUPERADMIN_USERNAME:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "超级管理员账号不受成员管理管辖")


@router.patch("/{user_id}")
def update_user(user_id: int, body: UpdateUserIn, db: DbSession, admin: User = Depends(require_roles("admin"))) -> dict:
    user = db.get(User, user_id)
    if user is None or user.tenant_id != admin.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "账号不存在")
    _forbid_superadmin(user)
    if body.role is not None and body.role not in VALID_ROLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "角色不合法")

    # 禁自停 / 自降权：当前管理员只能通过另一个管理员账号完成该操作
    if user.id == admin.id and (body.disabled or (body.role is not None and body.role != "admin")):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能停用或降级自己的账号")

    if body.display_name is not None:
        user.display_name = body.display_name.strip()
    if body.role is not None:
        user.role = body.role
    if body.disabled is not None:
        user.disabled = body.disabled
    db.add(AuditLog(
        tenant_id=admin.tenant_id, user_id=admin.id, action="user_update",
        detail={"target": user.username, "role": body.role, "disabled": body.disabled},
    ))
    db.commit()
    return {"ok": True}


@router.post("/{user_id}/reset-password")
def reset_password(user_id: int, db: DbSession, admin: User = Depends(require_roles("admin"))) -> dict:
    user = db.get(User, user_id)
    if user is None or user.tenant_id != admin.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "账号不存在")
    _forbid_superadmin(user)
    assert user.username is not None
    user.password_hash = hash_password(user.username)  # 重置 = 账号名（与建号口径一致）
    db.add(AuditLog(
        tenant_id=admin.tenant_id, user_id=admin.id, action="password_reset",
        detail={"target": user.username},
    ))
    db.commit()
    return {"ok": True, "password": user.username}


class SetPasswordIn(BaseModel):
    new_password: str = Field(min_length=1, max_length=128)


@router.post("/{user_id}/password")
def set_password(user_id: int, body: SetPasswordIn, db: DbSession, admin: User = Depends(require_roles("admin"))) -> dict:
    """管理员直接设置成员（含自己）的新密码，不走「重置为账号名」。"""
    user = db.get(User, user_id)
    if user is None or user.tenant_id != admin.tenant_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "账号不存在")
    _forbid_superadmin(user)
    ensure_password_strength(body.new_password, user.username)
    user.password_hash = hash_password(body.new_password)
    db.add(AuditLog(
        tenant_id=admin.tenant_id, user_id=admin.id, action="password_set",
        detail={"target": user.username},
    ))
    db.commit()
    return {"ok": True}
