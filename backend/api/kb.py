"""知识库路由：文档上传 / 列表 / 分块预览 / 删除 / 检索测试台（§9-11）。"""
from __future__ import annotations

import json

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from backend.api.deps import DbSession, require_roles
from backend.db.models import KbChunk, KbDocument, User
from backend.rag import retrieve
from backend.rag.ingest import delete_document, ingest_document

router = APIRouter(prefix="/api/kb", tags=["kb"])

ALLOWED_SUFFIXES = {".pdf", ".docx", ".md", ".markdown", ".txt", ".csv", ".json"}


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=512)
    category: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)


@router.get("/documents")
def list_documents(user: Annotated[User, Depends(require_roles("staff", "admin"))], db: DbSession) -> dict:
    docs = db.execute(
        select(KbDocument).order_by(KbDocument.created_at.desc())
    ).scalars().all()
    return {
        "documents": [
            {
                "id": d.id,
                "title": d.title,
                "filename": d.filename,
                "category": d.category,
                "source_url": d.source_url,
                "source_note": d.source_note,
                "status": d.status,
                "chunk_count": d.chunk_count,
            }
            for d in docs
        ]
    }


@router.post("/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(
    user: Annotated[User, Depends(require_roles("admin"))],
    db: DbSession,
    file: UploadFile | None = File(default=None),
    title: str | None = Form(default=None),
    category: str = Form(default="general"),
    source_url: str = Form(default=""),
    source_note: str = Form(default=""),
    markdown_text: str | None = Form(default=None),
) -> dict:
    """上传文件（multipart）或直接提交 markdown_text 建文档。"""
    try:
        if file is not None:
            suffix = ("." + (file.filename or "").rsplit(".", 1)[-1]).lower() if file.filename else ""
            if suffix not in ALLOWED_SUFFIXES:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"不支持的文件类型 {suffix}，支持：{sorted(ALLOWED_SUFFIXES)}")
            data = await file.read()
            doc, chunks = ingest_document(
                db,
                title=title or (file.filename or "未命名").rsplit(".", 1)[0],
                category=category,
                filename=file.filename or "",
                source_url=source_url,
                source_note=source_note,
                file_bytes=data,
                file_kind=suffix,
            )
        elif markdown_text:
            doc, chunks = ingest_document(
                db,
                title=title or "未命名文档",
                category=category,
                source_url=source_url,
                source_note=source_note,
                markdown_text=markdown_text,
            )
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "缺少文件或文本内容")
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"id": doc.id, "title": doc.title, "chunk_count": doc.chunk_count, "status": doc.status}


@router.get("/documents/{doc_id}/chunks")
def list_chunks(doc_id: int, user: Annotated[User, Depends(require_roles("admin"))], db: DbSession) -> dict:
    if db.get(KbDocument, doc_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文档不存在")
    chunks = db.execute(
        select(KbChunk).where(KbChunk.document_id == doc_id).order_by(KbChunk.seq)
    ).scalars().all()
    return {
        "chunks": [
            {"id": c.id, "seq": c.seq, "section_path": c.section_path, "page_no": c.page_no, "content": c.content}
            for c in chunks
        ]
    }


@router.delete("/documents/{doc_id}")
def remove_document(doc_id: int, user: Annotated[User, Depends(require_roles("admin"))], db: DbSession) -> dict:
    if not delete_document(db, doc_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文档不存在")
    return {"ok": True}


@router.post("/search")
def kb_search(body: SearchIn, user: Annotated[User, Depends(require_roles("staff", "admin"))], db: DbSession) -> dict:
    """检索测试台：输入查询看命中结果（调参用）。"""
    results = retrieve.search(db, body.query, category=body.category, top_k=body.top_k)
    return {
        "query": body.query,
        "results": [
            {
                "chunk_id": r.chunk_id,
                "document": r.document_title,
                "category": r.category,
                "section": r.section_path,
                "page_no": r.page_no,
                "score": r.score,
                "legs": r.legs,
                "content": r.content,
            }
            for r in results
        ],
    }
