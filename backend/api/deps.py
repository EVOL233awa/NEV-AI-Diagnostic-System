"""依赖注入：DB 会话、当前用户、角色鉴权。"""
from __future__ import annotations

from typing import Annotated, Callable, Iterator

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.base import SessionLocal
from backend.db.models import User
from backend.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)

ROLE_LABELS = {"owner": "车主", "staff": "店员", "admin": "管理员", "superadmin": "超级管理员"}


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    cred: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: DbSession,
) -> User:
    if cred is None or not cred.credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未登录")
    try:
        payload = decode_access_token(cred.credentials, settings.jwt_secret)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录已失效，请重新登录")
    user = db.get(User, int(payload["sub"]))
    if user is None or user.disabled:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账号不存在或已停用")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: str) -> Callable[..., User]:
    """接口级角色门禁：require_roles("admin") / require_roles("staff", "admin")。"""

    def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "无权访问")
        return user

    return checker


def client_ip(request: Request) -> str:
    if request.client is None:
        return ""
    return request.client.host
