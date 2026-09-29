"""安全加固回归：登录失败限速（A1）+ 改密码弱口令校验（A2）。

限速状态是 auth 模块级内存 dict——每个用例结束必须清理，避免污染后续登录；
锁定/爆破一律使用专用测试账号，绝不触碰种子账号（user001 等还要被其它用例登录）。
"""
from __future__ import annotations

from typing import Iterator

import pytest

import backend.api.auth as auth_mod
from backend.db.models import User
from backend.security import hash_password


@pytest.fixture
def clean_login_fails() -> Iterator[None]:
    """用例前后清空限速表：测试库可重建，进程内限速态必须手动还原。"""
    auth_mod._login_fails.clear()
    yield
    auth_mod._login_fails.clear()


def _create_user(db, username: str, password: str, role: str = "owner") -> User:
    user = User(
        tenant_id=1,
        username=username,
        password_hash=hash_password(password),
        role=role,
        display_name=username,
    )
    db.add(user)
    db.commit()
    return user


class TestLoginRateLimit:
    def test_five_failures_then_429(self, client, db_session, clean_login_fails):
        for _ in range(auth_mod.LOGIN_FAIL_LIMIT):
            r = client.post("/api/auth/login", json={"username": "bruteforce_x", "password": "wrong"})
            assert r.status_code == 401
        r = client.post("/api/auth/login", json={"username": "bruteforce_x", "password": "wrong"})
        assert r.status_code == 429
        assert "锁定" in r.json()["detail"]

    def test_lock_isolates_accounts(self, client, db_session, clean_login_fails):
        for _ in range(auth_mod.LOGIN_FAIL_LIMIT):
            client.post("/api/auth/login", json={"username": "bruteforce_x", "password": "wrong"})
        r = client.post("/api/auth/login", json={"username": "user001", "password": "wrong"})
        assert r.status_code == 401  # 其它账号不受同一账号锁定影响（按账号维度计数）

    def test_lock_rejects_correct_password_until_window(self, client, db_session, clean_login_fails):
        _create_user(db_session, "locktest001", "locktest001")
        for _ in range(auth_mod.LOGIN_FAIL_LIMIT):
            assert client.post(
                "/api/auth/login", json={"username": "locktest001", "password": "nope"}
            ).status_code == 401
        r = client.post("/api/auth/login", json={"username": "locktest001", "password": "locktest001"})
        assert r.status_code == 429  # 锁定窗口内正确密码也拒绝（验证前短路，不消耗 PBKDF2）
        r = client.post("/api/auth/login", json={"username": "locktest001", "password": "locktest001"})
        assert r.status_code == 429

    def test_success_resets_counter(self, client, db_session, clean_login_fails):
        """失败未达阈值 + 登录成功 → 计数清零，之后单次失败不会立即叠加锁定。"""
        _create_user(db_session, "locktest002", "Locktest2026x")
        for _ in range(auth_mod.LOGIN_FAIL_LIMIT - 1):
            client.post("/api/auth/login", json={"username": "locktest002", "password": "nope"})
        r = client.post("/api/auth/login", json={"username": "locktest002", "password": "Locktest2026x"})
        assert r.status_code == 200
        assert auth_mod._login_fails.get("locktest002") is None
        r = client.post("/api/auth/login", json={"username": "locktest002", "password": "nope"})
        assert r.status_code == 401  # 清零后 1 次失败远未到锁定线

    def test_expired_window_unlocks(self, client, db_session, clean_login_fails):
        """窗口外的旧失败记录自动剪除：模拟 15 分钟后锁定解除。"""
        from datetime import datetime, timedelta

        old = datetime.now() - auth_mod.LOGIN_LOCK_WINDOW - timedelta(seconds=1)
        auth_mod._login_fails["bruteforce_y"] = [old] * auth_mod.LOGIN_FAIL_LIMIT
        r = client.post("/api/auth/login", json={"username": "bruteforce_y", "password": "x"})
        assert r.status_code == 401  # 不再 429：过期窗口剪除即解锁
        # 本次 401 又记了 1 次新失败（窗口重启），而非沿用 5 次旧账
        assert len(auth_mod._login_fails["bruteforce_y"]) == 1


class TestPasswordStrength:
    def test_rule_unit(self):
        from fastapi import HTTPException

        from backend.api.auth import ensure_password_strength

        for bad in ("12345678", "abcdefgh", "Ab1", "user001x1", "PWuser001"):
            with pytest.raises(HTTPException):
                ensure_password_strength(bad, "user001")
        ensure_password_strength("NevDiag2026", "user001")  # 合法不抛

    def test_change_password_rejects_weak(self, client, db_session, clean_login_fails):
        _create_user(db_session, "pwtest001", "pwtest001")
        r = client.post("/api/auth/login", json={"username": "pwtest001", "password": "pwtest001"})
        assert r.status_code == 200
        headers = {"Authorization": f"Bearer {r.json()['token']}"}

        for weak in ("12345678", "abcdefgh", "pwtest001ab"):  # 纯数字 / 纯字母 / 含账号名
            r = client.post(
                "/api/auth/change-password",
                json={"old_password": "pwtest001", "new_password": weak},
                headers=headers,
            )
            assert r.status_code == 400, weak
            assert "8 位" in r.json()["detail"]

    def test_change_password_accepts_strong(self, client, db_session, clean_login_fails):
        _create_user(db_session, "pwtest002", "pwtest002")
        r = client.post("/api/auth/login", json={"username": "pwtest002", "password": "pwtest002"})
        headers = {"Authorization": f"Bearer {r.json()['token']}"}

        r = client.post(
            "/api/auth/change-password",
            json={"old_password": "pwtest002", "new_password": "NevDiag2026"},
            headers=headers,
        )
        assert r.status_code == 200
        # 新密码真实生效：旧密码 401、新密码 200
        assert client.post(
            "/api/auth/login", json={"username": "pwtest002", "password": "pwtest002"}
        ).status_code == 401
        assert client.post(
            "/api/auth/login", json={"username": "pwtest002", "password": "NevDiag2026"}
        ).status_code == 200

    def test_short_password_422(self, client, db_session, clean_login_fails):
        _create_user(db_session, "pwtest003", "pwtest003")
        r = client.post("/api/auth/login", json={"username": "pwtest003", "password": "pwtest003"})
        headers = {"Authorization": f"Bearer {r.json()['token']}"}
        r = client.post(
            "/api/auth/change-password",
            json={"old_password": "pwtest003", "new_password": "ab1"},
            headers=headers,
        )
        assert r.status_code == 422  # pydantic min_length=8 先于业务校验
