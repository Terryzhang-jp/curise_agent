"""Base interface for document extractors.

All extractor backends (Gemini, Document AI, future plugins) implement
`BaseExtractor`. The contract is intentionally narrow:

    bytes → ExtractedDocument

The extractor is responsible for:
  - Reading the file (PDF, image, etc.)
  - Producing semantic blocks
  - Reporting failure conditions (truncation, parse errors) explicitly

The extractor is NOT responsible for:
  - Knowing what the document means (PO/invoice/quotation/...)
  - Storing anything in DB
  - Deciding what to do next
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from services.extraction.schema import ExtractedDocument


class ExtractionError(Exception):
    """Raised when an extractor cannot produce a valid ExtractedDocument.

    Use the `kind` field to distinguish:
      - "config":     missing API key, bad model name, etc.
      - "input":      file too large, unsupported MIME, corrupt PDF
      - "provider":   upstream API error, network failure
      - "truncated":  output exceeded max_output_tokens
      - "parse":      provider returned a response we couldn't decode
      - "empty":      no usable content found
    """

    def __init__(self, message: str, kind: str = "provider"):
        super().__init__(message)
        self.kind = kind


class BaseExtractor(ABC):
    """Pluggable document extractor."""

    name: str = "base"

    @abstractmethod
    def extract(self, file_bytes: bytes, mime_type: str) -> ExtractedDocument:
        """Extract structured content from a document.

        Args:
            file_bytes: Raw file bytes.
            mime_type:  E.g. "application/pdf".

        Returns:
            An ExtractedDocument matching schema_version 1.0.

        Raises:
            ExtractionError: On any unrecoverable failure.
        """
        raise NotImplementedError
