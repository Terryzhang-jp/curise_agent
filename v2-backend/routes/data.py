from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, DataError
from sqlalchemy.orm import Session
from datetime import datetime, date
import logging

logger = logging.getLogger(__name__)

from core.database import get_db
from core.models import User, Country, Port, Category, Supplier, SupplierCategory, Product, ExchangeRate
from core.security import require_role
from core.schemas import (
    CountryCreate, CountryUpdate, CountryResponse,
    CategoryCreate, CategoryUpdate, CategoryResponse,
    PortCreate, PortUpdate, PortResponse,
    SupplierCreate, SupplierUpdate, SupplierResponse,
    ProductCreate, ProductUpdate, ProductResponse,
    ExchangeRateCreate, ExchangeRateUpdate, ExchangeRateResponse,
)

require_data_reader = require_role("superadmin", "admin", "employee")
require_data_writer = require_role("superadmin", "admin")


def _parse_date(value: str | None) -> datetime | None:
    """Parse date string to datetime, return None if empty/invalid."""
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise HTTPException(400, f"日期格式无效: '{value}'，请使用 YYYY-MM-DD")

router = APIRouter(prefix="/data", tags=["data"])


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════


def _country_name(db: Session, country_id: int | None) -> str | None:
    if not country_id:
        return None
    row = db.execute(text("SELECT name FROM countries WHERE id = :id"), {"id": country_id}).first()
    return row[0] if row else None


def _port_to_dict(r, country_name: str | None) -> dict:
    return {
        "id": r.id, "name": r.name, "code": r.code,
        "country_id": r.country_id, "country_name": country_name,
        "location": r.location, "status": r.status,
        "created_at": r.created_at, "updated_at": r.updated_at,
    }


def _supplier_to_dict(supplier: Supplier, db: Session) -> dict:
    country_name = _country_name(db, supplier.country_id)
    cat_rows = db.execute(
        text("""
            SELECT sc.category_id, c.name
            FROM supplier_categories sc
            JOIN categories c ON sc.category_id = c.id
            WHERE sc.supplier_id = :sid
            ORDER BY c.name
        """),
        {"sid": supplier.id},
    ).fetchall()
    return {
        "id": supplier.id, "name": supplier.name,
        "country_id": supplier.country_id, "country_name": country_name,
        "contact": supplier.contact, "email": supplier.email, "phone": supplier.phone,
        "categories": [r[1] for r in cat_rows],
        "category_ids": [r[0] for r in cat_rows],
        "status": supplier.status,
        "created_at": supplier.created_at, "updated_at": supplier.updated_at,
    }


def _product_to_dict(r, db: Session) -> dict:
    row = db.execute(
        text("""
            SELECT c.name, cat.name, s.name, pt.name
            FROM (SELECT 1) dummy
            LEFT JOIN countries c ON c.id = :cid
            LEFT JOIN categories cat ON cat.id = :catid
            LEFT JOIN suppliers s ON s.id = :sid
            LEFT JOIN ports pt ON pt.id = :pid
        """),
        {"cid": r.country_id, "catid": r.category_id, "sid": r.supplier_id, "pid": r.port_id},
    ).first()
    return {
        "id": r.id, "product_name_en": r.product_name_en, "product_name_jp": r.product_name_jp,
        "code": r.code, "country_id": r.country_id, "category_id": r.category_id,
        "supplier_id": r.supplier_id, "port_id": r.port_id,
        "country_name": row[0] if row else None,
        "category_name": row[1] if row else None,
        "supplier_name": row[2] if row else None,
        "port_name": row[3] if row else None,
        "unit": r.unit, "price": float(r.price) if r.price is not None else None,
        "unit_size": r.unit_size, "pack_size": r.pack_size,
        "country_of_origin": r.country_of_origin, "brand": r.brand, "currency": r.currency,
        "effective_from": str(r.effective_from) if r.effective_from else None,
        "effective_to": str(r.effective_to) if r.effective_to else None,
        "status": r.status,
    }


