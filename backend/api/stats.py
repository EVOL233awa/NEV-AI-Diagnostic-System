"""管理端统计看板与审计日志查询（用量统计 = 未来计费基础）。"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select

from backend.api.deps import DbSession, require_roles
from backend.config import settings
from backend.core import quota
from backend.core.agent.runner import normalize_diag
from backend.db.models import (
    Appointment, AuditLog, Case, Message, Session as ChatSession, UsageStat, User,
)

router = APIRouter(prefix="/api/admin", tags=["admin-stats"])


def _today_consumption(db, tenant_id: int) -> dict:
    """今日 ASR/搜索消耗与按用户 Top 5（限额未启用时也照常展示消耗）。"""
    day_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    rows = db.execute(
        select(
            UsageStat.user_id,
            func.coalesce(func.sum(UsageStat.duration_ms), 0),
            func.coalesce(func.sum(case((UsageStat.slot == "search", 1), else_=0)), 0),
            func.coalesce(func.sum(UsageStat.cost_estimate), 0.0),
        )
        .where(
            UsageStat.tenant_id == tenant_id,
            UsageStat.slot.in_(("asr", "search")),
            UsageStat.created_at >= day_start,
        )
        .group_by(UsageStat.user_id)
    ).all()
    user_ids = {row[0] for row in rows if row[0]}
    names = {
        u.id: (u.display_name or u.username or "")
        for u in db.execute(select(User).where(User.id.in_(user_ids))).scalars().all()
    } if user_ids else {}
    users = [
        {
            "user_id": uid,
            "username": names.get(uid, ""),
            "asr_seconds": round(float(ms or 0) / 1000.0, 1),
            "search_calls": int(calls or 0),
            "cost_cny": round(float(cost or 0.0), 6),
        }
        for uid, ms, calls, cost in rows
    ]
    users.sort(key=lambda u: (u["cost_cny"], u["asr_seconds"], u["search_calls"]), reverse=True)
    return {
        "asr_seconds_today": round(sum(u["asr_seconds"] for u in users), 1),
        "search_calls_today": sum(u["search_calls"] for u in users),
        "cost_today_cny": round(float(quota.global_cost_today(db)), 6),
        "top_users": users[:5],
        "limits": {
            "asr_daily_seconds_per_user": quota.normalize_limit(settings.quota.get("asr_daily_seconds_per_user")),
            "search_daily_calls_per_user": quota.normalize_limit(settings.quota.get("search_daily_calls_per_user")),
            "global_daily_cny": quota.normalize_limit(settings.quota.get("global_daily_cny")),
        },
    }


def _daily_usage(db, tenant_id: int, days: int = 14) -> list[dict]:
    """最近 N 天模型/搜索/ASR 调用趋势（按本地日期聚合，缺失日期补零）。"""
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start = today - timedelta(days=days - 1)
    rows = db.execute(
        select(
            func.date(UsageStat.created_at),
            func.count(UsageStat.id),
            func.coalesce(func.sum(UsageStat.tokens_in), 0),
            func.coalesce(func.sum(UsageStat.tokens_out), 0),
            func.coalesce(func.sum(UsageStat.cost_estimate), 0.0),
        )
        .where(UsageStat.tenant_id == tenant_id, UsageStat.created_at >= start)
        .group_by(func.date(UsageStat.created_at))
    ).all()
    found = {
        str(day): {
            "calls": int(calls),
            "tokens_in": int(tokens_in),
            "tokens_out": int(tokens_out),
            "cost_cny": round(float(cost), 6),
        }
        for day, calls, tokens_in, tokens_out, cost in rows
    }
    series = []
    for offset in range(days):
        day = (start + timedelta(days=offset)).date().isoformat()
        series.append({"date": day, **found.get(day, {"calls": 0, "tokens_in": 0, "tokens_out": 0, "cost_cny": 0.0})})
    return series


def _daily_appointments(db, tenant_id: int, days: int = 14) -> list[dict]:
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start = today - timedelta(days=days - 1)
    rows = db.execute(
        select(func.date(Appointment.created_at), func.count(Appointment.id))
        .where(Appointment.tenant_id == tenant_id, Appointment.created_at >= start)
        .group_by(func.date(Appointment.created_at))
    ).all()
    found = {str(day): int(count) for day, count in rows}
    return [
        {
            "date": (start + timedelta(days=offset)).date().isoformat(),
            "count": found.get((start + timedelta(days=offset)).date().isoformat(), 0),
        }
        for offset in range(days)
    ]


def _severity_distribution(db, tenant_id: int) -> dict:
    """按会话取最后一条诊断结论的严重度，避免同会话多轮重复计数。"""
    rows = db.execute(
        select(Message.session_id, Message.diag_json)
        .join(ChatSession, Message.session_id == ChatSession.id)
        .where(ChatSession.tenant_id == tenant_id, Message.diag_json.is_not(None))
        .order_by(Message.id)
    ).all()
    latest: dict[int, dict] = {}
    for session_id, diag in rows:
        if isinstance(diag, dict):
            latest[session_id] = diag
    counts = {"red": 0, "yellow": 0, "green": 0, "unknown": 0}
    for diag in latest.values():
        severity = normalize_diag(diag).get("severity")
        counts[severity if severity in ("red", "yellow", "green") else "unknown"] += 1
    return counts


def _stage_funnel(db, tenant_id: int, concluded: set[int]) -> list[dict]:
    valid = ("intake", "hypothesis", "verification", "conclusion")
    rows = db.execute(
        select(ChatSession.id, ChatSession.case_notes).where(ChatSession.tenant_id == tenant_id)
    ).all()
    counts = {stage: 0 for stage in valid}
    for session_id, notes in rows:
        stage = notes.get("stage") if isinstance(notes, dict) else None
        if stage not in valid:
            stage = "conclusion" if session_id in concluded else "intake"
        counts[stage] += 1
    return [{"stage": stage, "count": counts[stage]} for stage in valid]


def _recent_activity(db, tenant_id: int, limit: int = 8) -> list[dict]:
    rows = db.execute(
        select(AuditLog).where(AuditLog.tenant_id == tenant_id).order_by(AuditLog.id.desc()).limit(limit)
    ).scalars().all()
    ids = {row.user_id for row in rows if row.user_id}
    names = {
        user.id: (user.display_name or user.username or "")
        for user in db.execute(select(User).where(User.id.in_(ids))).scalars().all()
    } if ids else {}
    return [
        {
            "id": row.id,
            "action": row.action,
            "username": names.get(row.user_id, "") if row.user_id else "",
            "created_at": row.created_at.isoformat(timespec="seconds") if row.created_at else None,
        }
        for row in rows
    ]


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
    diag_rows = db.execute(
        select(Message.session_id, Message.diag_json)
        .join(ChatSession, Message.session_id == ChatSession.id)
        .where(ChatSession.tenant_id == tid, Message.diag_json.is_not(None))
        .order_by(Message.id)
    ).all()
    concluded = {session_id for session_id, diag in diag_rows if isinstance(diag, dict)}
    return {
        "usage": {
            "today": _usage_window(db, day_start, tid),
            "week": _usage_window(db, week_start, tid),
            "month": _usage_window(db, month_start, tid),
        },
        "appointments": {status: count for status, count in appt_rows},
        "cases": db.execute(select(func.count(Case.id)).where(Case.tenant_id == tid)).scalar() or 0,
        "users": db.execute(select(func.count(User.id)).where(User.tenant_id == tid, User.disabled.is_(False))).scalar() or 0,
        "consumption": _today_consumption(db, tid),
        "usage_daily": _daily_usage(db, tid),
        "appointments_daily": _daily_appointments(db, tid),
        "severity": _severity_distribution(db, tid),
        "stage_funnel": _stage_funnel(db, tid, concluded),
        "recent_activity": _recent_activity(db, tid),
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
