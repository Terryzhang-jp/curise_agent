from __future__ import annotations

import logging
import uuid
from datetime import datetime

from database import SessionLocal
from models import Document, Order
from services.documents.document_order_projection import create_or_update_order_from_document
from services.documents.document_processor import process_document
from services.common.file_storage import storage


logger = logging.getLogger(__name__)


def create_document_and_pending_order(
    db,
    *,
    user_id: int,
    filename: str,
    content: bytes,
    file_type: str,
    content_type: str | None = None,
) -> tuple[Document, Order]:
    """Atomic upload: blob + Document + Order in one compensated operation.

    This is the only supported entry point for the document-first upload flow.
    The legacy helpers `create_document_record` and `create_pending_order_for_document`
    are kept as building blocks for tests but callers MUST use this function —
    they split the work into two separate commits and leave orphaned blobs /
    documents when the second commit fails (Codex adversarial review finding,
    2026-04-12).

    Failure modes and compensations:

      1. Blob upload fails → nothing persisted, raise.
      2. Blob upload succeeds, DB transaction fails → delete the blob, raise.
      3. Both succeed → return (document, order).

    The blob upload is NOT transactional (it's an external Supabase API), so
    we use the saga pattern: upload first, then a single DB transaction that
    creates both rows, with a compensating delete on the blob if DB fails.
    """
    safe_name = f"{uuid.uuid4().hex[:8]}_{filename}"
    file_url = storage.upload(
        "documents",
        safe_name,
        content,
        content_type or "application/octet-stream",
    )

    try:
        # Single transaction for both rows. We use nested savepoints so that
        # this function composes with any outer transaction the caller may
        # already have open.
        with db.begin_nested():
            document = Document(
                user_id=user_id,
                filename=filename,
                file_url=file_url,
                file_type=file_type,
                file_size_bytes=len(content),
                status="uploaded",
            )
            db.add(document)
            db.flush()  # populate document.id

            order = Order(
                user_id=user_id,
                document_id=document.id,
                filename=filename,
                file_url=file_url,
                file_type=file_type,
                status="uploading",
            )
            db.add(order)
            db.flush()
        db.commit()
        db.refresh(document)
        db.refresh(order)
    except Exception:
        # Compensation: remove the orphan blob. Best-effort — failing to
        # delete the blob should NOT mask the original exception.
        logger.exception(
            "document/order atomic upload failed for user_id=%s filename=%s; "
            "compensating blob delete",
            user_id,
            filename,
        )
        try:
            storage.delete(file_url)
        except Exception:
            logger.exception("compensating delete failed for %s", file_url)
        db.rollback()
        raise

    return document, order


def create_document_record(
    db,
    *,
    user_id: int,
    filename: str,
    content: bytes,
    file_type: str,
    content_type: str | None = None,
) -> Document:
    """DEPRECATED: use `create_document_and_pending_order`.

    This helper is kept for tests and for routes that truly only need a
    document without a linked order (e.g. standalone document uploads).
    Production upload routes must use `create_document_and_pending_order`
    so that the blob + document + order are atomic.
    """
    safe_name = f"{uuid.uuid4().hex[:8]}_{filename}"
    file_url = storage.upload("documents", safe_name, content, content_type or "application/octet-stream")
    try:
        document = Document(
            user_id=user_id,
            filename=filename,
            file_url=file_url,
            file_type=file_type,
            file_size_bytes=len(content),
            status="uploaded",
        )
        db.add(document)
        db.commit()
        db.refresh(document)
    except Exception:
        try:
            storage.delete(file_url)
        except Exception:
            logger.exception("compensating delete failed for %s", file_url)
        db.rollback()
        raise
    return document


def create_pending_order_for_document(db, document: Document) -> Order:
    order = db.query(Order).filter(Order.document_id == document.id).first()
    if order:
        return order

    order = Order(
        user_id=document.user_id,
        document_id=document.id,
        filename=document.filename,
        file_url=document.file_url,
        file_type=document.file_type,
        status="uploading",
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def run_document_pipeline(document_id: int, file_bytes: bytes, create_order: bool = False, order_id: int | None = None):
    db = SessionLocal()
    try:
        document = db.query(Document).get(document_id)
        if not document:
            return

        document.status = "extracting"
        linked_order = db.query(Order).get(order_id) if order_id else None
        if linked_order:
            linked_order.status = "extracting"
        db.commit()

        result = process_document(file_bytes, document.file_type)
        document.doc_type = result["doc_type"]
        document.content_markdown = result["content_markdown"]
        document.extracted_data = result["extracted_data"]
        document.extraction_method = result["extraction_method"]
        document.status = "extracted"
        document.processing_error = None
        document.extracted_at = datetime.utcnow()
        db.commit()

        if create_order:
            # Ingestion path: always overwrite existing projection (force=True),
            # allow incomplete docs to persist as "needs_review" (allow_incomplete=True).
            # Status is computed by _resolve_order_status — blocked docs will NOT
            # become ready here. See ADR on 2026-04-12.
            order = create_or_update_order_from_document(
                document, db, force=True, allow_incomplete=True
            )
            logger.info(
                "Document %d projected to order %d (products=%d, warning=%s)",
                document.id,
                order.id,
                order.product_count,
                order.processing_error,
            )
        else:
            logger.info("Document %d extracted without order creation", document.id)
    except Exception as exc:
        logger.error("Document pipeline failed for %d: %s", document_id, exc, exc_info=True)
        db.rollback()
        try:
            document = db.query(Document).get(document_id)
            if document:
                document.status = "error"
                document.processing_error = str(exc)
            if order_id:
                linked_order = db.query(Order).get(order_id)
                if linked_order:
                    linked_order.status = "error"
                    linked_order.processing_error = f"文档处理失败: {exc}"
            db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()
