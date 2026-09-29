"""superadmin 调试后台回归：建号/密码策略、角色隔离、配置读写与掩码、参数热生效。

config.json 已由 conftest 重定向到临时目录：PUT 用例会真实 save_raw()，不会触碰
真实 data/config.json；settings.raw 是进程内单例，改动仅存活于本次 pytest 进程。
"""
from __future__ import annotations

import json

import pytest

import backend.config as config_mod
from backend.db.models import User
from backend.seed.seed import SUPERADMIN_USERNAME, reset_superadmin_password
from backend.security import verify_password


@pytest.fixture
def superadmin_headers(client):
    """重置 superadmin 密码（顺带覆盖 reset 路径）→ 登录拿 token。"""
    password = reset_superadmin_password()
    r = client.post("/api/auth/login", json={"username": SUPERADMIN_USERNAME, "password": password})
    assert r.status_code == 200, f"superadmin 登录失败: HTTP {r.status_code}"
    assert r.json()["user"]["role"] == "superadmin"
    return {"Authorization": f"Bearer {r.json()['token']}"}


class TestSeedAccount:
    def test_superadmin_seeded_with_random_password(self, db_session):
        user = db_session.query(User).filter(User.username == SUPERADMIN_USERNAME).one()
        assert user.role == "superadmin"
        assert user.display_name == "超级管理员"
        # 初始密码是随机字母数字，绝不是「账号名」口径
        assert not verify_password(SUPERADMIN_USERNAME, user.password_hash)
        # 明文同步存入临时 config.json（与 DB 哈希一致）——启动打印的数据源
        on_disk = json.loads(config_mod.CONFIG_PATH.read_text(encoding="utf-8"))
        stored = on_disk.get("superadmin", {}).get("password", "")
        assert len(stored) == 20 and stored.isalnum()
        assert verify_password(stored, user.password_hash)

    def test_reset_replaces_password_and_unlocks(self, client, db_session):
        user = db_session.query(User).filter(User.username == SUPERADMIN_USERNAME).one()
        old_hash = user.password_hash
        first = reset_superadmin_password()
        second = reset_superadmin_password()
        assert first != second and len(first) == 20 and first.isalnum()
        db_session.expire_all()
        assert user.password_hash != old_hash
        assert verify_password(second, user.password_hash)
        assert not verify_password(first, user.password_hash)
        # config.json 明文随 reset 同步更新为最新密码
        on_disk = json.loads(config_mod.CONFIG_PATH.read_text(encoding="utf-8"))
        assert on_disk["superadmin"]["password"] == second

    def test_ensure_seed_reprint_is_idempotent(self, db_session):
        """再次启动（ensure_seed）不改密码、不破坏 config 同步——只重复打印。"""
        from backend.seed.seed import ensure_seed

        user = db_session.query(User).filter(User.username == SUPERADMIN_USERNAME).one()
        hash_before = user.password_hash
        ensure_seed()
        db_session.expire_all()
        assert user.password_hash == hash_before
        on_disk = json.loads(config_mod.CONFIG_PATH.read_text(encoding="utf-8"))
        assert verify_password(on_disk["superadmin"]["password"], user.password_hash)


class TestAccessControl:
    def test_anonymous_rejected(self, client):
        assert client.get("/api/superadmin/config").status_code == 401

    @pytest.mark.parametrize("role_headers", ["owner_headers", "staff_headers", "admin_headers"])
    def test_other_roles_forbidden(self, client, role_headers, request):
        headers = request.getfixturevalue(role_headers)
        r = client.get("/api/superadmin/config", headers=headers)
        assert r.status_code == 403
        r = client.put(
            "/api/superadmin/config",
            headers=headers,
            json={"agent": {"max_tool_rounds": 9}},
        )
        assert r.status_code == 403

    def test_superadmin_hidden_from_member_management(self, client, db_session, admin_headers, superadmin_headers):
        rows = client.get("/api/admin/users", headers=admin_headers).json()["users"]
        assert all(u["role"] != "superadmin" for u in rows)
        target = (
            db_session.query(User).filter(User.username == SUPERADMIN_USERNAME).one().id
        )
        r = client.patch(f"/api/admin/users/{target}", headers=admin_headers, json={"display_name": "x"})
        assert r.status_code == 403
        r = client.post(f"/api/admin/users/{target}/reset-password", headers=admin_headers)
        assert r.status_code == 403
        r = client.post(f"/api/admin/users/{target}/password", headers=admin_headers, json={"new_password": "Abcd12345"})
        assert r.status_code == 403


