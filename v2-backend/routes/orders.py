"""
Order management REST endpoints.

Provides order CRUD, file upload with automatic processing,
anomaly detection, and inquiry generation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from datetime import datetime
from queue import Empty

from typing import Optional

from services.common.file_storage import storage

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session as DBSession

from core.config import settings
from core.database import get_db, SessionLocal
from core.models import Order, User, Country
from routes.auth import get_current_user
from core.security import require_role
from core.schemas import OrderListItem, OrderDetail, OrderReviewRequest, OrderUpdateRequest, OrderRematchRequest
from services.agent.stream_queue import (
    get_cancel_event,
    get_or_create_cancel_event,
    get_or_create_queue,
    get_queue,
    push_event,
    remove_cancel_event,
    remove_queue,
    set_cancelled,
)
from services.documents.document_workflow import (
    create_document_and_pending_order,
    create_document_record,
    create_pending_order_for_document,
    run_document_pipeline,
)

# Write operations require non-finance roles
require_writer = require_role("superadmin", "admin", "employee")

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/orders", tags=["orders"])

UPLOAD_DIR = settings.UPLOAD_DIR
MAX_FILE_SIZE = settings.MAX_UPLOAD_SIZE


def _get_order(db: DBSession, order_id: int, current_user: User | None = None) -> Order:
    """Fetch order. If current_user is provided and is employee, restrict to own orders."""
    query = db.query(Order).filter(Order.id == order_id)
    if current_user and current_user.role not in ("superadmin", "admin"):
        query = query.filter(Order.user_id == current_user.id)
    order = query.first()
    if not order:
        raise HTTPException(404, "订单不存在")
    return order


# ─── Upload & Process ──────────────────────────────────────────

@router.post("/upload", response_model=OrderDetail)
async def upload_order(
    file: UploadFile = File(...),
    current_user: User = Depends(require_writer),
    db: DBSession = Depends(get_db),
):
    """Upload a file and create an order through the document-first pipeline."""
    if not file.filename:
        raise HTTPException(400, "文件名不能为空")

    lower = file.filename.lower()
    if not (lower.endswith(".pdf") or lower.endswith(".xlsx")):
        raise HTTPException(400, "仅支持 PDF 和 XLSX 文件")

    content = await file.read()
    if not content:
        raise HTTPException(400, "文件内容不能为空")
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, "文件大小不能超过 25 MB")

    file_type = "pdf" if lower.endswith(".pdf") else "excel"
    # Atomic: blob + document + order all in one compensated operation.
    # If any step fails the blob is cleaned up and no DB rows remain.
    document, order = create_document_and_pending_order(
        db,
        user_id=current_user.id,
        filename=file.filename,
        content=content,
        file_type=file_type,
        content_type=file.content_type,
    )

    order_id = order.id
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, run_document_pipeline, document.id, content, True, order_id)

    return order


def _run_extract_only(order_id: int, file_bytes: bytes):
    """Background: extract order data from PDF, then wait for Agent to match.

    Old flow: extract → match → analyze (all automatic)
    New flow: extract only → status="extracted" → Agent decides next steps
    """
    from core.database import SessionLocal
    from core.models import Order
    from services.orders.order_processor import smart_extract, normalize_metadata, _validate_extraction
    from services.data.product_normalizer import normalize_products
    from sqlalchemy.orm.attributes import flag_modified
    import copy, logging, time

    logger = logging.getLogger(__name__)
    db = SessionLocal()
    try:
        order = db.query(Order).get(order_id)
        if not order:
            return

        order.status = "extracting"
        db.commit()

        start = time.time()
        extracted = smart_extract(file_bytes, order.file_type or "pdf")
        elapsed = time.time() - start

        order.extraction_data = extracted
        order.order_metadata = extracted.get("order_metadata")

        raw_products = copy.deepcopy(extracted.get("products") or [])
        order.products = normalize_products(raw_products)
        order.product_count = len(order.products)

        total_amount = (extracted.get("order_metadata") or {}).get("total_amount")
        if total_amount is not None:
            try:
                order.total_amount = float(total_amount)
            except (ValueError, TypeError):
                pass

        flag_modified(order, "extraction_data")
        flag_modified(order, "order_metadata")
        flag_modified(order, "products")

        # Quality gate
        warnings = _validate_extraction(order, extracted)
        if warnings:
            order.processing_error = "提取警告: " + "; ".join(warnings)

        if order.product_count == 0:
            order.status = "error"
            order.processing_error = "提取失败: 未识别到任何产品"
        else:
            order.status = "extracted"
            # Note: NOT "ready" — Agent needs to match products first

        order.processed_at = None  # Will be set after matching
        db.commit()
        logger.info("Order %d: extraction done — %d products, %.1fs", order_id, order.product_count, elapsed)

    except Exception as e:
        logger.error("Order %d extraction failed: %s", order_id, e, exc_info=True)
        db.rollback()
        try:
            order = db.query(Order).get(order_id)
            if order:
                order.status = "error"
                order.processing_error = str(e)
                db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()


def _run_process_order(order_id: int, file_bytes: bytes):
    """Legacy: full auto processing (extract + match + analyze). Kept for backward compat."""
    from services.orders.order_processor import process_order
    process_order(order_id, file_bytes)


# ─── List & Get ────────────────────────────────────────────────

@router.get("")
def list_orders(
    status: str | None = Query(None, description="Filter by status"),
    search: str | None = Query(None, description="Search filename"),
    limit: int = Query(20, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """List orders with optional filters."""
    query = db.query(Order)

    if status:
        query = query.filter(Order.status == status)
    if search:
        query = query.filter(Order.filename.ilike(f"%{search}%"))

    total = query.count()
    orders = query.order_by(desc(Order.created_at)).offset(offset).limit(limit).all()

    # Batch-resolve country names
    cids = {o.country_id for o in orders if o.country_id}
    country_map: dict[int, str] = {}
    if cids:
        rows = db.query(Country.id, Country.name).filter(Country.id.in_(cids)).all()
        country_map = {r.id: r.name for r in rows}

    items = []
    for o in orders:
        item = OrderListItem.model_validate(o)
        item.country_name = country_map.get(o.country_id) if o.country_id else None
        items.append(item)

    return {"total": total, "items": items}


@router.get("/{order_id}", response_model=OrderDetail)
def get_order(
    order_id: int,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Get order details."""
    order = _get_order(db, order_id)
    return order


