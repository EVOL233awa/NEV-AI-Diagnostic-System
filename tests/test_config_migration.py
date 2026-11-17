"""v2.0.x → v2 配置迁移：密钥保留、备份、幂等、非官方端点不继承。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import backend.config as config_mod


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def legacy_setup(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    _write(path, {
        "server": {"host": "127.0.0.1", "port": 8600},
        "deepseek": {
            "base_url": "https://api.deepseek.com",
            "main_model": "deepseek-flash",
            "main_key": "sk-main-123456",
            "background_base_url": "https://bg.example.com",
            "background_model": "bg-model",
            "background_key": "sk-bg-654321",
        },
        "tavily": {"api_key": "tvly-legacy-123456"},
        "local_models": {
            "embedding_url": "https://api.siliconflow.cn",
            "embedding_model": "BAAI/bge-m3",
            "embedding_key": "sf-embed-123456",
            "subagent_url": "http://127.0.0.1:11435",
        },
        "small_model": {
            "base_url": "https://api.siliconflow.cn",
            "model": "Qwen/Qwen3.5-4B",
            "api_key": "sk-small",
            "title_temperature": 0.5,
            "extract_max_tokens": 500,
        },
        "security": {"jwt_secret": "legacy-secret"},
    })
    monkeypatch.setattr(config_mod, "CONFIG_PATH", path)
    monkeypatch.setattr(config_mod, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "LOG_DIR", tmp_path / "logs")
    return path


def test_migrates_legacy_keys(legacy_setup: Path):
    path = legacy_setup
    raw = config_mod.load_raw()
    config_mod._migrate_config(raw)

    # 旧槽位移除 + 密钥迁移
    assert "small_model" not in raw
    assert raw["deepseek"]["aux_key"] == "sk-bg-654321"
    assert not {"background_base_url", "background_model", "background_key"} & set(raw["deepseek"])
    assert "subagent_url" not in raw["local_models"]
    assert raw["local_models"]["embedding_key"] == "sf-embed-123456"  # 其余密钥原样保留
    assert raw["deepseek"]["main_key"] == "sk-main-123456"
    # 旧 tavily 节 → search.tavily
    assert "tavily" not in raw
    assert raw["search"]["tavily"]["api_key"] == "tvly-legacy-123456"
    # 官方主端点被继承；quota 默认全部 null（演示不限额）
    assert raw["search"]["deepseek"]["base_url"] == "https://api.deepseek.com"
    assert raw["asr"]["deepseek"]["base_url"] == "https://api.deepseek.com"
    assert raw["quota"] == {
        "asr_daily_seconds_per_user": None,
        "search_daily_calls_per_user": None,
        "global_daily_usd": None,
    }
    # 小模型参数迁入 agent
    assert raw["agent"]["title_temperature"] == 0.5
    assert raw["agent"]["extract_max_tokens"] == 500
    assert raw["_meta"]["schema_version"] == 2

    # 备份存在；落盘内容已迁移
    backups = list(path.parent.glob("config.json.bak-*"))
    assert len(backups) == 1
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert "small_model" not in on_disk and on_disk["_meta"]["schema_version"] == 2
    log = (path.parent / "logs" / "migration.log").read_text(encoding="utf-8")
    assert "small_model 已移除" in log
    assert "background_key 已迁移" in log


def test_migration_is_idempotent(legacy_setup: Path):
    path = legacy_setup
    raw = config_mod.load_raw()
    config_mod._migrate_config(raw)
    backups_before = len(list(path.parent.glob("config.json.bak-*")))

    again = json.loads(path.read_text(encoding="utf-8"))
    config_mod._migrate_config(again)
    assert len(list(path.parent.glob("config.json.bak-*"))) == backups_before


def test_non_official_main_endpoint_not_inherited(legacy_setup: Path):
    path = legacy_setup
    data = json.loads(path.read_text(encoding="utf-8"))
    data["deepseek"]["base_url"] = "https://api.other-vendor.com"
    _write(path, data)
    raw = config_mod.load_raw()
    config_mod._migrate_config(raw)
    assert raw["search"]["deepseek"]["base_url"] == ""
    assert raw["asr"]["deepseek"]["base_url"] == ""


def test_aux_key_not_overwritten(legacy_setup: Path):
    path = legacy_setup
    data = json.loads(path.read_text(encoding="utf-8"))
    data["deepseek"]["aux_key"] = "sk-aux-existing"
    _write(path, data)
    raw = config_mod.load_raw()
    config_mod._migrate_config(raw)
    assert raw["deepseek"]["aux_key"] == "sk-aux-existing"


def test_is_official_deepseek():
    assert config_mod.is_official_deepseek("https://api.deepseek.com")
    assert config_mod.is_official_deepseek("https://api.deepseek.com/v1")
    assert not config_mod.is_official_deepseek("https://api.other-vendor.com")
    assert not config_mod.is_official_deepseek("https://api.deepseek.com.evil.example")
    assert not config_mod.is_official_deepseek("")
