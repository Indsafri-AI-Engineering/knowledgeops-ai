import json
import os
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from backend.app.knowledge.ingestion import KnowledgeChunk

DEFAULT_KNOWLEDGE_STORE_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "runtime" / "knowledge.json"
)
_KNOWLEDGE_STORE_LOCK = threading.RLock()


class StoredKnowledgeDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    title: str
    filename: str
    source: str
    document_type: str = "application/pdf"
    access_scope: str
    sha256: str
    uploaded_at: datetime
    chunk_count: int = Field(ge=1)
    owner: str | None = None
    version: str | None = None
    effective_date: str | None = None
    next_review: str | None = None
    environment: str | None = None


class StoredKnowledgeChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    document_id: str
    title: str
    source: str
    access_scope: str
    source_path: str
    section: str
    text: str
    ordinal: int = Field(ge=0)
    owner: str | None = None
    version: str | None = None
    effective_date: str | None = None
    next_review: str | None = None
    environment: str | None = None

    @classmethod
    def from_chunk(cls, chunk: KnowledgeChunk, ordinal: int) -> "StoredKnowledgeChunk":
        return cls(
            **{
                **chunk.__dict__,
                "ordinal": ordinal,
            }
        )

    def to_chunk(self) -> KnowledgeChunk:
        values = self.model_dump(exclude={"ordinal"})
        return KnowledgeChunk(**values)


class KnowledgeStoreSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    documents: dict[str, StoredKnowledgeDocument]
    chunks: dict[str, StoredKnowledgeChunk]


class DuplicateKnowledgeDocumentError(ValueError):
    pass


class CorruptKnowledgeStoreError(ValueError):
    """Raised when the knowledge JSON store cannot be safely validated."""


@runtime_checkable
class KnowledgeDocumentRepository(Protocol):
    def add_document(
        self,
        document: StoredKnowledgeDocument,
        chunks: list[KnowledgeChunk],
    ) -> None: ...

    def list_documents(self) -> list[StoredKnowledgeDocument]: ...

    def list_chunks(self) -> list[KnowledgeChunk]: ...

    def delete_document(self, document_id: str) -> bool: ...


class KnowledgeDocumentStore:
    def __init__(self, path: Path | None = None) -> None:
        configured_path = os.getenv("KNOWLEDGE_STORE_PATH")
        self.path = path or (
            Path(configured_path)
            if configured_path
            else DEFAULT_KNOWLEDGE_STORE_PATH
        )

    def _read(self) -> KnowledgeStoreSnapshot:
        if not self.path.exists():
            return KnowledgeStoreSnapshot(documents={}, chunks={})
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            snapshot = KnowledgeStoreSnapshot.model_validate(payload)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
            raise CorruptKnowledgeStoreError(
                f"Knowledge store contains invalid JSON or records: {self.path}"
            ) from error

        for key, document in snapshot.documents.items():
            if key != document.document_id:
                raise CorruptKnowledgeStoreError(
                    f"Knowledge document keys must match document IDs: {self.path}"
                )
        for key, chunk in snapshot.chunks.items():
            if (
                key != chunk.chunk_id
                or chunk.document_id not in snapshot.documents
            ):
                raise CorruptKnowledgeStoreError(
                    f"Knowledge chunks contain an invalid reference: {self.path}"
                )
        for document in snapshot.documents.values():
            document_chunks = [
                chunk
                for chunk in snapshot.chunks.values()
                if chunk.document_id == document.document_id
            ]
            if len(document_chunks) != document.chunk_count:
                raise CorruptKnowledgeStoreError(
                    f"Knowledge document chunk counts are inconsistent: {self.path}"
                )
        hashes = [document.sha256 for document in snapshot.documents.values()]
        if len(hashes) != len(set(hashes)):
            raise CorruptKnowledgeStoreError(
                f"Knowledge documents contain duplicate file hashes: {self.path}"
            )
        return snapshot

    def _write(self, snapshot: KnowledgeStoreSnapshot) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(
                    snapshot.model_dump_json(indent=2, exclude_none=False)
                )
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    def add_document(
        self,
        document: StoredKnowledgeDocument,
        chunks: list[KnowledgeChunk],
    ) -> None:
        if not chunks:
            raise ValueError("A knowledge document must contain at least one chunk.")
        if any(chunk.document_id != document.document_id for chunk in chunks):
            raise ValueError("All knowledge chunks must belong to the stored document.")
        if document.chunk_count != len(chunks):
            raise ValueError("Stored chunk count must match the document chunks.")

        with _KNOWLEDGE_STORE_LOCK:
            snapshot = self._read()
            if document.document_id in snapshot.documents:
                raise ValueError("Document ID already exists.")
            if any(
                existing.sha256 == document.sha256
                for existing in snapshot.documents.values()
            ):
                raise DuplicateKnowledgeDocumentError(
                    "This document has already been ingested."
                )
            if any(
                chunk.chunk_id in snapshot.chunks
                for chunk in chunks
            ):
                raise ValueError("A knowledge chunk ID already exists.")

            snapshot.documents[document.document_id] = document
            snapshot.chunks.update(
                {
                    chunk.chunk_id: StoredKnowledgeChunk.from_chunk(chunk, ordinal)
                    for ordinal, chunk in enumerate(chunks)
                }
            )
            self._write(snapshot)

    def list_documents(self) -> list[StoredKnowledgeDocument]:
        with _KNOWLEDGE_STORE_LOCK:
            documents = list(self._read().documents.values())
        return sorted(
            documents,
            key=lambda document: (document.uploaded_at, document.document_id),
            reverse=True,
        )

    def list_chunks(self) -> list[KnowledgeChunk]:
        with _KNOWLEDGE_STORE_LOCK:
            snapshot = self._read()
        chunks = sorted(
            snapshot.chunks.values(),
            key=lambda chunk: (
                snapshot.documents[chunk.document_id].uploaded_at,
                chunk.document_id,
                chunk.ordinal,
            ),
        )
        return [chunk.to_chunk() for chunk in chunks]

    def delete_document(self, document_id: str) -> bool:
        with _KNOWLEDGE_STORE_LOCK:
            snapshot = self._read()
            if snapshot.documents.pop(document_id, None) is None:
                return False
            snapshot.chunks = {
                chunk_id: chunk
                for chunk_id, chunk in snapshot.chunks.items()
                if chunk.document_id != document_id
            }
            self._write(snapshot)
            return True


def get_knowledge_document_repository() -> KnowledgeDocumentRepository:
    backend = os.getenv("KNOWLEDGE_STORE_BACKEND", "mongodb").strip().lower()
    if backend == "mongodb":
        from backend.app.storage.mongodb_knowledge import (
            MongoKnowledgeDocumentRepository,
        )

        return MongoKnowledgeDocumentRepository()
    if backend == "local":
        return KnowledgeDocumentStore()
    raise ValueError(f"Unsupported KNOWLEDGE_STORE_BACKEND: {backend}")
