"""管理端统计看板与审计日志查询（用量统计 = 未来计费基础）。"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from backend.api.deps import DbSession, require_roles
from backend.db.models import Appointment, AuditLog, Case, UsageStat, User

router = APIRouter(prefix="/api/admin", tags=["admin-stats"])


def _usage_window(db, since: datetime, tenant_id: int) -> dict:
    row = db.execute(
        select(
            func.count(UsageStat.id),
            func.coalesce(func.sum(UsageStat.tokens_in), 0),
            func.coalesce(func.sum(UsageStat.tokens_out), 0),
            func.coalesce(func.sum(UsageStat.cost_estimate), 0.0),
        ).where(UsageStat.tenant_id == tenant_id, UsageStat.created_at >= since)
    ).one()
    return {"calls": int(row[0]), "tokens_in": int(row[1]), "tokens_out": int(row[2]), "cost": round(float(row[3]), 4)}


@router.get("/stats")
def get_stats(db: DbSession, admin: User = Depends(require_roles("admin"))) -> dict:
    tid = admin.tenant_id
    now = datetime.now()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = day_start - timedelta(days=6)
    month_start = day_start - timedelta(days=29)
    appt_rows = db.execute(
        select(Appointment.status, func.count(Appointment.id))
        .where(Appointment.tenant_id == tid)
        .group_by(Appointment.status)
    ).all()
    return {
        "usage": {
            "today": _usage_window(db, day_start, tid),
            "week": _usage_window(db, week_start, tid),
            "month": _usage_window(db, month_start, tid),
        },
        "appointments": {status: count for status, count in appt_rows},
        "cases": db.execute(select(func.count(Case.id)).where(Case.tenant_id == tid)).scalar() or 0,
        "users": db.execute(select(func.count(User.id)).where(User.tenant_id == tid, User.disabled.is_(False))).scalar() or 0,
    }


@router.get("/audit-logs")
def list_audit_logs(
    db: DbSession,
    admin: User = Depends(require_roles("admin")),
    action: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    q = select(AuditLog).where(AuditLog.tenant_id == admin.tenant_id)
    if action:
        q = q.where(AuditLog.action == action)
    rows = db.execute(
        q.order_by(AuditLog.id.desc()).limit(min(limit, 500)).offset(max(offset, 0))
    ).scalars().all()
    author_ids = {row.user_id for row in rows if row.user_id}
    authors = {u.id: u.username for u in db.execute(
        select(User).where(User.id.in_(author_ids))
    ).scalars().all()} if author_ids else {}
    return {
        "logs": [
            {
                "id": row.id,
                "user_id": row.user_id,
                # user_id 可能指向已删除账号（历史数据），缺失时留空而非 500
                "username": authors.get(row.user_id) if row.user_id else None,
                "action": row.action,
                "detail": row.detail,
                "ip": row.ip,
                "created_at": row.created_at.isoformat(timespec="seconds") if row.created_at else None,
            }
            for row in rows
        ]
    }
