from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from src.domain.documents import SourceDocument
from src.domain.errors import DocumentRejectedError, SourceUnavailableError
from src.infrastructure.sources.folder import DEFAULT_MEDIA_TYPES, FolderDocumentSource


def _source(root: Path, max_file_bytes: int = 1024) -> FolderDocumentSource:
    return FolderDocumentSource(
        root, media_types=DEFAULT_MEDIA_TYPES, max_file_bytes=max_file_bytes
    )


async def test_lists_supported_files_recursively_with_posix_ids_and_hashes(tmp_path: Path):
    # Arrange
    (tmp_path / "policies").mkdir()
    (tmp_path / "a.md").write_bytes(b"# A")
    (tmp_path / "policies" / "b.PDF").write_bytes(b"%PDF")
    (tmp_path / "ignored.docx").write_bytes(b"x")

    # Act
    documents = await _source(tmp_path).list_documents()

    # Assert
    assert [(d.document_id, d.media_type) for d in documents] == [
        ("a.md", "text/markdown"),
        ("policies/b.PDF", "application/pdf"),
    ]
    assert documents[0].content_hash == hashlib.sha256(b"# A").hexdigest()
    assert documents[0].size_bytes == 3


async def test_hidden_files_and_folders_are_ignored(tmp_path: Path):
    # Arrange
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "notes.txt").write_text("x")
    (tmp_path / ".draft.md").write_text("x")
    (tmp_path / "visible.txt").write_text("x")

    # Act
    documents = await _source(tmp_path).list_documents()

    # Assert
    assert [d.document_id for d in documents] == ["visible.txt"]


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
async def test_symlinks_are_never_followed(tmp_path: Path):
    # Arrange: a link to a file and a link to a folder, both outside the source
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    root = tmp_path / "root"
    root.mkdir()
    (root / "link.txt").symlink_to(outside / "secret.txt")
    (root / "linked-folder").symlink_to(outside, target_is_directory=True)

    # Act
    documents = await _source(root).list_documents()

    # Assert
    assert documents == []


async def test_missing_folder_is_a_fatal_error_and_is_not_created(tmp_path: Path):
    # Arrange
    missing = tmp_path / "nope"

    # Act / Assert
    with pytest.raises(SourceUnavailableError):
        await _source(missing).list_documents()
    assert not missing.exists()


async def test_a_file_path_instead_of_a_folder_is_a_fatal_error(tmp_path: Path):
    # Arrange
    file = tmp_path / "file.txt"
    file.write_text("x")

    # Act / Assert
    with pytest.raises(SourceUnavailableError):
        await _source(file).list_documents()


async def test_oversized_file_is_listed_but_rejected_on_read(tmp_path: Path):
    # Arrange
    (tmp_path / "big.txt").write_bytes(b"x" * 20)
    source = _source(tmp_path, max_file_bytes=10)

    # Act
    [document] = await source.list_documents()

    # Assert
    assert document.size_bytes == 20
    with pytest.raises(DocumentRejectedError, match="over the limit"):
        await source.read_bytes(document)


async def test_reads_the_listed_content(tmp_path: Path):
    # Arrange
    (tmp_path / "a.txt").write_bytes(b"hello")
    source = _source(tmp_path)
    [document] = await source.list_documents()

    # Act / Assert
    assert await source.read_bytes(document) == b"hello"


async def test_a_file_changed_after_listing_is_rejected(tmp_path: Path):
    # Arrange
    (tmp_path / "a.txt").write_bytes(b"before")
    source = _source(tmp_path)
    [document] = await source.list_documents()
    (tmp_path / "a.txt").write_bytes(b"after")

    # Act / Assert
    with pytest.raises(DocumentRejectedError, match="changed while"):
        await source.read_bytes(document)


async def test_a_file_deleted_after_listing_is_rejected(tmp_path: Path):
    # Arrange
    (tmp_path / "a.txt").write_bytes(b"x")
    source = _source(tmp_path)
    [document] = await source.list_documents()
    (tmp_path / "a.txt").unlink()

    # Act / Assert
    with pytest.raises(DocumentRejectedError, match="no longer exists"):
        await source.read_bytes(document)


@pytest.mark.parametrize("document_id", ["../escape.txt", "/etc/passwd", "a/../../b.txt", ""])
async def test_ids_that_could_leave_the_folder_are_rejected(tmp_path: Path, document_id: str):
    # Arrange: ids will come from events one day, so they are not trusted
    document = SourceDocument(document_id, "text/plain", "h", 1)

    # Act / Assert
    with pytest.raises(DocumentRejectedError):
        await _source(tmp_path).read_bytes(document)


def test_size_limit_must_be_positive(tmp_path: Path):
    with pytest.raises(ValueError, match="max_file_bytes"):
        _source(tmp_path, max_file_bytes=0)
