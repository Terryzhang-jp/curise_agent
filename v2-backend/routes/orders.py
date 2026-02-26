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
import uuid
from datetime import datetime
from queue import Empty

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import desc
from sqlalchemy.orm import Session as DBSession

from config import settings
from database import get_db, SessionLocal
from models import Order, User
from routes.auth import get_current_user
from security import require_role
from schemas import OrderListItem, OrderDetail, OrderReviewRequest, OrderUpdateRequest, OrderRematchRequest
from services.agent.stream_queue import get_or_create_queue, get_queue, remove_queue, push_event

# Write operations require non-finance roles
require_writer = require_role("superadmin", "admin", "employee")

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/orders", tags=["orders"])

UPLOAD_DIR = settings.UPLOAD_DIR
MAX_FILE_SIZE = settings.MAX_UPLOAD_SIZE


# ─── Upload & Process ──────────────────────────────────────────

@router.post("/upload", response_model=OrderDetail)
async def upload_order(
    file: UploadFile = File(...),
    current_user: User = Depends(require_writer),
    db: DBSession = Depends(get_db),
):
    """Upload a file and create an order with automatic processing."""
    if not file.filename:
        raise HTTPException(400, "文件名不能为空")

    lower = file.filename.lower()
    if not (lower.endswith(".pdf") or lower.endswith(".xlsx")):
        raise HTTPException(400, "仅支持 PDF 和 XLSX 文件")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, "文件大小不能超过 20 MB")

    # Save file
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    path = os.path.join(UPLOAD_DIR, safe_name)
    with open(path, "wb") as f:
        f.write(content)
    file_url = f"/uploads/{safe_name}"

    file_type = "pdf" if lower.endswith(".pdf") else "excel"

    order = Order(
        user_id=current_user.id,
        filename=file.filename,
        file_url=file_url,
        file_type=file_type,
        status="uploading",
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    # Launch background processing
    order_id = order.id
    file_bytes = content
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, _run_process_order, order_id, file_bytes)

    return order


def _run_process_order(order_id: int, file_bytes: bytes):
    """Wrapper for background thread execution."""
    from services.order_processor import process_order
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
    query = db.query(Order).filter(Order.user_id == current_user.id)

    if status:
        query = query.filter(Order.status == status)
    if search:
        query = query.filter(Order.filename.ilike(f"%{search}%"))

    total = query.count()
    orders = query.order_by(desc(Order.created_at)).offset(offset).limit(limit).all()

    return {"total": total, "items": [OrderListItem.model_validate(o) for o in orders]}


