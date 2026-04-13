"""Google Document AI OCR extractor (Stage 1).

Uses the OCR_PROCESSOR to extract text layout and tables with accurate
per-element bounding boxes. This is the default extractor for all PDF
and image inputs.

Architecture:
  Document AI handles structural extraction (what's on the page, where).
  The PO projector (purchase_order.py) handles semantic interpretation
  (which paragraph is the PO number, which table has products).

  These are intentionally separate concerns. Document AI is NOT called
  again for semantic work, and no other AI (Gemini, etc.) is involved
  in this layer.

Document AI OCR Processor native output:
  page.blocks[]      — visual layout blocks (groups of paragraphs)
  page.paragraphs[]  — individual text paragraphs with bboxes
  page.lines[]       — individual lines
  page.tables[]      — tables with header rows + body rows, with bboxes
  page.tokens[]      — individual tokens (not used here)

NOTE: form_fields (key-value pairs) are NOT available in the OCR Processor.
That is a Form Parser feature. We use OCR because it handles arbitrary
document layouts without requiring a trained form template.
"""

from __future__ import annotations

import io
import logging
import time
from typing import Any

from services.extraction.base import BaseExtractor, ExtractionError
from services.extraction.schema import (
    EXTRACTION_SCHEMA_VERSION,
    ExtractedDocument,
    ExtractionStats,
)

logger = logging.getLogger(__name__)

SUPPORTED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/tiff",
}


class DocumentAIExtractor(BaseExtractor):
    """Google Document AI OCR extractor.

    Returns the universal block schema with accurate bounding boxes on every
    paragraph and table. No prompting, no generative model involved.
    """

    name = "document-ai-ocr-v1"

    def __init__(
        self,
        project_id: str | None = None,
        processor_id: str | None = None,
        location: str | None = None,
    ):
        try:
            from core.config import settings
            self._project_id = project_id or settings.DOCUMENT_AI_PROJECT_ID
            self._processor_id = processor_id or settings.DOCUMENT_AI_PROCESSOR_ID
            self._location = location or settings.DOCUMENT_AI_LOCATION or "us"
        except Exception:
            self._project_id = project_id or ""
            self._processor_id = processor_id or ""
            self._location = location or "us"

        if not self._project_id or not self._processor_id:
            raise ExtractionError(
                "DOCUMENT_AI_PROJECT_ID and DOCUMENT_AI_PROCESSOR_ID must be configured",
                kind="config",
            )

    # Document AI OCR processor page limit (imageless mode = 30, non-imageless = 15)
    _PAGE_LIMIT = 30

    def extract(self, file_bytes: bytes, mime_type: str = "application/pdf") -> ExtractedDocument:
        if not file_bytes:
            raise ExtractionError("Empty file", kind="input")
        if mime_type not in SUPPORTED_MIME_TYPES:
            raise ExtractionError(
                f"Unsupported mime type: {mime_type}. "
                f"Supported: {', '.join(sorted(SUPPORTED_MIME_TYPES))}",
                kind="input",
            )

        try:
            from google.cloud import documentai_v1 as documentai
        except ImportError as exc:
            raise ExtractionError(
                f"google-cloud-documentai not installed: {exc}", kind="config"
            )

        # Split PDF into chunks if it exceeds the page limit
        if mime_type == "application/pdf":
            chunks = _split_pdf(file_bytes, self._PAGE_LIMIT)
        else:
            chunks = [(file_bytes, 0)]  # (chunk_bytes, page_offset)

        client = documentai.DocumentProcessorServiceClient()
        processor_name = client.processor_path(
            self._project_id, self._location, self._processor_id
        )

        all_blocks: list[dict] = []
        total_page_count = 0
        total_elapsed = 0.0

        for chunk_bytes, page_offset in chunks:
            start = time.time()
            try:
                result = client.process_document(
                    request=documentai.ProcessRequest(
                        name=processor_name,
                        raw_document=documentai.RawDocument(
                            content=chunk_bytes, mime_type=mime_type
                        ),
                        # imageless_mode skips rendering page images — raises limit from 15 to 30
                        imageless_mode=True,
                    )
                )
            except Exception as exc:
                raise ExtractionError(
                    f"Document AI API error: {exc}", kind="provider"
                ) from exc
            elapsed = time.time() - start
            total_elapsed += elapsed

            doc = result.document
            full_text: str = doc.text or ""
            chunk_page_count = len(doc.pages)
            total_page_count += chunk_page_count

            blocks = _convert_document(doc, full_text, page_offset=page_offset)
            all_blocks.extend(blocks)

            logger.info(
                "DocumentAIExtractor: chunk pages %d–%d → %d blocks in %.1fs",
                page_offset + 1, page_offset + chunk_page_count, len(blocks), elapsed,
            )

        logger.info(
            "DocumentAIExtractor: total %d pages → %d blocks in %.1fs",
            total_page_count, len(all_blocks), total_elapsed,
        )

        return ExtractedDocument(
            schema_version=EXTRACTION_SCHEMA_VERSION,
            language=None,
            page_count=total_page_count,
            title=_first_heading(all_blocks),
            blocks=all_blocks,
            stats=ExtractionStats(
                extractor=self.name,
                elapsed_seconds=round(total_elapsed, 2),
                input_tokens=None,
                output_tokens=None,
                finish_reason="STOP",
                truncated=False,
            ),
        )


# ─── Document → Block conversion ────────────────────────────────────────────


