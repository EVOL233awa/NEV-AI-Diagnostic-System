"""ASR/搜索计量与可配置限额（默认留空 = 不限制）。

配置语义（quota 节）：
- null / 缺失 / 空串 / 0 → 不限制（短路，不查库、不写日志）
- 正数 → 当日上限；负数/非数字/NaN/Infinity 视为未启用（superadmin PUT 会拒绝非法值）
- 每用户限额按服务器本地日期统计，次日 00:00 重置
- global_daily_usd 统计当日所有 usage_stats.cost_estimate（仅搜索/ASR 有估算值）

无论是否启限额：搜索/ASR 都写 usage_stats，管理端始终能看到消耗。
并发：单进程 SQLite 的 check-then-act 存在极小竞态，本轮接受（多 worker 时再换原子计数表）。
"""
from __future__ import annotations

import math
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.config import settings
from backend.core import pricing
from backend.db.models import UsageStat


def normalize_limit(value: object) -> float | None:
    """配置值 → 生效上限；None 表示不限制。非有限数与非正数一律不限制。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _day_start() -> datetime:
    return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)


def asr_seconds_today(db: Session, user_id: int) -> float:
    total_ms = db.execute(
        select(func.coalesce(func.sum(UsageStat.duration_ms), 0)).where(
            UsageStat.user_id == user_id,
            UsageStat.slot == "asr",
            UsageStat.created_at >= _day_start(),
        )
    ).scalar() or 0
    return float(total_ms) / 1000.0


def search_calls_today(db: Session, user_id: int) -> int:
    return int(
        db.execute(
            select(func.count(UsageStat.id)).where(
                UsageStat.user_id == user_id,
                UsageStat.slot == "search",
                UsageStat.created_at >= _day_start(),
            )
        ).scalar()
        or 0
    )


def global_cost_today(db: Session) -> float:
    """当日全局搜索/ASR 估算成本（USD）。主模型调用 cost_estimate 为 None，不计入。"""
    return float(
        db.execute(
            select(func.coalesce(func.sum(UsageStat.cost_estimate), 0.0)).where(
                UsageStat.slot.in_(("search", "asr")),
                UsageStat.created_at >= _day_start(),
            )
        ).scalar()
        or 0.0
    )


def check_asr(db: Session, user_id: int) -> str | None:
    """返回 'user'（每用户秒数用尽）/ 'global'（全局预算用尽）/ None（放行）。"""
    user_limit = normalize_limit(settings.quota.get("asr_daily_seconds_per_user"))
    budget = normalize_limit(settings.quota.get("global_daily_usd"))
    if user_limit is None and budget is None:
        return None
    if user_limit is not None and asr_seconds_today(db, user_id) >= user_limit:
        return "user"
    if budget is not None and global_cost_today(db) >= budget:
        return "global"
    return None


def check_search(db: Session, user_id: int) -> str | None:
    """返回 'user'（每用户次数用尽）/ 'global'（全局预算用尽）/ None（放行）。"""
    user_limit = normalize_limit(settings.quota.get("search_daily_calls_per_user"))
    budget = normalize_limit(settings.quota.get("global_daily_usd"))
    if user_limit is None and budget is None:
        return None
    if user_limit is not None and search_calls_today(db, user_id) >= user_limit:
        return "user"
    if budget is not None and global_cost_today(db) >= budget:
        return "global"
    return None


def record_asr(
    db: Session,
    *,
    tenant_id: int,
    user_id: int,
    provider: str,
    model: str,
    duration_ms: int,
    latency_ms: int,
) -> None:
    db.add(
        UsageStat(
            tenant_id=tenant_id,
            user_id=user_id,
            slot="asr",
            provider=provider[:32],
            model=model[:128],
            duration_ms=max(int(duration_ms), 0),
            latency_ms=max(int(latency_ms), 0),
            cost_estimate=pricing.asr_cost_usd(duration_ms),
        )
    )
    db.commit()


def record_search(
    db: Session,
    *,
    tenant_id: int,
    user_id: int,
    provider: str,
    success: bool,
    latency_ms: int = 0,
) -> None:
    """一次工具级搜索记一行：成功（有非空结果）计成本，失败/零结果计 0，但都计次数。"""
    db.add(
        UsageStat(
            tenant_id=tenant_id,
            user_id=user_id,
            slot="search",
            provider=provider[:32],
            model="",
            latency_ms=max(int(latency_ms), 0),
            cost_estimate=pricing.search_cost_usd() if success else 0.0,
        )
    )
    db.commit()
