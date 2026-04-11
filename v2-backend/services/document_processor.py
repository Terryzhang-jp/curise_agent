"""Document processor — Stage 1 entrypoint.

Pipeline:
  1. EXTRACT (Stage 1):  PDF → universal block schema (type-agnostic)
  2. PROJECT (Stage 3):  blocks → PO-shaped {metadata, products}
  3. CLASSIFY:           decide doc_type from projection confidence

The output of process_document() is INTENTIONALLY backward-compatible with
the legacy `extracted_data` shape used by every downstream consumer (UI,
agent tools, projection.py). The legacy fields are populated by the new
projector. The NEW fields (`blocks`, `extraction_schema_version`, etc.) are
added alongside.

PDFs go through the new GeminiBlockExtractor.
Excel still goes through legacy `_extract_and_structure_excel`.
"""

from __future__ import annotations

import logging
from typing import Any

from services.extraction import (
    EXTRACTION_SCHEMA_VERSION,
    ExtractionError,
    GeminiBlockExtractor,
)
from services.projection import project_purchase_order

logger = logging.getLogger(__name__)


PRODUCT_HEADERS = [
    "line_number",
    "product_code",
    "product_name",
    "quantity",
    "unit",
    "unit_price",
    "total_price",
]


def process_document(file_bytes: bytes, file_type: str) -> dict[str, Any]:
    """Extract structured content from a document.

    For PDFs, uses the new universal block extractor + PO projector.
    For other types (excel), falls back to the legacy smart_extract path.
    """
    if file_type == "pdf":
        return _process_pdf(file_bytes)

    # Excel and anything else: fall back to legacy
    return _process_legacy(file_bytes, file_type)


# ─── New PDF path (Stage 1 v1.0) ────────────────────────────────────────────


def _process_pdf(file_bytes: bytes) -> dict[str, Any]:
    extractor = GeminiBlockExtractor()
    try:
        extracted_doc = extractor.extract(file_bytes, mime_type="application/pdf")
    except ExtractionError as exc:
        logger.warning("New extractor failed (%s): %s. Falling back to legacy.", exc.kind, exc)
        return _process_legacy(file_bytes, "pdf", error_kind=exc.kind, error_message=str(exc))

    blocks = extracted_doc.get("blocks") or []

    # Stage 3: project to PO shape (this also produces our doc classification)
    projection = project_purchase_order(extracted_doc)
    metadata = projection.get("metadata") or {}
    products = projection.get("products") or []
    confidence = projection.get("confidence") or {}

    # Classify based on projection confidence (NOT on the old circular logic)
    doc_type = _classify_from_confidence(confidence)

    tables = _build_legacy_tables(products)
    content_markdown = _build_markdown(doc_type, metadata, products)

    extractor_name = (extracted_doc.get("stats") or {}).get("extractor", "gemini-block-v1")

    return {
        "doc_type": doc_type,
        "content_markdown": content_markdown,
        "extracted_data": {
            # ── Legacy fields (consumed by all current downstream code) ──
            "metadata": metadata,
            "products": products,
            "tables": tables,
            "field_evidence": {},
            "raw_extraction": {
                "schema_version": EXTRACTION_SCHEMA_VERSION,
                "title": extracted_doc.get("title"),
                "language": extracted_doc.get("language"),
                "page_count": extracted_doc.get("page_count"),
                "stats": extracted_doc.get("stats"),
                "block_count": len(blocks),
            },
            # ── New fields (Stage 1 v1.0) ──
            "extraction_schema_version": EXTRACTION_SCHEMA_VERSION,
            "blocks": blocks,
            "title": extracted_doc.get("title"),
            "language": extracted_doc.get("language"),
            "page_count": extracted_doc.get("page_count"),
            "projection": {
                "purchase_order": {
                    "confidence": confidence,
                },
            },
        },
        "extraction_method": extractor_name,
        "product_count": len(products),
    }


def _classify_from_confidence(confidence: dict[str, Any]) -> str:
    """Decide doc_type from PO projection confidence.

    This replaces the old circular `_classify_document` which assumed
    'if Gemini returned po_number, it must be a PO'. Now we have a real
    multi-signal verdict.
    """
    verdict = confidence.get("verdict")
    if verdict == "purchase_order":
        return "purchase_order"
    if verdict == "possibly_purchase_order":
        # Conservative: ambiguous documents go to "unknown" so they don't
        # silently get treated as POs by the rest of the pipeline.
        # The user can review and manually re-classify if needed.
        return "unknown"
    return "unknown"


# ─── Legacy fallback (excel + PDF errors) ───────────────────────────────────


def _process_legacy(
    file_bytes: bytes,
    file_type: str,
    *,
    error_kind: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    """Original pipeline using smart_extract. Used for excel and as PDF fallback."""
    from services.order_processor import smart_extract

    extracted = smart_extract(file_bytes, file_type)
    metadata = extracted.get("order_metadata") or {}
    products = extracted.get("products") or []
    tables = _build_legacy_tables(products)
    doc_type = _classify_document_legacy(metadata, products, file_type)
    content_markdown = _build_markdown(doc_type, metadata, products)

    extracted_data = {
        "metadata": metadata,
        "products": products,
        "tables": tables,
        "field_evidence": {},
        "raw_extraction": extracted,
    }
    if error_kind:
        extracted_data["new_extractor_error"] = {"kind": error_kind, "message": error_message}

    return {
        "doc_type": doc_type,
        "content_markdown": content_markdown,
        "extracted_data": extracted_data,
        "extraction_method": extracted.get("extraction_method", "unknown"),
        "product_count": len(products),
    }


def _classify_document_legacy(metadata: dict[str, Any], products: list[dict[str, Any]], file_type: str) -> str:
    if metadata.get("po_number") or products:
        return "purchase_order"
    if file_type == "excel" and metadata:
        return "spreadsheet_document"
    return "unknown"


# ─── Shared formatters ──────────────────────────────────────────────────────


def _build_legacy_tables(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not products:
        return []

    rows = []
    for product in products:
        rows.append([product.get(header) for header in PRODUCT_HEADERS])

    return [
        {
            "table_id": "products",
            "headers": PRODUCT_HEADERS,
            "rows": rows,
        }
    ]


def _build_markdown(doc_type: str, metadata: dict[str, Any], products: list[dict[str, Any]]) -> str:
    lines = [
        f"# {doc_type}",
        "",
        "## Metadata",
    ]

    for key in (
        "po_number",
        "ship_name",
        "vendor_name",
        "delivery_date",
        "order_date",
        "currency",
        "destination_port",
        "total_amount",
    ):
        value = metadata.get(key)
        if value not in (None, "", []):
            lines.append(f"- {key}: {value}")

    if not products:
        return "\n".join(lines)

    lines.extend([
        "",
        "## Products",
        "| line_number | product_code | product_name | quantity | unit | unit_price | total_price |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ])

    for product in products:
        row = [str(product.get(header, "") or "") for header in PRODUCT_HEADERS]
        safe_row = [cell.replace("|", "\\|").replace("\n", " ").strip() for cell in row]
        lines.append("| " + " | ".join(safe_row) + " |")

    return "\n".join(lines)