def _split_pdf(file_bytes: bytes, page_limit: int) -> list[tuple[bytes, int]]:
    """Split a PDF into chunks of at most page_limit pages.

    Returns a list of (chunk_bytes, page_offset) tuples where page_offset is
    the 0-based index of the first page in that chunk within the original doc.
    """
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        # pypdf not available — return as single chunk and let Document AI error naturally
        logger.warning("pypdf not installed; cannot split large PDF, sending as-is")
        return [(file_bytes, 0)]

    reader = PdfReader(io.BytesIO(file_bytes))
    total = len(reader.pages)

    if total <= page_limit:
        return [(file_bytes, 0)]

    chunks: list[tuple[bytes, int]] = []
    for start in range(0, total, page_limit):
        end = min(start + page_limit, total)
        writer = PdfWriter()
        for i in range(start, end):
            writer.add_page(reader.pages[i])
        buf = io.BytesIO()
        writer.write(buf)
        chunks.append((buf.getvalue(), start))
        logger.info("_split_pdf: chunk pages %d–%d of %d", start + 1, end, total)

    return chunks


def _convert_document(doc: Any, full_text: str, page_offset: int = 0) -> list[dict]:
    """Convert a Document AI document to the universal block list.

    Output is strictly native Document AI structure:
      - Tables   → TableBlock  (Document AI natively detects tables)
      - Paragraphs → ParagraphBlock (Document AI natively detects paragraphs)

    Semantic interpretation (which paragraph = PO number, etc.) is left
    entirely to the downstream projector.

    page_offset: added to each block's page number so multi-chunk docs have
    globally correct page numbers.
    """
    blocks: list[dict] = []

    for page in doc.pages:
        page_num: int = page.page_number + page_offset

        # ── Tables ──────────────────────────────────────────────────────────
        # Collect table bboxes so we can exclude overlapping paragraph blocks
        table_bboxes: list[list[int]] = []
        for table in page.tables:
            block = _table_block(table, full_text, page_num)
            if block:
                blocks.append(block)
                if block.get("bbox"):
                    table_bboxes.append(block["bbox"])

        # ── Paragraphs ──────────────────────────────────────────────────────
        # Output every paragraph as-is. The projector reads Label:Value
        # patterns from paragraph text directly (Pass 2 in purchase_order.py).
        for para in page.paragraphs:
            text = _get_text(para.layout.text_anchor, full_text)
            if not text:
                continue
            bbox = _bbox_from_poly(para.layout.bounding_poly)
            # Skip text that falls inside a table we already captured
            if bbox and _inside_any_table(bbox, table_bboxes):
                continue
            block: dict = {
                "type": "paragraph",
                "text": text,
                "section": "unknown",
                "page": page_num,
            }
            if bbox:
                block["bbox"] = bbox
            blocks.append(block)

    return blocks


def _table_block(table: Any, full_text: str, page_num: int) -> dict | None:
    """Convert a Document AI Table to a TableBlock."""
    columns: list[str] = []
    if table.header_rows:
        for cell in table.header_rows[0].cells:
            columns.append(
                _get_text(cell.layout.text_anchor, full_text).strip()
                or f"col{len(columns)}"
            )

    rows: list[dict] = []
    for row in table.body_rows:
        row_data: dict = {}
        for i, cell in enumerate(row.cells):
            key = columns[i] if i < len(columns) else f"col{i}"
            row_data[key] = _get_text(cell.layout.text_anchor, full_text).strip() or None
        rows.append(row_data)

    if not columns and not rows:
        return None

    block: dict = {
        "type": "table",
        "caption": None,
        "columns": columns,
        "rows": rows,
        "page": page_num,
    }
    bbox = _bbox_from_poly(table.layout.bounding_poly)
    if bbox:
        block["bbox"] = bbox
    return block


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _get_text(text_anchor: Any, full_text: str) -> str:
    """Reconstruct text from a Document AI TextAnchor using the full document text."""
    if not text_anchor or not text_anchor.text_segments:
        return ""
    parts = []
    for seg in text_anchor.text_segments:
        start = int(seg.start_index) if seg.start_index else 0
        end = int(seg.end_index) if seg.end_index else 0
        if end > start:
            parts.append(full_text[start:end])
    return "".join(parts).strip()


def _bbox_from_poly(bounding_poly: Any) -> list[int] | None:
    """Convert Document AI normalized_vertices → [y1, x1, y2, x2] in 0–1000."""
    if not bounding_poly:
        return None
    verts = bounding_poly.normalized_vertices
    if not verts:
        return None
    xs = [v.x for v in verts]
    ys = [v.y for v in verts]
    if not xs or not ys:
        return None
    return [
        int(min(ys) * 1000),
        int(min(xs) * 1000),
        int(max(ys) * 1000),
        int(max(xs) * 1000),
    ]


def _inside_any_table(bbox: list[int], table_bboxes: list[list[int]]) -> bool:
    """Return True if bbox is fully contained within any table bbox (with 10-unit tolerance)."""
    y1, x1, y2, x2 = bbox
    for ty1, tx1, ty2, tx2 in table_bboxes:
        if y1 >= ty1 - 10 and x1 >= tx1 - 10 and y2 <= ty2 + 10 and x2 <= tx2 + 10:
            return True
    return False


def _first_heading(blocks: list[dict]) -> str | None:
    """Return text of the first short paragraph (likely a document title)."""
    for block in blocks:
        if block.get("type") == "paragraph":
            text = (block.get("text") or "").strip()
            if text and len(text) < 150 and "\n" not in text:
                return text
    return None
