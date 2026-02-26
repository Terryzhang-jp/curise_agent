import os
import uuid
import hashlib
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from config import settings
from models import User
from routes.auth import get_current_user
from services.excel_parser import parse_excel_file, parse_excel_cell_positions

router = APIRouter(prefix="/excel", tags=["excel"])

UPLOAD_DIR = settings.UPLOAD_DIR
MAX_FILE_SIZE = settings.MAX_UPLOAD_SIZE
ALLOWED_EXTENSIONS = (".xlsx", ".pdf")


async def _read_and_validate(file: UploadFile) -> tuple[bytes, str]:
    """Read uploaded file bytes and validate extension + size."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")
    lower_name = file.filename.lower()
    if not any(lower_name.endswith(ext) for ext in ALLOWED_EXTENSIONS):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx 和 .pdf 文件")
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="文件大小不能超过 10 MB")
    return content, file.filename


async def _read_and_validate_xlsx(file: UploadFile) -> tuple[bytes, str]:
    """Read uploaded file bytes and validate .xlsx extension + size."""
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx 文件")
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="文件大小不能超过 10 MB")
    return content, file.filename


def _save_file(content: bytes, filename: str) -> str:
    """Save file to uploads directory, return relative URL path."""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex[:8]}_{filename}"
    path = os.path.join(UPLOAD_DIR, safe_name)
    with open(path, "wb") as f:
        f.write(content)
    return f"/uploads/{safe_name}"


@router.post("/parse")
async def parse_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Upload an Excel or PDF file -> return headers + sample rows for column mapping.

    For .xlsx: uses openpyxl to parse headers and sample data.
    For .pdf: uses Gemini AI to analyze document structure.
    """
    content, filename = await _read_and_validate(file)
    file_url = _save_file(content, filename)

    if filename.lower().endswith(".pdf"):
        # PDF path: AI-driven analysis
        try:
            from services.pdf_analyzer import analyze_pdf_structure
            analysis = analyze_pdf_structure(content)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"PDF 分析失败: {str(e)}")

        # Convert to a format compatible with the Excel parse result
        table = analysis.get("table", {})
        columns = table.get("columns", [])
        sample_rows = table.get("sample_rows", [])

        # Build headers from table columns
        headers = [{"column": col["key"], "label": col["label"]} for col in columns]

        # Compute a fingerprint from column labels
        labels_str = "|".join(sorted(col["label"].lower().strip() for col in columns if col.get("label")))
        fingerprint = hashlib.sha256(labels_str.encode()).hexdigest()[:16] if labels_str else ""

        return {
            "file_type": "pdf",
            "sheets": [
                {
                    "name": "PDF Document",
                    "headers": headers,
                    "header_row": 1,
                    "data_start_row": 2,
                    "sample_rows": sample_rows,
                    "total_rows": table.get("row_count", len(sample_rows)),
                    "fingerprint": fingerprint,
                }
            ],
            "metadata": {
                "document_type": analysis.get("document_type", ""),
                "fields": analysis.get("metadata_fields", []),
            },
            "layout_prompt": analysis.get("layout_prompt", ""),
            "file_url": file_url,
        }
    else:
        # Excel path: original logic
        try:
            result = parse_excel_file(content)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Excel 解析失败: {str(e)}")
        result["file_url"] = file_url
        result["file_type"] = "excel"
        return result


@router.post("/parse-cells")
async def parse_excel_cells(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Upload an Excel file -> return all non-empty cell positions (for supplier template mapping)."""
    content, filename = await _read_and_validate_xlsx(file)
    try:
        result = parse_excel_cell_positions(content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Excel 解析失败: {str(e)}")
    file_url = _save_file(content, filename)
    result["file_url"] = file_url
    return result
