"""TXT, PDF and DOCX upload validation and FastAPI integration tests."""

from __future__ import annotations

from io import BytesIO

import pytest
from docx import Document
from fastapi.testclient import TestClient

from src.legal_contract_assistant.document_parser import (
    DocumentParseError,
    MAX_UPLOAD_BYTES,
    extract_contract_text,
)
from src.legal_contract_assistant.web_app import create_app


def _docx_bytes(text: str) -> bytes:
    doc = Document()
    doc.add_paragraph(text)
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "租金"
    table.cell(0, 1).text = "每月二萬元"
    output = BytesIO()
    doc.save(output)
    return output.getvalue()


def _pdf_bytes(text: str) -> bytes:
    # Minimal valid text-based PDF, generated without an extra test dependency.
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(pdf)
    pdf.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    return bytes(pdf)


def test_txt_with_utf8_bom_and_uppercase_extension() -> None:
    assert extract_contract_text("LEASE.TXT", b"\xef\xbb\xbf" + "租賃契約".encode()) == "租賃契約"


def test_docx_extracts_paragraphs_and_table() -> None:
    text = extract_contract_text("lease.docx", _docx_bytes("出租人與承租人約定租期。"))
    assert "出租人與承租人約定租期" in text
    assert "租金 | 每月二萬元" in text


def test_pdf_extracts_selectable_text() -> None:
    assert "Lease agreement" in extract_contract_text("lease.pdf", _pdf_bytes("Lease agreement"))


def test_scanned_pdf_without_text_is_rejected() -> None:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    output = BytesIO()
    writer.write(output)
    with pytest.raises(DocumentParseError, match="OCR"):
        extract_contract_text("scan.pdf", output.getvalue())


@pytest.mark.parametrize("filename,payload", [
    ("x.doc", b"old word"),
    ("x.exe", b"binary"),
    ("x.pdf", b"not really pdf"),
    ("x.txt", b""),
    ("x.txt", b"\xff\xfe\xfa"),
    ("x.docx", b"invalid"),
])
def test_invalid_files_return_readable_errors(filename: str, payload: bytes) -> None:
    with pytest.raises(DocumentParseError):
        extract_contract_text(filename, payload)


def test_oversized_upload_rejected() -> None:
    with pytest.raises(DocumentParseError, match="8 MB"):
        extract_contract_text("oversize.txt", b"x" * (MAX_UPLOAD_BYTES + 1))


@pytest.mark.parametrize("filename,payload,content_type", [
    ("contract.txt", "出租人與承租人約定租期。".encode(), "text/plain"),
    ("contract.docx", _docx_bytes("出租人與承租人約定租期。"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ("contract.pdf", _pdf_bytes("Lease agreement"), "application/pdf"),
])
def test_upload_formats_reach_review_endpoint(tmp_path, filename: str, payload: bytes, content_type: str) -> None:
    client = TestClient(create_app(env_path=tmp_path / ".env", static_dir=tmp_path))
    response = client.post("/api/review",
        data={"contract_type": "lease", "provider": "noop", "use_llm": "false"},
        files={"file": (filename, payload, content_type)},
    )
    assert response.status_code == 200, response.text
    assert "# 合約審查報告" in response.json()["markdown"]


def test_upload_bad_file_returns_400_not_500(tmp_path) -> None:
    client = TestClient(create_app(env_path=tmp_path / ".env", static_dir=tmp_path))
    response = client.post("/api/review",
        data={"contract_type": "lease", "provider": "noop", "use_llm": "false"},
        files={"file": ("scan.pdf", b"%PDF-broken", "application/pdf")},
    )
    assert response.status_code == 400
    assert response.json()["detail"]