@router.get("/{order_id}/file-preview")
def get_order_file_preview(
    order_id: int,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Return a short-lived signed URL for the order's original file (PDF/Excel).

    The signed URL is valid for 1 hour and can be embedded directly in an
    <iframe> or <object> tag for in-browser preview.
    """
    order = _get_order(db, order_id)
    if not order.file_url:
        raise HTTPException(404, "该订单没有关联的原始文件")
    try:
        url = storage.get_signed_url(order.file_url, expires_in=3600)
    except Exception as exc:
        logger.warning("Failed to sign file URL for order %s: %s", order_id, exc)
        raise HTTPException(500, "生成预览链接失败，请稍后重试")
    return {"url": url, "file_type": order.file_type, "filename": order.filename}


# ─── Delete ────────────────────────────────────────────────────

@router.delete("/{order_id}")
def delete_order(
    order_id: int,
    current_user: User = Depends(require_writer),
    db: DBSession = Depends(get_db),
):
    """Delete an order and its associated files."""
    order = _get_order(db, order_id, current_user)

    # Clean up uploaded file from storage
    if order.file_url:
        storage.delete(order.file_url)

    # Clean up generated inquiry files from storage
    if order.inquiry_data:
        for f in order.inquiry_data.get("generated_files", []):
            file_url = f.get("file_url") or f.get("filename")
            if file_url:
                storage.delete(file_url)
            preview_url = f.get("preview_url")
            if preview_url:
                storage.delete(preview_url)

    db.delete(order)
    db.commit()
    return {"detail": "已删除"}


# ─── Update ───────────────────────────────────────────────────

@router.patch("/{order_id}", response_model=OrderDetail)
def update_order(
    order_id: int,
    body: OrderUpdateRequest,
    current_user: User = Depends(require_writer),
    db: DBSession = Depends(get_db),
):
    """Update order metadata and/or products. Only editable when status is ready or error."""
    order = _get_order(db, order_id, current_user)
    if order.status not in ("ready", "error"):
        raise HTTPException(400, "仅已完成或出错的订单可编辑")

    if body.order_metadata is not None:
        order.order_metadata = body.order_metadata
        # Update total_amount from metadata if present
        total_amount = body.order_metadata.get("total_amount")
        if total_amount is not None:
            try:
                order.total_amount = float(total_amount)
            except (ValueError, TypeError):
                pass

    if body.products is not None:
        order.products = body.products
        order.product_count = len(body.products)
        # Recalculate total_amount from products if not set in metadata
        if body.order_metadata is None or body.order_metadata.get("total_amount") is None:
            try:
                total = sum(float(p.get("total_price", 0) or 0) for p in body.products)
                if total > 0:
                    order.total_amount = total
            except (ValueError, TypeError):
                pass

    if body.port_id is not None:
        order.port_id = body.port_id
    if body.country_id is not None:
        order.country_id = body.country_id

    db.commit()
    db.refresh(order)
    return order


# ─── Rematch ──────────────────────────────────────────────────

@router.post("/{order_id}/rematch", response_model=OrderDetail)
async def rematch_order(
    order_id: int,
    current_user: User = Depends(require_writer),
    db: DBSession = Depends(get_db),
):
    """Re-run matching on an order without re-extracting. Uses current products data."""
    order = _get_order(db, order_id, current_user)
    if order.status not in ("ready", "error"):
        raise HTTPException(400, "仅已完成或出错的订单可重新匹配")
    if not order.products:
        raise HTTPException(400, "没有产品数据，无法匹配")

    # Reset match-related fields
    order.match_results = None
    order.match_statistics = None
    order.anomaly_data = None
    order.financial_data = None
    order.inquiry_data = None
    order.status = "matching"
    db.commit()
    db.refresh(order)

    # Launch background rematch
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _run_rematch, order.id)

    return order


def _run_rematch(order_id: int):
    """Background thread: re-run matching using current order data."""
    from services.orders.order_processor import run_agent_matching

    db = SessionLocal()
    try:
        order = db.query(Order).get(order_id)
        if not order:
            logger.error("Rematch: Order %d not found", order_id)
            return

        extracted_data = {
            "order_metadata": order.order_metadata or {},
            "products": order.products or [],
        }

        match_result = run_agent_matching(order_id, extracted_data, db)

        order.match_results = match_result.get("match_results")
        order.match_statistics = match_result.get("statistics")
        order.country_id = match_result.get("country_id")
        order.port_id = match_result.get("port_id")
        order.delivery_date = match_result.get("delivery_date")

        if match_result.get("skipped_reason") == "missing_delivery_date":
            order.status = "ready"
            order.processing_error = "缺少交货日期(delivery_date)，请编辑订单元数据补充后重新匹配"
        else:
            order.status = "ready"
            order.processing_error = None

            # Auto-run financial analysis
            if order.match_results:
                try:
                    from services.orders.order_processor import run_financial_analysis
                    order.financial_data = run_financial_analysis(order)
                except Exception as e:
                    logger.warning("Rematch: Order %d financial analysis failed: %s", order_id, str(e))

                # Auto-run inquiry pre-analysis
                try:
                    from services.orders.inquiry_agent import run_inquiry_pre_analysis
                    order.inquiry_data = run_inquiry_pre_analysis(order, db)
                except Exception as e:
                    logger.warning("Rematch: Order %d inquiry pre-analysis failed: %s", order_id, str(e))

        order.processed_at = datetime.utcnow()
        db.commit()
        logger.info("Rematch: Order %d complete", order_id)
    except Exception as e:
        logger.error("Rematch: Order %d failed: %s", order_id, str(e), exc_info=True)
        db.rollback()
        # Use a fresh session to update error status
        err_db = SessionLocal()
        try:
            order = err_db.query(Order).get(order_id)
            if order:
                order.status = "error"
                order.processing_error = f"重新匹配失败: {str(e)}"
                err_db.commit()
        except Exception as inner_e:
            logger.error("Rematch: Order %d error status update failed: %s", order_id, str(inner_e))
            err_db.rollback()
        finally:
            err_db.close()
    finally:
        db.close()


# ─── Review ────────────────────────────────────────────────────

@router.post("/{order_id}/review")
def review_order(
    order_id: int,
    body: OrderReviewRequest,
    current_user: User = Depends(require_writer),
    db: DBSession = Depends(get_db),
):
    """Mark an order as reviewed."""
    order = _get_order(db, order_id, current_user)

    order.is_reviewed = True
    order.reviewed_at = datetime.utcnow()
    order.reviewed_by = current_user.id
    order.review_notes = body.notes
    db.commit()
    db.refresh(order)
    return {"detail": "已标记审核", "reviewed_at": order.reviewed_at.isoformat()}


# ─── Set Template (for pending_template orders) ──────────────

class SetTemplateRequest(BaseModel):
    template_id: int


@router.post("/{order_id}/set-template", response_model=OrderDetail)
async def set_order_template(
    order_id: int,
    body: SetTemplateRequest,
    current_user: User = Depends(require_writer),
    db: DBSession = Depends(get_db),
):
    """Set template for an order awaiting template selection, then resume processing."""
    order = _get_order(db, order_id, current_user)
    if order.status != "pending_template":
        raise HTTPException(400, "订单不在等待选择模板状态")

    # Validate template exists
    from core.models import OrderFormatTemplate
    template = db.query(OrderFormatTemplate).get(body.template_id)
    if not template:
        raise HTTPException(404, "模板不存在")

    # Read file bytes from storage
    if not order.file_url:
        raise HTTPException(400, "找不到原始文件")
    try:
        file_bytes = storage.download(order.file_url)
    except FileNotFoundError:
        raise HTTPException(400, "原始文件已丢失")

    # Reset to uploading and launch processing with template override
    order.status = "uploading"
    db.commit()
    db.refresh(order)

    loop = asyncio.get_event_loop()
    loop.run_in_executor(
        None, _run_process_order_with_template, order.id, file_bytes, body.template_id
    )
    return order


def _run_process_order_with_template(order_id: int, file_bytes: bytes, template_id: int):
    """Wrapper for background thread execution with template override."""
    from services.orders.order_processor import process_order
    process_order(order_id, file_bytes, template_id_override=template_id)


# ─── Reprocess ─────────────────────────────────────────────────

@router.post("/{order_id}/reprocess", response_model=OrderDetail)
async def reprocess_order(
    order_id: int,
    current_user: User = Depends(require_writer),
    db: DBSession = Depends(get_db),
):
    """Reprocess a failed order."""
    order = _get_order(db, order_id, current_user)
    if order.status not in ("error", "ready", "pending_template", "extracting", "matching"):
        raise HTTPException(400, "仅可重新处理出错、已完成或待选模板的订单")

    # Read file bytes from storage
    if not order.file_url:
        raise HTTPException(400, "找不到原始文件")
    try:
        file_bytes = storage.download(order.file_url)
    except FileNotFoundError:
        raise HTTPException(400, "原始文件已丢失")

    # Reset order state
    order.status = "uploading"
    order.processing_error = None
    order.extraction_data = None
    order.order_metadata = None
    order.products = None
    order.product_count = 0
    order.total_amount = None
    order.match_results = None
    order.match_statistics = None
    order.anomaly_data = None
    order.financial_data = None
    order.inquiry_data = None
    order.template_id = None
    order.template_match_method = None
    order.processed_at = None
    db.commit()
    db.refresh(order)

    # Launch background processing
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _run_process_order, order.id, file_bytes)

    return order


# ─── Anomaly Check ─────────────────────────────────────────────

@router.post("/{order_id}/anomaly-check", response_model=OrderDetail)
def anomaly_check(
    order_id: int,
    current_user: User = Depends(require_writer),
    db: DBSession = Depends(get_db),
):
    """Run anomaly detection on an order."""
    order = _get_order(db, order_id, current_user)
    if order.status not in ("ready", "extracted"):
        raise HTTPException(400, "订单尚未处理完成")

    from services.orders.order_processor import run_anomaly_check
    anomaly_data = run_anomaly_check(order)
    order.anomaly_data = anomaly_data
    db.commit()
    db.refresh(order)
    return order


# ─── Financial Analysis ──────────────────────────────────────

@router.post("/{order_id}/financial-analysis", response_model=OrderDetail)
def financial_analysis(
    order_id: int,
    base_currency: str | None = Query(None, description="分析输出币种"),
    order_currency: str | None = Query(None, description="订单价格所用币种（覆盖元数据，用于货币转换）"),
    current_user: User = Depends(require_writer),
    db: DBSession = Depends(get_db),
):
    """Run or re-run financial analysis on an order."""
    order = _get_order(db, order_id, current_user)
    if order.status not in ("ready", "extracted"):
        raise HTTPException(400, "订单尚未处理完成")
    if not order.match_results:
        raise HTTPException(400, "没有匹配结果，无法进行财务分析")

    from services.orders.order_processor import run_financial_analysis
    order.financial_data = run_financial_analysis(
        order, base_currency=base_currency, order_currency_override=order_currency
    )
    db.commit()
    db.refresh(order)
    return order


# ─── Delivery Environment ─────────────────────────────────────

@router.post("/{order_id}/delivery-environment", response_model=OrderDetail)
def delivery_environment(
    order_id: int,
    current_user: User = Depends(require_writer),
    db: DBSession = Depends(get_db),
):
    """Fetch or refresh delivery environment data for an order."""
    order = _get_order(db, order_id, current_user)
    if order.status != "ready":
        raise HTTPException(400, "订单尚未处理完成")
    if not order.port_id or not order.delivery_date:
        raise HTTPException(400, "缺少港口或交货日期信息")

    from services.integrations.weather_service import fetch_delivery_environment
    from core.models import Port, Country
    port = db.query(Port).get(order.port_id)
    country = db.query(Country).get(port.country_id) if port and port.country_id else None
    if not port or not country:
        raise HTTPException(400, "无法解析港口或国家信息")

    try:
        order.delivery_environment = fetch_delivery_environment(
            port.name, country.name, order.delivery_date, db
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.warning("Delivery environment fetch failed for order %d: %s", order_id, e)
        raise HTTPException(502, f"获取送货环境数据失败: {e}")

    db.commit()
    db.refresh(order)
    return order


# ─── Generate Inquiry (Streaming) ─────────────────────────────

class GenerateInquiryRequest(BaseModel):
    template_overrides: Optional[dict[int, Optional[int]]] = None
    supplier_ids: Optional[list[int]] = None

class GenerateInquirySingleRequest(BaseModel):
    template_id: Optional[int] = None


class CancelInquiryRequest(BaseModel):
    stream_key: Optional[str] = None

@router.post("/{order_id}/generate-inquiry")
def generate_inquiry(
    order_id: int,
    body: GenerateInquiryRequest = GenerateInquiryRequest(),
    current_user: User = Depends(require_writer),
    db: DBSession = Depends(get_db),
):
    """Start inquiry generation in background, return stream_key for SSE progress."""
    order = _get_order(db, order_id, current_user)
    if order.status != "ready":
        raise HTTPException(400, "订单尚未处理完成")
    if not order.match_results:
        raise HTTPException(400, "没有匹配结果，无法生成询价单")

    stream_key = f"inquiry-{order_id}"

    # Prevent duplicate concurrent generation
    if get_queue(stream_key) is not None:
        if get_cancel_event(stream_key) is not None:
            raise HTTPException(409, "询价单正在生成中，请稍候")
        remove_queue(stream_key)  # stale queue from interrupted SSE

    get_or_create_queue(stream_key)
    get_or_create_cancel_event(stream_key)

    threading.Thread(
        target=_run_inquiry_background,
        args=(order_id, stream_key, body.template_overrides, body.supplier_ids),
        daemon=True,
    ).start()

    return {"status": "generating", "stream_key": stream_key}


def _run_inquiry_background(order_id: int, stream_key: str, template_overrides=None, supplier_ids=None):
    """Background thread: run inquiry orchestrator and save results."""
    from services.orders.inquiry_agent import InquiryCancelledError, run_inquiry_orchestrator

    db = SessionLocal()
    try:
        order = db.query(Order).get(order_id)
        if not order:
            logger.error("Inquiry: Order %d not found", order_id)
            push_event(stream_key, {"type": "error", "message": "订单不存在"})
            return

        inquiry_data = run_inquiry_orchestrator(
            order,
            db,
            stream_key,
            template_overrides,
            supplier_ids=supplier_ids,
        )

        order.inquiry_data = inquiry_data
        cancel_event = get_or_create_cancel_event(stream_key)
        # Auto-advance fulfillment status to inquiry_sent
        if order.fulfillment_status == "pending" and not cancel_event.is_set():
            order.fulfillment_status = "inquiry_sent"
        db.commit()
        logger.info("Inquiry: Order %d saved, %d files generated",
                     order_id, len(inquiry_data.get("generated_files", [])))

        # Push done only after DB commit succeeds
        if not cancel_event.is_set():
            push_event(stream_key, {"type": "done", "data": inquiry_data})
    except InquiryCancelledError:
        db.rollback()
    except Exception as e:
        logger.error("Inquiry: Order %d failed: %s", order_id, str(e), exc_info=True)
        db.rollback()
        try:
            order = db.query(Order).get(order_id)
            if order:
                order.processing_error = f"询价生成失败: {str(e)}"
                db.commit()
        except Exception:
            db.rollback()
        push_event(stream_key, {"type": "error", "message": str(e)})
    finally:
        remove_cancel_event(stream_key)
        db.close()


@router.get("/{order_id}/inquiry-stream")
async def inquiry_stream(
    order_id: int,
    stream_key: str | None = Query(None, description="Override stream key for single-supplier redo"),
    current_user: User = Depends(get_current_user),
):
    """SSE stream for real-time inquiry generation progress."""
    if not stream_key:
        stream_key = f"inquiry-{order_id}"

    async def event_generator():
        loop = asyncio.get_event_loop()
        q = get_queue(stream_key)
        if q is None:
            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
            return

        max_polls = 360  # 360 * 0.5s = 180s timeout
        for _ in range(max_polls):
            try:
                event = await loop.run_in_executor(None, lambda: q.get(True, 0.5))
            except Empty:
                continue

            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            event_type = event.get("type", "")
            if event_type in ("done", "error", "cancelled"):
                remove_queue(stream_key)
                return

        # Timeout — clean up
        remove_queue(stream_key)
        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ─── Single Supplier Inquiry (Re-do) ────────────────────────

@router.post("/{order_id}/generate-inquiry/{supplier_id}")
def generate_inquiry_single(
    order_id: int,
    supplier_id: int,
    body: GenerateInquirySingleRequest = GenerateInquirySingleRequest(),
    current_user: User = Depends(require_writer),
    db: DBSession = Depends(get_db),
):
    """Re-generate inquiry for a single supplier."""
    order = _get_order(db, order_id, current_user)
    if order.status != "ready":
        raise HTTPException(400, "订单尚未处理完成")
    if not order.match_results:
        raise HTTPException(400, "没有匹配结果")

    # Verify supplier has products in this order
    has_supplier = any(
        (item.get("matched_product") or {}).get("supplier_id") == supplier_id
        for item in order.match_results
    )
    if not has_supplier:
        raise HTTPException(404, f"供应商 {supplier_id} 不在此订单中")

    stream_key = f"inquiry-{order_id}-{supplier_id}"

    if get_queue(stream_key) is not None:
        # If cancel event still exists, a background thread is truly active → block
        if get_cancel_event(stream_key) is not None:
            raise HTTPException(409, "该供应商询价单正在生成中")
        # Otherwise it's a stale queue (SSE disconnected before cleanup) → clear it
        remove_queue(stream_key)

    get_or_create_queue(stream_key)
    get_or_create_cancel_event(stream_key)

    threading.Thread(
        target=_run_inquiry_single_background,
        args=(order_id, supplier_id, stream_key, body.template_id),
        daemon=True,
    ).start()

    return {"status": "generating", "stream_key": stream_key, "supplier_id": supplier_id}


@router.post("/{order_id}/cancel-inquiry")
def cancel_inquiry(
    order_id: int,
    body: CancelInquiryRequest = CancelInquiryRequest(),
    current_user: User = Depends(require_writer),
    db: DBSession = Depends(get_db),
):
    """Cancel an ongoing inquiry generation run for an order or a single supplier."""
    _get_order(db, order_id, current_user)

    stream_key = body.stream_key or f"inquiry-{order_id}"
    set_cancelled(stream_key)
    push_event(stream_key, {"type": "cancelled", "message": "询价生成已停止"})
    return {"status": "cancelled", "stream_key": stream_key}


def _run_inquiry_single_background(order_id: int, supplier_id: int, stream_key: str, template_id=None):
    """Background thread: run single supplier inquiry and merge result into order."""
    from services.orders.inquiry_agent import InquiryCancelledError, run_inquiry_single_supplier

    db = SessionLocal()
    try:
        order = db.query(Order).get(order_id)
        if not order:
            push_event(stream_key, {"type": "error", "message": "订单不存在"})
            return

        result = run_inquiry_single_supplier(order, db, supplier_id, stream_key, template_id)

        # Merge result into existing inquiry_data
        inquiry_data = order.inquiry_data or {"suppliers": {}, "generated_files": []}
        suppliers = inquiry_data.setdefault("suppliers", {})
        suppliers[str(supplier_id)] = result

        # Update generated_files flat list (replace existing entry for this supplier)
        gen_files = inquiry_data.get("generated_files", [])
        gen_files = [f for f in gen_files if f.get("supplier_id") != supplier_id]
        if result.get("file"):
            gen_files.append(result["file"])
        inquiry_data["generated_files"] = gen_files
        inquiry_data["supplier_count"] = len(set(f.get("supplier_id") for f in gen_files if f.get("supplier_id")))

        from sqlalchemy.orm.attributes import flag_modified
        order.inquiry_data = inquiry_data
        flag_modified(order, "inquiry_data")
        db.commit()

        cancel_event = get_or_create_cancel_event(stream_key)
        if not cancel_event.is_set():
            push_event(stream_key, {"type": "done", "data": result})
    except InquiryCancelledError:
        db.rollback()
    except Exception as e:
        logger.error("Inquiry single supplier %d for order %d failed: %s",
                     supplier_id, order_id, str(e), exc_info=True)
        db.rollback()
        push_event(stream_key, {"type": "error", "message": str(e)})
    finally:
        remove_cancel_event(stream_key)
        db.close()


@router.get("/{order_id}/inquiry-preview/{supplier_id}")
def inquiry_preview(
    order_id: int,
    supplier_id: int,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Get saved preview HTML for a supplier's inquiry."""
    order = _get_order(db, order_id)
    inquiry_data = order.inquiry_data or {}
    suppliers = inquiry_data.get("suppliers", {})
    supplier_data = suppliers.get(str(supplier_id))

    if not supplier_data:
        raise HTTPException(404, "未找到该供应商的询价数据")

    file_info = supplier_data.get("file")
    if not file_info or not file_info.get("preview_url"):
        raise HTTPException(404, "没有预览文件")

    preview_url = file_info["preview_url"]
    try:
        html_bytes = storage.download(preview_url)
        html = html_bytes.decode("utf-8")
    except FileNotFoundError:
        raise HTTPException(404, "预览文件已丢失")

    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html)


