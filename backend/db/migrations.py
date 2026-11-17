"""轻量列迁移：SQLite 场景在 alembic 引入前的务实方案。

只做两类变更：加列（ALTER TABLE ADD COLUMN）、
以及 users 表的约束放宽重建（phone NOT NULL → 可空，账号登录迁移）。
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

# 表名 -> [(列名, DDL 类型)]
_PLANNED: dict[str, list[tuple[str, str]]] = {
    "sessions": [
        ("case_notes", "JSON"),  # 诊断状态卡（update_case_notes 维护）
        ("context_summary", "TEXT"),  # 前情摘要（双阀门压缩）
        ("summarized_until_id", "INTEGER"),  # 已压缩消息边界
    ],
    "users": [
        ("privacy_share_admin", "BOOLEAN NOT NULL DEFAULT 0"),  # 管理员查看原文授权（默认关）
    ],
    "vehicle_profiles": [
        ("mileage", "INTEGER"),  # 里程 km（可选）
    ],
    "usage_stats": [
        ("duration_ms", "INTEGER NOT NULL DEFAULT 0"),  # ASR 音频时长
    ],
}

# JSON 列旧行把 None 存成了文本 'null'（SQLAlchemy JSON 默认 none_as_null=False），
# 使 `col IS NOT NULL` 对所有行成立。模型已改为 none_as_null=True，这里清理存量。
_JSON_NULL_COLUMNS = (
    ("sessions", "pending_questions"),
    ("sessions", "case_notes"),
    ("messages", "tool_calls"),
    ("messages", "diag_json"),
    ("appointments", "summary_card"),
    ("provider_configs", "params"),
    ("audit_logs", "detail"),
)

_USERS_REBUILD_SQL = """
CREATE TABLE users_new (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    username VARCHAR(32),
    phone VARCHAR(32),
    password_hash VARCHAR(256) NOT NULL,
    role VARCHAR(16) NOT NULL,
    display_name VARCHAR(64) NOT NULL,
    privacy_share_dialog BOOLEAN NOT NULL,
    privacy_share_admin BOOLEAN NOT NULL DEFAULT 0,
    disabled BOOLEAN NOT NULL,
    created_at DATETIME NOT NULL,
    last_login_at DATETIME
)
"""


def ensure_columns(db: Session) -> None:
    for table, columns in _PLANNED.items():
        existing = {row[1] for row in db.execute(text(f"PRAGMA table_info({table})")).fetchall()}
        if not existing:
            continue
        for col, ddl in columns:
            if col not in existing:
                db.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))

    user_cols = {row[1] for row in db.execute(text("PRAGMA table_info(users)")).fetchall()}
    if user_cols:
        if "username" not in user_cols:
            db.execute(text("ALTER TABLE users ADD COLUMN username VARCHAR(32)"))
        db.execute(text("UPDATE users SET username = phone WHERE username IS NULL OR username = ''"))

        # phone NOT NULL 约束无法用 ALTER 放宽：整表重建（SQLite 标准十二步法）
        phone_notnull = db.execute(
            text("PRAGMA table_info(users)")
        ).fetchall()
        needs_rebuild = any(row[1] == "phone" and row[3] == 1 for row in phone_notnull)
        if needs_rebuild:
            db.execute(text(_USERS_REBUILD_SQL))
            db.execute(
                text(
                    "INSERT INTO users_new (id, tenant_id, username, phone, password_hash, role,"
                    " display_name, privacy_share_dialog, privacy_share_admin, disabled, created_at, last_login_at)"
                    " SELECT id, tenant_id, username, phone, password_hash, role, display_name,"
                    " privacy_share_dialog, privacy_share_admin, disabled, created_at, last_login_at FROM users"
                )
            )
            db.execute(text("DROP TABLE users"))
            db.execute(text("ALTER TABLE users_new RENAME TO users"))

        db.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users(username)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS ix_users_tenant_id ON users(tenant_id)"))

    for table, col in _JSON_NULL_COLUMNS:
        cols = {row[1] for row in db.execute(text(f"PRAGMA table_info({table})")).fetchall()}
        if col in cols:
            db.execute(text(f"UPDATE {table} SET {col} = NULL WHERE {col} = 'null'"))
    db.commit()
