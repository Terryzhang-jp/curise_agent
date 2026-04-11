"""Gemini-backed universal block extractor (Stage 1).

Sends the entire PDF to Gemini 2.5 Flash in a single call and asks for a
universal block schema. Does NOT assume any document type. Does NOT impose
PO field names. The output is faithful to the document's structure.

Why single-call (no chunking):
  - Gemini 2.5 Flash supports 1M input tokens and 65,535 output tokens.
  - 1 PDF page ≈ 258 input tokens. A 30 MB / ~200 page PDF fits comfortably.
  - 65K output ≈ 500-600 product rows in structured JSON form.
  - Chunking would lose cross-page context (table headers on page 1, rows on
    page 2-N) which is the dominant failure mode of naive chunking.
  - Truncation is explicitly detected via finish_reason — we fail loud,
    not silent.

If we ever need to handle 1000-page documents we will add a chunking fallback
in a separate file. Until then, single-call wins on simplicity and quality.
"""

from __future__ import annotations

import json
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


# Single source of truth for the model. If the project upgrades models,
# change this constant and re-run the extraction tests.
GEMINI_MODEL = "gemini-2.5-flash"

# Gemini 2.5 Flash hard maximum (per Google docs, April 2026).
# Don't bump this without checking the model card — Gemini 2.0 Flash is 8192,
# Gemini 3 Flash preview is 65536, etc.
MAX_OUTPUT_TOKENS = 65535


# The new prompt is type-agnostic by design. It tells the model:
#   1. The document type is unknown.
#   2. Faithfully extract structure, do not interpret meaning.
#   3. Tables MUST use column headers as keys (the user's explicit ask).
#   4. Field labels MUST stay in original language, no translation.
#   5. Reading order must be preserved.
EXTRACTION_PROMPT = """You are extracting structured content from a business document.

The document type is UNKNOWN. It could be a purchase order, invoice, quotation,
contract, shipping document, packing list, delivery note, or anything else.
Your job is to faithfully extract the document's content while preserving
its semantic structure. Do NOT interpret what the document means. Do NOT
force the content into any particular schema.

Return a single JSON object with this exact shape:

{
  "language": "en" | "zh" | "ja" | ...   // ISO 639 code, or null if mixed/unknown
  "page_count": <integer>,
  "title": "the document's most prominent title text, or null",
  "blocks": [
    // ordered array of blocks, in reading order
  ]
}

Each block in `blocks` MUST be one of these shapes:

1. HEADING — a title or section header
   {
     "type": "heading",
     "level": 1 | 2 | 3,        // 1 = biggest (document title), 3 = smallest
     "text": "...",
     "page": <int>
   }

2. PARAGRAPH — a block of running prose (instructions, notes, terms)
   {
     "type": "paragraph",
     "text": "...",
     "section": "header" | "body" | "footer" | "unknown",
     "page": <int>
   }

3. FIELD_GROUP — a group of "Label: Value" pairs (very common in headers)
   {
     "type": "field_group",
     "section": "header" | "body" | "footer" | "unknown",
     "fields": [
       { "label": "PO Number", "value": "12345" },
       { "label": "Vendor",    "value": "ABC Corp" },
       { "label": "Date",      "value": null }   // null if missing
     ],
     "page": <int>
   }

4. TABLE — tabular data
   {
     "type": "table",
     "caption": "Items to deliver" | null,
     "columns": ["Code", "Description", "Qty", "Unit", "Price", "Total"],
     "rows": [
       { "Code": "SKU-001", "Description": "...", "Qty": "10", "Unit": "kg", "Price": "1.50", "Total": "15.00" },
       { "Code": "SKU-002", "Description": "...", "Qty": "5",  "Unit": "kg", "Price": "2.00", "Total": "10.00" }
     ],
     "page": <int> | [<int>, <int>, ...]   // list when the table spans pages
   }

5. LIST — bullet or numbered list
   {
     "type": "list",
     "style": "bullet" | "numbered",
     "items": ["item 1", "item 2"],
     "section": "header" | "body" | "footer" | "unknown",
     "page": <int>
   }

6. SIGNATURE_BLOCK — labeled signature lines
   {
     "type": "signature_block",
     "labels": ["Authorized by", "Date"],
     "values": [null, null],   // fill in if visible, otherwise null
     "page": <int>
   }

7. OTHER — escape hatch for content that doesn't fit anything above
   {
     "type": "other",
     "text": "...",
     "page": <int>
   }

CRITICAL RULES (read carefully):

A. READING ORDER. Blocks must appear in the order they appear in the
   document. Top-of-page header before body before bottom-of-page footer.
   Page 1 before page 2.

B. TABLES — use column headers as keys.
   - ALWAYS make `rows` an array of objects keyed by the column header.
   - Use the column headers EXACTLY as they appear in the document.
     If the header is "Item Code", use "Item Code" — don't normalize to
     "item_code" or "code".
   - If a table spans multiple pages, merge it into ONE table block whose
     `page` field is a list of pages. Only put the column headers ONCE.
   - If a table has no obvious header row, set columns to ["col1", "col2",
     ...] and note "headers were missing" in the caption.

C. FIELD GROUPS — keep labels in the original language.
   - If the label says "供应商", use "供应商" as the label, not "Vendor".
   - If the label says "PO #", use "PO #", not "PO Number".
   - Group contiguous label-value pairs together. Don't split them across
     multiple field_group blocks unless they are visually separated.

D. DON'T FABRICATE.
   - If a value is unclear or missing, use null. Do not guess.
   - Do not infer dates, quantities, or prices that are not visible.

E. DON'T INTERPRET.
   - Do not classify the document type. That's not your job.
   - Do not add fields that are not explicitly visible in the document.
   - Do not "fix" mistakes you see in the document.

F. EXTRACT EVERY PAGE. Do not skip pages. Do not skip table rows.
   If the document has 100 product rows, return all 100 — not the first 20
   plus an "... and so on".

G. BLOCK ORDERING is CRITICAL. The downstream consumer relies on the order
   of blocks to reconstruct the document flow.

Output ONLY the JSON object. No prose before or after. No markdown fences.
"""


