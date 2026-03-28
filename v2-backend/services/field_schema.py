"""Schema-driven field resolution and gap analysis for inquiry generation.

Replaces the hardcoded FIELD_DATA_PATHS approach with a data-driven schema
where each template defines its own field requirements. The schema is stored
in template_styles.field_schema and includes:
  - What fields the template needs (key, cell, label, type)
  - Where each field's data comes from (source path)
  - Whether the field is required or optional
  - What to do when data is missing (fallback strategy)

Key functions:
  build_field_schema() — generate schema from AI analysis output
  analyze_gaps()       — check order data against schema, find missing fields
  resolve_fields()     — resolve all field values for template fill
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ── Field categories ───────────────────────────────────────────

CATEGORY_ORDER = "order"
CATEGORY_SUPPLIER = "supplier"
CATEGORY_COMPANY = "company"
CATEGORY_DELIVERY = "delivery"

# ── Known source paths ────────────────────────────────────────
# Auto-mapping table: when AI identifies a field_key, we know where
# the data lives in order_data. This is the SAME knowledge as the old
# FIELD_DATA_PATHS, but now used only as a default — templates can
# override with custom source paths.

_KNOWN_SOURCES: dict[str, dict[str, Any]] = {
    # Order fields
    "ship_name":          {"source": "ship_name",           "category": CATEGORY_ORDER,    "type": "text",   "required": True},
    "ship_name_alt":      {"source": "ship_name",           "category": CATEGORY_ORDER,    "type": "text",   "required": False},
    "po_number":          {"source": "po_number",           "category": CATEGORY_ORDER,    "type": "text",   "required": True},
    "order_date":         {"source": "order_date",          "category": CATEGORY_ORDER,    "type": "date",   "required": False},
    "delivery_date":      {"source": "delivery_date",       "category": CATEGORY_ORDER,    "type": "date",   "required": True},
    "delivery_address":   {"source": "delivery_address",    "category": CATEGORY_DELIVERY, "type": "text",   "required": False},
    "delivery_contact":   {"source": "delivery_location.contact_person", "category": CATEGORY_DELIVERY, "type": "text", "required": False},
    "delivery_time_notes":{"source": "delivery_location.delivery_notes", "category": CATEGORY_DELIVERY, "type": "text", "required": False},
    "destination":        {"source": "destination_port",    "category": CATEGORY_ORDER,    "type": "text",   "required": False},
    "destination_port":   {"source": "destination_port",    "category": CATEGORY_ORDER,    "type": "text",   "required": False},
    "voyage":             {"source": "voyage",              "category": CATEGORY_ORDER,    "type": "text",   "required": False},
    "invoice_number":     {"source": "po_number",           "category": CATEGORY_ORDER,    "type": "text",   "required": False},
    "currency":           {"source": "currency",            "category": CATEGORY_ORDER,    "type": "text",   "required": False},
    "payment_date":       {"source": "suppliers.{sid}.supplier_info.default_payment_terms",  "category": CATEGORY_SUPPLIER, "type": "text", "required": False},
    "payment_method":     {"source": "suppliers.{sid}.supplier_info.default_payment_method", "category": CATEGORY_SUPPLIER, "type": "text", "required": False},
    # Supplier fields
    "supplier_name":      {"source": "suppliers.{sid}.supplier_name",         "category": CATEGORY_SUPPLIER, "type": "text", "required": True},
    "supplier_contact":   {"source": "suppliers.{sid}.supplier_info.contact", "category": CATEGORY_SUPPLIER, "type": "text", "required": False},
    "supplier_tel":       {"source": "suppliers.{sid}.supplier_info.phone",   "category": CATEGORY_SUPPLIER, "type": "text", "required": False},
    "supplier_fax":       {"source": "suppliers.{sid}.supplier_info.fax",     "category": CATEGORY_SUPPLIER, "type": "text", "required": False},
    "supplier_email":     {"source": "suppliers.{sid}.supplier_info.email",   "category": CATEGORY_SUPPLIER, "type": "text", "required": False},
    "supplier_address":   {"source": "suppliers.{sid}.supplier_info.address", "category": CATEGORY_SUPPLIER, "type": "text", "required": False},
    "supplier_zip_code":  {"source": "suppliers.{sid}.supplier_info.zip_code","category": CATEGORY_SUPPLIER, "type": "text", "required": False},
    "supplier_bank":      {"source": "suppliers.{sid}.supplier_info.bank_info",   "category": CATEGORY_SUPPLIER, "type": "text", "required": False},
    "supplier_account":   {"source": "suppliers.{sid}.supplier_info.account_info","category": CATEGORY_SUPPLIER, "type": "text", "required": False},
    # Company fields — typically kept from template original
    "company_name":       {"source": None, "category": CATEGORY_COMPANY, "type": "text", "required": False, "fallback": "template_original"},
    "company_contact":    {"source": None, "category": CATEGORY_COMPANY, "type": "text", "required": False, "fallback": "template_original"},
    "company_address":    {"source": None, "category": CATEGORY_COMPANY, "type": "text", "required": False, "fallback": "template_original"},
    "company_zip_code":   {"source": None, "category": CATEGORY_COMPANY, "type": "text", "required": False, "fallback": "template_original"},
    "company_tel":        {"source": None, "category": CATEGORY_COMPANY, "type": "text", "required": False, "fallback": "template_original"},
    "company_fax":        {"source": None, "category": CATEGORY_COMPANY, "type": "text", "required": False, "fallback": "template_original"},
    "company_email":      {"source": None, "category": CATEGORY_COMPANY, "type": "text", "required": False, "fallback": "template_original"},
    # Delivery location fields (from CompanyConfig / DeliveryLocation)
    "delivery_company_name": {"source": "delivery_location.name",           "category": CATEGORY_DELIVERY, "type": "text", "required": False},
    "delivery_company_tel":  {"source": "delivery_location.contact_phone",  "category": CATEGORY_DELIVERY, "type": "text", "required": False},
    "ship_name_label":       {"source": "delivery_location.ship_name_label","category": CATEGORY_DELIVERY, "type": "text", "required": False},
}

# Human-readable labels for known fields
_FIELD_LABELS: dict[str, str] = {
    "ship_name": "船名", "po_number": "PO 号", "order_date": "订单日期",
    "delivery_date": "交付日期", "delivery_address": "交付地址",
    "delivery_contact": "交付联系人", "delivery_time_notes": "交付备注",
    "destination": "目的港", "destination_port": "目的港", "voyage": "航次",
    "invoice_number": "发票号", "currency": "货币",
    "payment_date": "支付条件", "payment_method": "支付方式",
    "supplier_name": "供应商名称", "supplier_contact": "联系人",
    "supplier_tel": "电话", "supplier_fax": "传真",
    "supplier_email": "邮箱", "supplier_address": "地址",
    "supplier_zip_code": "邮编", "supplier_bank": "银行信息",
    "supplier_account": "账户信息",
    "company_name": "公司名称", "company_contact": "公司联系人",
    "company_address": "公司地址", "company_tel": "公司电话",
    "delivery_company_name": "交付公司", "ship_name_label": "船名标签",
    "ship_name_alt": "船名",
}


# ── Schema Builder ────────────────────────────────────────────


def build_field_schema(
    field_positions: dict[str, str],
    cell_map: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build a field schema from AI analysis output.

    Each entry describes one header field the template needs:
      key:      canonical field name (e.g. "ship_name")
      cell:     Excel cell reference (e.g. "A2")
      label:    human-readable name (e.g. "船名")
      type:     data type ("text", "date", "number")
      required: whether missing blocks generation
      source:   dotted path in order_data (e.g. "ship_name") or null
      fallback: what to do when source is null:
                  null       → needs user input
                  "template_original" → keep template's existing value
                  string     → use as default value
      category: "order" | "supplier" | "company" | "delivery"

    Args:
        field_positions: {field_key: cell_ref} from AI analysis
        cell_map: Optional full cell classification for richer metadata

    Returns:
        List of field definition dicts
    """
    schema: list[dict[str, Any]] = []

    for field_key, cell_ref in field_positions.items():
        known = _KNOWN_SOURCES.get(field_key, {})

        # Get label from cell_map (AI-extracted original text) or fallback
        label = _FIELD_LABELS.get(field_key, field_key)
        if cell_map and cell_ref in cell_map:
            ai_label = cell_map[cell_ref].get("label")
            if ai_label:
                label = ai_label

        schema.append({
            "key": field_key,
            "cell": cell_ref,
            "label": label,
            "type": known.get("type", "text"),
            "required": known.get("required", False),
            "source": known.get("source"),  # None if unknown field
            "fallback": known.get("fallback"),
            "category": known.get("category", _infer_category(field_key)),
        })

    # Check for fields in cell_map that AI identified but aren't in field_positions
    if cell_map:
        known_cells = set(field_positions.values())
        for cell_ref, info in cell_map.items():
            if cell_ref in known_cells:
                continue
            if not info.get("writable") or not info.get("field_key"):
                continue
            fk = info["field_key"]
            if fk in field_positions:
                continue  # already handled
            known = _KNOWN_SOURCES.get(fk, {})
            schema.append({
                "key": fk,
                "cell": cell_ref,
                "label": info.get("label") or _FIELD_LABELS.get(fk, fk),
                "type": known.get("type", "text"),
                "required": known.get("required", False),
                "source": known.get("source"),
                "fallback": known.get("fallback"),
                "category": known.get("category", _infer_category(fk)),
            })

    unmapped = [f for f in schema if f["source"] is None and f["fallback"] is None]
    if unmapped:
        logger.warning(
            "field_schema: %d fields have no source mapping: %s",
            len(unmapped),
            [f["key"] for f in unmapped],
        )

    return schema


