"""SQLite 引擎与会话工厂。单文件库 data/data.db，换机 = 拷 data 目录。"""
from __future__ import annotations

import sqlite3

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.config import DB_PATH

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)

# sqlite-vec 扩展：每个连接都要加载一次（向量检索路）。
# 加载失败不致命：retrieve 层据此退化为纯关键词路（商用容错）。
VEC_AVAILABLE = True
try:
    import sqlite_vec
except ImportError:  # pragma: no cover
    VEC_AVAILABLE = False

    def _load_vec(dbapi_conn: object, _record: object) -> None:  # type: ignore[misc]
        return None

else:

    def _load_vec(dbapi_conn: object, _record: object) -> None:  # type: ignore[misc]
        if isinstance(dbapi_conn, sqlite3.Connection):
            try:
                dbapi_conn.enable_load_extension(True)
                sqlite_vec.load(dbapi_conn)
                dbapi_conn.enable_load_extension(False)
            except (AttributeError, sqlite3.Error):
                global VEC_AVAILABLE
                VEC_AVAILABLE = False


event.listen(Engine, "connect", _load_vec)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    from backend.db import migrations
    from backend.db import models  # noqa: F401  确保模型全部注册后再建表

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    # create_all 不改已有表结构，轻量列迁移补齐（alembic 在多店阶段引入）
    with SessionLocal() as s:
        migrations.ensure_columns(s)
