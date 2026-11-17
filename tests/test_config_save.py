"""config.json 写入与测试隔离回归：原子替换、失败不破坏旧文件、不读真实配置。"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import backend.config as config_mod


def test_conftest_uses_isolated_config_path() -> None:
    assert config_mod.CONFIG_PATH == Path(os.environ["NEV_CONFIG_PATH"])
    assert config_mod.CONFIG_PATH != config_mod.BASE_DIR / "data" / "config.json"
    assert "nev-diag-test-" in str(config_mod.CONFIG_PATH.parent)


def test_save_raw_is_atomic_and_leaves_no_tmp(tmp_path, monkeypatch) -> None:
    path = tmp_path / "config.json"
    path.write_text('{"old": true}\n', encoding="utf-8")
    monkeypatch.setattr(config_mod, "CONFIG_PATH", path)
    monkeypatch.setattr(config_mod, "DATA_DIR", tmp_path)

    config_mod.save_raw({"old": False, "密钥": "值"})

    assert json.loads(path.read_text(encoding="utf-8")) == {"old": False, "密钥": "值"}
    assert not (tmp_path / "config.json.tmp").exists()


def test_save_raw_failure_keeps_previous_file(tmp_path, monkeypatch) -> None:
    path = tmp_path / "config.json"
    path.write_text('{"stable": true}\n', encoding="utf-8")
    monkeypatch.setattr(config_mod, "CONFIG_PATH", path)
    monkeypatch.setattr(config_mod, "DATA_DIR", tmp_path)

    def _boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(config_mod.os, "replace", _boom)
    with pytest.raises(OSError, match="disk full"):
        config_mod.save_raw({"stable": False})

    assert json.loads(path.read_text(encoding="utf-8")) == {"stable": True}
    assert not (tmp_path / "config.json.tmp").exists()
