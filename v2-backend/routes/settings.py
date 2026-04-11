import os
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db
from models import (
    User, FieldSchema, FieldDefinition, OrderFormatTemplate, SupplierTemplate,
    Supplier, DeliveryLocation, CompanyConfig,
)
from routes.auth import get_current_user
from security import require_role
from services.file_storage import storage

require_admin = require_role("superadmin", "admin")
from schemas import (
    FieldSchemaCreate, FieldSchemaResponse,
    FieldDefinitionCreate, FieldDefinitionUpdate, FieldDefinitionResponse,
    OrderFormatTemplateCreate, OrderFormatTemplateUpdate, OrderFormatTemplateResponse,
    SupplierTemplateCreate, SupplierTemplateUpdate, SupplierTemplateResponse,
    SupplierInfoUpdate, SupplierInfoResponse,
    DeliveryLocationCreate, DeliveryLocationUpdate, DeliveryLocationResponse,
    CompanyConfigUpdate, CompanyConfigResponse,
)

router = APIRouter(prefix="/settings", tags=["settings"])

# ═══════════════════════════════════════════════════════════════════
# Field Schema CRUD
# ═══════════════════════════════════════════════════════════════════


@router.get("/field-schemas", response_model=list[FieldSchemaResponse])
def list_field_schemas(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    return db.query(FieldSchema).order_by(FieldSchema.id).all()


@router.post("/field-schemas", response_model=FieldSchemaResponse, status_code=201)
def create_field_schema(
    body: FieldSchemaCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    schema = FieldSchema(name=body.name, description=body.description, created_by=current_user.id)
    db.add(schema)
    db.commit()
    db.refresh(schema)
    return schema


@router.get("/field-schemas/{schema_id}", response_model=FieldSchemaResponse)
def get_field_schema(
    schema_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    schema = db.query(FieldSchema).filter(FieldSchema.id == schema_id).first()
    if not schema:
        raise HTTPException(status_code=404, detail="字段模式不存在")
    return schema


@router.put("/field-schemas/{schema_id}", response_model=FieldSchemaResponse)
def update_field_schema(
    schema_id: int,
    body: FieldSchemaCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    schema = db.query(FieldSchema).filter(FieldSchema.id == schema_id).first()
    if not schema:
        raise HTTPException(status_code=404, detail="字段模式不存在")
    schema.name = body.name
    if body.description is not None:
        schema.description = body.description
    db.commit()
    db.refresh(schema)
    return schema


@router.delete("/field-schemas/{schema_id}")
def delete_field_schema(
    schema_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    schema = db.query(FieldSchema).filter(FieldSchema.id == schema_id).first()
    if not schema:
        raise HTTPException(status_code=404, detail="字段模式不存在")
    db.delete(schema)
    db.commit()
    return {"detail": "已删除"}


# ─── Field Definitions ──────────────────────────────────────────


@router.post("/field-schemas/{schema_id}/definitions", response_model=FieldDefinitionResponse, status_code=201)
def add_field_definition(
    schema_id: int,
    body: FieldDefinitionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    schema = db.query(FieldSchema).filter(FieldSchema.id == schema_id).first()
    if not schema:
        raise HTTPException(status_code=404, detail="字段模式不存在")
    defn = FieldDefinition(schema_id=schema_id, **body.model_dump())
    db.add(defn)
    db.commit()
    db.refresh(defn)
    return defn


@router.put("/field-schemas/{schema_id}/definitions/{def_id}", response_model=FieldDefinitionResponse)
def update_field_definition(
    schema_id: int,
    def_id: int,
    body: FieldDefinitionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    defn = (
        db.query(FieldDefinition)
        .filter(FieldDefinition.id == def_id, FieldDefinition.schema_id == schema_id)
        .first()
    )
    if not defn:
        raise HTTPException(status_code=404, detail="字段定义不存在")
    for key, val in body.model_dump(exclude_unset=True).items():
        setattr(defn, key, val)
    db.commit()
    db.refresh(defn)
    return defn


@router.delete("/field-schemas/{schema_id}/definitions/{def_id}")
def delete_field_definition(
    schema_id: int,
    def_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    defn = (
        db.query(FieldDefinition)
        .filter(FieldDefinition.id == def_id, FieldDefinition.schema_id == schema_id)
        .first()
    )
    if not defn:
        raise HTTPException(status_code=404, detail="字段定义不存在")
    if defn.is_core:
        raise HTTPException(status_code=400, detail="核心字段不可删除")
    db.delete(defn)
    db.commit()
    return {"detail": "已删除"}


# ─── Seed Defaults ──────────────────────────────────────────────


CORE_FIELDS = [
    {"field_key": "product_name", "field_label": "品名", "field_type": "string", "is_core": True, "is_required": True, "sort_order": 1, "extraction_hint": "产品名称/品名/商品名"},
    {"field_key": "product_code", "field_label": "商品代码", "field_type": "string", "is_core": True, "is_required": False, "sort_order": 2, "extraction_hint": "商品コード/Item Code"},
    {"field_key": "quantity", "field_label": "数量", "field_type": "number", "is_core": True, "is_required": True, "sort_order": 3, "extraction_hint": "数量/Qty/Quantity"},
    {"field_key": "unit", "field_label": "单位", "field_type": "string", "is_core": True, "is_required": False, "sort_order": 4, "extraction_hint": "单位/Unit (CT/KG/L/PCS)"},
    {"field_key": "unit_price", "field_label": "单价", "field_type": "number", "is_core": True, "is_required": False, "sort_order": 5, "extraction_hint": "单价/Unit Price"},
    {"field_key": "currency", "field_label": "币种", "field_type": "string", "is_core": True, "is_required": False, "sort_order": 6, "extraction_hint": "币种/Currency (USD/JPY/AUD)"},
    {"field_key": "delivery_date", "field_label": "交货日期", "field_type": "date", "is_core": True, "is_required": False, "sort_order": 7, "extraction_hint": "纳品日/Delivery Date"},
    {"field_key": "po_number", "field_label": "PO番号", "field_type": "string", "is_core": True, "is_required": False, "sort_order": 8, "extraction_hint": "PO No/注文番号"},
]


@router.post("/field-schemas/seed-defaults", response_model=FieldSchemaResponse)
def seed_defaults(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    existing = db.query(FieldSchema).filter(FieldSchema.is_default == True).first()
    if existing:
        return existing
    schema = FieldSchema(
        name="默认字段模式",
        description="系统默认的 8 个核心字段",
        is_default=True,
        created_by=current_user.id,
    )
    db.add(schema)
    db.flush()
    for field_data in CORE_FIELDS:
        defn = FieldDefinition(schema_id=schema.id, **field_data)
        db.add(defn)
    db.commit()
    db.refresh(schema)
    return schema


# ═══════════════════════════════════════════════════════════════════
# Order Format Template CRUD
# ═══════════════════════════════════════════════════════════════════


@router.post("/order-templates/infer")
def infer_order_template(
    body: dict,
    current_user: User = Depends(require_admin),
):
    """Use Gemini to infer template name, source_company, and match_keywords from file content."""
    import logging as _log
    logger = _log.getLogger(__name__)

    raw_text = (body.get("raw_text") or "").strip()
    headers = body.get("headers") or []
    file_type = body.get("file_type") or "excel"

    if not raw_text:
        raise HTTPException(status_code=400, detail="raw_text is required")

    prompt = f"""你是采购订单格式分析专家。根据以下订单文件内容，推断：

1. name: 一个简洁的模板名称（中文或英文均可，描述这种订单格式，如"RCCL 标准采购单"、"MSC Purchase Order"）
2. source_company: 发出此订单的公司名称（如 Royal Caribbean、MSC Cruises）。如果无法确定，返回空字符串。
3. match_keywords: 3-5个在同类文档中必然出现的、具有区分度的关键词（大写，如 ["ROYAL CARIBBEAN", "RCI", "PURCHASE ORDER"]）

文件类型: {file_type}
列头: {', '.join(headers) if headers else '无'}
文件内容:
{raw_text[:4000]}"""

    try:
        from google import genai
        from google.genai import types
        from services.agent.config import load_api_key

        client = genai.Client(api_key=load_api_key())
        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "source_company": {"type": "string"},
                        "match_keywords": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["name", "source_company", "match_keywords"],
                },
                thinking_config=types.ThinkingConfig(thinking_budget=1024),
                temperature=0.1,
            ),
        )
        import json
        result = json.loads(response.text)
        return {
            "name": result.get("name", ""),
            "source_company": result.get("source_company", ""),
            "match_keywords": result.get("match_keywords", []),
        }
    except Exception as e:
        logger.warning("Order template inference failed: %s", e)
        raise HTTPException(status_code=500, detail=f"AI 推理失败: {str(e)}")


@router.post("/order-templates/analyze-pdf")
async def analyze_order_template_pdf(
    file: UploadFile = File(...),
    current_user: User = Depends(require_admin),
):
    """Analyze uploaded PDF template -> return document_schema."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "请上传 PDF 文件")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(400, "文件为空")
    if len(file_bytes) > 25 * 1024 * 1024:
        raise HTTPException(400, "文件大小不能超过 25 MB")

    # Save file to Supabase Storage
    safe_name = f"template_{uuid.uuid4().hex[:8]}_{file.filename}"
    storage.upload("templates", safe_name, file_bytes, content_type="application/pdf")

    try:
        import asyncio
        from services.schema_extraction import analyze_template, _infer_field_mapping

        loop = asyncio.get_event_loop()
        schema = await loop.run_in_executor(None, analyze_template, file_bytes)

        # Auto-infer field_mapping
        schema["field_mapping"] = _infer_field_mapping(schema)

        return {
            "document_schema": schema,
            "document_type": schema.get("document_type", "Unknown"),
            "sample_file_url": f"/uploads/{safe_name}",
            "timing": schema.pop("_timing", {}),
        }
    except Exception as e:
        raise HTTPException(500, f"PDF 分析失败: {str(e)}")


@router.get("/order-templates", response_model=list[OrderFormatTemplateResponse])
def list_order_templates(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    return db.query(OrderFormatTemplate).order_by(OrderFormatTemplate.id.desc()).all()


@router.post("/order-templates", response_model=OrderFormatTemplateResponse, status_code=201)
def create_order_template(
    body: OrderFormatTemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    tpl = OrderFormatTemplate(**body.model_dump(), created_by=current_user.id)
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return tpl


@router.get("/order-templates/{tpl_id}", response_model=OrderFormatTemplateResponse)
def get_order_template(
    tpl_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    tpl = db.query(OrderFormatTemplate).filter(OrderFormatTemplate.id == tpl_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="订单格式模板不存在")
    return tpl


@router.put("/order-templates/{tpl_id}", response_model=OrderFormatTemplateResponse)
def update_order_template(
    tpl_id: int,
    body: OrderFormatTemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    tpl = db.query(OrderFormatTemplate).filter(OrderFormatTemplate.id == tpl_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="订单格式模板不存在")
    for key, val in body.model_dump(exclude_unset=True).items():
        setattr(tpl, key, val)
    db.commit()
    db.refresh(tpl)
    return tpl


@router.delete("/order-templates/{tpl_id}")
def delete_order_template(
    tpl_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    tpl = db.query(OrderFormatTemplate).filter(OrderFormatTemplate.id == tpl_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="订单格式模板不存在")
    db.delete(tpl)
    db.commit()
    return {"detail": "已删除"}


# ═══════════════════════════════════════════════════════════════════
# Supplier Template CRUD
# ═══════════════════════════════════════════════════════════════════


@router.get("/supplier-templates", response_model=list[SupplierTemplateResponse])
def list_supplier_templates(
    supplier_id: int | None = None,
    include_legacy: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    from services.inquiry_agent import get_production_templates

    q = db.query(SupplierTemplate)
    if supplier_id is not None:
        q = q.filter(SupplierTemplate.supplier_id == supplier_id)
    templates = q.order_by(SupplierTemplate.id.desc()).all()
    if include_legacy:
        return templates
    return get_production_templates(templates)


@router.post("/supplier-templates", response_model=SupplierTemplateResponse, status_code=201)
def create_supplier_template(
    body: SupplierTemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    tpl = SupplierTemplate(**body.model_dump(), created_by=current_user.id)
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return tpl


@router.get("/supplier-templates/{tpl_id}", response_model=SupplierTemplateResponse)
def get_supplier_template(
    tpl_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    tpl = db.query(SupplierTemplate).filter(SupplierTemplate.id == tpl_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="供应商模板不存在")
    return tpl


@router.put("/supplier-templates/{tpl_id}", response_model=SupplierTemplateResponse)
def update_supplier_template(
    tpl_id: int,
    body: SupplierTemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    tpl = db.query(SupplierTemplate).filter(SupplierTemplate.id == tpl_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="供应商模板不存在")
    for key, val in body.model_dump(exclude_unset=True).items():
        setattr(tpl, key, val)
    db.commit()
    db.refresh(tpl)
    return tpl


@router.delete("/supplier-templates/{tpl_id}")
def delete_supplier_template(
    tpl_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    tpl = db.query(SupplierTemplate).filter(SupplierTemplate.id == tpl_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="供应商模板不存在")

    # Clean up template file from storage
    if tpl.template_file_url:
        storage.delete(tpl.template_file_url)

    db.delete(tpl)
    db.commit()
    return {"detail": "已删除"}


@router.post("/supplier-templates/{tpl_id}/upload-file", response_model=SupplierTemplateResponse)
async def upload_supplier_template_file(
    tpl_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Upload (or replace) the Excel template file for a supplier template to Supabase Storage."""
    tpl = db.query(SupplierTemplate).filter(SupplierTemplate.id == tpl_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="供应商模板不存在")

    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="请上传 .xlsx 文件")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(file_bytes) > 25 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件大小不能超过 25 MB")

    # Delete old file if exists
    if tpl.template_file_url:
        storage.delete(tpl.template_file_url)

    # Upload to storage
    safe_name = f"template_{uuid.uuid4().hex[:8]}_{file.filename}"
    file_url = storage.upload(
        "templates", safe_name, file_bytes,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    tpl.template_file_url = file_url
    db.commit()
    db.refresh(tpl)
    return tpl


@router.post("/supplier-templates/analyze")
async def analyze_supplier_template(
    file: UploadFile = File(...),
    order_template_id: int | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """AI-analyze an uploaded Excel template to discover field positions and product table layout.

    If order_template_id is provided, uses enhanced analysis with order context for targeted matching.
    """
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="请上传 .xlsx 文件")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="文件为空")

    # Save the uploaded template file to Supabase Storage
    safe_name = f"template_{uuid.uuid4().hex[:8]}_{file.filename}"
    file_url = storage.upload(
        "templates", safe_name, file_bytes,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    order_template_name = None

    try:
        import asyncio
        from services.template_analysis_agent import run_template_analysis_agent

        order_context = None
        if order_template_id:
            order_tpl = db.query(OrderFormatTemplate).filter(
                OrderFormatTemplate.id == order_template_id
            ).first()
            if not order_tpl:
                raise HTTPException(status_code=404, detail="订单格式模板不存在")

            order_template_name = order_tpl.name
            order_context = _build_order_context(order_tpl, db)

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            run_template_analysis_agent,
            file_bytes,
            order_context,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 分析失败: {str(e)}")

    # Extract styles (code-based, not AI) and merge with semantic analysis
    template_styles = None
    try:
        from services.template_style_extractor import extract_template_styles, merge_semantic_and_styles
        styles = extract_template_styles(file_bytes)
        template_styles = merge_semantic_and_styles(
            result.get("cell_map", {}), styles, result.get("product_table_config"),
        )
    except Exception as style_err:
        import logging as _log
        _log.getLogger(__name__).warning("Style extraction failed: %s", style_err)

    # Build zone config for deterministic template engine
    zone_config = None
    try:
        from services.zone_config_builder import build_zone_config
        from services.template_contract import build_template_contract
        ptc = result.get("product_table_config", {})
        fp = result.get("field_positions", {})
        if ptc.get("start_row") and (fp or ptc.get("columns")):
            zone_config = build_zone_config(
                file_bytes=file_bytes,
                field_positions=fp,
                product_table_config=ptc,
                cell_map=result.get("cell_map"),
            )
            # Merge zone_config into template_styles (engine reads from template_styles)
            if template_styles is None:
                template_styles = {}
            template_styles.update(zone_config)
            template_styles["template_contract"] = build_template_contract(
                file_bytes=file_bytes,
                zone_config=zone_config,
            )
    except Exception as zc_err:
        import logging as _log
        _log.getLogger(__name__).warning("Zone config build failed: %s", zc_err)

    # Generate HTML preview (non-critical — failure does not block analysis)
    template_html = None
    try:
        from services.template_analyzer import generate_template_html
        template_html = generate_template_html(file_bytes)
    except Exception as html_err:
        import logging as _log
        _log.getLogger(__name__).warning("HTML preview generation failed: %s", html_err)

    response = {
        "field_positions": result.get("field_positions", {}),
        "product_table_config": result.get("product_table_config", {}),
        "cell_map": result.get("cell_map", {}),
        "template_styles": template_styles,
        "notes": result.get("notes", ""),
        "file_url": file_url,
        "template_html": template_html,
    }
    if order_template_id:
        response["field_mapping_preview"] = result.get("field_mapping_preview", [])
        response["order_template_name"] = order_template_name
    return response


def _build_order_context(order_tpl: OrderFormatTemplate, db: Session) -> dict:
    """Build order_context dict from an OrderFormatTemplate for enhanced AI analysis."""
    header_fields: list[dict] = []

    # 1. extracted_fields → header fields
    if order_tpl.extracted_fields:
        for ef in order_tpl.extracted_fields:
            if isinstance(ef, dict) and ef.get("key"):
                header_fields.append({"key": ef["key"], "label": ef.get("label", ef["key"])})

    # 2. Fallback: field_schema_id → FieldDefinition
    if not header_fields and order_tpl.field_schema_id:
        definitions = (
            db.query(FieldDefinition)
            .filter(FieldDefinition.schema_id == order_tpl.field_schema_id)
            .order_by(FieldDefinition.sort_order)
            .all()
        )
        for d in definitions:
            header_fields.append({"key": d.field_key, "label": d.field_label})

    # 3. column_mapping → product fields (deduplicate header keys)
    product_fields: list[dict] = []
    header_keys = {f["key"] for f in header_fields}
    if order_tpl.column_mapping:
        for _col, field_key in order_tpl.column_mapping.items():
            if field_key and field_key not in header_keys:
                product_fields.append({"key": field_key, "label": field_key})

    return {
        "header_fields": header_fields,
        "product_fields": product_fields,
        "source_company": order_tpl.source_company,
    }


# ═══════════════════════════════════════════════════════════════════
# Countries (read-only, from shared DB)
# ═══════════════════════════════════════════════════════════════════

@router.get("/countries")
def list_countries(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all countries from the shared countries table."""
    rows = db.execute(text("SELECT id, name, code FROM countries ORDER BY name")).fetchall()
    return [{"id": r[0], "name": r[1], "code": r[2]} for r in rows]


# ═══════════════════════════════════════════════════════════════════
# Supplier Info (extended fields for inquiry templates)
# ═══════════════════════════════════════════════════════════════════


@router.get("/suppliers", response_model=list[SupplierInfoResponse])
def list_suppliers_info(
    search: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    q = db.query(Supplier).filter(Supplier.status == True)
    if search:
        q = q.filter(Supplier.name.ilike(f"%{search}%"))
    return q.order_by(Supplier.name).all()


@router.patch("/suppliers/{supplier_id}", response_model=SupplierInfoResponse)
def update_supplier_info(
    supplier_id: int,
    body: SupplierInfoUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="供应商不存在")
    for key, val in body.model_dump(exclude_unset=True).items():
        setattr(supplier, key, val)
    db.commit()
    db.refresh(supplier)
    return supplier


# ═══════════════════════════════════════════════════════════════════
# Delivery Locations (仓库/配送点)
# ═══════════════════════════════════════════════════════════════════


@router.get("/delivery-locations", response_model=list[DeliveryLocationResponse])
def list_delivery_locations(
    port_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    q = db.query(DeliveryLocation)
    if port_id is not None:
        q = q.filter(DeliveryLocation.port_id == port_id)
    rows = q.order_by(DeliveryLocation.id).all()
    # Attach port_name
    result = []
    for loc in rows:
        data = DeliveryLocationResponse.model_validate(loc)
        if loc.port_id:
            port_row = db.execute(
                text("SELECT name FROM ports WHERE id = :pid"), {"pid": loc.port_id}
            ).fetchone()
            if port_row:
                data.port_name = port_row[0]
        result.append(data)
    return result


@router.post("/delivery-locations", response_model=DeliveryLocationResponse, status_code=201)
def create_delivery_location(
    body: DeliveryLocationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    loc = DeliveryLocation(**body.model_dump(), created_by=current_user.id)
    db.add(loc)
    db.commit()
    db.refresh(loc)
    return loc


@router.put("/delivery-locations/{loc_id}", response_model=DeliveryLocationResponse)
def update_delivery_location(
    loc_id: int,
    body: DeliveryLocationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    loc = db.query(DeliveryLocation).filter(DeliveryLocation.id == loc_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="配送点不存在")
    for key, val in body.model_dump(exclude_unset=True).items():
        setattr(loc, key, val)
    db.commit()
    db.refresh(loc)
    return loc


@router.delete("/delivery-locations/{loc_id}")
def delete_delivery_location(
    loc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    loc = db.query(DeliveryLocation).filter(DeliveryLocation.id == loc_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="配送点不存在")
    db.delete(loc)
    db.commit()
    return {"detail": "已删除"}


# ═══════════════════════════════════════════════════════════════════
# Company Config (公司配置)
# ═══════════════════════════════════════════════════════════════════


@router.get("/company-config", response_model=list[CompanyConfigResponse])
def get_company_config(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    return db.query(CompanyConfig).order_by(CompanyConfig.sort_order).all()


@router.put("/company-config")
def update_company_config(
    body: CompanyConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    for item in body.items:
        row = db.query(CompanyConfig).filter(CompanyConfig.key == item.key).first()
        if row:
            row.value = item.value
            if item.label is not None:
                row.label = item.label
            row.updated_by = current_user.id
        else:
            row = CompanyConfig(
                key=item.key,
                value=item.value,
                label=item.label,
                updated_by=current_user.id,
            )
            db.add(row)
    db.commit()
    return {"detail": "已更新"}
