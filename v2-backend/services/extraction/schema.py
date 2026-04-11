"""Universal document block schema (Stage 1 output).

This is the contract between the extraction layer and everything downstream.
Any extractor backend (Gemini, Document AI, future plugins) MUST produce
output matching `ExtractedDocument`. Any consumer (PO projector, invoice
projector, UI) MUST be able to read it.

Schema version 1.0 — bump SCHEMA_VERSION when making breaking changes.
Adding optional fields is non-breaking. Removing or renaming fields is.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict, Union

EXTRACTION_SCHEMA_VERSION = "1.0"


# ─── Block types ────────────────────────────────────────────────────────────

BlockType = Literal[
    "heading",
    "paragraph",
    "field_group",
    "table",
    "list",
    "signature_block",
    "other",
]

SectionHint = Literal["header", "body", "footer", "unknown"]


class HeadingBlock(TypedDict, total=False):
    type: Literal["heading"]
    text: str
    level: int  # 1 = biggest (document title), 3 = smallest
    page: int


class ParagraphBlock(TypedDict, total=False):
    type: Literal["paragraph"]
    text: str
    section: SectionHint
    page: int


class FieldEntry(TypedDict, total=False):
    label: str  # original label as shown in the document
    value: str | None  # null if value is missing or unreadable


class FieldGroupBlock(TypedDict, total=False):
    type: Literal["field_group"]
    section: SectionHint
    fields: list[FieldEntry]
    page: int


class TableBlock(TypedDict, total=False):
    type: Literal["table"]
    caption: str | None
    columns: list[str]  # column headers as they appear in the document
    rows: list[dict[str, Any]]  # each row keyed by column name
    page: int | list[int]  # int for single-page table, list[int] for multi-page


class ListBlock(TypedDict, total=False):
    type: Literal["list"]
    style: Literal["bullet", "numbered"]
    items: list[str]
    section: SectionHint
    page: int


class SignatureBlock(TypedDict, total=False):
    type: Literal["signature_block"]
    labels: list[str]
    values: list[str | None]
    page: int


class OtherBlock(TypedDict, total=False):
    """Escape hatch for content the extractor can't classify."""
    type: Literal["other"]
    text: str
    page: int


Block = Union[
    HeadingBlock,
    ParagraphBlock,
    FieldGroupBlock,
    TableBlock,
    ListBlock,
    SignatureBlock,
    OtherBlock,
]


# ─── Document envelope ──────────────────────────────────────────────────────


class ExtractionStats(TypedDict, total=False):
    extractor: str  # e.g. "gemini-2.5-flash" or "documentai/form-parser-v1"
    elapsed_seconds: float
    input_tokens: int | None
    output_tokens: int | None
    finish_reason: str | None  # raw provider value, e.g. "STOP" or "MAX_TOKENS"
    truncated: bool  # True iff finish_reason indicates output truncation


class ExtractedDocument(TypedDict, total=False):
    schema_version: str  # always EXTRACTION_SCHEMA_VERSION for new records
    language: str | None  # ISO 639 code, e.g. "en", "zh", "ja"; None if unknown
    page_count: int | None
    title: str | None  # most prominent heading, or None
    blocks: list[Block]
    stats: ExtractionStats