def _check_fk_references(db: Session, table: str, column: str, value: int, entity_name: str):
    """Check if any rows in `table` reference `column` = value. Raise 409 if so."""
    cnt = db.execute(
        text(f"SELECT COUNT(*) FROM {table} WHERE {column} = :val"),
        {"val": value},
    ).scalar()
    if cnt and cnt > 0:
        raise HTTPException(409, f"无法删除：有 {cnt} 条{entity_name}引用此记录")


def _check_unique(db: Session, model, field_name: str, value, exclude_id: int | None = None):
    """Check unique constraint on a field. Raise 409 on conflict."""
    if value is None:
        return
    q = db.query(model).filter(getattr(model, field_name) == value)
    if exclude_id is not None:
        q = q.filter(model.id != exclude_id)
    if q.first():
        raise HTTPException(409, f"{field_name} '{value}' 已存在")


# ═══════════════════════════════════════════════════════════════════
# Countries
# ═══════════════════════════════════════════════════════════════════


@router.get("/countries")
def list_countries(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_data_reader),
):
    rows = db.execute(
        text("SELECT id, name, code, status FROM countries ORDER BY name")
    ).fetchall()
    return [
        {"id": r[0], "name": r[1], "code": r[2], "status": r[3]}
        for r in rows
    ]


@router.post("/countries", status_code=201)
def create_country(
    body: CountryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_data_writer),
):
    if body.code:
        body.code = body.code.upper()
        _check_unique(db, Country, "code", body.code)
    obj = Country(name=body.name, code=body.code, status=body.status)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return {"id": obj.id, "name": obj.name, "code": obj.code, "status": obj.status}


@router.patch("/countries/{country_id}")
def update_country(
    country_id: int,
    body: CountryUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_data_writer),
):
    obj = db.query(Country).filter(Country.id == country_id).first()
    if not obj:
        raise HTTPException(404, "国家不存在")
    data = body.model_dump(exclude_unset=True)
    if "code" in data and data["code"]:
        data["code"] = data["code"].upper()
        _check_unique(db, Country, "code", data["code"], exclude_id=country_id)
    for k, v in data.items():
        setattr(obj, k, v)
    obj.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(obj)
    return {"id": obj.id, "name": obj.name, "code": obj.code, "status": obj.status}


@router.delete("/countries/{country_id}", status_code=204)
def delete_country(
    country_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_data_writer),
):
    obj = db.query(Country).filter(Country.id == country_id).first()
    if not obj:
        raise HTTPException(404, "国家不存在")
    _check_fk_references(db, "ports", "country_id", country_id, "港口")
    _check_fk_references(db, "suppliers", "country_id", country_id, "供应商")
    _check_fk_references(db, "products", "country_id", country_id, "产品")
    db.delete(obj)
    db.commit()


# ═══════════════════════════════════════════════════════════════════
# Categories
# ═══════════════════════════════════════════════════════════════════


@router.get("/categories")
def list_categories(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_data_reader),
):
    rows = db.execute(
        text("SELECT id, name, code, description, status FROM categories ORDER BY name")
    ).fetchall()
    return [
        {
            "id": r[0], "name": r[1], "code": r[2],
            "description": r[3], "status": r[4],
        }
        for r in rows
    ]


@router.post("/categories", status_code=201)
def create_category(
    body: CategoryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_data_writer),
):
    if body.code:
        _check_unique(db, Category, "code", body.code)
    obj = Category(name=body.name, code=body.code, description=body.description, status=body.status)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return {"id": obj.id, "name": obj.name, "code": obj.code, "description": obj.description, "status": obj.status}


@router.patch("/categories/{category_id}")
def update_category(
    category_id: int,
    body: CategoryUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_data_writer),
):
    obj = db.query(Category).filter(Category.id == category_id).first()
    if not obj:
        raise HTTPException(404, "类别不存在")
    data = body.model_dump(exclude_unset=True)
    if "code" in data and data["code"]:
        _check_unique(db, Category, "code", data["code"], exclude_id=category_id)
    for k, v in data.items():
        setattr(obj, k, v)
    obj.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(obj)
    return {"id": obj.id, "name": obj.name, "code": obj.code, "description": obj.description, "status": obj.status}


