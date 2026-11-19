"""A local folder as the document source (ADR 0002).

Defensive by design, because the folder is input we do not control:

- the folder must exist: it is never created (the old service created a missing folder and
  reported "no documents", which hid a wrong path);
- symlinks are not followed and hidden files and folders (``.git``, ``.DS_Store``) are
  ignored, so nothing outside the folder can be read;
- a document id coming back to ``read_bytes`` (later from an event) is re-checked: it must
  resolve inside the folder;
- files over the size limit are listed but rejected, so they appear in the report instead
  of disappearing silently.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from src.domain.documents import SourceDocument
from src.domain.errors import DocumentRejectedError, SourceUnavailableError

logger = logging.getLogger(__name__)

_READ_BLOCK = 1024 * 1024
# Placeholder hash for files that are too large to read: they are rejected anyway.
_NOT_HASHED = "not-hashed"

DEFAULT_MEDIA_TYPES: Mapping[str, str] = {
    ".pdf": "application/pdf",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
}


class FolderDocumentSource:
    def __init__(
        self,
        root: Path,
        *,
        media_types: Mapping[str, str],
        max_file_bytes: int,
    ) -> None:
        if max_file_bytes < 1:
            raise ValueError("max_file_bytes must be at least 1")
        self._root = root
        self._media_types = {suffix.lower(): media for suffix, media in media_types.items()}
        self._max_file_bytes = max_file_bytes

    async def list_documents(self) -> list[SourceDocument]:
        return await asyncio.to_thread(self._scan)

    async def read_bytes(self, document: SourceDocument) -> bytes:
        return await asyncio.to_thread(self._read, document)

    # ---- blocking work, run in a thread ------------------------------------------------

    def _resolved_root(self) -> Path:
        if not self._root.is_dir():
            raise SourceUnavailableError(f"Source folder does not exist: {self._root}")
        return self._root.resolve()

    def _scan(self) -> list[SourceDocument]:
        root = self._resolved_root()
        documents: list[SourceDocument] = []
        try:
            # os.walk with followlinks=False: symlinked folders are never entered.
            for folder, subfolders, files in os.walk(root, followlinks=False):
                subfolders[:] = sorted(name for name in subfolders if not name.startswith("."))
                for name in sorted(files):
                    document = self._describe(root, Path(folder) / name)
                    if document is not None:
                        documents.append(document)
        except OSError as err:
            raise SourceUnavailableError(f"Source folder cannot be read: {self._root}") from err
        return documents

    def _describe(self, root: Path, path: Path) -> SourceDocument | None:
        if path.name.startswith(".") or path.is_symlink() or not path.is_file():
            return None
        media_type = self._media_types.get(path.suffix.lower())
        if media_type is None:
            logger.debug("Ignored: unsupported file type", extra={"file": path.name})
            return None
        document_id = path.relative_to(root).as_posix()
        size = path.stat().st_size
        if size > self._max_file_bytes:
            return SourceDocument(document_id, media_type, _NOT_HASHED, size)
        return SourceDocument(document_id, media_type, _hash_file(path), size)

    def _read(self, document: SourceDocument) -> bytes:
        path = self._path_for(document.document_id)
        try:
            if path.is_symlink():
                raise DocumentRejectedError("Document is a symbolic link")
            size = path.stat().st_size
            if size > self._max_file_bytes:
                raise DocumentRejectedError(
                    f"Document is {size} bytes, over the limit of {self._max_file_bytes}"
                )
            data = path.read_bytes()
        except FileNotFoundError as err:
            raise DocumentRejectedError("Document no longer exists in the source") from err
        except OSError as err:
            raise DocumentRejectedError("Document cannot be read") from err
        if document.content_hash != hashlib.sha256(data).hexdigest():
            # Its version was computed from other bytes; the next sync sees the new content.
            raise DocumentRejectedError("Document changed while it was being ingested")
        return data

    def _path_for(self, document_id: str) -> Path:
        """Map an id back to a path, refusing anything that could leave the folder."""
        relative = PurePosixPath(document_id)
        if not document_id or relative.is_absolute() or ".." in relative.parts:
            raise DocumentRejectedError("Invalid document id")
        root = self._resolved_root()
        path = root.joinpath(*relative.parts)
        if not path.resolve().is_relative_to(root):
            raise DocumentRejectedError("Document id resolves outside the source folder")
        return path


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(_READ_BLOCK):
            digest.update(block)
    return digest.hexdigest()
