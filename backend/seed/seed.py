"""种子数据：内置账号 admin / staff001 / user001（账号登录，2026-09-25 用户裁定）。

初始密码 = 账号名（2026-09-26 用户裁定，测试方便）：admin/admin、
staff001/staff001、user001/user001。config.json 的 seed_admin 节仅作记录，
不再存随机密码（公开仓库零明文）。

superadmin 账号（v2.1.0 固定密码口径，代码不内置默认值）：
密码来源优先级：环境变量 NEV_SUPERADMIN_PASSWORD > config.json superadmin.password
> 首次启动生成一次性随机值（标记 generated，提示尽快固定）。
`python main.py --set-superadmin-password <value>` 写入 config 与 DB 哈希后退出。
明文只存服务器本机 data/config.json 的 superadmin 节（不进仓库/DB/接口响应），
每次启动打印到后端 stdout，并标注来源（env/config/generated）。

另含演示车辆档案：user001 名下绑定一台默认车，
供车辆档案归档与历史诊断跨会话测试。
"""
from __future__ import annotations

import os
import secrets
import string

from backend.config import save_raw, settings
from backend.db.base import SessionLocal
from backend.db.models import AuditLog, OwnerVehicle, User, VehicleProfile
from backend.security import hash_password, verify_password

# (username, role, display_name)，初始密码 = username
BUILTIN_ACCOUNTS: list[tuple[str, str, str]] = [
    ("admin", "admin", "管理员"),
    ("staff001", "staff", "店员001"),
    ("user001", "owner", "车主001"),
]

SUPERADMIN_USERNAME = "superadmin"
SUPERADMIN_DISPLAY_NAME = "超级管理员"
SUPERADMIN_PASSWORD_LEN = 20  # 字母数字 20 位 ≈ 119 bit 熵，公网环境抗爆破
SUPERADMIN_ENV_VAR = "NEV_SUPERADMIN_PASSWORD"

SOURCE_LABELS = {
    "env": "环境变量 NEV_SUPERADMIN_PASSWORD",
    "config": "本机 data/config.json（固定值）",
    "generated": "首次启动随机生成（一次性，建议尽快固定）",
}

# 演示车（仅 user001）：无则创建
DEMO_VEHICLE = {
    "vin": "LSVDEMO000000001",
    "plate_no": "桂A·8D001",
    "brand": "比亚迪",
    "model_name": "汉 EV",
    "model_year": "2023",
    "power_type": "EV",
    "notes": "演示车辆：日常市区通勤，家用慢充桩充电",
}


def generate_superadmin_password() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(SUPERADMIN_PASSWORD_LEN))


def _stored_superadmin_password() -> str:
    """config.json superadmin 节里的明文密码（未记录返回空串）。"""
    return str(settings.raw.get("superadmin", {}).get("password") or "")


def _stored_password_source() -> str:
    source = str(settings.raw.get("superadmin", {}).get("password_source") or "").strip()
    return source if source in ("env", "config", "generated") else ""


def _store_superadmin_password(password: str, source: str) -> None:
    settings.raw["superadmin"] = {"password": password, "password_source": source}
    save_raw(settings.raw)


def _validate_or_exit(password: str) -> None:
    """env/CLI 指定的密码必须过强度校验；不通过拒绝启动，不静默降级。"""
    from fastapi import HTTPException

    from backend.api.auth import ensure_password_strength

    try:
        ensure_password_strength(password, SUPERADMIN_USERNAME)
    except HTTPException as exc:
        print(f"[seed] superadmin 密码不符合要求：{exc.detail}")
        raise SystemExit(1) from exc


def _print_superadmin_password(password: str, source: str) -> None:
    print()
    print("=" * 64)
    print("  [超级管理员账号] 本窗口可见，请勿转发/截图外传")
    print(f"  账号：{SUPERADMIN_USERNAME}")
    if source == "generated":
        # 仅一次性生成时输出明文，便于首次登录；之后从 config 读取不再回显到日志
        print(f"  密码：{password}")
    else:
        print("  密码：（来自环境变量/配置文件，出于安全不在日志显示）")
    print(f"  来源：{SOURCE_LABELS.get(source, source)}")
    if source == "generated":
        print("  （建议部署时用 --set-superadmin-password 或环境变量固定，避免误以为会变）")
    elif source == "env":
        print("  （环境变量优先于面板修改：改面板密码后重启会被 env 覆盖）")
    print("=" * 64)
    print()


