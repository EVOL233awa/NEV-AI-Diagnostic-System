"""店员/管理员故障码速查：DTC 搜索与详情（不暴露给车主）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from backend.api.deps import DbSession, require_roles
from backend.core import dtc
from backend.db.models import User

router = APIRouter(prefix="/api/dtc", tags=["dtc"])


@router.get("/search")
def search_codes(
    db: DbSession,
    user: User = Depends(require_roles("staff", "admin")),
    q: str = "",
    limit: int = 20,
) -> dict:
    if limit < 1 or limit > 50:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "limit 需在 1~50 之间")
    entries = dtc.search(q, limit=limit)
    return {
        "results": [
            {"code": entry.code, "zh": entry.zh, "note": entry.note}
            for entry in entries
        ]
    }


@router.get("/{code}")
def code_detail(
    code: str,
    db: DbSession,
    user: User = Depends(require_roles("staff", "admin")),
) -> dict:
    normalized = dtc.normalize_code(code)
    if not dtc.CODE_RE.match(normalized):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "故障码格式不合法（如 P0A80）")
    payload = dtc.detail(db, normalized)
    if payload is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未收录该故障码")
    return payload
