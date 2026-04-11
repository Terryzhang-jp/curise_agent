from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

from core.models import Document, Order

logger = logging.getLogger(__name__)


REQUIRED_ORDER_FIELDS = ("po_number", "ship_name", "delivery_date")
EDITABLE_DOCUMENT_FIELDS = (
    "po_number",
    "ship_name",
    "vendor_name",
    "delivery_date",
    "order_date",
    "currency",
    "destination_port",
    "total_amount",
)


# Currency normalization: free-form symbol/text → ISO 4217 three-letter code.
# Per SKILL.md §7.3, output MUST be a 3-letter uppercase code or None.
# Ambiguous cases (e.g. ¥ which is both JPY and CNY) return None — never guess.
_UNAMBIGUOUS_SYMBOL_MAP = {
    "$": "USD",
    "us$": "USD",
    "usd$": "USD",
    "€": "EUR",
    "£": "GBP",
    "₩": "KRW",
    "₽": "RUB",
    "₹": "INR",
    "฿": "THB",
    "a$": "AUD",
    "au$": "AUD",
    "c$": "CAD",
    "ca$": "CAD",
    "nz$": "NZD",
    "hk$": "HKD",
    "sg$": "SGD",
}

# Three-letter codes we accept verbatim (case-insensitive). Anything outside this
# set is treated as unknown rather than blindly accepted, to prevent typos like
# "USS" or "EUO" from polluting downstream financial logic.
_KNOWN_ISO_CODES = {
    "USD", "EUR", "GBP", "JPY", "CNY", "AUD", "CAD", "NZD", "HKD", "SGD",
    "KRW", "INR", "THB", "RUB", "MYR", "IDR", "PHP", "VND", "TWD", "CHF",
    "SEK", "NOK", "DKK", "ZAR", "BRL", "MXN", "AED", "SAR",
}

# Symbols that map to multiple currencies — by policy we DO NOT guess.
_AMBIGUOUS_SYMBOLS = {"¥", "￥"}  # JPY vs CNY


def _normalize_currency(raw: Any) -> str | None:
    """Normalize a free-form currency value to an ISO 4217 code.

    Returns None when the input is ambiguous, unknown, or empty.
    Never guesses.
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None

    # Already a valid 3-letter ISO code?
    upper = text.upper()
    if upper in _KNOWN_ISO_CODES:
        return upper

    # Single ambiguous symbol — refuse to guess
    if text in _AMBIGUOUS_SYMBOLS:
        return None

    # Unambiguous symbol or short prefix
    key = text.lower()
    if key in _UNAMBIGUOUS_SYMBOL_MAP:
        return _UNAMBIGUOUS_SYMBOL_MAP[key]

    # Substring fallback — only if exactly one known prefix matches
    matches = {code for prefix, code in _UNAMBIGUOUS_SYMBOL_MAP.items() if prefix in key}
    if len(matches) == 1:
        return next(iter(matches))

    return None


def build_order_payload(document: Document) -> dict[str, Any]:
    extracted_data = get_document_extracted_view(document)
    metadata = dict(extracted_data.get("metadata") or {})
    products = list(extracted_data.get("products") or [])
    field_evidence = dict(extracted_data.get("field_evidence") or {})

    order_metadata = {
        "po_number": metadata.get("po_number"),
        "ship_name": metadata.get("ship_name"),
        "vendor_name": metadata.get("vendor_name"),
        "delivery_date": metadata.get("delivery_date"),
        "order_date": metadata.get("order_date"),
        "currency": _normalize_currency(metadata.get("currency")),
        "destination_port": metadata.get("destination_port"),
        "total_amount": metadata.get("total_amount"),
        "source_document_id": document.id,
        "source_doc_type": document.doc_type,
    }

    missing_fields = [field for field in REQUIRED_ORDER_FIELDS if not order_metadata.get(field)]
    blocking_missing_fields = list(missing_fields)
    if document.doc_type not in (None, "purchase_order"):
        blocking_missing_fields.append("doc_type")

    inferred_evidence = _build_evidence(order_metadata, products, field_evidence, document)
    status = "ready" if not blocking_missing_fields and products else "needs_review"

    return {
        "document_id": document.id,
        "doc_type": document.doc_type,
        "order_metadata": order_metadata,
        "products": products,
        "product_count": len(products),
        "missing_fields": missing_fields,
        "blocking_missing_fields": blocking_missing_fields,
        "field_evidence": inferred_evidence,
        "confidence_summary": {
            "status": status,
            "has_products": bool(products),
            "metadata_fields_present": sum(1 for key in REQUIRED_ORDER_FIELDS if order_metadata.get(key)),
            "metadata_fields_required": len(REQUIRED_ORDER_FIELDS),
        },
        "ready_for_order_creation": status == "ready",
    }


def create_or_update_order_from_document(
    document: Document,
    db,
    *,
    force: bool = False,
    allow_incomplete: bool = False,
    admin_override: bool = False,
) -> Order:
    """Project a document into an order row.

    Args:
        force: Overwrite an existing order if one is already linked (reproject).
            When False and an order already exists, return it unchanged.
            Reproject is blocked after fulfillment has started (any status other
            than "pending") to prevent clobbering financial/logistics records.
        allow_incomplete: If True, skip the pre-check that raises on missing
            fields, BUT still write the correct status (needs_review / error)
            via `_resolve_order_status`. Used by the background ingestion
            pipeline to persist blocked orders instead of losing them.
        admin_override: Bypass everything AND force status="ready" even if
            blocking fields are missing. ONLY callable from an admin UI with
            explicit user confirmation. Every use is logged.

    Security note:
        Before 2026-04-12, `force=True` silently implied `allow_incomplete=True`
        AND status was always "ready" regardless of blocking fields. This let
        the background pipeline produce ready orders from incomplete documents
        (Codex adversarial review finding, 2026-04-12). The fix is:
        - `force` only controls overwrite semantics now
        - Missing-field validation is controlled by `allow_incomplete`
        - Persisted status is computed from `_resolve_order_status(payload)`,
          which respects blocking_missing_fields

    Uniqueness note:
        Migration 030 adds a partial unique index on document_id (WHERE NOT NULL).
        On a race condition a second INSERT would raise IntegrityError; we catch
        it and return the row that won the race instead of propagating the error.
    """
    from sqlalchemy.exc import IntegrityError

    payload = build_order_payload(document)
    if not allow_incomplete and not admin_override:
        _ensure_order_creation_allowed(payload)

    if admin_override:
        logger.warning(
            "ADMIN_OVERRIDE document→order projection: document_id=%s "
            "user_id=%s blocking_missing=%s — forcing status=ready",
            document.id,
            getattr(document, "user_id", None),
            payload.get("blocking_missing_fields"),
        )

    order = db.query(Order).filter(Order.document_id == document.id).first()
    if order is None:
        try:
            order = Order(
                user_id=document.user_id,
                document_id=document.id,
                filename=document.filename,
                file_url=document.file_url,
                file_type=document.file_type,
            )
            db.add(order)
            db.flush()
        except IntegrityError:
            # Race condition: another request inserted the same document_id
            # between our SELECT and INSERT. Roll back to clean state and
            # re-read the winning row.
            db.rollback()
            order = db.query(Order).filter(Order.document_id == document.id).first()
            if order is None:
                raise  # Unexpected — re-raise if still not found
            if not force:
                return order
    elif not force:
        return order

    # Phase gate: block reproject once fulfillment has started.
    # Fulfillment records (delivery data, invoices, payment) belong to the
    # order lifecycle, not the document. Overwriting products after they've
    # been quoted/confirmed/delivered would corrupt those records.
    if force and not admin_override:
        fs = getattr(order, "fulfillment_status", "pending") or "pending"
        if fs != "pending":
            raise ValueError(
                f"Cannot reproject order #{order.id}: fulfillment has already "
                f"started (fulfillment_status='{fs}'). Use admin_override=True "
                f"to force."
            )

    # Clear derived/stale state when reprojecting so downstream tools don't
    # operate on data from the previous document version.
    if force:
        order.match_results = None
        order.match_statistics = None
        order.anomaly_data = None
        order.financial_data = None
        order.inquiry_data = None
        flag_modified(order, "match_results")
        flag_modified(order, "match_statistics")
        flag_modified(order, "anomaly_data")
        flag_modified(order, "financial_data")
        flag_modified(order, "inquiry_data")

    order.filename = document.filename
    order.file_url = document.file_url
    order.file_type = document.file_type
    order.document_id = document.id
    order.extraction_data = get_document_extracted_view(document)
    order.order_metadata = payload["order_metadata"]
    order.products = payload["products"]
    order.product_count = payload["product_count"]
    order.delivery_date = payload["order_metadata"].get("delivery_date")
    if admin_override:
        order.status = "ready"
    else:
        order.status = _resolve_order_status(payload)
    order.processing_error = _build_order_warning(payload)

    total_amount = payload["order_metadata"].get("total_amount")
    if total_amount is not None:
        try:
            order.total_amount = float(total_amount)
        except (TypeError, ValueError):
            order.total_amount = None

    flag_modified(order, "extraction_data")
    flag_modified(order, "order_metadata")
    flag_modified(order, "products")
    db.commit()
    db.refresh(order)
    return order


def get_document_extracted_view(document: Document) -> dict[str, Any]:
    """Return a read-model of extracted_data with manual overrides applied.

    The raw machine extraction is preserved in `document.extracted_data`.
    Consumers that need the user-reviewed view should call this helper.
    """
    extracted_data = dict(document.extracted_data or {})
    base_metadata = dict(extracted_data.get("metadata") or {})
    manual_overrides = dict(extracted_data.get("manual_overrides") or {})
    merged_metadata = dict(base_metadata)
    merged_metadata.update(manual_overrides)

    field_evidence = dict(extracted_data.get("field_evidence") or {})
    for key, value in manual_overrides.items():
        if value in (None, "", []):
            continue
        field_evidence[key] = {
            "value": value,
            "source": "user_override",
            "document_id": document.id,
        }

    extracted_data["metadata"] = merged_metadata
    extracted_data["field_evidence"] = field_evidence
    return extracted_data


def apply_document_field_overrides(
    document: Document,
    updates: dict[str, Any] | None = None,
    clear_fields: list[str] | None = None,
) -> dict[str, Any]:
    """Mutate document.extracted_data manual overrides in-place.

    This preserves the original machine extraction while allowing a reviewed
    layer to override user-facing / order-facing values.
    """
    raw = dict(document.extracted_data or {})
    if not raw:
        raw = {"metadata": {}, "products": [], "field_evidence": {}}

    overrides = dict(raw.get("manual_overrides") or {})

    for field in clear_fields or []:
        if field in EDITABLE_DOCUMENT_FIELDS:
            overrides.pop(field, None)

    for key, value in (updates or {}).items():
        if key not in EDITABLE_DOCUMENT_FIELDS:
            continue
        normalized = _normalize_override_value(key, value)
        if normalized in (None, ""):
            overrides.pop(key, None)
        else:
            overrides[key] = normalized

    raw["manual_overrides"] = overrides
    document.extracted_data = raw
    return get_document_extracted_view(document)


def summarize_order_payload(payload: dict[str, Any]) -> str:
    metadata = payload.get("order_metadata") or {}
    # Use blocking_missing_fields (NOT missing_fields) so preview reflects the
    # exact same gate that create() will enforce. Otherwise the LLM sees
    # "missing 3 fields" in preview but create rejects with "missing 4 fields".
    blocking = payload.get("blocking_missing_fields") or []
    products = payload.get("products") or []
    lines = [
        f"## 文档 #{payload.get('document_id')} → 订单投影",
        f"- 文档类型: {payload.get('doc_type') or '-'}",
        f"- PO号: {metadata.get('po_number') or '-'}",
        f"- 船名: {metadata.get('ship_name') or '-'}",
        f"- 交货日期: {metadata.get('delivery_date') or '-'}",
        f"- 供应商: {metadata.get('vendor_name') or '-'}",
        f"- 币种: {metadata.get('currency') or '-'}",
        f"- 总金额: {metadata.get('total_amount') if metadata.get('total_amount') is not None else '-'}",
        f"- 产品数: {len(products)}",
        f"- 可直接建单: {'是' if payload.get('ready_for_order_creation') else '否'}",
    ]
    if blocking:
        lines.append(f"- 缺失字段: {', '.join(blocking)}")
    if not products:
        lines.append("- 阻断原因: 产品列表为空")
    return "\n".join(lines)


def _build_evidence(order_metadata: dict[str, Any], products: list[dict[str, Any]],
                    existing_evidence: dict[str, Any], document: Document) -> dict[str, Any]:
    evidence = dict(existing_evidence)
    for key, value in order_metadata.items():
        if key in evidence or value in (None, "", []):
            continue
        evidence[key] = {
            "value": value,
            "source": "metadata",
            "document_id": document.id,
        }

    if "products" not in evidence and products:
        evidence["products"] = {
            "count": len(products),
            "source": "products",
            "document_id": document.id,
        }
    return evidence


def _normalize_override_value(key: str, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
    if value in ("", []):
        return None

    if key in ("delivery_date", "order_date"):
        from services.projection.purchase_order import _normalize_date

        return _normalize_date(str(value)) or str(value).strip()

    if key == "currency":
        normalized = _normalize_currency(str(value))
        return normalized or str(value).strip().upper()

    if key == "total_amount":
        from services.projection.purchase_order import _parse_money

        return _parse_money(str(value))

    if isinstance(value, str):
        return value.strip()
    return value


def _build_order_warning(payload: dict[str, Any]) -> str | None:
    if not payload.get("products"):
        return "提取失败: 未识别到任何产品"
    missing = payload.get("blocking_missing_fields") or []
    if missing:
        return f"待补充关键字段: {', '.join(missing)}"
    return None


def _resolve_order_status(payload: dict[str, Any]) -> str:
    """Compute order status from payload.

    - no products           → "error" (extraction failed)
    - blocking_missing_fields → "needs_review" (caller must complete)
    - else                  → "ready"

    This is the single source of truth for status. Do NOT special-case
    "ready" elsewhere — if you need to bypass, use `admin_override` in
    `create_or_update_order_from_document`.
    """
    if not payload.get("products"):
        return "error"
    if payload.get("blocking_missing_fields"):
        return "needs_review"
    return "ready"


def _ensure_order_creation_allowed(payload: dict[str, Any]) -> None:
    """Raise ValueError if the payload cannot produce a valid order.

    Note: this used to take `force=True` to short-circuit the check — that
    was the source of a silent regression (see docstring on
    create_or_update_order_from_document). Use `allow_incomplete=True`
    on the caller instead if you want to persist incomplete orders.
    """
    if not payload.get("products"):
        raise ValueError("当前未识别到任何产品，不能创建订单")
    blocking_missing = payload.get("blocking_missing_fields") or []
    if blocking_missing:
        raise ValueError(f"当前缺少关键字段，不能创建订单: {', '.join(blocking_missing)}")