class GeminiBlockExtractor(BaseExtractor):
    """Universal extractor backed by Gemini 2.5 Flash native PDF input."""

    name = "gemini-block-v1"

    def __init__(self, api_key: str | None = None, model: str = GEMINI_MODEL):
        if not api_key:
            try:
                from core.config import settings
                api_key = settings.GOOGLE_API_KEY
            except Exception:
                api_key = None
        if not api_key:
            raise ExtractionError("GOOGLE_API_KEY not configured", kind="config")
        self._api_key = api_key
        self._model = model

    def extract(self, file_bytes: bytes, mime_type: str = "application/pdf") -> ExtractedDocument:
        if not file_bytes:
            raise ExtractionError("Empty file", kind="input")

        if mime_type != "application/pdf":
            raise ExtractionError(
                f"Unsupported mime type: {mime_type}. Only application/pdf is supported by this extractor.",
                kind="input",
            )

        # Lazy import so test environments without google-genai installed still load the module
        try:
            from google import genai
            from google.genai import types
        except Exception as exc:  # pragma: no cover
            raise ExtractionError(f"google-genai not installed: {exc}", kind="config")

        client = genai.Client(api_key=self._api_key)
        pdf_part = types.Part.from_bytes(data=file_bytes, mime_type=mime_type)

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            max_output_tokens=MAX_OUTPUT_TOKENS,
        )

        start = time.time()
        try:
            response = client.models.generate_content(
                model=self._model,
                contents=[pdf_part, EXTRACTION_PROMPT],
                config=config,
            )
        except Exception as exc:
            raise ExtractionError(f"Gemini API error: {exc}", kind="provider") from exc
        elapsed = time.time() - start

        # Detect truncation BEFORE attempting to parse — a truncated JSON
        # produces nonsense if we try to json.loads it.
        finish_reason = _extract_finish_reason(response)
        truncated = bool(finish_reason and finish_reason.upper() not in ("STOP", "FINISH_REASON_STOP"))

        raw_text = (response.text or "").strip()
        if not raw_text:
            raise ExtractionError(
                f"Gemini returned empty response (finish_reason={finish_reason})",
                kind="empty",
            )

        if truncated:
            raise ExtractionError(
                f"Gemini output was truncated (finish_reason={finish_reason}). "
                f"This document is too large for a single-call extraction. "
                f"Output budget was {MAX_OUTPUT_TOKENS} tokens. "
                f"Consider splitting the document or contacting support.",
                kind="truncated",
            )

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            # Sometimes Gemini wraps JSON in ```json fences despite being told not to
            cleaned = _strip_json_fences(raw_text)
            try:
                data = json.loads(cleaned)
            except json.JSONDecodeError:
                raise ExtractionError(
                    f"Failed to parse Gemini JSON response: {exc}. First 500 chars: {raw_text[:500]}",
                    kind="parse",
                ) from exc

        if not isinstance(data, dict):
            raise ExtractionError(
                f"Expected JSON object, got {type(data).__name__}",
                kind="parse",
            )

        blocks = data.get("blocks") or []
        if not isinstance(blocks, list):
            raise ExtractionError("blocks field is not a list", kind="parse")

        # Sanitize blocks: drop ones missing 'type', coerce page to int when possible.
        # We are intentionally permissive — partial extraction is better than none.
        clean_blocks = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if not block.get("type"):
                continue
            clean_blocks.append(block)

        usage = _extract_usage(response)

        result: ExtractedDocument = {
            "schema_version": EXTRACTION_SCHEMA_VERSION,
            "language": data.get("language"),
            "page_count": data.get("page_count"),
            "title": data.get("title"),
            "blocks": clean_blocks,
            "stats": ExtractionStats(
                extractor=f"{self._model}/block-v1",
                elapsed_seconds=round(elapsed, 2),
                input_tokens=usage.get("input"),
                output_tokens=usage.get("output"),
                finish_reason=finish_reason,
                truncated=False,
            ),
        }

        logger.info(
            "GeminiBlockExtractor: %d blocks in %.1fs (input=%s output=%s)",
            len(clean_blocks),
            elapsed,
            usage.get("input"),
            usage.get("output"),
        )

        return result


# ─── Helpers ────────────────────────────────────────────────────────────────


def _extract_finish_reason(response: Any) -> str | None:
    """Pull finish_reason out of a Gemini response, tolerating SDK shape changes."""
    try:
        candidates = getattr(response, "candidates", None) or []
        if candidates:
            fr = getattr(candidates[0], "finish_reason", None)
            if fr is None:
                return None
            # SDK enum: convert to str
            return getattr(fr, "name", None) or str(fr)
    except Exception:  # pragma: no cover
        pass
    return None


def _extract_usage(response: Any) -> dict[str, int | None]:
    """Pull token usage out of a Gemini response, tolerating SDK shape changes."""
    try:
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            return {"input": None, "output": None}
        return {
            "input": getattr(usage, "prompt_token_count", None),
            "output": getattr(usage, "candidates_token_count", None),
        }
    except Exception:  # pragma: no cover
        return {"input": None, "output": None}


def _strip_json_fences(text: str) -> str:
    """Remove ```json ... ``` fences if present."""
    text = text.strip()
    if text.startswith("```"):
        # Drop first line and last line
        lines = text.splitlines()
        if len(lines) >= 2:
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            return "\n".join(lines).strip()
    return text
