"""superadmin 后台回归：密码来源优先级、角色隔离、配置读写与掩码、参数热生效。

config.json 已由 conftest 重定向到临时目录：PUT 用例会真实 save_raw()，不会触碰
真实 data/config.json；settings.raw 是进程内单例，改动仅存活于本次 pytest 进程。
"""
from __future__ import annotations

import json

import pytest

import backend.config as config_mod
from backend.db.models import AuditLog, User
from backend.seed.seed import (
    SUPERADMIN_ENV_VAR,
    SUPERADMIN_USERNAME,
    reset_superadmin_password,
)
from backend.security import verify_password


@pytest.fixture
def superadmin_headers(client, monkeypatch):
    """按优先级重新应用密码（env 未设 → config 固定值）→ 登录拿 token。"""
    monkeypatch.delenv(SUPERADMIN_ENV_VAR, raising=False)
    password = reset_superadmin_password()
    r = client.post("/api/auth/login", json={"username": SUPERADMIN_USERNAME, "password": password})
    assert r.status_code == 200, f"superadmin 登录失败: HTTP {r.status_code}"
    assert r.json()["user"]["role"] == "superadmin"
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _config_on_disk() -> dict:
    return json.loads(config_mod.CONFIG_PATH.read_text(encoding="utf-8"))


