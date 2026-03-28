"""
inquiry_workflow 组工具 — 询价单工作流自动化。

Provides 3 tools that mirror the frontend inquiry UI flow:
  1. check_inquiry_readiness  — gap analysis across all suppliers
  2. fill_inquiry_gaps        — fill missing field values
  3. generate_inquiries       — trigger generation for one or all suppliers

These tools share the same backend APIs as the frontend, ensuring
consistent behavior between manual UI operation and agent automation.
"""

from __future__ import annotations

import json
import logging

from services.tools.registry_loader import ToolMetaInfo

logger = logging.getLogger(__name__)

TOOL_META = {
    "check_inquiry_readiness": ToolMetaInfo(
        display_name="检查询价就绪状态",
        group="business",
        description="检查订单各供应商的询价数据完整性，识别缺失字段",
        prompt_description="检查订单询价就绪状态（缺失字段、模板绑定等）",
        summary="检查询价就绪状态",
        is_enabled_default=True,
    ),
    "fill_inquiry_gaps": ToolMetaInfo(
        display_name="补充询价字段",
        group="business",
        description="为供应商补充缺失的询价字段值",
        prompt_description="为指定供应商补充缺失的询价表头字段",
        summary="补充询价字段",
        is_enabled_default=True,
    ),
    "generate_inquiries": ToolMetaInfo(
        display_name="生成询价单",
        group="business",
        description="为订单生成供应商询价Excel（单个或全部）",
        prompt_description="生成询价单Excel文件",
        summary="生成询价单",
        is_enabled_default=True,
    ),
}