# ── Gap Analysis ──────────────────────────────────────────────


def analyze_gaps(
    field_schema: list[dict[str, Any]],
    order_data: dict[str, Any],
    supplier_id: str | int,
    field_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Analyze data completeness against a template's field schema.

    Returns:
        {
            "resolved": {cell_ref: value, ...},   — fields with values
            "gaps": [...],                          — fields needing attention
            "ready": bool,                          — can generate without user input
            "summary": {"total": N, "resolved": N, "warnings": N, "blocking": N}
        }
    """
    sid = str(supplier_id)
    overrides = field_overrides or {}

    resolved: dict[str, Any] = {}
    gaps: list[dict[str, Any]] = []

    for field in field_schema:
        cell = field["cell"]

        # Priority 1: user override
        if cell in overrides and overrides[cell].strip():
            resolved[cell] = overrides[cell]
            continue

        # Priority 2: resolve from source path
        if field["source"]:
            value = _resolve_path(order_data, field["source"], sid)
            if value is not None and str(value).strip():
                resolved[cell] = value
                continue

        # Priority 3: fallback strategy
        fb = field.get("fallback")
        if fb == "template_original":
            # Keep whatever is in the template cell — don't touch it
            continue
        if fb and fb != "manual":
            resolved[cell] = fb
            continue

        # No value available — this is a gap
        severity = "blocking" if field["required"] else "warning"
        gaps.append({
            "key": field["key"],
            "cell": cell,
            "label": field["label"],
            "type": field["type"],
            "category": field["category"],
            "severity": severity,
            "current_value": None,
        })

    n_blocking = sum(1 for g in gaps if g["severity"] == "blocking")
    n_warning = sum(1 for g in gaps if g["severity"] == "warning")

    return {
        "resolved": resolved,
        "gaps": gaps,
        "ready": n_blocking == 0,
        "summary": {
            "total": len(field_schema),
            "resolved": len(resolved),
            "warnings": n_warning,
            "blocking": n_blocking,
        },
    }


def resolve_fields(
    field_schema: list[dict[str, Any]],
    order_data: dict[str, Any],
    supplier_id: str | int,
    field_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Resolve all field values — ready for template_engine.

    Returns {cell_ref: value} for every field that has a value.
    User overrides take highest priority.
    """
    result = analyze_gaps(field_schema, order_data, supplier_id, field_overrides)
    return result["resolved"]


# ── Backward Compatibility ────────────────────────────────────


def schema_from_zone_config(zone_config: dict[str, Any]) -> list[dict[str, Any]]:
    """Build a field_schema from an existing zone_config (backward compat).

    Old zone_configs store header_fields as {cell_ref: data_path}.
    This converts them to the new field_schema format so gap analysis
    works on old templates without re-analyzing.
    """
    header_fields = zone_config.get("header_fields", {})

    # Invert _KNOWN_SOURCES to find field_key from source path
    source_to_key: dict[str, str] = {}
    for key, info in _KNOWN_SOURCES.items():
        if info.get("source"):
            source_to_key[info["source"]] = key

    schema: list[dict[str, Any]] = []
    for cell_ref, data_path in header_fields.items():
        field_key = source_to_key.get(data_path, data_path.split(".")[-1])
        known = _KNOWN_SOURCES.get(field_key, {})
        schema.append({
            "key": field_key,
            "cell": cell_ref,
            "label": _FIELD_LABELS.get(field_key, field_key),
            "type": known.get("type", "text"),
            "required": known.get("required", False),
            "source": data_path,
            "fallback": known.get("fallback"),
            "category": known.get("category", _infer_category(field_key)),
        })

    return schema


# ── Private Helpers ───────────────────────────────────────────


def _resolve_path(data: dict, path: str, sid: str) -> Any:
    """Resolve a dotted path like 'suppliers.{sid}.supplier_info.contact'."""
    path = path.replace("{sid}", sid)
    obj = data
    for key in path.split("."):
        if isinstance(obj, dict):
            obj = obj.get(key)
        else:
            return None
        if obj is None:
            return None
    return obj


def _infer_category(field_key: str) -> str:
    """Infer field category from key name when not in _KNOWN_SOURCES."""
    if field_key.startswith("supplier_"):
        return CATEGORY_SUPPLIER
    if field_key.startswith("company_"):
        return CATEGORY_COMPANY
    if field_key.startswith("delivery_") or field_key.startswith("ship_name_label"):
        return CATEGORY_DELIVERY
    return CATEGORY_ORDER