class TestSeedAccount:
    def test_superadmin_seeded_with_random_password(self, db_session):
        user = db_session.query(User).filter(User.username == SUPERADMIN_USERNAME).one()
        assert user.role == "superadmin"
        assert user.display_name == "超级管理员"
        # 初始密码是随机字母数字，绝不是「账号名」口径
        assert not verify_password(SUPERADMIN_USERNAME, user.password_hash)
        # 明文同步存入临时 config.json（与 DB 哈希一致）——启动打印的数据源
        on_disk = _config_on_disk()
        stored = on_disk.get("superadmin", {}).get("password", "")
        assert len(stored) == 20 and stored.isalnum()
        assert verify_password(stored, user.password_hash)

    def test_reset_keeps_fixed_password(self, client, db_session):
        """固定值语义：config 已有密码时 reset 不再无条件随机。"""
        user = db_session.query(User).filter(User.username == SUPERADMIN_USERNAME).one()
        first = reset_superadmin_password()
        second = reset_superadmin_password()
        assert first == second == _config_on_disk()["superadmin"]["password"]
        db_session.expire_all()
        assert verify_password(second, user.password_hash)

    def test_reset_generates_when_no_password(self, client, db_session, monkeypatch):
        monkeypatch.delenv(SUPERADMIN_ENV_VAR, raising=False)
        config_mod.settings.raw["superadmin"] = {}
        config_mod.save_raw(config_mod.settings.raw)

        first = reset_superadmin_password()
        assert len(first) == 20 and first.isalnum()
        on_disk = _config_on_disk()
        assert on_disk["superadmin"]["password"] == first
        assert on_disk["superadmin"]["password_source"] == "generated"

        second = reset_superadmin_password()
        assert second == first  # 一次性生成后即固定

    def test_env_overrides_and_syncs(self, client, db_session, monkeypatch):
        monkeypatch.setenv(SUPERADMIN_ENV_VAR, "EnvPass12345")
        user = db_session.query(User).filter(User.username == SUPERADMIN_USERNAME).one()
        password = reset_superadmin_password()
        assert password == "EnvPass12345"
        db_session.expire_all()
        assert verify_password(password, user.password_hash)
        on_disk = _config_on_disk()
        assert on_disk["superadmin"] == {"password": "EnvPass12345", "password_source": "env"}

    def test_env_weak_password_refuses_start(self, client, monkeypatch):
        monkeypatch.setenv(SUPERADMIN_ENV_VAR, "short")
        with pytest.raises(SystemExit):
            reset_superadmin_password()

    def test_ensure_seed_reprint_is_idempotent(self, db_session, monkeypatch):
        """再次启动（ensure_seed）不改密码、不破坏 config 同步——只重复打印。"""
        from backend.seed.seed import ensure_seed

        monkeypatch.delenv(SUPERADMIN_ENV_VAR, raising=False)
        user = db_session.query(User).filter(User.username == SUPERADMIN_USERNAME).one()
        hash_before = user.password_hash
        ensure_seed()
        db_session.expire_all()
        assert user.password_hash == hash_before
        on_disk = _config_on_disk()
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

    def test_aux_key_masked_and_clearable(self, client, superadmin_headers):
        aux_key = "sk-aux-abcdef123456"
        r = client.put(
            "/api/superadmin/config",
            headers=superadmin_headers,
            json={"providers": {"main": {"aux_key": aux_key}}},
        )
        assert r.status_code == 200
        cfg = client.get("/api/superadmin/config", headers=superadmin_headers).json()
        assert cfg["providers"]["main"]["aux_has_key"] is True
        assert aux_key not in json.dumps(cfg)
        assert cfg["providers"]["main"]["aux_key_masked"].endswith("3456")

        # 空串 = 保持；__clear__ = 显式清除
        client.put("/api/superadmin/config", headers=superadmin_headers,
                   json={"providers": {"main": {"aux_key": ""}}})
        cfg = client.get("/api/superadmin/config", headers=superadmin_headers).json()
        assert cfg["providers"]["main"]["aux_has_key"] is True
        client.put("/api/superadmin/config", headers=superadmin_headers,
                   json={"providers": {"main": {"aux_key": "__clear__"}}})
        cfg = client.get("/api/superadmin/config", headers=superadmin_headers).json()
        assert cfg["providers"]["main"]["aux_has_key"] is False

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

    def test_failed_put_rolls_back_hot_and_disk_config(self, client, superadmin_headers):
        """同一 PUT 里前面的合法字段不能因后面的非法字段而半生效。"""
        before_url = client.get(
            "/api/superadmin/config", headers=superadmin_headers
        ).json()["providers"]["main"]["base_url"]
        before_disk_url = _config_on_disk().get("deepseek", {}).get("base_url", "")
        before_rounds = config_mod.agent_param("max_tool_rounds")

        r = client.put(
            "/api/superadmin/config",
            headers=superadmin_headers,
            json={
                "providers": {"main": {"base_url": "https://rollback.example/v1"}},
                "agent": {"max_tool_rounds": 999},
            },
        )
        assert r.status_code == 400
        after_url = client.get(
            "/api/superadmin/config", headers=superadmin_headers
        ).json()["providers"]["main"]["base_url"]
        assert after_url == before_url
        assert _config_on_disk().get("deepseek", {}).get("base_url", "") == before_disk_url
        assert config_mod.agent_param("max_tool_rounds") == before_rounds

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
                "providers": {"main": {"base_url": "https://api.example.com/v1", "model": "test-model"}},
                "search": {"provider": "tavily", "count": 8},
            },
        )
        assert r.status_code == 200
        on_disk = _config_on_disk()
        assert on_disk["deepseek"]["base_url"] == "https://api.example.com/v1"
        assert on_disk["deepseek"]["main_model"] == "test-model"
        assert on_disk["search"]["provider"] == "tavily"
        assert on_disk["search"]["count"] == 8

    def test_search_asr_config_put(self, client, superadmin_headers):
        r = client.put(
            "/api/superadmin/config",
            headers=superadmin_headers,
            json={
                "search": {
                    "provider": "tavily",
                    "fallback_to_tavily": True,
                    "fallback_on_empty": True,
                    "tavily": {"search_depth": "advanced", "api_key": "tvly-secret-123456",
                               "max_results": 7},
                    "deepseek": {"dynamic_language": False, "timeout": 15},
                },
                "asr": {
                    "provider": "openai",
                    "max_seconds": 90,
                    "openai": {"base_url": "https://asr.example.com", "model": "whisper-1",
                               "api_key": "asr-secret-123456"},
                },
            },
        )
        assert r.status_code == 200
        cfg = client.get("/api/superadmin/config", headers=superadmin_headers).json()
        assert cfg["search"]["provider"] == "tavily"
        assert cfg["search"]["fallback_on_empty"] is True
        assert cfg["search"]["tavily"]["search_depth"] == "advanced"
        assert cfg["search"]["tavily"]["has_key"] is True
        assert cfg["search"]["tavily"]["key_masked"].endswith("3456")
        assert cfg["search"]["deepseek"]["dynamic_language"] is False
        assert cfg["asr"]["provider"] == "openai"
        assert cfg["asr"]["max_seconds"] == 90
        assert cfg["asr"]["openai"]["has_key"] is True
        assert "tvly-secret-123456" not in json.dumps(cfg)
        assert "asr-secret-123456" not in json.dumps(cfg)

    def test_quota_null_zero_and_positive(self, client, superadmin_headers):
        r = client.put(
            "/api/superadmin/config",
            headers=superadmin_headers,
            json={"quota": {k: None for k in
                            ("asr_daily_seconds_per_user", "search_daily_calls_per_user", "global_daily_cny")}},
        )
        assert r.status_code == 200
        cfg = client.get("/api/superadmin/config", headers=superadmin_headers).json()
        assert cfg["quota"] == {k: None for k in cfg["quota"]}

        r = client.put("/api/superadmin/config", headers=superadmin_headers,
                       json={"quota": {"asr_daily_seconds_per_user": 300,
                                       "search_daily_calls_per_user": 50,
                                       "global_daily_cny": 2.0}})
        assert r.status_code == 200
        assert config_mod.settings.quota == {
            "asr_daily_seconds_per_user": 300.0,
            "search_daily_calls_per_user": 50.0,
            "global_daily_cny": 2.0,
        }
        # 0 = 不限制
        r = client.put("/api/superadmin/config", headers=superadmin_headers,
                       json={"quota": {"asr_daily_seconds_per_user": 0}})
        assert r.status_code == 200
        assert config_mod.settings.quota["asr_daily_seconds_per_user"] is None
        # 负数拒绝
        r = client.put("/api/superadmin/config", headers=superadmin_headers,
                       json={"quota": {"global_daily_cny": -1}})
        assert r.status_code == 400

    def test_put_empty_body_rejected(self, client, superadmin_headers):
        r = client.put("/api/superadmin/config", headers=superadmin_headers, json={})
        assert r.status_code == 400

    def test_update_writes_audit_log(self, client, db_session, superadmin_headers):
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

    def test_password_endpoint(self, client, db_session, superadmin_headers, monkeypatch):
        monkeypatch.delenv(SUPERADMIN_ENV_VAR, raising=False)
        r = client.put("/api/superadmin/password", headers=superadmin_headers,
                       json={"new_password": "NewPass12345"})
        assert r.status_code == 200
        on_disk = _config_on_disk()
        assert on_disk["superadmin"] == {"password": "NewPass12345", "password_source": "config"}
        user = db_session.query(User).filter(User.username == SUPERADMIN_USERNAME).one()
        db_session.expire_all()
        assert verify_password("NewPass12345", user.password_hash)
        # 新密码可登录
        r = client.post("/api/auth/login",
                        json={"username": SUPERADMIN_USERNAME, "password": "NewPass12345"})
        assert r.status_code == 200
        # 强度不足（含账号名）拒绝
        r = client.put("/api/superadmin/password", headers=superadmin_headers,
                       json={"new_password": "superadmin123"})
        assert r.status_code == 400
        # 审计存在
        row = (db_session.query(AuditLog)
               .filter(AuditLog.action == "superadmin_password_set")
               .order_by(AuditLog.id.desc()).first())
        assert row is not None


class TestHealth:
    def test_health_fields(self, client):
        body = client.get("/api/health").json()
        assert body["version"] == "2.1.0"
        providers = body["providers"]
        assert providers["search_provider"] in ("deepseek", "tavily", "custom")
        assert isinstance(providers["asr_configured"], bool)
        assert isinstance(providers["web_search"], bool)