@router.delete("/categories/{category_id}", status_code=204)
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_data_writer),
):
    obj = db.query(Category).filter(Category.id == category_id).first()
    if not obj:
        raise HTTPException(404, "类别不存在")
    _check_fk_references(db, "products", "category_id", category_id, "产品")
    _check_fk_references(db, "supplier_categories", "category_id", category_id, "供应商类别关联")
    db.delete(obj)
    db.commit()


# ═══════════════════════════════════════════════════════════════════
# Ports
# ═══════════════════════════════════════════════════════════════════


@router.get("/ports")
def list_ports(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_data_reader),
):
    rows = db.execute(
        text("""
            SELECT p.id, p.name, p.code, p.country_id, p.location, p.status,
                   c.name AS country_name
            FROM ports p
            LEFT JOIN countries c ON p.country_id = c.id
            ORDER BY p.name
        """)
    ).fetchall()
    return [
        {
            "id": r[0], "name": r[1], "code": r[2],
            "country_id": r[3], "location": r[4], "status": r[5],
            "country_name": r[6],
        }
        for r in rows
    ]


@router.post("/ports", status_code=201)
def create_port(
    body: PortCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_data_writer),
):
    if body.code:
        _check_unique(db, Port, "code", body.code)
    if body.country_id:
        if not db.query(Country).filter(Country.id == body.country_id).first():
            raise HTTPException(400, "国家不存在")
    obj = Port(name=body.name, code=body.code, country_id=body.country_id, location=body.location, status=body.status)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return _port_to_dict(obj, _country_name(db, obj.country_id))


@router.patch("/ports/{port_id}")
def update_port(
    port_id: int,
    body: PortUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_data_writer),
):
    obj = db.query(Port).filter(Port.id == port_id).first()
    if not obj:
        raise HTTPException(404, "港口不存在")
    data = body.model_dump(exclude_unset=True)
    if "code" in data and data["code"]:
        _check_unique(db, Port, "code", data["code"], exclude_id=port_id)
    if "country_id" in data and data["country_id"]:
        if not db.query(Country).filter(Country.id == data["country_id"]).first():
            raise HTTPException(400, "国家不存在")
    for k, v in data.items():
        setattr(obj, k, v)
    obj.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(obj)
    return _port_to_dict(obj, _country_name(db, obj.country_id))


@router.delete("/ports/{port_id}", status_code=204)
def delete_port(
    port_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_data_writer),
):
    obj = db.query(Port).filter(Port.id == port_id).first()
    if not obj:
        raise HTTPException(404, "港口不存在")
    _check_fk_references(db, "products", "port_id", port_id, "产品")
    db.delete(obj)
    db.commit()


# ═══════════════════════════════════════════════════════════════════
# Suppliers
# ═══════════════════════════════════════════════════════════════════


@router.get("/suppliers")
def list_suppliers(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_data_reader),
):
    rows = db.execute(
        text("""
            SELECT s.id, s.name, s.country_id, s.contact, s.email, s.phone, s.status,
                   c.name AS country_name
            FROM suppliers s
            LEFT JOIN countries c ON s.country_id = c.id
            ORDER BY s.name
        """)
    ).fetchall()

    # Build supplier category map (names + IDs)
    cat_rows = db.execute(
        text("""
            SELECT sc.supplier_id, cat.name, sc.category_id
            FROM supplier_categories sc
            JOIN categories cat ON sc.category_id = cat.id
            ORDER BY cat.name
        """)
    ).fetchall()

    cat_name_map: dict[int, list[str]] = {}
    cat_id_map: dict[int, list[int]] = {}
    for cr in cat_rows:
        cat_name_map.setdefault(cr[0], []).append(cr[1])
        cat_id_map.setdefault(cr[0], []).append(cr[2])

    return [
        {
            "id": r[0], "name": r[1], "country_id": r[2],
            "contact": r[3], "email": r[4], "phone": r[5], "status": r[6],
            "country_name": r[7],
            "categories": cat_name_map.get(r[0], []),
            "category_ids": cat_id_map.get(r[0], []),
        }
        for r in rows
    ]


