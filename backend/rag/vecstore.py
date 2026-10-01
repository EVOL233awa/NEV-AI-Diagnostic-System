"""sqlite-vec 单文件向量库封装（底层语义路）。

vec_chunks 虚拟表：rowid = kb_chunks.id，embedding float[1024]（bge-m3 实测维度）。
扩展加载失败（VEC_AVAILABLE=False）时本模块全部操作空转，上层退化纯关键词路。
"""
from __future__ import annotations

import struct

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from backend.db.base import VEC_AVAILABLE

EMBED_DIM = 1024

_vec_ensured = False


def ensure_vec_table(db: Session) -> bool:
    """建 vec0 虚拟表（幂等）。返回向量路是否可用。"""
    global _vec_ensured
    if not VEC_AVAILABLE:
        return False
    if _vec_ensured:
        return True
    try:
        db.execute(
            text(f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(embedding float[{EMBED_DIM}])")
        )
        db.commit()
        _vec_ensured = True
        return True
    except Exception:
        return False


def _to_blob(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)


def upsert(db: Session, chunk_id: int, vector: list[float]) -> None:
    if not VEC_AVAILABLE:
        return
    db.execute(text("DELETE FROM vec_chunks WHERE rowid = :cid"), {"cid": chunk_id})
    db.execute(
        text("INSERT INTO vec_chunks(rowid, embedding) VALUES (:cid, :vec)"),
        {"cid": chunk_id, "vec": _to_blob(vector)},
    )


def delete(db: Session, chunk_ids: list[int]) -> None:
    if not VEC_AVAILABLE or not chunk_ids:
        return
    db.execute(
        text("DELETE FROM vec_chunks WHERE rowid IN :ids").bindparams(
            bindparam("ids", expanding=True)
        ),
        {"ids": chunk_ids},
    )


def knn_search(db: Session, query_vector: list[float], top_k: int) -> list[tuple[int, float]]:
    """返回 [(chunk_id, distance)]，distance 越小越相似。

    k 用 vec0 专用约束列（k = :k）而非 SQL LIMIT：老版 SQLite（如 Ubuntu 22.04 的 3.37）
    无法把绑定参数形式的 LIMIT 传进 vec0 查询计划，会报 "A LIMIT or 'k = ?' constraint
    is required"；k 约束由 vtab 层读取，新旧 SQLite 均兼容。
    """
    if not VEC_AVAILABLE:
        return []
    rows = db.execute(
        text(
            "SELECT rowid, distance FROM vec_chunks "
            "WHERE embedding MATCH :vec AND k = :k ORDER BY distance"
        ),
        {"vec": _to_blob(query_vector), "k": top_k},
    ).fetchall()
    return [(int(r[0]), float(r[1])) for r in rows]
