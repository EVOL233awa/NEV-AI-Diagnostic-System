"""DTC 码表共享服务：种子码表加载 + 知识块精确查询 + 模糊搜索 + 详情。

Agent 的 dtc_lookup 工具与店员端 /api/dtc/* 共用同一套精确查询逻辑，
避免码表解释出现两套口径。语料缺失时记录 warning 并返回空，不阻塞启动。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.config import BASE_DIR
from backend.db.models import Case, KbChunk, KbDocument

logger = logging.getLogger(__name__)

CORPUS_DIR = Path(BASE_DIR) / "backend" / "seed" / "corpus"
DTC_FILES = [
    "dtc_p0_generic.json",
    "dtc_p0a_ev.json",
    "dtc_u_c.json",
    "dtc_p0_extra.json",
]
CODE_RE = re.compile(r"^[PUC][0-9A-F]{4}$")


@dataclass(frozen=True)
class DtcEntry:
    code: str
    zh: str
    note: str
    doc_title: str
    source_note: str


_catalog: dict[str, DtcEntry] | None = None


def normalize_code(code: str) -> str:
    return str(code or "").strip().upper()


def catalog() -> dict[str, DtcEntry]:
    """启动后首次访问时加载全部 dtc_*.json（进程内缓存）。"""
    global _catalog
    if _catalog is not None:
        return _catalog
    entries: dict[str, DtcEntry] = {}
    for filename in DTC_FILES:
        path = CORPUS_DIR / filename
        if not path.exists():
            logger.warning("DTC 语料缺失：%s", path)
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("DTC 语料读取失败 %s：%s", filename, exc)
            continue
        doc_title = str(data.get("doc_title") or "")
        source_note = str(data.get("source_note") or "")
        for item in data.get("codes") or []:
            if not isinstance(item, dict):
                continue
            code = normalize_code(item.get("code", ""))
            if not code:
                continue
            entries.setdefault(code, DtcEntry(
                code=code,
                zh=str(item.get("zh") or ""),
                note=str(item.get("note") or ""),
                doc_title=doc_title,
                source_note=source_note,
            ))
    if not entries:
        logger.warning("DTC 种子码表为空：/api/dtc 将只返回知识库命中")
    _catalog = entries
    return entries


def lookup_chunks(db: Session, code: str, limit: int = 3) -> list[dict]:
    """精确命中的知识块（category=dtc 且 section_path=code），带文档来源。"""
    normalized = normalize_code(code)
    rows = db.execute(
        select(
            KbChunk.content,
            KbChunk.section_path,
            KbDocument.title,
            KbDocument.source_note,
        )
        .join(KbDocument, KbChunk.document_id == KbDocument.id)
        .where(
            KbDocument.category == "dtc",
            KbDocument.status == "ready",
            KbChunk.section_path == normalized,
        )
        .limit(max(1, min(limit, 10)))
    ).all()
    return [
        {
            "content": str(content),
            "section_path": str(section or normalized),
            "doc_title": str(title),
            "source_note": str(note or ""),
        }
        for content, section, title, note in rows
    ]


def search(query: str, limit: int = 20) -> list[DtcEntry]:
    """按码前缀/包含、中文名/说明模糊匹配，码前缀优先。"""
    keyword = str(query or "").strip().upper()
    if not keyword:
        return []
    matches = [
        entry for entry in catalog().values()
        if keyword in entry.code or keyword in entry.zh.upper() or keyword in entry.note.upper()
    ]
    matches.sort(key=lambda entry: (0 if entry.code.startswith(keyword) else 1, entry.code))
    return matches[: max(1, min(limit, 50))]


def _parse_chunk(content: str) -> tuple[str, str]:
    """从 `[CODE] 名称\\n类别…\\n说明：…` 提取中文名与说明（知识库有、种子码表无时兜底）。"""
    zh = ""
    note = ""
    for line in content.splitlines():
        text = line.strip()
        if not zh and text.startswith("[") and "]" in text:
            zh = text.split("]", 1)[1].strip()
        elif not note and text.startswith("说明："):
            note = text[len("说明："):].strip()
    return zh, note


def detail(db: Session, code: str, case_limit: int = 5) -> dict | None:
    """码表解释 + 知识块 + 相关案例；种子码表与知识库都没有时返回 None。"""
    normalized = normalize_code(code)
    entry = catalog().get(normalized)
    chunks = lookup_chunks(db, normalized)
    if entry is None and not chunks:
        return None

    zh = entry.zh if entry else ""
    note = entry.note if entry else ""
    doc_title = entry.doc_title if entry else ""
    source_note = entry.source_note if entry else ""
    if not zh and chunks:
        zh, parsed_note = _parse_chunk(chunks[0]["content"])
        note = note or parsed_note
        doc_title = doc_title or chunks[0]["doc_title"]
        source_note = source_note or chunks[0]["source_note"]

    pattern = normalized
    cases = db.execute(
        select(Case).where(
            or_(
                Case.title.contains(pattern),
                Case.symptoms.contains(pattern),
                Case.diagnosis.contains(pattern),
            )
        ).order_by(Case.id.desc()).limit(max(1, min(case_limit, 20)))
    ).scalars().all()

    return {
        "code": normalized,
        "zh": zh,
        "note": note,
        "source_note": source_note,
        "doc_title": doc_title,
        "chunks": [
            {
                "document": chunk["doc_title"],
                "section_path": chunk["section_path"],
                "snippet": chunk["content"][:500],
                "source_note": chunk["source_note"],
            }
            for chunk in chunks
        ],
        "cases": [
            {
                "id": case.id,
                "title": case.title,
                "symptoms": case.symptoms,
                "diagnosis": case.diagnosis,
                "repair_result": case.repair_result,
                "created_at": case.created_at.isoformat(timespec="minutes") if case.created_at else None,
            }
            for case in cases
        ],
    }
