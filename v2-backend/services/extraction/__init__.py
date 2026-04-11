"""Universal document extraction layer (Stage 1).

This package is type-agnostic: it knows how to take a PDF (or other document)
and produce a structured `ExtractedDocument` with semantic blocks (headings,
paragraphs, field groups, tables, lists). It does NOT know what an "order" or
an "invoice" is — that domain interpretation lives in `services/projection/`.

The split exists so we can extract any kind of document without having to
hard-code a domain schema in the prompt or post-processing.
"""

from services.extraction.base import BaseExtractor, ExtractionError
from services.extraction.schema import (
    EXTRACTION_SCHEMA_VERSION,
    Block,
    BlockType,
    ExtractedDocument,
    FieldGroupBlock,
    HeadingBlock,
    ListBlock,
    ParagraphBlock,
    TableBlock,
)
from services.extraction.gemini_block import GeminiBlockExtractor

__all__ = [
    "EXTRACTION_SCHEMA_VERSION",
    "BaseExtractor",
    "ExtractionError",
    "GeminiBlockExtractor",
    "ExtractedDocument",
    "Block",
    "BlockType",
    "HeadingBlock",
    "ParagraphBlock",
    "FieldGroupBlock",
    "TableBlock",
    "ListBlock",
]