@router.get("/{order_id}", response_model=OrderDetail)
def get_order(
    order_id: int,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Get order details."""
    order = db.query(Order).filter(
        Order.id == order_id,
        Order.user_id == current_user.id,
    ).first()
    if not order:
        raise HTTPException(404, "订单不存在")
    return order


# ─── Delete ────────────────────────────────────────────────────

@router.delete("/{order_id}")
def delete_order(
    order_id: int,
    current_user: User = Depends(require_writer),
    db: DBSession = Depends(get_db),
):
    """Delete an order and its associated files."""
    order = db.query(Order).filter(
        Order.id == order_id,
        Order.user_id == current_user.id,
    ).first()
    if not order:
        raise HTTPException(404, "订单不存在")

    # Clean up uploaded file
    if order.file_url:
        fpath = os.path.join(UPLOAD_DIR, os.path.basename(order.file_url))
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
            except OSError as e:
                logger.warning("Failed to delete %s: %s", fpath, e)

    # Clean up generated inquiry Excel files
    if order.inquiry_data:
        for f in order.inquiry_data.get("generated_files", []):
            fname = f.get("filename")
            if fname:
                fpath = os.path.join(UPLOAD_DIR, os.path.basename(fname))
                if os.path.exists(fpath):
                    try:
                        os.remove(fpath)
                    except OSError as e:
                        logger.warning("Failed to delete %s: %s", fpath, e)

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
    order = db.query(Order).filter(
        Order.id == order_id,
        Order.user_id == current_user.id,
    ).first()
    if not order:
        raise HTTPException(404, "订单不存在")
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
    order = db.query(Order).filter(
        Order.id == order_id,
        Order.user_id == current_user.id,
    ).first()
    if not order:
        raise HTTPException(404, "订单不存在")
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
    from services.order_processor import run_agent_matching

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
                    from services.order_processor import run_financial_analysis
                    order.financial_data = run_financial_analysis(order)
                except Exception as e:
                    logger.warning("Rematch: Order %d financial analysis failed: %s", order_id, str(e))

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
    order = db.query(Order).filter(
        Order.id == order_id,
        Order.user_id == current_user.id,
    ).first()
    if not order:
        raise HTTPException(404, "订单不存在")

    order.is_reviewed = True
    order.reviewed_at = datetime.utcnow()
    order.reviewed_by = current_user.id
    order.review_notes = body.notes
    db.commit()
    db.refresh(order)
    return {"detail": "已标记审核", "reviewed_at": order.reviewed_at.isoformat()}


# ─── Reprocess ─────────────────────────────────────────────────

@router.post("/{order_id}/reprocess", response_model=OrderDetail)
async def reprocess_order(
    order_id: int,
    current_user: User = Depends(require_writer),
    db: DBSession = Depends(get_db),
):
    """Reprocess a failed order."""
    order = db.query(Order).filter(
        Order.id == order_id,
        Order.user_id == current_user.id,
    ).first()
    if not order:
        raise HTTPException(404, "订单不存在")
    if order.status not in ("error", "ready"):
        raise HTTPException(400, "仅可重新处理出错或已完成的订单")

    # Read file bytes from saved file
    if not order.file_url:
        raise HTTPException(400, "找不到原始文件")
    file_path = os.path.join(UPLOAD_DIR, os.path.basename(order.file_url))
    if not os.path.exists(file_path):
        raise HTTPException(400, "原始文件已丢失")

    with open(file_path, "rb") as f:
        file_bytes = f.read()

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
    order = db.query(Order).filter(
        Order.id == order_id,
        Order.user_id == current_user.id,
    ).first()
    if not order:
        raise HTTPException(404, "订单不存在")
    if order.status != "ready":
        raise HTTPException(400, "订单尚未处理完成")

    from services.order_processor import run_anomaly_check
    anomaly_data = run_anomaly_check(order)
    order.anomaly_data = anomaly_data
    db.commit()
    db.refresh(order)
    return order


# ─── Financial Analysis ──────────────────────────────────────

@router.post("/{order_id}/financial-analysis", response_model=OrderDetail)
def financial_analysis(
    order_id: int,
    current_user: User = Depends(require_writer),
    db: DBSession = Depends(get_db),
):
    """Run or re-run financial analysis on an order."""
    order = db.query(Order).filter(
        Order.id == order_id,
        Order.user_id == current_user.id,
    ).first()
    if not order:
        raise HTTPException(404, "订单不存在")
    if order.status != "ready":
        raise HTTPException(400, "订单尚未处理完成")
    if not order.match_results:
        raise HTTPException(400, "没有匹配结果，无法进行财务分析")

    from services.order_processor import run_financial_analysis
    order.financial_data = run_financial_analysis(order)
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
    order = db.query(Order).filter(
        Order.id == order_id,
        Order.user_id == current_user.id,
    ).first()
    if not order:
        raise HTTPException(404, "订单不存在")
    if order.status != "ready":
        raise HTTPException(400, "订单尚未处理完成")
    if not order.port_id or not order.delivery_date:
        raise HTTPException(400, "缺少港口或交货日期信息")

    from services.weather_service import fetch_delivery_environment
    from models import Port, Country
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

@router.post("/{order_id}/generate-inquiry")
def generate_inquiry(
    order_id: int,
    current_user: User = Depends(require_writer),
    db: DBSession = Depends(get_db),
):
    """Start inquiry generation in background, return stream_key for SSE progress."""
    order = db.query(Order).filter(
        Order.id == order_id,
        Order.user_id == current_user.id,
    ).first()
    if not order:
        raise HTTPException(404, "订单不存在")
    if order.status != "ready":
        raise HTTPException(400, "订单尚未处理完成")
    if not order.match_results:
        raise HTTPException(400, "没有匹配结果，无法生成询价单")

    stream_key = f"inquiry-{order_id}"

    # Prevent duplicate concurrent generation
    if get_queue(stream_key) is not None:
        raise HTTPException(409, "询价单正在生成中，请稍候")

    get_or_create_queue(stream_key)

    threading.Thread(
        target=_run_inquiry_background,
        args=(order_id, stream_key),
        daemon=True,
    ).start()

    return {"status": "generating", "stream_key": stream_key}


def _run_inquiry_background(order_id: int, stream_key: str):
    """Background thread: run streaming inquiry agent and save results."""
    from services.inquiry_agent import run_inquiry_agent_streaming

    db = SessionLocal()
    try:
        order = db.query(Order).get(order_id)
        if not order:
            logger.error("Inquiry: Order %d not found", order_id)
            push_event(stream_key, {"type": "error", "message": "订单不存在"})
            return

        inquiry_data = run_inquiry_agent_streaming(order, db, stream_key)

        order.inquiry_data = inquiry_data
        # Auto-advance fulfillment status to inquiry_sent
        if order.fulfillment_status == "pending":
            order.fulfillment_status = "inquiry_sent"
        db.commit()
        logger.info("Inquiry: Order %d saved, %d files generated",
                     order_id, len(inquiry_data.get("generated_files", [])))

        # Push done only after DB commit succeeds
        push_event(stream_key, {"type": "done", "data": inquiry_data})
    except Exception as e:
        logger.error("Inquiry: Order %d failed: %s", order_id, str(e), exc_info=True)
        db.rollback()
        try:
            order = db.query(Order).get(order_id)
            if order:
                order.status = "error"
                order.processing_error = f"询价生成失败: {str(e)}"
                db.commit()
        except Exception:
            db.rollback()
        push_event(stream_key, {"type": "error", "message": str(e)})
    finally:
        db.close()


@router.get("/{order_id}/inquiry-stream")
async def inquiry_stream(
    order_id: int,
    current_user: User = Depends(get_current_user),
):
    """SSE stream for real-time inquiry generation progress."""
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
            if event_type in ("done", "error"):
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


# ─── Files ─────────────────────────────────────────────────────

@router.get("/{order_id}/files")
def list_order_files(
    order_id: int,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """List generated files for an order."""
    order = db.query(Order).filter(
        Order.id == order_id,
        Order.user_id == current_user.id,
    ).first()
    if not order:
        raise HTTPException(404, "订单不存在")

    inquiry = order.inquiry_data or {}
    return inquiry.get("generated_files", [])


def _get_download_user(
    token: str | None = Query(None),
    db: DBSession = Depends(get_db),
) -> User:
    """Authenticate via ?token= query param for direct download links."""
    if not token:
        raise HTTPException(401, "Not authenticated")
    from security import decode_token as _decode
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
    order = db.query(Order).filter(
        Order.id == order_id,
        Order.user_id == current_user.id,
    ).first()
    if not order:
        raise HTTPException(404, "订单不存在")

    # Verify file belongs to this order
    inquiry = order.inquiry_data or {}
    files = inquiry.get("generated_files", [])
    valid = any(f.get("filename") == filename for f in files)
    if not valid:
        raise HTTPException(404, "文件不存在")

    safe_filename = os.path.basename(filename)
    file_path = os.path.realpath(os.path.join(UPLOAD_DIR, safe_filename))
    if not file_path.startswith(os.path.realpath(UPLOAD_DIR)):
        raise HTTPException(400, "非法文件路径")
    if not os.path.exists(file_path):
        raise HTTPException(404, "文件已丢失")

    return FileResponse(
        file_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=safe_filename,
    )


@router.post("/{order_id}/files/{filename}/download")
def download_order_file_secure(
    order_id: int,
    filename: str,
    current_user: User = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """Download a generated file. Auth via Authorization header (preferred)."""
    order = db.query(Order).filter(
        Order.id == order_id,
        Order.user_id == current_user.id,
    ).first()
    if not order:
        raise HTTPException(404, "订单不存在")

    inquiry = order.inquiry_data or {}
    files = inquiry.get("generated_files", [])
    valid = any(f.get("filename") == filename for f in files)
    if not valid:
        raise HTTPException(404, "文件不存在")

    safe_filename = os.path.basename(filename)
    file_path = os.path.realpath(os.path.join(UPLOAD_DIR, safe_filename))
    if not file_path.startswith(os.path.realpath(UPLOAD_DIR)):
        raise HTTPException(400, "非法文件路径")
    if not os.path.exists(file_path):
        raise HTTPException(404, "文件已丢失")

    return FileResponse(
        file_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=safe_filename,
    )
