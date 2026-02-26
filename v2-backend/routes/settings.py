import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db
from models import User, FieldSchema, FieldDefinition, OrderFormatTemplate, SupplierTemplate
from routes.auth import get_current_user
from security import require_role

require_admin = require_role("superadmin", "admin")
from schemas import (
    FieldSchemaCreate, FieldSchemaResponse,
    FieldDefinitionCreate, FieldDefinitionUpdate, FieldDefinitionResponse,
    OrderFormatTemplateCreate, OrderFormatTemplateUpdate, OrderFormatTemplateResponse,
    SupplierTemplateCreate, SupplierTemplateUpdate, SupplierTemplateResponse,
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
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    q = db.query(SupplierTemplate)
    if supplier_id is not None:
        q = q.filter(SupplierTemplate.supplier_id == supplier_id)
    return q.order_by(SupplierTemplate.id.desc()).all()


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

    # Clean up template file
    if tpl.template_file_url:
        upload_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
        fpath = os.path.join(upload_dir, os.path.basename(tpl.template_file_url))
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
            except OSError:
                pass

    db.delete(tpl)
    db.commit()
    return {"detail": "已删除"}


@router.post("/supplier-templates/analyze")
async def analyze_supplier_template(
    file: UploadFile = File(...),
    current_user: User = Depends(require_admin),
):
    """AI-analyze an uploaded Excel template to discover field positions and product table layout."""
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="请上传 .xlsx 文件")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="文件为空")

    # Save the uploaded template file
    upload_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    safe_name = f"template_{uuid.uuid4().hex[:8]}_{file.filename}"
    filepath = os.path.join(upload_dir, safe_name)
    with open(filepath, "wb") as f:
        f.write(file_bytes)
    file_url = f"/uploads/{safe_name}"

    try:
        from services.template_analyzer import analyze_excel_template
        result = analyze_excel_template(file_bytes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 分析失败: {str(e)}")

    return {
        "field_positions": result.get("field_positions", {}),
        "product_table_config": result.get("product_table_config", {}),
        "notes": result.get("notes", ""),
        "file_url": file_url,
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