class TestConfigApi:
    def test_get_masks_keys(self, client, superadmin_headers):
        known_key = "sk-test-abcdef1234567890"
        r = client.put(
            "/api/superadmin/config",
            headers=superadmin_headers,
            json={"providers": {"main": {"api_key": known_key}}},
        )
        assert r.status_code == 200
        cfg = client.get("/api/superadmin/config", headers=superadmin_headers).json()
        assert cfg["providers"]["main"]["has_key"] is True
        assert known_key not in json.dumps(cfg)  # 全文任何位置都不得出现完整明文 key
        assert cfg["providers"]["main"]["key_masked"].endswith("7890")

    def test_put_agent_params_hot_effective(self, client, superadmin_headers):
        r = client.put(
            "/api/superadmin/config",
            headers=superadmin_headers,
            json={"agent": {"max_tool_rounds": 9, "force_first_round_search": True}},
        )
        assert r.status_code == 200
        assert "max_tool_rounds" in r.json()["updated"]
        # 进程内热生效：agent_param 直读 settings.raw
        assert config_mod.agent_param("max_tool_rounds") == 9
        assert config_mod.agent_param("force_first_round_search") is True
        # 越界拒绝且不落值
        r = client.put(
            "/api/superadmin/config",
            headers=superadmin_headers,
            json={"agent": {"max_tool_rounds": 999}},
        )
        assert r.status_code == 400
        assert config_mod.agent_param("max_tool_rounds") == 9

    def test_put_empty_key_keeps_old_value(self, client, superadmin_headers):
        r = client.put(
            "/api/superadmin/config",
            headers=superadmin_headers,
            json={"providers": {"main": {"api_key": "sk-keep-me-1234567890"}}},
        )
        assert r.status_code == 200
        r = client.put(
            "/api/superadmin/config",
            headers=superadmin_headers,
            json={"providers": {"main": {"api_key": "", "model": "deepseek-chat"}}},
        )
        assert r.status_code == 200
        cfg = client.get("/api/superadmin/config", headers=superadmin_headers).json()
        assert cfg["providers"]["main"]["has_key"] is True  # 空串 = 不修改
        assert cfg["providers"]["main"]["model"] == "deepseek-chat"

    def test_put_persists_to_config_file(self, client, superadmin_headers):
        r = client.put(
            "/api/superadmin/config",
            headers=superadmin_headers,
            json={
                "providers": {
                    "main": {"base_url": "https://api.example.com/v1", "model": "test-model"},
                    "background": {"base_url": "https://bg.example.com"},
                }
            },
        )
        assert r.status_code == 200
        on_disk = json.loads(config_mod.CONFIG_PATH.read_text(encoding="utf-8"))
        assert on_disk["deepseek"]["base_url"] == "https://api.example.com/v1"
        assert on_disk["deepseek"]["main_model"] == "test-model"
        assert on_disk["deepseek"]["background_base_url"] == "https://bg.example.com"

    def test_put_empty_body_rejected(self, client, superadmin_headers):
        r = client.put("/api/superadmin/config", headers=superadmin_headers, json={})
        assert r.status_code == 400

    def test_update_writes_audit_log(self, client, db_session, superadmin_headers):
        from backend.db.models import AuditLog

        client.put(
            "/api/superadmin/config",
            headers=superadmin_headers,
            json={"agent": {"temperature": 0.3}},
        )
        row = (
            db_session.query(AuditLog)
            .filter(AuditLog.action == "superadmin_config_update")
            .order_by(AuditLog.id.desc())
            .first()
        )
        assert row is not None
        assert "temperature" in row.detail["keys"]
        # 审计只记键名，不记值
        assert "0.3" not in json.dumps(row.detail)
