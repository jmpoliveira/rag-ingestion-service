from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from typing import Any

import pytest
from pypdf import PdfWriter

from src.domain.documents import SourceDocument
from src.domain.errors import DocumentRejectedError
from src.infrastructure.parsing import pdf as pdf_module
from src.infrastructure.parsing.pdf import PdfParser
from src.infrastructure.parsing.text import TextParser

PDF = SourceDocument("doc.pdf", "application/pdf", "h", 1)
TXT = SourceDocument("doc.md", "text/markdown", "h", 1)


def _blank_pdf(pages: int, password: str | None = None) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    if password is not None:
        writer.encrypt(user_password=password, owner_password="owner", algorithm="RC4-128")
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


async def test_real_pdf_without_text_gives_empty_pages():
    # Act
    parsed = await PdfParser(max_pages=10).parse(PDF, _blank_pdf(2))

    # Assert
    assert [page.number for page in parsed.pages] == [1, 2]
    assert not parsed.has_text


async def test_extracted_text_is_kept_per_page(monkeypatch: pytest.MonkeyPatch):
    # Arrange: pypdf cannot write text, so its reader is replaced
    pages = [
        SimpleNamespace(extract_text=lambda: "first"),
        SimpleNamespace(extract_text=lambda: None),
    ]
    reader = SimpleNamespace(is_encrypted=False, pages=pages)
    monkeypatch.setattr(pdf_module, "PdfReader", lambda _stream: reader)  # type: ignore[arg-type]

    # Act
    parsed = await PdfParser(max_pages=10).parse(PDF, b"%PDF")

    # Assert
    assert [(p.number, p.text) for p in parsed.pages] == [(1, "first"), (2, "")]


async def test_corrupted_pdf_is_rejected():
    with pytest.raises(DocumentRejectedError, match="could not be parsed"):
        await PdfParser(max_pages=10).parse(PDF, b"%PDF-1.7 this is not a pdf")


async def test_empty_bytes_are_rejected():
    with pytest.raises(DocumentRejectedError):
        await PdfParser(max_pages=10).parse(PDF, b"")


async def test_password_protected_pdf_is_rejected():
    with pytest.raises(DocumentRejectedError, match="password"):
        await PdfParser(max_pages=10).parse(PDF, _blank_pdf(1, password="s3cret"))


async def test_pdf_encrypted_with_an_empty_password_is_read():
    # Act
    parsed = await PdfParser(max_pages=10).parse(PDF, _blank_pdf(1, password=""))

    # Assert
    assert len(parsed.pages) == 1


async def test_too_many_pages_is_rejected():
    with pytest.raises(DocumentRejectedError, match="over the limit of 2"):
        await PdfParser(max_pages=2).parse(PDF, _blank_pdf(3))


async def test_unexpected_parser_errors_become_a_rejection(monkeypatch: pytest.MonkeyPatch):
    # Arrange
    def broken(_stream: Any) -> Any:
        raise KeyError("/Root")

    monkeypatch.setattr(pdf_module, "PdfReader", broken)

    # Act / Assert
    with pytest.raises(DocumentRejectedError):
        await PdfParser(max_pages=10).parse(PDF, b"%PDF")


def test_pdf_page_limit_must_be_positive():
    with pytest.raises(ValueError, match="max_pages"):
        PdfParser(max_pages=0)


async def test_text_parser_decodes_utf8_and_drops_the_bom():
    # Act
    parsed = await TextParser().parse(TXT, "\ufeff# Título".encode())

    # Assert
    assert [(p.number, p.text) for p in parsed.pages] == [(1, "# Título")]


async def test_text_parser_rejects_other_encodings():
    with pytest.raises(DocumentRejectedError, match="UTF-8"):
        await TextParser().parse(TXT, "café".encode("latin-1"))


def test_media_types():
    assert PdfParser(max_pages=1).media_types == {"application/pdf"}
    assert TextParser().media_types == {"text/plain", "text/markdown"}
