"""种子语料导入：OBD 码表（结构化逐条成块）+ 三电知识 MD（结构感知分块）。

幂等：按 kb_documents.title 查重，已存在则跳过。
用法：D:/Python/python.exe -m backend.seed.load_corpus
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from backend.config import BASE_DIR
from backend.db.base import SessionLocal, init_db
from backend.db.models import KbDocument
from backend.rag.bm25 import bm25_index
from backend.rag.ingest import ingest_document

CORPUS_DIR = Path(BASE_DIR) / "backend" / "seed" / "corpus"

DTC_FILES = [
    "dtc_p0_generic.json",
    "dtc_p0a_ev.json",
    "dtc_u_c.json",
    "dtc_p0_extra.json",
]

MD_FILES = [
    ("kb_battery.md", "battery", "动力电池与 BMS 常见问题知识"),
    ("kb_motor.md", "motor", "驱动电机与电驱系统常见问题知识"),
    ("kb_electric_control.md", "electric_control", "高压电控、低压系统与整车电气知识"),
    ("kb_charging.md", "charging", "充电系统常见问题知识"),
    ("kb_diagnosis_method.md", "method", "新能源汽车故障诊断方法论"),
    ("kb_low_temp.md", "scenario", "低温环境与续航衰减场景知识"),
    ("kb_indicators.md", "indicators", "仪表指示灯与报警语义"),
    ("kb_maintenance.md", "maintenance", "新能源车使用与维护通识"),
]


def _exists(db: SessionLocal, title: str) -> bool:
    return db.scalar(select(KbDocument.id).where(KbDocument.title == title)) is not None


def load_all() -> dict[str, int]:
    init_db()
    stats = {"dtc_chunks": 0, "md_docs": 0, "md_chunks": 0, "skipped": 0}
    db = SessionLocal()
    try:
        for filename in DTC_FILES:
            with open(CORPUS_DIR / filename, encoding="utf-8") as f:
                data = json.load(f)
            if _exists(db, data["doc_title"]):
                stats["skipped"] += 1
                continue
            chunks_meta: list[tuple[str, str]] = []
            for item in data["codes"]:
                content = (
                    f"[{item['code']}] {item['zh']}\n"
                    f"类别：OBD-II 通用码（SAE J2012 公开定义）\n"
                    f"说明：{item['note']}"
                )
                chunks_meta.append((item["code"], content))
            doc, chunks = ingest_document(
                db,
                title=data["doc_title"],
                category="dtc",
                filename=filename,
                source_note=data["source_note"],
                markdown_text="\n\n".join(f"## {code}\n\n{content}" for code, content in chunks_meta),
            )
            stats["dtc_chunks"] += doc.chunk_count
            print(f"[corpus] {filename}: {doc.chunk_count} blocks")

        for filename, category, title in MD_FILES:
            if _exists(db, title):
                stats["skipped"] += 1
                continue
            text = (CORPUS_DIR / filename).read_text(encoding="utf-8")
            doc, _chunks = ingest_document(
                db,
                title=title,
                category=category,
                filename=filename,
                source_note="公开技术资料与标准通识整理（GB 38031、GB/T 18384 等公开标准口径），供诊断辅助参考",
                markdown_text=text,
            )
            stats["md_docs"] += 1
            stats["md_chunks"] += doc.chunk_count
            print(f"[corpus] {filename}: {doc.chunk_count} blocks")

        bm25_index.rebuild(db)
        print(f"[corpus] done: {json.dumps(stats, ensure_ascii=False)}")
        return stats
    finally:
        db.close()


if __name__ == "__main__":
    load_all()
