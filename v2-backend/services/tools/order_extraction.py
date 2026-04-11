"""
Order extraction tool — Agent-triggered PDF extraction using Gemini native PDF.

Replaces the old auto-extraction in process_order(). Now Agent explicitly
calls this tool and can observe/react to the results.
"""

from __future__ import annotations

import json
import logging
import time

from services.tools.registry_loader import ToolMetaInfo

logger = logging.getLogger(__name__)

TOOL_META = {
    "extract_order": ToolMetaInfo(
        display_name="提取订单",
        group="business",
        description="从已上传的订单 PDF 中提取元数据和产品列表 (Gemini 原生 PDF)",
        prompt_description="从订单 PDF 提取元数据+产品列表",
        summary="提取订单",
    ),
}


def register(registry, ctx=None):
    """Register extract_order tool."""

    @registry.tool(
        description=(
            "从已上传的订单 PDF 中提取结构化数据 (元数据 + 产品列表)。\n"
            "使用 Gemini 2.5 Flash 原生 PDF 输入, 一次调用提取全部内容。\n"
            "提取后自动进行数值交叉验证 (price × qty ≈ total)。\n\n"
            "返回: 提取状态、产品数量、元数据摘要、验证警告。\n"
            "如果提取失败或产品数为 0, 会说明原因。\n\n"
            "示例:\n"
            '  extract_order(order_id=123)\n'
            '  extract_order(order_id=123, force=true)  # 重新提取, 覆盖之前的结果'
        ),
        parameters={
            "order_id": {
                "type": "NUMBER",
                "description": "订单 ID",
            },
            "force": {
                "type": "STRING",
                "description": "是否强制重新提取 (true/false, 默认 false — 如果已有提取结果则跳过)",
                "required": False,
            },
        },
        group="business",
    )
    def extract_order(order_id: int = 0, force: str = "false") -> str:
        if not order_id:
            return "Error: 需要 order_id"
        order_id = int(order_id)
        force_extract = force.lower().strip() in ("true", "1", "yes")

        from core.models import Order
        from sqlalchemy.orm.attributes import flag_modified
        from services.tools._security import scope_to_owner

        query = ctx.db.query(Order).filter(Order.id == order_id)
        query = scope_to_owner(query, Order, ctx)
        order = query.first()
        if not order:
            return f"Error: 订单 {order_id} 不存在"

        # Skip if already extracted (unless force)
        if not force_extract and order.products and len(order.products) > 0:
            products = order.products
            meta = order.order_metadata or {}
            return (
                f"订单 {order_id} 已有提取结果 (共 {len(products)} 个产品)。\n"
                f"PO: {meta.get('po_number', '-')}, 船名: {meta.get('ship_name', '-')}, "
                f"交货日期: {meta.get('delivery_date', '-')}\n"
                f"如需重新提取, 请设置 force=true。"
            )

        # Get file bytes
        file_bytes = None
        if order.file_url:
            try:
                from services.common.file_storage import storage
                file_bytes = storage.download(order.file_url)
            except Exception as e:
                return f"Error: 无法下载文件 {order.file_url}: {e}"

        if not file_bytes:
            return f"Error: 订单 {order_id} 没有关联的文件"

        # Extract
        start = time.time()
        order.status = "extracting"
        ctx.db.commit()

        try:
            from services.orders.order_processor import smart_extract, normalize_metadata
            from services.data.product_normalizer import normalize_products
            import copy

            extracted = smart_extract(file_bytes, order.file_type or "pdf")
            elapsed = time.time() - start

            # Save to order
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

            order.status = "extracted"
            order.processing_error = None
            flag_modified(order, "extraction_data")
            flag_modified(order, "order_metadata")
            flag_modified(order, "products")
            ctx.db.commit()

            # Build response
            meta = order.order_metadata or {}
            products = order.products or []
            method = extracted.get("extraction_method", "unknown")

            # Validation warnings
            from services.orders.order_processor import _validate_extraction_numbers
            num_warnings = _validate_extraction_numbers(products)

            lines = [
                f"## 提取完成 — 订单 #{order_id}",
                f"- 方法: {method}",
                f"- 耗时: {elapsed:.1f}s",
                f"- 产品数: {len(products)}",
                "",
                f"## 元数据",
                f"- PO号: {meta.get('po_number', '-')}",
                f"- 船名: {meta.get('ship_name', '-')}",
                f"- 供应商: {meta.get('vendor_name', '-')}",
                f"- 交货日期: {meta.get('delivery_date', '-')}",
                f"- 币种: {meta.get('currency', '-')}",
                f"- 目的港: {meta.get('destination_port', '-')}",
            ]

            if num_warnings:
                lines += ["", f"## ⚠️ 数值验证警告 ({len(num_warnings)} 项)"]
                for w in num_warnings[:5]:
                    lines.append(f"  - {w}")

            if len(products) == 0:
                lines += ["", "## ❌ 未识别到任何产品", "建议: 检查文件格式, 或尝试重新提取 (force=true)"]
                order.status = "error"
                order.processing_error = "提取失败: 未识别到任何产品"
                ctx.db.commit()

            # Register order for artifact panel
            ctx.register_order(order_id)

            return "\n".join(lines)

        except Exception as e:
            elapsed = time.time() - start
            logger.error("extract_order %d failed after %.1fs: %s", order_id, elapsed, e, exc_info=True)
            order.status = "error"
            order.processing_error = f"提取失败: {type(e).__name__}: {e}"
            ctx.db.commit()
            return f"Error: 提取失败 ({elapsed:.1f}s): {e}"
