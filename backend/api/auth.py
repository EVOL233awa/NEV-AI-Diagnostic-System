"""认证路由：登录（失败限速）/ 当前用户 / 修改密码（弱口令校验）。"""
from __future__ import annotations

import re
import threading
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from backend.api.deps import DbSession, client_ip
from backend.api.deps import CurrentUser
from backend.config import APP_VERSION, settings
from backend.db.models import AuditLog, User
from backend.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

# ---- 登录失败限速（单进程内存态；商用多实例部署时需换集中存储，见部署文档） ----
LOGIN_FAIL_LIMIT = 5
LOGIN_LOCK_WINDOW = timedelta(minutes=15)
_login_fails: dict[str, list[datetime]] = {}
_login_lock = threading.Lock()  # sync 端点跑在线程池，计数读写须互斥


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordIn(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


def _prune_window(key: str, now: datetime) -> list[datetime]:
    recent = [t for t in _login_fails.get(key, []) if now - t < LOGIN_LOCK_WINDOW]
    if recent:
        _login_fails[key] = recent
    else:
        _login_fails.pop(key, None)
    return recent


def _is_login_locked(account: str) -> bool:
    with _login_lock:
        return len(_prune_window(account.lower(), datetime.now())) >= LOGIN_FAIL_LIMIT


def _record_login_failure(account: str) -> int:
    """记一次失败，返回窗口内累计失败次数。"""
    with _login_lock:
        key = account.lower()
        now = datetime.now()
        recent = _prune_window(key, now)
        recent.append(now)
        _login_fails[key] = recent
        return len(recent)


def _clear_login_failures(account: str) -> None:
    with _login_lock:
        _login_fails.pop(account.lower(), None)


# ---- 弱口令校验（仅改密码口径；建号/重置的初始密码=账号名是演示裁定，豁免） ----
PASSWORD_RULE = "密码至少 8 位，须同时包含字母和数字，且不能包含账号名"


def ensure_password_strength(password: str, username: str) -> None:
    if len(password) < 8:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, PASSWORD_RULE)
    if not (re.search(r"[A-Za-z]", password) and re.search(r"[0-9]", password)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, PASSWORD_RULE)
    if username and username.lower() in password.lower():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, PASSWORD_RULE)


def _user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "display_name": user.display_name or user.username,
        "privacy_share_dialog": user.privacy_share_dialog,
    }


@router.post("/login")
def login(body: LoginIn, request: Request, db: DbSession) -> dict:
    account = body.username.strip()
    # 锁定短路在密码验证之前：锁定期间不消耗 PBKDF2 计算（防资源耗尽）
    if _is_login_locked(account):
        db.add(
            AuditLog(action="login_locked", detail={"username": account}, ip=client_ip(request))
        )
        db.commit()
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "失败次数过多，账号已临时锁定，请 15 分钟后再试"
        )
    user = db.scalar(select(User).where(User.username == account))
    if user is None or not verify_password(body.password, user.password_hash):
        fails = _record_login_failure(account)
        db.add(
            AuditLog(
                user_id=user.id if user else None,
                action="login_failed",
                detail={"username": account, "fails": fails},
                ip=client_ip(request),
            )
        )
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账号或密码不正确")
    if user.disabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "账号已停用，请联系管理员")
    _clear_login_failures(account)
    user.last_login_at = datetime.now()
    db.add(
        AuditLog(
            user_id=user.id,
            action="login",
            detail={"role": user.role},
            ip=client_ip(request),
        )
    )
    db.commit()
    token = create_access_token(user.id, user.role, settings.jwt_secret)
    return {"token": token, "user": _user_payload(user), "version": APP_VERSION}


@router.get("/me")
def me(user: CurrentUser) -> dict:
    return {"user": _user_payload(user)}


class PrivacyIn(BaseModel):
    privacy_share_dialog: bool


@router.patch("/privacy")
def update_privacy(body: PrivacyIn, user: CurrentUser, db: DbSession) -> dict:
    """车主隐私开关（决策 #15）：对之后的诊断立即生效。"""
    user.privacy_share_dialog = body.privacy_share_dialog
    db.add(AuditLog(user_id=user.id, action="privacy_update", detail={"value": body.privacy_share_dialog}))
    db.commit()
    return {"ok": True, "privacy_share_dialog": user.privacy_share_dialog}


@router.post("/change-password")
def change_password(body: ChangePasswordIn, user: CurrentUser, db: DbSession) -> dict:
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "原密码不正确")
    ensure_password_strength(body.new_password, user.username)
    user.password_hash = hash_password(body.new_password)
    db.add(AuditLog(user_id=user.id, action="change_password", detail={}))
    db.commit()
    return {"ok": True}