# ─── Files ─────────────────────────────────────────────────────

@router.get("/{order_id}/files")
def list_order_files(
    order_id: int,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """List generated files for an order."""
    order = _get_order(db, order_id)
    inquiry = order.inquiry_data or {}
    return inquiry.get("generated_files", [])


def _get_download_user(
    token: str | None = Query(None),
    db: DBSession = Depends(get_db),
) -> User:
    """Authenticate via ?token= query param for direct download links."""
    if not token:
        raise HTTPException(401, "Not authenticated")
    from core.security import decode_token as _decode
    from jose import JWTError
    try:
        payload = _decode(token)
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(401, "无效的认证凭证")
    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(401, "用户不存在或已停用")
    return user


@router.get("/{order_id}/files/{filename}")
def download_order_file(
    order_id: int,
    filename: str,
    current_user: User = Depends(_get_download_user),
    db: DBSession = Depends(get_db),
):
    """Download a generated file. Auth via ?token= query param."""
    order = _get_order(db, order_id)

    # Verify file belongs to this order
    inquiry = order.inquiry_data or {}
    files = inquiry.get("generated_files", [])
    valid = any(f.get("filename") == filename for f in files)
    if not valid:
        raise HTTPException(404, "文件不存在")

    # Find the file_url from inquiry data
    file_url = None
    for f in files:
        if f.get("filename") == filename:
            file_url = f.get("file_url", filename)
            break

    try:
        content = storage.download(file_url or filename)
    except FileNotFoundError:
        raise HTTPException(404, "文件已丢失")

    from fastapi.responses import Response
    safe_filename = os.path.basename(filename)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )


