from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from core.config import settings
from core.database import get_db
from core.models import Document, Order, User
from routes.auth import get_current_user
from core.schemas import OrderDetail
from core.security import require_role
from services.documents.document_order_projection import (
    get_document_extracted_view,
    build_order_payload,
    create_or_update_order_from_document,
)
from services.common.file_storage import storage
from services.documents.document_workflow import create_document_record, run_document_pipeline


require_writer = require_role("superadmin", "admin", "employee")
logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])
MAX_FILE_SIZE = settings.MAX_UPLOAD_SIZE


class DocumentResponse(BaseModel):
    id: int
    user_id: int
    filename: str
    file_url: str | None = None
    file_type: str
    file_size_bytes: int | None = None
    doc_type: str | None = None
    extraction_method: str | None = None
    status: str
    processing_error: str | None = None
    product_count: int = 0
    linked_order_id: int | None = None
    preview_url: str | None = None
    preview_text: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    extracted_at: datetime | None = None


class DocumentDetailResponse(DocumentResponse):
    content_markdown: str | None = None
    extracted_data: dict | None = None


class OrderPayloadResponse(BaseModel):
    document_id: int
    doc_type: str | None = None
    order_metadata: dict
    products: list[dict]
    product_count: int
    missing_fields: list[str]
    blocking_missing_fields: list[str]
    field_evidence: dict
    confidence_summary: dict
    ready_for_order_creation: bool


class DocumentCreateOrderRequest(BaseModel):
    force: bool = False


class DocumentTypeUpdateRequest(BaseModel):
    doc_type: str


# Allowed manual doc_type values. The set is intentionally narrow — only
# types the system has a real downstream projector for. Adding a new type
# here means a new projector + new skill must already exist.
ALLOWED_DOC_TYPES = {"purchase_order", "unknown"}


class PaginatedDocumentsResponse(BaseModel):
    total: int
    items: list[DocumentResponse]


def _serialize_document(document: Document, linked_order_id: int | None = None) -> dict:
    extracted_data = get_document_extracted_view(document)
    products = extracted_data.get("products") or []
    preview_text = None
    if document.content_markdown:
        preview_text = document.content_markdown.replace("\n", " ").strip()[:240]

    preview_url = None
    if document.file_url:
        try:
            preview_url = storage.get_signed_url(document.file_url, expires_in=3600)
        except Exception as exc:
            logger.warning("Failed to create preview URL for document %s: %s", document.id, exc)

    return {
        "id": document.id,
        "user_id": document.user_id,
        "filename": document.filename,
        "file_url": document.file_url,
        "file_type": document.file_type,
        "file_size_bytes": document.file_size_bytes,
        "doc_type": document.doc_type,
        "extraction_method": document.extraction_method,
        "status": document.status,
        "processing_error": document.processing_error,
        "product_count": len(products),
        "linked_order_id": linked_order_id,
        "preview_url": preview_url,
        "preview_text": preview_text,
        "created_at": document.created_at,
        "updated_at": document.updated_at,
        "extracted_at": document.extracted_at,
        "content_markdown": document.content_markdown,
        "extracted_data": extracted_data,
    }


def _get_document(db: DBSession, document_id: int, current_user: User) -> Document:
    query = db.query(Document).filter(Document.id == document_id)
    if current_user.role not in ("superadmin", "admin"):
        query = query.filter(Document.user_id == current_user.id)
    document = query.first()
    if not document:
        raise HTTPException(404, "文档不存在")
    return document


def _ensure_document_extract_ready(document: Document):
    if document.status in ("uploaded", "extracting"):
        raise HTTPException(409, "文档尚在提取中，请稍后再试")
    if document.status == "error":
        raise HTTPException(400, document.processing_error or "文档提取失败")


@router.get("", response_model=PaginatedDocumentsResponse)
def list_documents(
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    query = db.query(Document)
    if current_user.role not in ("superadmin", "admin"):
        query = query.filter(Document.user_id == current_user.id)
    if status:
        query = query.filter(Document.status == status)

    total = query.count()
    items = query.order_by(Document.created_at.desc()).offset(offset).limit(limit).all()
    document_ids = [item.id for item in items]
    order_map: dict[int, int] = {}
    if document_ids:
        linked_orders = db.query(Order.id, Order.document_id).filter(Order.document_id.in_(document_ids)).all()
        order_map = {document_id: order_id for order_id, document_id in linked_orders if document_id is not None}

    return {
        "total": total,
        "items": [_serialize_document(item, order_map.get(item.id)) for item in items],
    }


@router.post("/upload", response_model=DocumentResponse)
async def upload_document(
    file: UploadFile = File(...),
    current_user: User = Depends(require_writer),
    db: DBSession = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(400, "文件名不能为空")

    lower = file.filename.lower()
    if not (lower.endswith(".pdf") or lower.endswith(".xlsx")):
        raise HTTPException(400, "仅支持 PDF 和 XLSX 文件")

    content = await file.read()
    if not content:
        raise HTTPException(400, "文件内容不能为空")
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, "文件大小不能超过 30 MB")

    file_type = "pdf" if lower.endswith(".pdf") else "excel"
    document = create_document_record(
        db,
        user_id=current_user.id,
        filename=file.filename,
        content=content,
        file_type=file_type,
        content_type=file.content_type,
    )
    document_id = document.id
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, run_document_pipeline, document_id, content)
    return _serialize_document(document)



@router.get("/{document_id}", response_model=DocumentDetailResponse)
def get_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    document = _get_document(db, document_id, current_user)
    linked_order = db.query(Order.id).filter(Order.document_id == document.id).first()
    return _serialize_document(document, linked_order[0] if linked_order else None)


@router.patch("/{document_id}", response_model=DocumentDetailResponse)
def update_document_type(
    document_id: int,
    body: DocumentTypeUpdateRequest,
    current_user: User = Depends(require_writer),
    db: DBSession = Depends(get_db),
):
    """Manually override a document's classification.

    The auto-classifier is good but not perfect. When confidence is borderline,
    the user is the final authority on what kind of document this is. This
    endpoint lets them flip doc_type without re-running the extractor.

    Note: this does NOT re-run the projector. The blocks + projection results
    were computed once at extraction time and remain valid; we're just
    changing the classification flag the rest of the system reads.
    """
    if body.doc_type not in ALLOWED_DOC_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported doc_type: {body.doc_type}. Allowed: {sorted(ALLOWED_DOC_TYPES)}",
        )
    document = _get_document(db, document_id, current_user)
    document.doc_type = body.doc_type
    document.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(document)
    linked_order = db.query(Order.id).filter(Order.document_id == document.id).first()
    return _serialize_document(document, linked_order[0] if linked_order else None)


@router.get("/{document_id}/order-payload", response_model=OrderPayloadResponse)
def get_document_order_payload(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    document = _get_document(db, document_id, current_user)
    _ensure_document_extract_ready(document)
    return build_order_payload(document)


@router.post("/{document_id}/create-order", response_model=OrderDetail)
def create_order_from_document(
    document_id: int,
    body: DocumentCreateOrderRequest,
    current_user: User = Depends(require_writer),
    db: DBSession = Depends(get_db),
):
    document = _get_document(db, document_id, current_user)
    _ensure_document_extract_ready(document)
    try:
        # User-triggered "force create" means both: overwrite existing order AND
        # allow incomplete docs (persist as needs_review). Status is always
        # computed by _resolve_order_status — forcing does NOT imply "ready".
        order = create_or_update_order_from_document(
            document, db, force=body.force, allow_incomplete=body.force,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return order


@router.delete("/{document_id}")
def delete_document(
    document_id: int,
    force: bool = Query(default=False),
    current_user: User = Depends(require_writer),
    db: DBSession = Depends(get_db),
):
    """Delete a document.

    By default refuses to delete if there is a linked Order — orders may
    already be matched / quoted / sent to suppliers, and cascade-deleting them
    would lose real business data.

    Pass ?force=true to delete the Document AND unlink the Order
    (Order.document_id ← NULL). The Order itself is preserved.

    Storage file removal is best-effort and never blocks the DB delete.
    """
    document = _get_document(db, document_id, current_user)
    linked_order = (
        db.query(Order).filter(Order.document_id == document.id).first()
    )

    if linked_order and not force:
        raise HTTPException(
            status_code=409,
            detail=(
                f"该文档已生成订单 #{linked_order.id}。"
                f"如确认要删除，请使用 force=true（订单将保留但与文档解除关联）。"
            ),
        )

    file_url = document.file_url

    if linked_order and force:
        linked_order.document_id = None
        db.add(linked_order)

    db.delete(document)
    db.commit()

    # Best-effort storage cleanup — DB delete is the source of truth
    if file_url:
        try:
            storage.delete(file_url)
        except Exception as exc:
            logger.warning(
                "Storage delete failed for document %s (%s): %s",
                document_id, file_url, exc,
            )

    return {
        "ok": True,
        "document_id": document_id,
        "unlinked_order_id": linked_order.id if linked_order else None,
    }