def _sync_supplier_categories(db: Session, supplier_id: int, category_ids: list[int]):
    """Replace supplier_categories for a supplier."""
    db.query(SupplierCategory).filter(SupplierCategory.supplier_id == supplier_id).delete()
    for cid in category_ids:
        if db.query(Category).filter(Category.id == cid).first():
            db.add(SupplierCategory(supplier_id=supplier_id, category_id=cid))


@router.post("/suppliers", status_code=201)
def create_supplier(
    body: SupplierCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_data_writer),
):
    if body.country_id:
        if not db.query(Country).filter(Country.id == body.country_id).first():
            raise HTTPException(400, "国家不存在")
    obj = Supplier(
        name=body.name, country_id=body.country_id,
        contact=body.contact, email=body.email, phone=body.phone, status=body.status,
    )
    db.add(obj)
    db.flush()
    if body.category_ids:
        _sync_supplier_categories(db, obj.id, body.category_ids)
    db.commit()
    db.refresh(obj)
    return _supplier_to_dict(obj, db)


@router.patch("/suppliers/{supplier_id}")
def update_supplier(
    supplier_id: int,
    body: SupplierUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_data_writer),
):
    obj = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not obj:
        raise HTTPException(404, "供应商不存在")
    data = body.model_dump(exclude_unset=True)
    category_ids = data.pop("category_ids", None)
    if "country_id" in data and data["country_id"]:
        if not db.query(Country).filter(Country.id == data["country_id"]).first():
            raise HTTPException(400, "国家不存在")
    for k, v in data.items():
        setattr(obj, k, v)
    obj.updated_at = datetime.utcnow()
    if category_ids is not None:
        _sync_supplier_categories(db, supplier_id, category_ids)
    db.commit()
    db.refresh(obj)
    return _supplier_to_dict(obj, db)


@router.delete("/suppliers/{supplier_id}", status_code=204)
def delete_supplier(
    supplier_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_data_writer),
):
    obj = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not obj:
        raise HTTPException(404, "供应商不存在")
    _check_fk_references(db, "products", "supplier_id", supplier_id, "产品")
    # Also delete supplier_categories associations
    db.query(SupplierCategory).filter(SupplierCategory.supplier_id == supplier_id).delete()
    db.delete(obj)
    db.commit()


# ═══════════════════════════════════════════════════════════════════
# Products
# ═══════════════════════════════════════════════════════════════════


@router.get("/products")
def list_products(
    search: str | None = Query(None),
    country_id: int | None = Query(None),
    category_id: int | None = Query(None),
    supplier_id: int | None = Query(None),
    limit: int = Query(20, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_data_reader),
):
    where = " WHERE 1=1"
    params: dict = {}

    if search:
        where += " AND (p.product_name_en ILIKE :search OR p.code ILIKE :search)"
        params["search"] = f"%{search}%"
    if country_id is not None:
        where += " AND p.country_id = :country_id"
        params["country_id"] = country_id
    if category_id is not None:
        where += " AND p.category_id = :category_id"
        params["category_id"] = category_id
    if supplier_id is not None:
        where += " AND p.supplier_id = :supplier_id"
        params["supplier_id"] = supplier_id

    from_clause = """
        FROM products p
        LEFT JOIN countries c ON p.country_id = c.id
        LEFT JOIN categories cat ON p.category_id = cat.id
        LEFT JOIN suppliers s ON p.supplier_id = s.id
        LEFT JOIN ports pt ON p.port_id = pt.id
    """

    # Count total matching rows
    total = db.execute(text(f"SELECT COUNT(*) {from_clause} {where}"), params).scalar()

    # Fetch page
    sql = f"""
        SELECT p.id, p.product_name_en, p.product_name_jp, p.code,
               p.unit, p.price, p.unit_size, p.pack_size,
               p.country_of_origin, p.brand, p.currency, p.status,
               c.name AS country_name, cat.name AS category_name,
               s.name AS supplier_name, pt.name AS port_name,
               p.country_id, p.category_id, p.supplier_id, p.port_id,
               p.effective_from, p.effective_to
        {from_clause} {where}
        ORDER BY p.id DESC LIMIT :limit OFFSET :offset
    """
    params["limit"] = limit
    params["offset"] = offset

    rows = db.execute(text(sql), params).fetchall()
    items = [
        {
            "id": r[0],
            "product_name_en": r[1],
            "product_name_jp": r[2],
            "code": r[3],
            "unit": r[4],
            "price": float(r[5]) if r[5] is not None else None,
            "unit_size": r[6],
            "pack_size": r[7],
            "country_of_origin": r[8],
            "brand": r[9],
            "currency": r[10],
            "status": r[11],
            "country_name": r[12],
            "category_name": r[13],
            "supplier_name": r[14],
            "port_name": r[15],
            "country_id": r[16],
            "category_id": r[17],
            "supplier_id": r[18],
            "port_id": r[19],
            "effective_from": str(r[20]) if r[20] else None,
            "effective_to": str(r[21]) if r[21] else None,
        }
        for r in rows
    ]
    return {"total": total, "items": items}