def _sync_superadmin_password(password: str, source: str, *, audit_action: str) -> None:
    """同步 DB 哈希 + config 明文；账号不存在则创建。"""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == SUPERADMIN_USERNAME).first()
        if user is None:
            user = User(
                username=SUPERADMIN_USERNAME,
                password_hash="",
                role="superadmin",
                display_name=SUPERADMIN_DISPLAY_NAME,
            )
            db.add(user)
            db.flush()
            db.add(AuditLog(user_id=user.id, action="seed_account_created",
                            detail={"username": SUPERADMIN_USERNAME, "role": "superadmin"}, ip=""))
        user.password_hash = hash_password(password)
        user.disabled = False  # 固定/重置即解锁：这是管理员被锁在门外时的恢复通道
        db.add(AuditLog(user_id=user.id, action=audit_action, detail={"source": source}, ip=""))
        db.commit()
    finally:
        db.close()
    _store_superadmin_password(password, source)


def apply_superadmin_password(env_password: str | None = None) -> tuple[str, str]:
    """按优先级解析 superadmin 密码并同步落库：env > config > 一次性生成。"""
    if env_password is None:
        env_password = os.environ.get(SUPERADMIN_ENV_VAR, "")
    env_password = (env_password or "").strip()
    stored = _stored_superadmin_password()
    source = _stored_password_source()

    if env_password:
        _validate_or_exit(env_password)
        if stored != env_password or source != "env":
            _sync_superadmin_password(env_password, "env", audit_action="superadmin_password_env_sync")
        return env_password, "env"

    if stored:
        # config 里有值：沿用；来源缺失（旧配置）按 config 记，generated 保留警示
        if source not in ("config", "generated"):
            _store_superadmin_password(stored, "config")
            source = "config"
        return stored, source

    password = generate_superadmin_password()
    _sync_superadmin_password(password, "generated", audit_action="superadmin_password_generated")
    return password, "generated"


def reset_superadmin_password() -> str:
    """按优先级重新应用 superadmin 密码（--reset-superadmin / 测试夹具入口）。

    语义（v2.1.0）：env 优先；否则沿用 config 固定值；都没有才生成一次性随机值。
    返回最终生效的密码。
    """
    password, _source = apply_superadmin_password()
    return password


def ensure_seed(superadmin_override: str | None = None) -> None:
    db = SessionLocal()
    try:
        # 遗留迁移：手机号时期的唯一管理员（username 被回填成手机号）→ 改为 admin
        legacy = db.query(User).filter(User.username == "13800000000").first()
        if legacy is not None and db.query(User).filter(User.username == "admin").first() is None:
            legacy.username = "admin"
            legacy.phone = legacy.phone or "13800000000"
            db.commit()

        created: list[str] = []
        for username, role, display_name in BUILTIN_ACCOUNTS:
            if db.query(User).filter(User.username == username).first() is not None:
                continue
            user = User(
                username=username,
                password_hash=hash_password(username),  # 初始密码 = 账号名
                role=role,
                display_name=display_name,
            )
            db.add(user)
            db.flush()
            db.add(
                AuditLog(
                    user_id=user.id,
                    action="seed_account_created",
                    detail={"username": username, "role": role},
                    ip="",
                )
            )
            created.append(username)
        db.commit()

        if created:
            raw = settings.raw
            if raw.get("seed_admin", {}).get("password"):
                # 旧随机密码口径已废弃，规范成账号=密码记录
                raw["seed_admin"] = {"username": "admin", "password": "admin"}
                save_raw(raw)
            print(f"[seed] 已创建内置账号 {'、'.join(created)}（初始密码 = 账号名）")
    finally:
        db.close()

    # superadmin：固定密码流程（CLI 覆盖 > env > config > 一次性生成），每次启动打印
    if superadmin_override:
        _validate_or_exit(superadmin_override)
        _sync_superadmin_password(superadmin_override, "config", audit_action="superadmin_password_set")
        _print_superadmin_password(superadmin_override, "config")
    else:
        password, source = apply_superadmin_password()
        _print_superadmin_password(password, source)

    # 演示车辆档案绑定（幂等：按 VIN 查重）
    db = SessionLocal()
    try:
        owner = db.query(User).filter(User.username == "user001").first()
        if owner is not None:
            vehicle = (
                db.query(VehicleProfile)
                .filter(VehicleProfile.vin == DEMO_VEHICLE["vin"])
                .first()
            )
            if vehicle is None:
                vehicle = VehicleProfile(tenant_id=1, **DEMO_VEHICLE)
                db.add(vehicle)
                db.flush()
                db.add(
                    AuditLog(
                        user_id=owner.id,
                        action="seed_vehicle_created",
                        detail={"vin": DEMO_VEHICLE["vin"], "model": DEMO_VEHICLE["model_name"]},
                        ip="",
                    )
                )
            bound = (
                db.query(OwnerVehicle)
                .filter(OwnerVehicle.owner_id == owner.id, OwnerVehicle.vehicle_id == vehicle.id)
                .first()
            )
            if bound is None:
                db.add(OwnerVehicle(owner_id=owner.id, vehicle_id=vehicle.id, is_default=True))
            db.commit()
    finally:
        db.close()
