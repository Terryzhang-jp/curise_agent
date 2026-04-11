"""Product field normalization — structural validation for AI-extracted data.

AI extraction (Gemini Vision, schema-guided) is probabilistic and can produce
malformed field values.  Common corruption patterns:

  - unit + adjacent number concatenated: "KG2.2", "CT15.0"
  - quantity containing unit text: "100KG", "50CT"
  - unit_price as string instead of number: "1,500.00"
  - empty/null products mixed into the list

This module provides a deterministic post-extraction cleaning pass that
enforces structural constraints on each field type.  It does NOT use
whitelists — instead it relies on invariants that are always true:

  - unit is a short alphabetic token (1–5 chars)
  - quantity and unit_price are numeric
  - every product must have at least product_name or product_code

This is Layer 1 of the 3-layer data quality architecture:

  Layer 1: Post-extraction normalization  (this module)
  Layer 2: DB-authoritative override      (product_matching.py)
  Layer 3: Consumer-level DB-first        (excel_writer.py, template_engine.py)
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


def normalize_products(products: list[dict] | None) -> list[dict]:
    """Clean a list of AI-extracted products.

    Returns a new list with:
      - Malformed fields corrected (unit stripped of trailing numbers, etc.)
      - Empty/garbage rows removed
      - Numeric fields coerced to numbers
    """
    if not products:
        return []

    cleaned = []
    removed = 0
    fixed_fields = 0

    for p in products:
        if not isinstance(p, dict):
            removed += 1
            continue

        # ── Skip empty rows (no name AND no code) ──
        has_name = bool((p.get("product_name") or "").strip())
        has_code = bool((p.get("product_code") or "").strip())
        if not has_name and not has_code:
            removed += 1
            continue

        # ── unit: must be purely alphabetic, 1-5 chars ──
        raw_unit = str(p.get("unit") or "").strip()
        clean_unit = _clean_unit(raw_unit)
        if clean_unit != raw_unit:
            p["unit"] = clean_unit
            fixed_fields += 1

        # ── quantity: must be numeric ──
        qty = p.get("quantity")
        clean_qty = _to_numeric(qty)
        if clean_qty is not None and clean_qty != qty:
            p["quantity"] = clean_qty
            fixed_fields += 1

        # ── unit_price: must be numeric ──
        price = p.get("unit_price")
        clean_price = _to_numeric(price)
        if clean_price is not None and clean_price != price:
            p["unit_price"] = clean_price
            fixed_fields += 1

        # ── total_price: must be numeric ──
        total = p.get("total_price")
        clean_total = _to_numeric(total)
        if clean_total is not None and clean_total != total:
            p["total_price"] = clean_total
            fixed_fields += 1

        cleaned.append(p)

    if removed or fixed_fields:
        logger.info(
            "normalize_products: %d products → %d kept, %d removed, %d fields fixed",
            len(products), len(cleaned), removed, fixed_fields,
        )

    return cleaned


# ── Field-level helpers ──────────────────────────────────────────────


def _clean_unit(raw: str) -> str:
    """Extract a clean unit from potentially corrupted value.

    Examples:
        "KG2.2"  → "KG"   (unit + trailing number)
        "CT15.0" → "CT"   (unit + trailing number)
        "100KG"  → "KG"   (leading number + unit)
        "KG"     → "KG"   (already clean)
        "FL OZ"  → "FL OZ" (multi-word unit, preserved)
        ""       → ""
    """
    if not raw:
        return raw

    # Fast path: already clean alphabetic
    if raw.isalpha() and len(raw) <= 5:
        return raw.upper()

    # Pattern: alphabetic prefix followed by digits (e.g., "KG2.2")
    m = re.match(r'^([A-Za-z]{1,5})\s*[\d.]+$', raw)
    if m:
        return m.group(1).upper()

    # Pattern: digits followed by alphabetic suffix (e.g., "100KG")
    m = re.match(r'^[\d.]+\s*([A-Za-z]{1,5})$', raw)
    if m:
        return m.group(1).upper()

    # Multi-word unit like "FL OZ" — keep as-is if purely alpha + spaces
    if all(c.isalpha() or c.isspace() for c in raw):
        return raw.upper().strip()

    # Can't clean — return as-is
    return raw


def _to_numeric(val) -> int | float | None:
    """Coerce a value to a number if possible.

    Handles:
        "1,500.00" → 1500.0  (comma-separated)
        "100"      → 100     (int when possible)
        "12.5"     → 12.5
        "100KG"    → 100     (trailing text stripped)
        None       → None
        42         → 42      (already numeric, unchanged)
    """
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return val
    if not isinstance(val, str):
        return None

    s = val.strip()
    if not s:
        return None

    # Remove commas (thousands separator)
    s = s.replace(",", "")

    # Try direct parse
    try:
        f = float(s)
        if not (f == f and f != float("inf") and f != float("-inf")):  # reject nan/inf
            return None
        return int(f) if f == int(f) and "." not in s else f
    except (ValueError, TypeError, OverflowError):
        pass

    # Strip trailing non-numeric chars (e.g., "100KG" → "100")
    m = re.match(r'^([\d.]+)', s)
    if m:
        try:
            f = float(m.group(1))
            if not (f == f and f != float("inf") and f != float("-inf")):
                return None
            return int(f) if f == int(f) else f
        except (ValueError, TypeError, OverflowError):
            pass

    return None