@router.post("/products", status_code=201)
def create_product(
    body: ProductCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_data_writer),
):
    # Validate FK references
    if body.country_id and not db.query(Country).filter(Country.id == body.country_id).first():
        raise HTTPException(400, "国家不存在")
    if body.category_id and not db.query(Category).filter(Category.id == body.category_id).first():
        raise HTTPException(400, "类别不存在")
    if body.supplier_id and not db.query(Supplier).filter(Supplier.id == body.supplier_id).first():
        raise HTTPException(400, "供应商不存在")
    if body.port_id and not db.query(Port).filter(Port.id == body.port_id).first():
        raise HTTPException(400, "港口不存在")

    # Parse dates (str → datetime) before passing to ORM
    eff_from = _parse_date(body.effective_from)
    eff_to = _parse_date(body.effective_to)

    obj = Product(
        product_name_en=body.product_name_en,
        product_name_jp=body.product_name_jp,
        code=body.code,
        country_id=body.country_id,
        category_id=body.category_id,
        supplier_id=body.supplier_id,
        port_id=body.port_id,
        unit=body.unit,
        price=body.price,
        unit_size=body.unit_size,
        pack_size=body.pack_size,
        country_of_origin=body.country_of_origin,
        brand=body.brand,
        currency=body.currency,
        effective_from=eff_from,
        effective_to=eff_to,
        status=body.status,
    )
    db.add(obj)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "该产品在同一国家和港口下已存在（同名+同国家+同港口）")
    except DataError as e:
        db.rollback()
        logger.warning("create_product DataError: %s", e)
        raise HTTPException(400, "数据格式错误，请检查字段长度和类型")
    except Exception as e:
        db.rollback()
        logger.exception("create_product unexpected error")
        raise HTTPException(500, f"创建失败: {str(e)[:200]}")
    db.refresh(obj)
    return _product_to_dict(obj, db)


@router.patch("/products/{product_id}")
def update_product(
    product_id: int,
    body: ProductUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_data_writer),
):
    obj = db.query(Product).filter(Product.id == product_id).first()
    if not obj:
        raise HTTPException(404, "产品不存在")
    data = body.model_dump(exclude_unset=True)
    # Validate FK references if changing
    if "country_id" in data and data["country_id"] and not db.query(Country).filter(Country.id == data["country_id"]).first():
        raise HTTPException(400, "国家不存在")
    if "category_id" in data and data["category_id"] and not db.query(Category).filter(Category.id == data["category_id"]).first():
        raise HTTPException(400, "类别不存在")
    if "supplier_id" in data and data["supplier_id"] and not db.query(Supplier).filter(Supplier.id == data["supplier_id"]).first():
        raise HTTPException(400, "供应商不存在")
    if "port_id" in data and data["port_id"] and not db.query(Port).filter(Port.id == data["port_id"]).first():
        raise HTTPException(400, "港口不存在")
    # Parse date strings before setattr
    for date_field in ("effective_from", "effective_to"):
        if date_field in data:
            data[date_field] = _parse_date(data[date_field])
    for k, v in data.items():
        setattr(obj, k, v)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "该产品在同一国家和港口下已存在（同名+同国家+同港口）")
    except DataError as e:
        db.rollback()
        logger.warning("update_product DataError: %s", e)
        raise HTTPException(400, "数据格式错误，请检查字段长度和类型")
    except Exception as e:
        db.rollback()
        logger.exception("update_product unexpected error")
        raise HTTPException(500, f"更新失败: {str(e)[:200]}")
    db.refresh(obj)
    return _product_to_dict(obj, db)


