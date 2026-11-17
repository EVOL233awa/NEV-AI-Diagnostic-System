"""限额与计量：null/0 不限制短路、每用户/全局上限、当日边界、usage 落账。"""
from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

import backend.core.quota as quota_mod
from backend.core.tools import registry
from backend.db.models import AuditLog, Session as ChatSession, UsageStat, User

USER = 9001


def _settings(**quota) -> SimpleNamespace:
    defaults = {
        "asr_daily_seconds_per_user": None,
        "search_daily_calls_per_user": None,
        "global_daily_usd": None,
    }
    defaults.update(quota)
    return SimpleNamespace(quota=defaults)


class TestNormalizeLimit:
    @pytest.mark.parametrize("value", [None, "", "  ", 0, 0.0, -1, "abc", math.nan, math.inf])
    def test_unlimited_values(self, value):
        assert quota_mod.normalize_limit(value) is None

    @pytest.mark.parametrize("value,expected", [(300, 300.0), ("50", 50.0), (2.5, 2.5)])
    def test_positive_values(self, value, expected):
        assert quota_mod.normalize_limit(value) == expected


def test_disabled_short_circuits_without_db(monkeypatch):
    monkeypatch.setattr(quota_mod, "settings", _settings())

    class _Boom:
        def execute(self, *args, **kwargs):  # pragma: no cover - 触达即失败
            raise AssertionError("未启用限额时不应查库")

    assert quota_mod.check_asr(_Boom(), USER) is None
    assert quota_mod.check_search(_Boom(), USER) is None


def test_asr_user_limit_and_reset(db_session, monkeypatch):
    monkeypatch.setattr(quota_mod, "settings", _settings(asr_daily_seconds_per_user=300))
    db_session.add(UsageStat(tenant_id=1, user_id=USER, slot="asr", duration_ms=200_000))
    db_session.commit()
    assert quota_mod.check_asr(db_session, USER) is None
    db_session.add(UsageStat(tenant_id=1, user_id=USER, slot="asr", duration_ms=100_000))
    db_session.commit()
    assert quota_mod.check_asr(db_session, USER) == "user"

    # 昨天的用量不计入今日
    db_session.add(UsageStat(tenant_id=1, user_id=USER + 1, slot="asr", duration_ms=999_000,
                             created_at=datetime.now() - timedelta(days=1)))
    db_session.commit()
    assert quota_mod.check_asr(db_session, USER + 1) is None


def test_search_user_limit(db_session, monkeypatch):
    monkeypatch.setattr(quota_mod, "settings", _settings(search_daily_calls_per_user=2))
    for _ in range(2):
        db_session.add(UsageStat(tenant_id=1, user_id=USER + 2, slot="search",
                                 cost_estimate=0.0))
    db_session.commit()
    assert quota_mod.check_search(db_session, USER + 2) == "user"
    assert quota_mod.check_search(db_session, USER + 3) is None


def test_global_budget_blocks_both(db_session, monkeypatch):
    db_session.add(UsageStat(tenant_id=1, user_id=USER + 4, slot="search",
                             cost_estimate=1.2))
    db_session.add(UsageStat(tenant_id=1, user_id=USER + 4, slot="asr",
                             duration_ms=1000, cost_estimate=0.9))
    db_session.commit()
    monkeypatch.setattr(quota_mod, "settings", _settings(global_daily_usd=2.0))
    assert quota_mod.check_asr(db_session, USER + 5) == "global"
    assert quota_mod.check_search(db_session, USER + 5) == "global"

    # 清空预算立即恢复
    monkeypatch.setattr(quota_mod, "settings", _settings())
    assert quota_mod.check_asr(db_session, USER + 5) is None


def test_record_asr_and_search(db_session, monkeypatch):
    monkeypatch.setattr(quota_mod, "settings", _settings())
    quota_mod.record_asr(
        db_session, tenant_id=1, user_id=USER + 6, provider="deepseek",
        model="asr", duration_ms=60_000, latency_ms=1200,
    )
    row = (db_session.query(UsageStat)
           .filter_by(user_id=USER + 6, slot="asr")
           .order_by(UsageStat.id.desc()).first())
    assert row is not None and row.duration_ms == 60_000
    assert row.cost_estimate == pytest.approx(60_000 / 3_600_000 * 0.116, rel=1e-3)

    quota_mod.record_search(db_session, tenant_id=1, user_id=USER + 6, provider="tavily",
                            success=True, latency_ms=300)
    quota_mod.record_search(db_session, tenant_id=1, user_id=USER + 6, provider="tavily",
                            success=False, latency_ms=100)
    rows = (db_session.query(UsageStat)
            .filter_by(user_id=USER + 6, slot="search")
            .order_by(UsageStat.id).all())
    assert [r.cost_estimate for r in rows] == [0.00075, 0.0]
    # 用户搜索限额按发起次数计：失败/零结果同样占一次
    monkeypatch.setattr(quota_mod, "settings", _settings(search_daily_calls_per_user=2))
    assert quota_mod.check_search(db_session, USER + 6) == "user"


def test_blocked_web_search_writes_audit(db_session, monkeypatch) -> None:
    """限额拒绝也要留痕（D24），否则无法追查谁在撞额度。"""
    owner = db_session.query(User).filter_by(username="user001").one()
    session = ChatSession(tenant_id=1, user_id=owner.id, title="限额审计", channel="owner")
    db_session.add(session)
    db_session.add(UsageStat(tenant_id=1, user_id=owner.id, slot="search", cost_estimate=0.0))
    db_session.commit()
    monkeypatch.setattr(quota_mod, "settings", _settings(search_daily_calls_per_user=1))

    outcome = asyncio.run(
        registry._tool_web_search(
            db_session, "测试查询", registry.ToolContext(session=session)
        )
    )
    assert "额度已用完" in outcome.text
    db_session.expire_all()
    audit = (
        db_session.query(AuditLog)
        .filter_by(action="search_quota_blocked", user_id=owner.id)
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert audit is not None
    assert audit.detail["blocked"] == "user"
    assert "测试查询" not in str(audit.detail)
