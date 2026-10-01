"""种子数据：内置账号 admin / staff001 / user001（账号登录，2026-09-25 用户裁定）。

初始密码 = 账号名（2026-09-26 用户裁定，测试方便）：admin/admin、
staff001/staff001、user001/user001。config.json 的 seed_admin 节仅作记录，
不再存随机密码（公开仓库零明文）。

superadmin 调试账号（2026-09-29 用户裁定，启动脚本 = 最小化 cmd 窗口跑 main.py）：
密码 20 位随机字母数字，明文存服务器本机 data/config.json 的 superadmin 节
（与 API Key 同一密钥宿主，不进仓库/DB/任何接口响应/日志）；
**每次启动进程都打印到后端 stdout**（即启动脚本弹出的 cmd 窗口，点开即看）。
公网环境下面板 /superadmin 仅此角色可进，admin 成员管理对其不可见。

另含演示车辆档案：user001 名下绑定一台默认车，
供车辆档案归档与历史诊断跨会话测试。
"""
from __future__ import annotations

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


def _store_superadmin_password(password: str) -> None:
    settings.raw["superadmin"] = {"password": password}
    save_raw(settings.raw)


def _print_superadmin_password(password: str, created: bool) -> None:
    header = "超级管理员账号已创建" if created else "超级管理员账号"
    print()
    print("=" * 64)
    print(f"  [{header}] 本窗口可见，请勿转发/截图外传")
    print(f"  账号：{SUPERADMIN_USERNAME}")
    print(f"  密码：{password}")
    print("  （明文仅存服务器本机 data/config.json；重新生成请运行：")
    print("   python main.py --reset-superadmin）")
    print("=" * 64)
    print()


def _announce_superadmin(user: User) -> None:
    """每次启动打印 superadmin 凭据（2026-09-29 用户裁定：启动即见，点开最小化窗口可查）。

    config 明文与 DB 哈希不一致（手动改过其中一边）时只告警不改数据，恢复通道走 reset。
    """
    stored = _stored_superadmin_password()
    if stored and verify_password(stored, user.password_hash):
        _print_superadmin_password(stored, created=False)
    elif not stored:
        print("[seed] superadmin 账号已存在但明文密码未记录，"
              "运行 python main.py --reset-superadmin 重新生成")
    else:
        print("[seed] config.json 的 superadmin.password 与登录凭据不一致（可能被手动修改），"
              "登录以数据库为准；忘记密码请运行 python main.py --reset-superadmin")


def reset_superadmin_password() -> str:
    """重新随机生成 superadmin 密码：旧密码立即作废，明文经返回值交给调用方打印。

    同步更新 DB 哈希与 config.json 明文（下次启动照常打印）。账号不存在则顺带创建。
    """
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
        password = generate_superadmin_password()
        user.password_hash = hash_password(password)
        user.disabled = False  # 重置即解锁：这是管理员被锁在门外时的恢复通道
        db.add(AuditLog(user_id=user.id, action="superadmin_password_reset", detail={}, ip=""))
        db.commit()
        _store_superadmin_password(password)
        return password
    finally:
        db.close()


def ensure_seed() -> None:
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

        # superadmin 调试账号：不存在则创建（明文同步入 config.json）；
        # 已存在则每次启动照常打印凭据（启动脚本的最小化 cmd 窗口即查看入口）
        superadmin = db.query(User).filter(User.username == SUPERADMIN_USERNAME).first()
        if superadmin is None:
            password = generate_superadmin_password()
            user = User(
                username=SUPERADMIN_USERNAME,
                password_hash=hash_password(password),
                role="superadmin",
                display_name=SUPERADMIN_DISPLAY_NAME,
            )
            db.add(user)
            db.flush()
            db.add(
                AuditLog(
                    user_id=user.id,
                    action="seed_account_created",
                    detail={"username": SUPERADMIN_USERNAME, "role": "superadmin"},
                    ip="",
                )
            )
            db.commit()
            _store_superadmin_password(password)
            _print_superadmin_password(password, created=True)
        else:
            _announce_superadmin(superadmin)

        # 演示车辆档案绑定（幂等：按 VIN 查重）
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
