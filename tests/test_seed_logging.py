"""启动日志脱敏：superadmin 密码只在一次性生成时回显，env/config 来源不得出日志。"""
from __future__ import annotations

from backend.seed import seed


def test_config_source_password_not_printed(capsys) -> None:
    seed._print_superadmin_password("ConfigSecret123", "config")
    out = capsys.readouterr().out
    assert "ConfigSecret123" not in out
    assert "不在日志显示" in out


def test_env_source_password_not_printed(capsys) -> None:
    seed._print_superadmin_password("EnvSecret12345", "env")
    out = capsys.readouterr().out
    assert "EnvSecret12345" not in out


def test_generated_password_still_printed_once(capsys) -> None:
    seed._print_superadmin_password("Generated12345", "generated")
    out = capsys.readouterr().out
    assert "Generated12345" in out