def register(registry, ctx=None):
    """Register inquiry workflow tools."""

    @registry.tool(
        description=(
            "检查订单的询价单生成就绪状态。返回每个供应商的状态：ready（可生成）、needs_input（缺必填字段）、completed（已生成）。\n"
            "在调用 generate_inquiries 前使用此工具确认数据完整性。\n"
            "如果供应商状态为 completed，说明已有询价单，再次调用 generate_inquiries 会重新生成（覆盖旧文件）。"
        ),
        parameters={
            "order_id": {
                "type": "NUMBER",
                "description": "订单 ID",
            },
        },
        group="business",
    )
    def check_inquiry_readiness(order_id: int) -> str:
        if not ctx or not ctx.db:
            return "Error: no database session available"

        try:
            from models import Order, SupplierTemplate
            from services.inquiry_agent import resolve_template, _build_order_data_for_engine
            from services.field_schema import analyze_gaps, schema_from_zone_config
            import sqlalchemy

            db = ctx.db
            order = db.query(Order).filter(Order.id == int(order_id)).first()
            if not order:
                return f"Error: 订单 {order_id} 不存在"
            if not order.match_results:
                return f"Error: 订单 {order_id} 还没有匹配结果，请先完成产品匹配"

            ctx.register_order(int(order_id))

            # Group products by supplier
            products_by_supplier: dict[int, list] = {}
            for p in order.match_results:
                sid = (p.get("matched_product") or {}).get("supplier_id")
                if sid:
                    products_by_supplier.setdefault(sid, []).append(p)

            all_templates = db.query(SupplierTemplate).all()
            supplier_ids = list(products_by_supplier.keys())

            # Load supplier info
            supplier_rows = {}
            if supplier_ids:
                rows = db.execute(
                    sqlalchemy.text("SELECT id, name, contact, email, phone FROM suppliers WHERE id = ANY(:ids)"),
                    {"ids": supplier_ids},
                ).fetchall()
                for row in rows:
                    supplier_rows[row[0]] = {"name": row[1], "contact": row[2], "email": row[3], "phone": row[4]}

            order_meta = order.order_metadata or {}
            inquiry_data = order.inquiry_data or {}
            existing_suppliers = inquiry_data.get("suppliers", {})

            results = []
            total_ready = 0
            total_needs_input = 0

            for sid, products in products_by_supplier.items():
                info = supplier_rows.get(sid, {"name": f"供应商 #{sid}"})
                template, method, _ = resolve_template(sid, all_templates)

                existing_entry = existing_suppliers.get(str(sid), {})
                field_overrides = existing_entry.get("field_overrides", {})

                order_data = _build_order_data_for_engine(
                    order.id, order_meta, sid, products, info,
                )

                # Get field_schema
                has_zone_config = False
                gap_report = {"gaps": [], "summary": {"total": 0, "resolved": 0, "warnings": 0, "blocking": 0}}

                if template:
                    ts = template.template_styles or {}
                    if "zones" in ts:
                        has_zone_config = True
                        field_schema = ts.get("field_schema") or schema_from_zone_config(ts)
                        gap_report = analyze_gaps(field_schema, order_data, sid, field_overrides)

                gen_status = existing_entry.get("status", "pending")
                blocking = gap_report["summary"]["blocking"]
                warnings = gap_report["summary"]["warnings"]

                if gen_status == "completed":
                    status = "completed"
                elif blocking > 0:
                    status = "needs_input"
                    total_needs_input += 1
                else:
                    status = "ready"
                    total_ready += 1

                supplier_line = {
                    "supplier_id": sid,
                    "supplier_name": info.get("name", ""),
                    "product_count": len(products),
                    "status": status,
                    "gen_status": gen_status,
                    "template": template.template_name if template else None,
                    "template_method": method,
                    "has_zone_config": has_zone_config,
                    "blocking_gaps": blocking,
                    "warning_gaps": warnings,
                    "resolved_fields": gap_report["summary"].get("resolved", 0),
                    "total_fields": gap_report["summary"].get("total", 0),
                }

                # Include gap details if there are any
                if gap_report["gaps"]:
                    supplier_line["gaps"] = [
                        {"key": g["key"], "label": g["label"], "cell": g["cell"],
                         "severity": g["severity"], "category": g["category"]}
                        for g in gap_report["gaps"]
                    ]

                results.append(supplier_line)

            summary = {
                "order_id": order_id,
                "supplier_count": len(products_by_supplier),
                "ready": total_ready,
                "needs_input": total_needs_input,
                "total_products": sum(len(v) for v in products_by_supplier.values()),
            }

            return json.dumps({"summary": summary, "suppliers": results}, ensure_ascii=False)

        except Exception as e:
            logger.error("check_inquiry_readiness failed: %s", e, exc_info=True)
            return f"Error: {type(e).__name__}: {e}"

    @registry.tool(
        description=(
            "补充供应商询价单的缺失字段值。先用 check_inquiry_readiness 确认哪些字段缺失，"
            "然后用此工具传入 JSON 格式的字段值。保存后下次生成询价单时自动使用。"
        ),
        parameters={
            "order_id": {
                "type": "NUMBER",
                "description": "订单 ID",
            },
            "supplier_id": {
                "type": "NUMBER",
                "description": "供应商 ID",
            },
            "field_values": {
                "type": "STRING",
                "description": (
                    'JSON 格式的字段映射，如: {"H8": "2026/04/01", "B5": "供应商名称"}'
                ),
            },
        },
        group="business",
    )
    def fill_inquiry_gaps(order_id: int, supplier_id: int, field_values: str = "{}") -> str:
        if not ctx or not ctx.db:
            return "Error: no database session available"

        try:
            from models import Order
            from sqlalchemy.orm.attributes import flag_modified

            db = ctx.db
            order = db.query(Order).filter(Order.id == int(order_id)).first()
            if not order:
                return f"Error: 订单 {order_id} 不存在"

            ctx.register_order(int(order_id))

            # Parse field values
            try:
                overrides = json.loads(field_values) if isinstance(field_values, str) else field_values
            except json.JSONDecodeError:
                return "Error: field_values 不是有效的 JSON"

            if not isinstance(overrides, dict):
                return "Error: field_values 必须是 JSON 对象 (cell -> value)"

            # Merge into existing inquiry_data
            sid_str = str(int(supplier_id))
            inquiry_data = order.inquiry_data or {}
            suppliers = inquiry_data.setdefault("suppliers", {})
            supplier_entry = suppliers.setdefault(sid_str, {})
            existing_overrides = supplier_entry.get("field_overrides", {})
            existing_overrides.update(overrides)
            supplier_entry["field_overrides"] = existing_overrides

            order.inquiry_data = inquiry_data
            flag_modified(order, "inquiry_data")
            db.commit()

            return json.dumps({
                "status": "saved",
                "supplier_id": int(supplier_id),
                "fields_updated": len(overrides),
                "total_overrides": len(existing_overrides),
            }, ensure_ascii=False)

        except Exception as e:
            logger.error("fill_inquiry_gaps failed: %s", e, exc_info=True)
            return f"Error: {type(e).__name__}: {e}"

    @registry.tool(
        description=(
            "Generate inquiry Excel files for an order. "
            "Can generate for all suppliers (default) or a single supplier. "
            "This runs the full inquiry orchestrator: template resolution, "
            "data filling, format enforcement, and file upload. "
            "生成完成后，Excel 文件会同时保存到工作目录，你可以用 bash + openpyxl 进一步修改格式。\n"
            "单价和合计列默认保留2位小数（0.00）。如果用户要求不同的小数位数，生成后用 bash 修改即可。\n"
            "返回生成结果摘要，包含文件名和产品数。"
        ),
        parameters={
            "order_id": {
                "type": "NUMBER",
                "description": "订单 ID",
            },
            "supplier_id": {
                "type": "NUMBER",
                "description": "供应商 ID。留空或传 0 则为所有供应商生成。",
                "required": False,
            },
            "template_id": {
                "type": "NUMBER",
                "description": "模板 ID（查 v2_supplier_templates 表获取）。留空则自动匹配。",
                "required": False,
            },
        },
        group="business",
    )
    def generate_inquiries(order_id: int, supplier_id: int = 0, template_id: int = 0) -> str:
        if not ctx or not ctx.db:
            return "Error: no database session available"

        try:
            from models import Order

            db = ctx.db
            order = db.query(Order).filter(Order.id == int(order_id)).first()
            if not order:
                return f"Error: 订单 {order_id} 不存在"
            if not order.match_results:
                return f"Error: 订单 {order_id} 还没有匹配结果"

            ctx.register_order(int(order_id))

            stream_key = ctx.pipeline_session_id or ""

            if supplier_id and int(supplier_id) > 0:
                # Single supplier generation
                from services.inquiry_agent import run_inquiry_single_supplier
                result = run_inquiry_single_supplier(
                    order=order,
                    db=db,
                    supplier_id=int(supplier_id),
                    stream_key=stream_key,
                    template_id=int(template_id) if template_id else None,
                )
            else:
                # All suppliers
                from services.inquiry_agent import run_inquiry_orchestrator
                result = run_inquiry_orchestrator(
                    order=order,
                    db=db,
                    stream_key=stream_key,
                )

            # Build summary
            # Handle both formats:
            #   - Single supplier: result is a flat dict with "supplier_name", "file", etc.
            #   - All suppliers (orchestrator): result has "suppliers" nested dict
            if "suppliers" in result:
                suppliers = result["suppliers"]
            elif "supplier_name" in result:
                # Single supplier result — wrap into suppliers dict format
                suppliers = {str(supplier_id): result}
            else:
                suppliers = {}

            lines = [f"询价单生成完成 — 订单 #{order_id}"]
            success = 0
            fail = 0
            first_filename = None
            for sid, info in suppliers.items():
                status = info.get("status", "unknown")
                name = info.get("supplier_name", f"供应商 #{sid}")
                if status in ("completed", "done"):
                    success += 1
                    f_info = info.get("file", {})
                    fname = f_info.get("filename", "") if isinstance(f_info, dict) else ""
                    lines.append(f"  ✓ {name}: {fname}")
                    if fname and not first_filename:
                        first_filename = fname
                elif status == "error":
                    fail += 1
                    err = info.get("error", "未知错误")
                    lines.append(f"  ✗ {name}: {err}")

            lines.append(f"\n成功: {success}, 失败: {fail}")
            elapsed = result.get("total_elapsed_seconds") or result.get("elapsed_seconds")
            if elapsed:
                lines.append(f"耗时: {elapsed:.1f}s")

            # Tell agent where the file is and how to modify it
            if first_filename and ctx and ctx.workspace_dir:
                import os
                ws_path = os.path.join(ctx.workspace_dir, first_filename)
                if os.path.isfile(ws_path):
                    lines.append(f"\n文件已保存到工作目录: {first_filename}")
                    lines.append("如需修改（如改税率、改格式），搜索 modify_excel 工具直接修改，无需重新查询数据。")

                    # Anthropic "structured note-taking": persist to DB (Cloud Run safe)
                    try:
                        key_cells = {}
                        try:
                            from models import SupplierTemplate
                            tmpl = db.query(SupplierTemplate).filter(
                                SupplierTemplate.id == int(template_id) if template_id else False
                            ).first()
                            if tmpl and tmpl.template_styles:
                                styles = tmpl.template_styles
                                for sf in styles.get("summary_formulas", []):
                                    if sf.get("label", "").lower() == "tax":
                                        key_cells["tax_cell"] = sf.get("cell", "")
                                        key_cells["tax_formula"] = sf.get("formula_template", "")
                                if tmpl.field_positions:
                                    fp = tmpl.field_positions
                                    dd = fp.get("delivery_date", {})
                                    if isinstance(dd, dict):
                                        key_cells["delivery_date_cell"] = dd.get("position", "")
                                    elif isinstance(dd, str):
                                        key_cells["delivery_date_cell"] = dd
                        except Exception:
                            pass

                        _save_operation_state(ctx, {
                            "last_generated_file": first_filename,
                            "order_id": int(order_id),
                            "supplier_id": int(supplier_id) if supplier_id else "all",
                            "template_id": int(template_id) if template_id else "auto",
                            "product_count": success,
                            **key_cells,
                            "hint": "用 modify_excel 工具可直接修改此文件",
                        })
                    except Exception:
                        pass

            summary = "\n".join(lines)

            # Emit structured card so frontend auto-opens artifact panel
            if first_filename and ctx and ctx.pipeline_session_id:
                card = json.dumps({
                    "card_type": "generated_file",
                    "filename": first_filename,
                    "session_id": ctx.pipeline_session_id,
                })
                summary += f"\n__STRUCTURED__\n{card}"

            return summary

        except Exception as e:
            logger.error("generate_inquiries failed: %s", e, exc_info=True)
            return f"Error: {type(e).__name__}: {e}"


def _save_operation_state(ctx, state: dict):
    """Save operational state to session.context_data (Cloud Run safe).

    Anthropic "structured note-taking" pattern: persist to DB instead of filesystem.
    """
    db = getattr(ctx, 'db', None)
    session_id = getattr(ctx, 'pipeline_session_id', None)
    if not db or not session_id:
        return
    try:
        from models import AgentSession
        from sqlalchemy.orm.attributes import flag_modified
        session = db.query(AgentSession).filter(AgentSession.id == session_id).first()
        if session:
            ctx_data = session.context_data or {}
            ctx_data["operation_state"] = state
            session.context_data = ctx_data
            flag_modified(session, "context_data")
            db.commit()
    except Exception as e:
        logger.debug("Failed to save operation state: %s", e)
        try:
            db.rollback()
        except Exception:
            pass
