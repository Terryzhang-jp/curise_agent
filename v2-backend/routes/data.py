from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from datetime import datetime

from database import get_db
from models import User, Country, Port, Category, Supplier, SupplierCategory, Product
from security import require_role
from schemas import (
    CountryCreate, CountryUpdate, CountryResponse,
    CategoryCreate, CategoryUpdate, CategoryResponse,
    PortCreate, PortUpdate, PortResponse,
    SupplierCreate, SupplierUpdate, SupplierResponse,
    ProductCreate, ProductUpdate, ProductResponse,
)

require_data_reader = require_role("superadmin", "admin", "employee")
require_data_writer = require_role("superadmin", "admin")

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
        "created_at": r.created_at, "updated_at": r.updated_at,
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
        effective_from=body.effective_from,
        effective_to=body.effective_to,
        status=body.status,
    )
    db.add(obj)
    db.commit()
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
    for k, v in data.items():
        setattr(obj, k, v)
    obj.updated_at = datetime.utcnow()
    db.commit()
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
