"""PDF structure analysis service using Gemini AI.

Two core functions:
- analyze_pdf_structure: Analyze a PDF to discover its layout and fields (template creation)
- extract_with_prompt: Extract data from a PDF using a saved layout prompt (order parsing)
"""

import io
import json
import re
import logging
import tempfile
import os

import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from pdf2image import convert_from_bytes
from PIL import Image

from config import settings

logger = logging.getLogger(__name__)

ANALYSIS_PROMPT = """Analyze this document image(s) and return a JSON object describing its structure.

Return ONLY a valid JSON object (no markdown, no code blocks, no explanation).

Required JSON structure:
{
  "document_type": "string (e.g. 'Purchase Order', 'Invoice', 'Quotation Request')",
  "metadata_fields": [
    {
      "key": "snake_case_key (e.g. 'po_number', 'delivery_date')",
      "label": "Original label as shown in document (e.g. 'Purchase Order #')",
      "value": "The actual value found (e.g. '68358749')"
    }
  ],
  "table": {
    "columns": [
      {"key": "A", "label": "Column header text (e.g. 'Product Number')"}
    ],
    "row_count": 73,
    "sample_rows": [
      ["cell1", "cell2", "cell3", "..."],
      ["cell1", "cell2", "cell3", "..."]
    ]
  },
  "layout_prompt": "A detailed prompt describing this document's layout for future extraction. Include: where headers are, where the table starts, column order, and any special formatting notes. This prompt will be injected into future AI calls to parse similar documents."
}

Instructions:
1. Identify ALL metadata fields in the header/footer area (PO number, dates, vendor info, currency, ship name, etc.)
2. Use descriptive snake_case keys for metadata_fields (e.g. po_number, delivery_date, vendor_name, currency, ship_name, destination_port)
3. Identify the main data table: list all column headers and provide up to 5 sample rows
4. Count total data rows in the table
5. Write a detailed layout_prompt that describes the document structure precisely enough for another AI to extract data from similar documents
6. Return ONLY the JSON object — start with { and end with }
"""


def _get_model():
    """Initialize and return a Gemini model instance."""
    if not settings.GOOGLE_API_KEY:
        raise ValueError("GOOGLE_API_KEY 未配置")
    genai.configure(api_key=settings.GOOGLE_API_KEY)
    return genai.GenerativeModel(
        "gemini-2.5-flash",
        generation_config={
            "temperature": 0.1,
            "top_p": 0.95,
            "max_output_tokens": 20000,
        },
        safety_settings={
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
        },
    )


def _pdf_bytes_to_images(file_bytes: bytes, dpi: int = 200) -> list[Image.Image]:
    """Convert PDF bytes to a list of PIL Images."""
    return convert_from_bytes(file_bytes, dpi=dpi)


def _parse_json_response(text: str) -> dict:
    """Extract a JSON object from Gemini response text, handling markdown wrappers."""
    text = text.strip()

    def _try_parse(s: str) -> dict | None:
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass
        # Fix common invalid escapes (e.g. LaTeX \frac, \text) by replacing
        # lone backslashes that are not valid JSON escapes.
        fixed = re.sub(
            r'\\(?!["\\/bfnrtu])',
            r'\\\\',
            s,
        )
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            return None

    result = _try_parse(text)
    if result is not None:
        return result
    # Try extracting from ```json ... ```
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        result = _try_parse(m.group(1))
        if result is not None:
            return result
    # Try extracting first { ... }
    m = re.search(r"(\{.*\})", text, re.DOTALL)
    if m:
        result = _try_parse(m.group(1))
        if result is not None:
            return result
    raise ValueError("无法从 AI 响应中提取有效 JSON")


def analyze_pdf_structure(file_bytes: bytes) -> dict:
    """Analyze a PDF document to discover its structure and fields.

    Used during template creation. Sends PDF pages as images to Gemini
    and returns document type, metadata fields, table structure, and
    a layout prompt for future extraction.

    Returns:
        {
            "document_type": "Purchase Order",
            "metadata_fields": [...],
            "table": {"columns": [...], "row_count": N, "sample_rows": [...]},
            "layout_prompt": "..."
        }
    """
    model = _get_model()

    logger.info("Converting PDF to images...")
    images = _pdf_bytes_to_images(file_bytes)
    logger.info(f"Converted {len(images)} pages")

    # Build content: prompt + all page images
    content = [ANALYSIS_PROMPT] + images

    logger.info("Calling Gemini API for PDF structure analysis...")
    response = model.generate_content(content)
    response_text = response.text.strip()

    logger.info(f"Gemini response length: {len(response_text)} chars")

    result = _parse_json_response(response_text)

    # Ensure expected keys exist
    result.setdefault("document_type", "Unknown")
    result.setdefault("metadata_fields", [])
    result.setdefault("table", {"columns": [], "row_count": 0, "sample_rows": []})
    result.setdefault("layout_prompt", "")

    logger.info(
        f"PDF analysis complete: type={result['document_type']}, "
        f"metadata_fields={len(result['metadata_fields'])}, "
        f"table_columns={len(result['table'].get('columns', []))}, "
        f"table_rows={result['table'].get('row_count', 0)}"
    )

    return result


def extract_with_prompt(file_bytes: bytes, layout_prompt: str, fields: list[dict]) -> dict:
    """Extract structured data from a PDF using a saved layout prompt.

    Used during order parsing — injects the template's layout prompt and
    the list of fields to extract.

    Args:
        file_bytes: PDF file content
        layout_prompt: The layout prompt saved in the template
        fields: List of field definitions to extract, e.g.
                [{"key": "po_number", "label": "PO Number"}, ...]

    Returns:
        {
            "metadata": {"po_number": "68358749", ...},
            "rows": [{"product_name": "...", "quantity": 100, ...}, ...]
        }
    """
    model = _get_model()
    images = _pdf_bytes_to_images(file_bytes)

    # Build field list for the prompt
    field_list = "\n".join(f"- {f['key']}: {f.get('label', f['key'])}" for f in fields)

    extraction_prompt = f"""You are extracting data from a document with this known layout:

{layout_prompt}

Extract the following fields:
{field_list}

Return ONLY a valid JSON object (no markdown, no code blocks):
{{
  "metadata": {{
    "field_key": "extracted value",
    ...
  }},
  "rows": [
    {{"column_key": "cell value", ...}},
    ...
  ]
}}

Instructions:
- Extract ALL rows from the data table
- Use the exact field keys specified above
- Numbers should be actual numbers, not strings
- Dates should be in their original format as shown in the document
- If a field is not found, use null
- Return ONLY the JSON object
"""

    content = [extraction_prompt] + images
    response = model.generate_content(content)
    return _parse_json_response(response.text.strip())