@router.delete("/products/{product_id}", status_code=204)
def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_data_writer),
):
    obj = db.query(Product).filter(Product.id == product_id).first()
    if not obj:
        raise HTTPException(404, "产品不存在")
    db.delete(obj)
    db.commit()


# ═══════════════════════════════════════════════════════════════════
# Exchange Rates
# ═══════════════════════════════════════════════════════════════════


def _db_rate_lookup(db: Session, from_curr: str, to_curr: str, target_date: date) -> tuple[float, date] | None:
    """DB-only lookup: direct match, then reverse match."""
    # Direct
    row = (
        db.query(ExchangeRate)
        .filter(ExchangeRate.from_currency == from_curr, ExchangeRate.to_currency == to_curr,
                ExchangeRate.effective_date <= target_date)
        .order_by(ExchangeRate.effective_date.desc()).first()
    )
    if row:
        return (float(row.rate), row.effective_date)
    # Reverse
    row = (
        db.query(ExchangeRate)
        .filter(ExchangeRate.from_currency == to_curr, ExchangeRate.to_currency == from_curr,
                ExchangeRate.effective_date <= target_date)
        .order_by(ExchangeRate.effective_date.desc()).first()
    )
    if row and float(row.rate) != 0:
        return (round(1.0 / float(row.rate), 8), row.effective_date)
    return None


def _fetch_and_store_rates(db: Session, base: str) -> bool:
    """Fetch latest rates from API for a base currency, store in DB. Returns True on success."""
    import httpx
    try:
        resp = httpx.get(f"https://open.er-api.com/v6/latest/{base}", timeout=15.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return False
    if data.get("result") != "success":
        return False
    rates = data.get("rates", {})
    today = date.today()
    for code, rate_value in rates.items():
        if code == base:
            continue
        existing = (
            db.query(ExchangeRate)
            .filter(ExchangeRate.from_currency == base, ExchangeRate.to_currency == code,
                    ExchangeRate.effective_date == today)
            .first()
        )
        if existing:
            existing.rate = rate_value
            existing.source = "api"
            existing.updated_at = datetime.utcnow()
        else:
            db.add(ExchangeRate(from_currency=base, to_currency=code,
                                rate=rate_value, effective_date=today, source="api"))
    db.commit()
    return True


def get_exchange_rate(db: Session, from_curr: str, to_curr: str, target_date: date | None = None) -> tuple[float, date] | None:
    """Look up exchange rate with 3-tier fallback. Returns (rate, effective_date) or None.

    1. Same currency → 1.0
    2. DB direct/reverse match
    3. DB cross-rate via USD bridge (from→USD × USD→to)
    4. Auto-fetch from API → store → retry
    """
    from_curr = from_curr.strip().upper()
    to_curr = to_curr.strip().upper()
    if from_curr == to_curr:
        return (1.0, target_date or date.today())
    if target_date is None:
        target_date = date.today()

    # Tier 1: DB direct/reverse
    result = _db_rate_lookup(db, from_curr, to_curr, target_date)
    if result:
        return result

    # Tier 2: cross-rate via USD bridge
    if from_curr != "USD" and to_curr != "USD":
        r1 = _db_rate_lookup(db, from_curr, "USD", target_date)
        r2 = _db_rate_lookup(db, "USD", to_curr, target_date)
        if r1 and r2:
            cross_rate = round(r1[0] * r2[0], 8)
            older_date = min(r1[1], r2[1])
            return (cross_rate, older_date)

    # Tier 3: auto-fetch from API, then retry
    if _fetch_and_store_rates(db, from_curr):
        result = _db_rate_lookup(db, from_curr, to_curr, target_date)
        if result:
            return result

    return None


@router.get("/exchange-rates")
def list_exchange_rates(
    from_currency: str | None = Query(None),
    to_currency: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_data_reader),
):
    q = db.query(ExchangeRate)
    if from_currency:
        q = q.filter(ExchangeRate.from_currency == from_currency.upper())
    if to_currency:
        q = q.filter(ExchangeRate.to_currency == to_currency.upper())
    rows = q.order_by(ExchangeRate.from_currency, ExchangeRate.to_currency, ExchangeRate.effective_date.desc()).all()
    return [
        {
            "id": r.id,
            "from_currency": r.from_currency,
            "to_currency": r.to_currency,
            "rate": float(r.rate),
            "effective_date": str(r.effective_date),
            "source": r.source,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
        }
        for r in rows
    ]


