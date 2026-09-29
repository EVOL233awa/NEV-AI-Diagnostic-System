"""启动入口：python main.py（一条命令，Windows 本机与云服务器同款跑法）。

superadmin 密码每次启动都会打印到本进程的终端窗口（明文存服务器本机
data/config.json）；python main.py --reset-superadmin 可重新生成后退出（不启动服务）。
"""
from __future__ import annotations

import argparse

import uvicorn

from backend.config import settings


def _reset_superadmin() -> None:
    from backend.db.base import init_db
    from backend.seed.seed import SUPERADMIN_USERNAME, reset_superadmin_password

    init_db()
    password = reset_superadmin_password()
    print()
    print("=" * 64)
    print("  [超级管理员密码已重置] 旧密码立即作废，请立即妥善保管")
    print(f"  账号：{SUPERADMIN_USERNAME}")
    print(f"  密码：{password}")
    print("  （明文已同步写入 data/config.json，之后每次启动后端都会在本窗口显示）")
    print("=" * 64)
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="新能源汽车 AI 智能诊断系统 2.0")
    parser.add_argument("--host", default=settings.host, help="监听地址（店内局域网直连用 0.0.0.0）")
    parser.add_argument("--port", type=int, default=settings.port)
    parser.add_argument("--reload", action="store_true", help="开发模式热重载")
    parser.add_argument(
        "--reset-superadmin", action="store_true",
        help="重新生成 superadmin 随机密码并打印到当前终端后退出（不启动服务）",
    )
    args = parser.parse_args()
    if args.reset_superadmin:
        _reset_superadmin()
        return
    uvicorn.run("backend.app:create_app", factory=True, host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