# ─── Inquiry Readiness ─────────────────────────────────────────

@router.get("/{order_id}/inquiry-readiness")
def inquiry_readiness(
    order_id: int,
    template_overrides: str | None = Query(default=None, description="JSON: {supplier_id: template_id}"),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Check inquiry generation readiness for ALL suppliers in an order.

    Returns per-supplier status (ready/needs_input/blocked), gaps that need
    user attention, and an overall summary. This is the single source of truth
    for the frontend's inquiry tab rendering.
    """
    from services.orders.inquiry_agent import select_template, _build_order_data_for_engine
    from services.data.field_schema import analyze_gaps, schema_from_zone_config
    from core.models import SupplierTemplate
    import sqlalchemy, json

    # Parse template overrides: {str(supplier_id): template_id}
    parsed_overrides: dict[int, int] = {}
    if template_overrides:
        try:
            raw = json.loads(template_overrides)
            parsed_overrides = {int(k): int(v) for k, v in raw.items() if v is not None}
        except Exception:
            pass

    order = _get_order(db, order_id, current_user)
    if not order.match_results:
        return {"suppliers": {}, "summary": {"ready": 0, "needs_input": 0, "blocked": 0, "total": 0}}

    # Group products by supplier
    products_by_supplier: dict[int, list] = {}
    for p in order.match_results:
        sid = (p.get("matched_product") or {}).get("supplier_id")
        if sid:
            products_by_supplier.setdefault(sid, []).append(p)

    # Load all templates + supplier info (fetch all fields used by templates)
    all_templates = db.query(SupplierTemplate).all()
    all_templates_by_id = {t.id: t for t in all_templates}
    supplier_ids = list(products_by_supplier.keys())
    supplier_rows = {}
    if supplier_ids:
        rows = db.execute(
            sqlalchemy.text(
                "SELECT id, name, contact, email, phone, fax, address, zip_code,"
                " default_payment_method, default_payment_terms"
                " FROM suppliers WHERE id = ANY(:ids)"
            ),
            {"ids": supplier_ids},
        ).fetchall()
        for row in rows:
            supplier_rows[row[0]] = {
                "name": row[1] or "", "contact": row[2] or "", "email": row[3] or "",
                "phone": row[4] or "", "fax": row[5] or "", "address": row[6] or "",
                "zip_code": row[7] or "", "default_payment_method": row[8] or "",
                "default_payment_terms": row[9] or "",
            }

    order_meta = dict(order.order_metadata or {})

    # Enrich order_meta with port location (same as _generate_single_supplier does)
    if order.port_id:
        p_row = db.execute(
            sqlalchemy.text("SELECT name, location, code FROM ports WHERE id = :pid"),
            {"pid": order.port_id},
        ).fetchone()
        if p_row:
            order_meta.setdefault("port_name", p_row[0] or "")
            order_meta.setdefault("delivery_address", p_row[1] or "")
            order_meta.setdefault("port_code", p_row[2] or "")

    # Pre-fetch default delivery location for delivery_info fields
    delivery_info: dict = {}
    try:
        from core.models import DeliveryLocation
        loc = db.query(DeliveryLocation).filter(DeliveryLocation.is_default == True).first()
        if loc:
            delivery_info = {
                "name": loc.name, "address": loc.address,
                "contact_person": loc.contact_person,
                "contact_phone": loc.contact_phone,
                "delivery_notes": loc.delivery_notes,
                "ship_name_label": loc.ship_name_label,
            }
    except Exception:
        pass

    inquiry_data = order.inquiry_data or {}
    existing_suppliers = inquiry_data.get("suppliers", {})

    result_suppliers: dict[str, Any] = {}
    total_ready = 0
    total_needs_input = 0
    total_blocked = 0

    for sid, products in products_by_supplier.items():
        sid_str = str(sid)
        info = supplier_rows.get(sid, {"name": f"供应商 #{sid}", "contact": "", "email": "", "phone": "", "fax": "", "address": "", "zip_code": "", "default_payment_method": "", "default_payment_terms": ""})

        # Template resolution — honour frontend override if provided
        if sid in parsed_overrides:
            override_tid = parsed_overrides[sid]
            override_tpl = all_templates_by_id.get(override_tid)
            if override_tpl:
                template, method, candidates = override_tpl, "manual_override", [override_tpl]
            else:
                template, method, candidates = select_template(sid, all_templates)
        else:
            template, method, candidates = select_template(sid, all_templates)

        # Check for user template override in inquiry_data
        existing_entry = existing_suppliers.get(sid_str, {})
        field_overrides = existing_entry.get("field_overrides", {})

        # Build order_data for gap analysis
        order_data = _build_order_data_for_engine(
            order.id, order_meta, sid, products, info,
            delivery_info=delivery_info, _db=db,
        )

        # Get field_schema
        field_schema = None
        template_name = None
        has_zone_config = False

        if template:
            template_name = template.template_name
            ts = template.template_styles or {}
            if "zones" in ts:
                has_zone_config = True
                # Prefer new field_schema, fall back to building from header_fields
                field_schema = ts.get("field_schema")
                if not field_schema:
                    field_schema = schema_from_zone_config(ts)

        # Gap analysis
        if has_zone_config and field_schema is not None:
            if field_schema:
                # Template has header fields → run gap analysis
                gap_report = analyze_gaps(field_schema, order_data, sid, field_overrides)
            else:
                # Template has zone_config but empty header_fields (flat-table format,
                # e.g. Korean template) — no header to fill, generation can proceed
                gap_report = {
                    "gaps": [],
                    "summary": {"total": 0, "resolved": 0, "warnings": 0, "blocking": 0},
                    "ready": True,
                }
            if gap_report["ready"]:
                status = "ready"
                total_ready += 1
            elif gap_report["summary"]["blocking"] > 0:
                status = "needs_input"
                total_needs_input += 1
            else:
                status = "ready"  # only warnings, can still generate
                total_ready += 1
        else:
            gap_report = {
                "gaps": [],
                "summary": {"total": 0, "resolved": 0, "warnings": 0, "blocking": 1},
                "ready": False,
            }
            status = "blocked"
            total_blocked += 1

        # If product data fell back to snapshot (DB re-hydration failed), add a warning gap
        if order_data.get("_data_stale"):
            gap_report["gaps"].append({
                "key": "data_freshness",
                "cell": "_stale",
                "label": "产品数据来自快照，建议重新匹配以获取最新价格",
                "type": "text",
                "category": "order",
                "severity": "warning",
                "current_value": None,
            })
            gap_report["summary"]["warnings"] = gap_report["summary"].get("warnings", 0) + 1
            gap_report["summary"]["total"] = gap_report["summary"].get("total", 0) + 1

        # Compute subtotal
        subtotal = 0.0
        for p in products:
            mp = p.get("matched_product") or {}
            qty = p.get("quantity") or 0
            price = p.get("unit_price") or mp.get("price") or 0
            try:
                subtotal += float(qty) * float(price)
            except (TypeError, ValueError):
                pass

        # Check generation status from existing inquiry_data
        gen_status = existing_entry.get("status", "pending")
        if gen_status == "completed":
            status = "completed"

        result_suppliers[sid_str] = {
            "status": status,
            "gen_status": gen_status,
            "supplier_name": info.get("name", ""),
            "product_count": len(products),
            "subtotal": round(subtotal, 2),
            "currency": order_meta.get("currency", ""),
            "template": {
                "id": template.id if template else None,
                "name": template_name,
                "method": method,
                "has_zone_config": has_zone_config,
                "candidate_count": len(candidates),
            },
            "fields": gap_report.get("fields", []),
            "gaps": gap_report["gaps"],
            "gap_summary": gap_report["summary"],
            "file": existing_entry.get("file"),
            "verify_results": existing_entry.get("verify_results"),
            "elapsed_seconds": existing_entry.get("elapsed_seconds"),
            "error": existing_entry.get("error") or (
                "当前供应商没有已上架的 zone_config 模板，无法生成询价单"
                if not template else None
            ),
        }

    return {
        "suppliers": result_suppliers,
        "summary": {
            "ready": total_ready,
            "needs_input": total_needs_input,
            "blocked": total_blocked,
            "total": len(products_by_supplier),
        },
    }


# ─── Inquiry Data Preview ─────────────────────────────────────

@router.get("/{order_id}/inquiry-data-preview/{supplier_id}")
def inquiry_data_preview(
    order_id: int,
    supplier_id: int,
    template_id: int | None = Query(None, description="Override template ID"),
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Preview what order data will fill into a supplier's inquiry template.

    Returns structured preview of header fields (with resolved values),
    product data summary, and any warnings — without generating the actual Excel.
    """
    from services.orders.inquiry_agent import select_template, _build_order_data_for_engine
    from services.data.field_schema import _resolve_path
    from services.templates.template_engine_legacy import _resolve_product_field
    from core.models import SupplierTemplate
    import sqlalchemy

    order = _get_order(db, order_id, current_user)
    if not order.match_results:
        raise HTTPException(400, "没有匹配结果")

    # Gather products for this supplier
    products = [
        p for p in order.match_results
        if (p.get("matched_product") or {}).get("supplier_id") == supplier_id
    ]
    if not products:
        raise HTTPException(404, f"供应商 {supplier_id} 不在此订单中")

    # Load supplier info
    row = db.execute(
        sqlalchemy.text("SELECT id, name, contact, email, phone FROM suppliers WHERE id = :sid"),
        {"sid": supplier_id},
    ).fetchone()
    supplier_info = {
        "name": row[1] if row else "",
        "contact": row[2] if row else "",
        "email": row[3] if row else "",
        "phone": row[4] if row else "",
    } if row else {"name": f"供应商 #{supplier_id}", "contact": "", "email": "", "phone": ""}

    # Resolve template
    all_templates = db.query(SupplierTemplate).all()
    try:
        template, method, candidates = select_template(
            supplier_id,
            all_templates,
            template_id_override=template_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Build order_data (same as generation pipeline)
    order_meta = order.order_metadata or {}
    order_data = _build_order_data_for_engine(
        order.id, order_meta, supplier_id, products, supplier_info, _db=db,
    )

    sid = str(supplier_id)
    warnings: list[str] = []
    header_fields: list[dict] = []
    product_preview: list[dict] = []

    # Get zone_config from template
    # zone_config fields (zones, header_fields, product_columns, etc.) are stored
    # flat at the root of template_styles, not nested under a "zone_config" key.
    zone_config = None
    template_name = None
    if template:
        template_name = template.template_name
        ts = template.template_styles or {}
        if "zones" in ts:
            zone_config = ts

    if zone_config:
        # Resolve header fields
        for cell_ref, data_path in zone_config.get("header_fields", {}).items():
            value = _resolve_path(order_data, data_path, sid)
            # Determine field label from path
            label = data_path.split(".")[-1]
            label_map = {
                "po_number": "PO 号", "ship_name": "船名", "delivery_date": "交付日期",
                "order_date": "订单日期", "currency": "货币", "destination_port": "目的港",
                "delivery_address": "交付地址", "voyage": "航次",
                "supplier_name": "供应商名称", "name": "名称", "contact": "联系人",
                "email": "邮箱", "phone": "电话", "address": "地址",
                "contact_person": "联系人", "contact_phone": "联系电话",
                "ship_name_label": "船名标签", "delivery_notes": "交付备注",
                "fax": "传真", "company_name": "公司名称",
            }
            header_fields.append({
                "cell": cell_ref,
                "path": data_path,
                "label": label_map.get(label, label),
                "value": str(value) if value is not None else None,
                "source": "order" if not data_path.startswith("suppliers.") and not data_path.startswith("company.") and not data_path.startswith("delivery_location.") else (
                    "supplier" if "supplier" in data_path else (
                        "company" if data_path.startswith("company.") else "delivery"
                    )
                ),
            })
            if value is None or (isinstance(value, str) and not value.strip()):
                warnings.append(f"字段 {label_map.get(label, label)} ({cell_ref}) 无数据")

        # Build product preview from zone_config column mapping
        col_map = zone_config.get("product_columns", {})
        po_number = order_data.get("po_number", "")
        currency = order_data.get("currency") or "JPY"
        engine_products = order_data.get("suppliers", {}).get(sid, {}).get("products", [])

        # Flat order context for per-row order-level fields (flat-table templates)
        _sup_data = order_data.get("suppliers", {}).get(sid, {})
        _order_ctx = {
            "ship_name": order_data.get("ship_name", ""),
            "delivery_date": order_data.get("delivery_date", ""),
            "order_date": order_data.get("order_date", ""),
            "supplier_name": _sup_data.get("supplier_name", ""),
        }

        for i, p in enumerate(engine_products[:20]):  # cap at 20 for preview
            row_data: dict = {"_index": i + 1}
            for col_letter, field_name in col_map.items():
                val = _resolve_product_field(field_name, p, i, po_number, currency, _order_ctx)
                row_data[field_name] = val
            product_preview.append(row_data)

        # Check for formula columns
        formula_cols = list(zone_config.get("product_row_formulas", {}).keys())
        summary_formulas = zone_config.get("summary_formulas", [])
    else:
        # No production template — still show raw product data for inspection,
        # but make the block reason explicit so generation stays deterministic.
        formula_cols = []
        summary_formulas = []
        engine_products = order_data.get("suppliers", {}).get(sid, {}).get("products", [])
        for i, p in enumerate(engine_products[:20]):
            product_preview.append({
                "_index": i + 1,
                "product_code": p.get("product_code", ""),
                "product_name": p.get("product_name", ""),
                "quantity": p.get("quantity"),
                "unit": p.get("unit", ""),
                "unit_price": p.get("unit_price"),
                "pack_size": p.get("pack_size", ""),
            })
        if candidates:
            warnings.append(
                f"当前无精确模板绑定，将使用候选模板自动选择逻辑；候选数: {len(candidates)}"
            )
        else:
            warnings.append("当前供应商没有已上架的 zone_config 模板，无法生成询价单")

    # Data completeness warnings — only warn about unit_price if the template uses it
    missing_vals = sum(1 for h in header_fields if h["value"] is None)
    template_uses_price = zone_config and "unit_price" in (zone_config.get("product_columns") or {}).values()
    if template_uses_price:
        empty_prices = sum(1 for p in product_preview if p.get("unit_price") is None)
        if empty_prices:
            warnings.append(f"{empty_prices} 个产品缺少单价")

    # Load existing field_overrides if any
    inquiry_data = order.inquiry_data or {}
    existing_overrides = (
        inquiry_data.get("suppliers", {}).get(str(supplier_id), {}).get("field_overrides", {})
    )

    return {
        "supplier_id": supplier_id,
        "supplier_name": supplier_info.get("name", ""),
        "template": {
            "id": template.id if template else None,
            "name": template_name,
            "method": method,
            "has_zone_config": zone_config is not None,
        },
        "header_fields": header_fields,
        "field_overrides": existing_overrides,
        "product_columns": list((zone_config or {}).get("product_columns", {}).items()) if zone_config else None,
        "formula_columns": formula_cols if zone_config else None,
        "summary_formulas": [{"cell": sf["cell"], "type": sf["type"], "label": sf.get("label", "")} for sf in summary_formulas] if zone_config else None,
        "products": product_preview,
        "total_products": len(engine_products),
        "warnings": warnings,
        "order_metadata": {
            "po_number": order_meta.get("po_number", ""),
            "ship_name": order_meta.get("ship_name", ""),
            "delivery_date": order_meta.get("delivery_date", ""),
            "currency": order_meta.get("currency", ""),
        },
    }


class FieldOverridesRequest(BaseModel):
    overrides: dict[str, str]

@router.post("/{order_id}/inquiry-field-overrides/{supplier_id}")
def save_inquiry_field_overrides(
    order_id: int,
    supplier_id: int,
    body: FieldOverridesRequest,
    current_user: User = Depends(require_writer),
    db: DBSession = Depends(get_db),
):
    """Save user-edited field overrides for a supplier's inquiry generation.

    Stored in order.inquiry_data.suppliers[sid].field_overrides = {cell_ref: value}.
    These overrides are applied on top of resolved values during Excel generation.
    """
    from sqlalchemy.orm.attributes import flag_modified

    order = _get_order(db, order_id, current_user)
    inquiry_data = order.inquiry_data or {"suppliers": {}}
    suppliers = inquiry_data.setdefault("suppliers", {})
    sid = str(supplier_id)
    supplier_entry = suppliers.setdefault(sid, {})

    # Only store non-empty overrides
    cleaned = {k: v for k, v in body.overrides.items() if v and v.strip()}
    supplier_entry["field_overrides"] = cleaned

    order.inquiry_data = inquiry_data
    flag_modified(order, "inquiry_data")
    db.commit()

    return {"status": "saved", "overrides_count": len(cleaned)}


@router.post("/{order_id}/files/{filename}/download")
def download_order_file_secure(
    order_id: int,
    filename: str,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Download a generated file. Auth via Authorization header (preferred)."""
    order = _get_order(db, order_id)
    inquiry = order.inquiry_data or {}
    files = inquiry.get("generated_files", [])
    valid = any(f.get("filename") == filename for f in files)
    if not valid:
        raise HTTPException(404, "文件不存在")

    # Find the file_url from inquiry data
    file_url = None
    for f in files:
        if f.get("filename") == filename:
            file_url = f.get("file_url", filename)
            break

    try:
        content = storage.download(file_url or filename)
    except FileNotFoundError:
        raise HTTPException(404, "文件已丢失")

    from fastapi.responses import Response
    safe_filename = os.path.basename(filename)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )
