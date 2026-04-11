"""Project a universal ExtractedDocument into a Purchase Order.

The output shape is INTENTIONALLY identical to the legacy `extracted_data`
format used everywhere downstream:

    {
        "metadata": {po_number, ship_name, vendor_name, delivery_date,
                     order_date, currency, destination_port, total_amount,
                     extra_fields},
        "products": [{product_code, product_name, quantity, unit,
                      unit_price, total_price}, ...]
    }

This way the new extractor can plug into the existing pipeline without
forcing every consumer (UI, agent tools, projection.py) to change shape.

The projection logic is fuzzy-match based: it scans field_groups for
PO-related labels and tables for product-shaped columns. It does NOT call
an LLM — it's pure Python text matching, so it's fast, deterministic,
and unit-testable.
"""

from __future__ import annotations

import logging
import re
from typing import Any, TypedDict

from services.extraction.schema import ExtractedDocument

logger = logging.getLogger(__name__)


class POMetadata(TypedDict, total=False):
    po_number: str | None
    ship_name: str | None
    vendor_name: str | None
    delivery_date: str | None
    order_date: str | None
    currency: str | None
    destination_port: str | None
    total_amount: float | None
    extra_fields: dict[str, Any]


class POProduct(TypedDict, total=False):
    line_number: int | None
    product_code: str | None
    product_name: str | None
    quantity: float | None
    unit: str | None
    unit_price: float | None
    total_price: float | None


class PurchaseOrderProjection(TypedDict, total=False):
    metadata: POMetadata
    products: list[POProduct]
    confidence: dict[str, Any]  # how sure we are this is actually a PO


# ─── Label fuzzy matching ───────────────────────────────────────────────────
#
# Each tuple is (canonical_field, [possible_label_substrings_lowercase]).
# Order matters: earlier entries win when multiple match.

_PO_FIELD_LABELS: list[tuple[str, list[str]]] = [
    ("po_number", [
        "po number", "po #", "po no", "po:", "purchase order #",
        "purchase order no", "purchase order", "p.o.",
        "po号", "采购订单", "订单编号", "订单号", "発注番号",
        "order number",  # weak — last resort
    ]),
    ("ship_name", [
        "ship name", "ship:", "vessel", "船名", "船舶", "船",
        "comments",  # weak — many cruise PO docs put "Comments: <SHIP>: <ref>"
    ]),
    ("vendor_name", [
        "vendor", "supplier", "from:", "shipper", "seller",
        "供应商", "卖方", "供应方", "仕入先", "ベンダー",
    ]),
    ("delivery_date", [
        "delivery date", "expected delivery", "deliver by", "needed by",
        "required by", "etd", "loading date", "loading",
        "交货日期", "送货日期", "交货", "纳期", "納期", "配送日",
    ]),
    ("order_date", [
        "order date", "purchase order date", "issued", "date issued", "po date",
        "下单日期", "订单日期", "発行日",
    ]),
    ("currency", [
        "currency", "vendor currency", "ccy", "币种", "貨幣", "通貨",
    ]),
    ("destination_port", [
        "destination port", "port code", "final destination", "destination",
        "ship to", "deliver to",
        "目的港", "送货地", "送达港", "ポート", "到着港",
    ]),
    ("total_amount", [
        "total amount", "grand total", "total:", "amount due", "extended value",
        "总金额", "合计", "総額", "合計",
    ]),
]


# Column-name fuzzy matching for product table detection.
# A table is considered "product-like" if it has columns matching at least
# 2 of these categories.
#
# IMPORTANT: patterns within each canonical are ordered MOST SPECIFIC FIRST.
# The matcher uses a global longest-pattern-wins strategy so that
# "Product Number" maps to product_code (via "product number") before it
# accidentally maps to product_name (via "product").
_PRODUCT_COLUMN_PATTERNS: dict[str, list[str]] = {
    "product_code": [
        "product number", "product code", "item code", "item number",
        "item no", "item #", "part number", "part no", "part #",
        "sku", "code",
        "商品コード", "品番", "代码", "编号", "产品编号",
    ],
    "product_name": [
        "product name", "item description", "product description",
        "description", "particulars", "product", "item",
        "品名", "商品名", "描述", "名称", "品目",
        # "name" alone is too generic — only put it last
        "name",
    ],
    "quantity": [
        "order quantity", "qty ordered", "quantity", "qty",
        "数量", "数",
    ],
    "unit": [
        "unit of measure", "uom", "unit",
        "单位", "単位",
    ],
    "unit_price": [
        "unit price", "price per unit", "unit cost", "rate",
        "单价", "単価",
        "price",  # generic — last
    ],
    "total_price": [
        "extended value", "extended price", "line total", "subtotal",
        "amount", "total",
        "金额", "金額", "小计",
    ],
}


# ─── Public API ─────────────────────────────────────────────────────────────


def project_purchase_order(doc: ExtractedDocument) -> PurchaseOrderProjection:
    """Project an ExtractedDocument into a PO-shaped object.

    Returns a projection even for documents that aren't actually POs — the
    caller decides whether to trust it based on `confidence`.
    """
    blocks = doc.get("blocks") or []

    metadata = _extract_metadata(blocks)
    products = _extract_products(blocks)

    confidence = _compute_confidence(metadata, products, blocks)

    return PurchaseOrderProjection(
        metadata=metadata,
        products=products,
        confidence=confidence,
    )


# ─── Metadata extraction ────────────────────────────────────────────────────


def _extract_metadata(blocks: list[dict[str, Any]]) -> POMetadata:
    """Walk field_group AND paragraph blocks to find PO-relevant fields.

    Many real POs (especially cruise procurement docs) format header info as
    inline `LABEL: VALUE` paragraphs rather than table-style form fields.
    A faithful extractor will preserve them as paragraphs — so we have to
    handle both shapes here.
    """
    found: dict[str, str] = {}
    extras: dict[str, Any] = {}

    # Pass 1: structured field_group blocks (highest priority)
    for block in blocks:
        if block.get("type") != "field_group":
            continue
        for entry in block.get("fields") or []:
            label = (entry.get("label") or "").strip()
            value = entry.get("value")
            if not label:
                continue
            if value is None or (isinstance(value, str) and not value.strip()):
                continue

            canonical = _match_field_label(label)
            value_str = str(value).strip() if not isinstance(value, str) else value.strip()
            if canonical and canonical not in found:
                found[canonical] = value_str
            else:
                # Stash unmatched fields under extra_fields with original label
                extras[label] = value

    # Pass 2: paragraph blocks containing inline `LABEL: VALUE` patterns.
    # Only fills fields not already found in pass 1.
    for block in blocks:
        if block.get("type") != "paragraph":
            continue
        text = (block.get("text") or "").strip()
        if not text or ":" not in text:
            continue
        # Try parsing as one or more "Label: Value" segments separated by ":" or newlines
        for label, value in _parse_inline_label_value(text):
            canonical = _match_field_label(label)
            if not canonical or canonical in found:
                continue
            found[canonical] = value

    # Special case for ship_name extracted from "Comments: SHIP: ref" pattern.
    # The label match would land us at "comments" → ship_name with value
    # "SHIPNAME: REFNUM". Strip the trailing ": ref".
    if found.get("ship_name") and ":" in found["ship_name"]:
        candidate = found["ship_name"].split(":")[0].strip()
        if candidate:
            found["ship_name"] = candidate

    metadata: POMetadata = {
        "po_number": found.get("po_number"),
        "ship_name": found.get("ship_name"),
        "vendor_name": found.get("vendor_name"),
        "delivery_date": _normalize_date(found.get("delivery_date")),
        "order_date": _normalize_date(found.get("order_date")),
        "currency": found.get("currency"),  # downstream projection layer normalizes symbol → ISO
        "destination_port": found.get("destination_port"),
        "total_amount": _parse_money(found.get("total_amount")),
        "extra_fields": extras,
    }
    return metadata


def _parse_inline_label_value(text: str) -> list[tuple[str, str]]:
    """Parse a paragraph like 'PORT CODE: SYD' or 'Comments: CELEBRITY EDGE: EG-0317'.

    Returns a list of (label, value) tuples. Handles single-line and multi-line.
    """
    pairs: list[tuple[str, str]] = []
    # Split on newlines first — each line might be its own label/value
    for line in text.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        # Use only the FIRST colon as the separator: "Label: rest of the line"
        idx = line.find(":")
        label = line[:idx].strip()
        value = line[idx + 1:].strip()
        if label and value:
            pairs.append((label, value))
    return pairs


def _match_field_label(label: str) -> str | None:
    """Return the canonical PO field name a label matches, or None."""
    label_lower = label.lower().strip().rstrip(":：").strip()
    for canonical, candidates in _PO_FIELD_LABELS:
        for candidate in candidates:
            if candidate in label_lower:
                return canonical
    return None


def _normalize_date(value: str | None) -> str | None:
    """Best-effort date normalization to YYYY-MM-DD.

    Accepts: 2026-01-05, 2026/01/05, 01/05/2026, Jan 5 2026, 5 Jan 2026,
    2026年1月5日, etc. Returns None if it can't parse confidently.
    """
    if not value:
        return None
    s = value.strip()

    # Already YYYY-MM-DD
    m = re.match(r"^(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})", s)
    if m:
        y, mo, d = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"

    # MM/DD/YYYY or DD/MM/YYYY — ambiguous, prefer MM/DD if first part <= 12
    m = re.match(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})", s)
    if m:
        a, b, y = m.groups()
        a_i, b_i = int(a), int(b)
        # If first > 12, it must be DD/MM
        if a_i > 12:
            return f"{int(y):04d}-{b_i:02d}-{a_i:02d}"
        return f"{int(y):04d}-{a_i:02d}-{b_i:02d}"

    # English month name: "Jan 5 2026" or "5 January 2026"
    months = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10,
        "november": 11, "december": 12,
    }
    m = re.match(r"^([A-Za-z]+)\s+(\d{1,2})[,]?\s+(\d{4})", s)
    if m:
        mon_name, d, y = m.groups()
        mo = months.get(mon_name.lower())
        if mo:
            return f"{int(y):04d}-{mo:02d}-{int(d):02d}"
    m = re.match(r"^(\d{1,2})\s+([A-Za-z]+)[,]?\s+(\d{4})", s)
    if m:
        d, mon_name, y = m.groups()
        mo = months.get(mon_name.lower())
        if mo:
            return f"{int(y):04d}-{mo:02d}-{int(d):02d}"

    return None


def _parse_money(value: str | None) -> float | None:
    """Pull a number out of a string like 'USD 55,203.08' or '$55,203.08'."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    # Strip currency symbols and letters
    s = re.sub(r"[^\d.,\-]", "", s)
    if not s:
        return None
    # Remove thousand separators (assume the LAST . or , is the decimal)
    if "." in s and "," in s:
        if s.rfind(".") > s.rfind(","):
            s = s.replace(",", "")
        else:
            s = s.replace(".", "").replace(",", ".")
    elif "," in s and s.count(",") == 1 and len(s.split(",")[-1]) == 2:
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


# ─── Product table extraction ───────────────────────────────────────────────


def _extract_products(blocks: list[dict[str, Any]]) -> list[POProduct]:
    """Find the most product-like table and convert its rows to POProduct."""
    best_table = None
    best_score = 0
    best_mapping: dict[str, str] = {}

    for block in blocks:
        if block.get("type") != "table":
            continue
        columns = block.get("columns") or []
        if not columns:
            continue
        mapping, score = _score_columns_as_product_table(columns)
        if score > best_score:
            best_score = score
            best_table = block
            best_mapping = mapping

    if not best_table or best_score < 2:
        # No table looks product-like enough
        return []

    products: list[POProduct] = []
    for idx, row in enumerate(best_table.get("rows") or []):
        if not isinstance(row, dict):
            continue
        product: POProduct = {
            "line_number": idx + 1,
            "product_code": _row_get_str(row, best_mapping.get("product_code")),
            "product_name": _row_get_str(row, best_mapping.get("product_name")),
            "quantity": _row_get_number(row, best_mapping.get("quantity")),
            "unit": _row_get_str(row, best_mapping.get("unit")),
            "unit_price": _row_get_number(row, best_mapping.get("unit_price")),
            "total_price": _row_get_number(row, best_mapping.get("total_price")),
        }
        # Skip rows that have no name and no code (likely a totals row or junk)
        if not product["product_name"] and not product["product_code"]:
            continue
        products.append(product)

    return products


def _score_columns_as_product_table(columns: list[str]) -> tuple[dict[str, str], int]:
    """Map raw column names to canonical product fields and score the match.

    Strategy: for each (canonical, raw_column) pair, find the LONGEST pattern
    that matches. The longest match wins globally — this prevents short
    generic patterns like "product" from grabbing a column that a more
    specific pattern like "product number" would match better.

    Returns (mapping_canonical_to_raw, score). Higher score = more product-like.
    """
    # Build all candidate matches: (match_length, canonical, raw_col)
    candidates: list[tuple[int, str, str]] = []
    for canonical, patterns in _PRODUCT_COLUMN_PATTERNS.items():
        for raw_col in columns:
            raw_lower = raw_col.lower().strip()
            best_pat_len = 0
            for pat in patterns:
                if pat in raw_lower and len(pat) > best_pat_len:
                    best_pat_len = len(pat)
            if best_pat_len > 0:
                candidates.append((best_pat_len, canonical, raw_col))

    # Sort by match length descending — longest match wins first
    candidates.sort(key=lambda x: x[0], reverse=True)

    mapping: dict[str, str] = {}
    used_columns: set[str] = set()
    for _len, canonical, raw_col in candidates:
        if canonical in mapping:
            continue
        if raw_col in used_columns:
            continue
        mapping[canonical] = raw_col
        used_columns.add(raw_col)

    return mapping, len(mapping)


def _row_get_str(row: dict[str, Any], key: str | None) -> str | None:
    if not key:
        return None
    val = row.get(key)
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def _row_get_number(row: dict[str, Any], key: str | None) -> float | None:
    if not key:
        return None
    val = row.get(key)
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    return _parse_money(str(val))


# ─── Confidence scoring ─────────────────────────────────────────────────────


def _compute_confidence(
    metadata: POMetadata,
    products: list[POProduct],
    blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    """How confident are we that this document is a purchase order?"""
    has_po_number = bool(metadata.get("po_number"))
    has_ship = bool(metadata.get("ship_name"))
    has_delivery = bool(metadata.get("delivery_date"))
    has_vendor = bool(metadata.get("vendor_name"))
    has_products = len(products) > 0

    # Look for PO-suggesting headings
    title_signal = False
    for block in blocks:
        if block.get("type") == "heading":
            text = (block.get("text") or "").lower()
            if any(kw in text for kw in ("purchase order", "po ", "采购订单", "発注書")):
                title_signal = True
                break

    score = 0
    if has_po_number: score += 3
    if has_ship: score += 1
    if has_delivery: score += 2
    if has_vendor: score += 1
    if has_products: score += 3
    if title_signal: score += 2
    # Max score = 12

    if score >= 6:
        verdict = "purchase_order"
    elif score >= 3:
        verdict = "possibly_purchase_order"
    else:
        verdict = "not_purchase_order"

    return {
        "verdict": verdict,
        "score": score,
        "max_score": 12,
        "signals": {
            "has_po_number": has_po_number,
            "has_ship": has_ship,
            "has_delivery": has_delivery,
            "has_vendor": has_vendor,
            "product_count": len(products),
            "title_signal": title_signal,
        },
    }
