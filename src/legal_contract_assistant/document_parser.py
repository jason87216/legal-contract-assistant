"""Safely extract text from user-provided TXT, PDF or DOCX contracts.

This module extracts selectable text; scanned/image-only PDFs require OCR.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_EXTRACTED_CHARS = 250_000
MAX_PDF_PAGES = 100
MAX_DOCX_UNCOMPRESSED_BYTES = 40 * 1024 * 1024
ALLOWED_EXTENSIONS = frozenset({".txt", ".pdf", ".docx"})


class DocumentParseError(ValueError):
    """Validation or text-extraction failure that can be shown to the user."""


def extract_contract_text(filename: str, data: bytes) -> str:
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise DocumentParseError("僅支援 TXT、PDF、DOCX（不支援舊版 .doc）。")
    if not data:
        raise DocumentParseError("上傳檔案是空的。")
    if len(data) > MAX_UPLOAD_BYTES:
        raise DocumentParseError("檔案超過 8 MB 上傳上限。")

    try:
        if extension == ".txt":
            extracted = data.decode("utf-8-sig")
        elif extension == ".pdf":
            extracted = _pdf_text(data)
        else:
            extracted = _docx_text(data)
    except DocumentParseError:
        raise
    except (ValueError, RuntimeError, OSError, BadZipFile, UnicodeError) as exc:
        raise DocumentParseError("檔案格式損壞、受密碼保護或無法讀取。") from exc
    except Exception as exc:
        # Parser libraries can raise their own format-specific exceptions.
        raise DocumentParseError("無法解析檔案，請確認內容與副檔名相符。") from exc

    if len(extracted) > MAX_EXTRACTED_CHARS:
        raise DocumentParseError("合約文字超過 250,000 字上限，請分段審查。")
    if not extracted.strip():
        raise DocumentParseError(
            "檔案沒有可擷取的文字；掃描 PDF 或圖片內容需先進行 OCR（文字辨識）。"
        )
    return extracted.strip()


def _pdf_text(data: bytes) -> str:
    if not data.startswith(b"%PDF-"):
        raise DocumentParseError("檔案不是有效的 PDF 格式。")
    reader = PdfReader(BytesIO(data), strict=True)
    if reader.is_encrypted:
        raise DocumentParseError("不支援受密碼保護的 PDF。")
    if len(reader.pages) > MAX_PDF_PAGES:
        raise DocumentParseError("PDF 超過 100 頁上限。")
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)


def _docx_text(data: bytes) -> str:
    # Check archive size before python-docx decompresses it.
    try:
        with ZipFile(BytesIO(data)) as archive:
            files = archive.infolist()
            if len(files) > 1500 or sum(part.file_size for part in files) > MAX_DOCX_UNCOMPRESSED_BYTES:
                raise DocumentParseError("DOCX 解壓後的內容超過安全限制。")
    except BadZipFile as exc:
        raise DocumentParseError("DOCX 不是有效的 Word 文件。") from exc

    document = Document(BytesIO(data))
    parts: list[str] = []
    for item in document.iter_inner_content():
        if isinstance(item, Paragraph):
            parts.append(item.text)
        elif isinstance(item, Table):
            for row in item.rows:
                parts.append(" | ".join(cell.text for cell in row.cells))
    return "\n".join(parts)