@router.post("/exchange-rates", status_code=201)
def create_exchange_rate(
    body: ExchangeRateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_data_writer),
):
    obj = ExchangeRate(
        from_currency=body.from_currency.upper(),
        to_currency=body.to_currency.upper(),
        rate=body.rate,
        effective_date=body.effective_date,
        source="manual",
    )
    db.add(obj)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "该币种对在该日期已有汇率记录")
    db.refresh(obj)
    return {
        "id": obj.id,
        "from_currency": obj.from_currency,
        "to_currency": obj.to_currency,
        "rate": float(obj.rate),
        "effective_date": str(obj.effective_date),
        "source": obj.source,
    }


@router.patch("/exchange-rates/{rate_id}")
def update_exchange_rate(
    rate_id: int,
    body: ExchangeRateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_data_writer),
):
    obj = db.query(ExchangeRate).filter(ExchangeRate.id == rate_id).first()
    if not obj:
        raise HTTPException(404, "汇率记录不存在")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(obj, k, v)
    obj.updated_at = datetime.utcnow()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "该币种对在该日期已有汇率记录")
    db.refresh(obj)
    return {
        "id": obj.id,
        "from_currency": obj.from_currency,
        "to_currency": obj.to_currency,
        "rate": float(obj.rate),
        "effective_date": str(obj.effective_date),
        "source": obj.source,
    }


@router.delete("/exchange-rates/{rate_id}", status_code=204)
def delete_exchange_rate(
    rate_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_data_writer),
):
    obj = db.query(ExchangeRate).filter(ExchangeRate.id == rate_id).first()
    if not obj:
        raise HTTPException(404, "汇率记录不存在")
    db.delete(obj)
    db.commit()


class FetchRatesRequest(BaseModel):
    base_currency: str = "USD"
    target_currencies: list[str] = []


@router.post("/exchange-rates/fetch")
def fetch_exchange_rates(
    body: FetchRatesRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_data_writer),
):
    """Fetch latest exchange rates from free API and save to DB."""
    import httpx

    base = body.base_currency.upper()
    try:
        resp = httpx.get(f"https://open.er-api.com/v6/latest/{base}", timeout=15.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise HTTPException(502, f"获取汇率失败: {e}")

    if data.get("result") != "success":
        raise HTTPException(502, f"API 返回错误: {data.get('error-type', 'unknown')}")

    rates = data.get("rates", {})
    today = date.today()
    targets = [c.upper() for c in body.target_currencies] if body.target_currencies else list(rates.keys())

    created = 0
    updated = 0
    for currency_code in targets:
        if currency_code == base or currency_code not in rates:
            continue
        rate_value = rates[currency_code]
        existing = (
            db.query(ExchangeRate)
            .filter(
                ExchangeRate.from_currency == base,
                ExchangeRate.to_currency == currency_code,
                ExchangeRate.effective_date == today,
            )
            .first()
        )
        if existing:
            existing.rate = rate_value
            existing.source = "api"
            existing.updated_at = datetime.utcnow()
            updated += 1
        else:
            db.add(ExchangeRate(
                from_currency=base,
                to_currency=currency_code,
                rate=rate_value,
                effective_date=today,
                source="api",
            ))
            created += 1

    db.commit()
    return {"created": created, "updated": updated, "base": base, "date": str(today)}
