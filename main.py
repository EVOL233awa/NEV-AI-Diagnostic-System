"""启动入口：python main.py（一条命令，Windows 本机与云服务器同款跑法）。

superadmin 密码在每次启动时打印到本进程终端窗口（来源标注 env/config/generated）：
- 固定密码：python main.py --set-superadmin-password <value>（写入 config 后退出）
- 环境变量：NEV_SUPERADMIN_PASSWORD（部署优先，systemd EnvironmentFile 权限受限）
- 重新应用优先级：python main.py --reset-superadmin（不启动服务）
"""
from __future__ import annotations

import argparse

import uvicorn

from backend.config import settings


def _reapply_superadmin(override: str | None = None) -> None:
    from backend.db.base import init_db
    from backend.seed.seed import ensure_seed

    init_db()
    ensure_seed(superadmin_override=override)


def main() -> None:
    parser = argparse.ArgumentParser(description="新能源汽车 AI 智能诊断系统 2.1")
    parser.add_argument("--host", default=settings.host, help="监听地址（店内局域网直连用 0.0.0.0）")
    parser.add_argument("--port", type=int, default=settings.port)
    parser.add_argument("--reload", action="store_true", help="开发模式热重载")
    parser.add_argument(
        "--set-superadmin-password", metavar="PASSWORD", default=None,
        help="设置 superadmin 固定密码（写入 config 与 DB 后退出；会进 shell history，仅一次性设置用）",
    )
    parser.add_argument(
        "--reset-superadmin", action="store_true",
        help="按优先级重新应用 superadmin 密码（env > config > 一次性随机）后退出，不启动服务",
    )
    args = parser.parse_args()
    if args.set_superadmin_password:
        _reapply_superadmin(args.set_superadmin_password)
        return
    if args.reset_superadmin:
        _reapply_superadmin()
        return
    uvicorn.run("backend.app:create_app", factory=True, host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
