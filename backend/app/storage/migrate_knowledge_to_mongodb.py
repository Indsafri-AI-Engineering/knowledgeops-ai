import argparse
from collections import Counter
from datetime import UTC, datetime
import os

from backend.app.core.environment import load_environment
from backend.app.knowledge.ingestion import KnowledgeChunk
from backend.app.knowledge.mongodb_index import MongoAtlasKnowledgeIndex
from backend.app.storage.knowledge import (
    KnowledgeDocumentStore,
    StoredKnowledgeDocument,
)
from backend.app.storage.mongodb import close_mongodb_client
from backend.app.storage.mongodb_knowledge import MongoKnowledgeDocumentRepository


def _read_source() -> tuple[
    list[StoredKnowledgeDocument],
    list[KnowledgeChunk],
]:
    source = KnowledgeDocumentStore()
    return source.list_documents(), source.list_chunks()


def _print_plan(
    documents: list[StoredKnowledgeDocument],
    chunks: list[KnowledgeChunk],
) -> None:
    scopes = Counter(document.access_scope for document in documents)
    scope_summary = ", ".join(
        f"{scope}={count}"
        for scope, count in sorted(scopes.items())
    ) or "none"
    print(
        f"Migration plan: {len(documents)} document(s), {len(chunks)} "
        f"chunk(s); documents by scope: {scope_summary}."
    )


def _preflight(
    repository: MongoKnowledgeDocumentRepository,
    documents: list[StoredKnowledgeDocument],
    chunks: list[KnowledgeChunk],
) -> list[StoredKnowledgeDocument]:
    existing_documents = {
        document.document_id: document
        for document in repository.list_documents()
    }
    existing_by_hash = {
        document.sha256: document
        for document in existing_documents.values()
    }
    existing_chunks = repository.list_chunks()
    existing_chunk_ids = {chunk.chunk_id for chunk in existing_chunks}
    existing_chunks_by_document: dict[str, dict[str, KnowledgeChunk]] = {}
    for chunk in existing_chunks:
        existing_chunks_by_document.setdefault(chunk.document_id, {})[
            chunk.chunk_id
        ] = chunk

    chunks_by_document: dict[str, dict[str, KnowledgeChunk]] = {}
    for chunk in chunks:
        chunks_by_document.setdefault(chunk.document_id, {})[chunk.chunk_id] = chunk

    documents_to_import: list[StoredKnowledgeDocument] = []
    for document in documents:
        existing = existing_documents.get(document.document_id)
        if existing is not None:
            source_chunks = chunks_by_document.get(document.document_id, {})
            target_chunks = existing_chunks_by_document.get(document.document_id, {})
            if (
                not _same_document(existing, document)
                or source_chunks != target_chunks
            ):
                raise ValueError(
                    "MongoDB already contains a different or incomplete record "
                    f"for document {document.document_id}; no migration was started."
                )
            continue
        duplicate = existing_by_hash.get(document.sha256)
        if duplicate is not None:
            raise ValueError(
                "MongoDB already contains the same file hash under document "
                f"{duplicate.document_id}; no migration was started."
            )
        document_chunks = chunks_by_document.get(document.document_id, {})
        if len(document_chunks) != document.chunk_count:
            raise ValueError(
                f"Source chunks are incomplete for document {document.document_id}."
            )
        if existing_chunk_ids.intersection(document_chunks):
            raise ValueError(
                f"MongoDB already contains a chunk ID for document "
                f"{document.document_id}; no migration was started."
            )
        documents_to_import.append(document)
    return documents_to_import


def _same_document(
    existing: StoredKnowledgeDocument,
    source: StoredKnowledgeDocument,
) -> bool:
    if existing.model_dump(exclude={"uploaded_at"}) != source.model_dump(
        exclude={"uploaded_at"}
    ):
        return False

    def epoch_milliseconds(value: datetime) -> int:
        normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value
        return int(normalized.timestamp() * 1000)

    return epoch_milliseconds(existing.uploaded_at) == epoch_milliseconds(
        source.uploaded_at
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Migrate the local knowledge JSON store to MongoDB Atlas. "
            "Defaults to a read-only dry run."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the validated source documents and chunks to MongoDB",
    )
    arguments = parser.parse_args(argv)

    if os.getenv("APP_ENV", "").lower() != "test":
        load_environment()
    documents, chunks = _read_source()
    _print_plan(documents, chunks)
    if not arguments.apply:
        print("Dry run only. No MongoDB connection or writes were made.")
        return
    if not documents:
        print("No source documents to migrate.")
        return

    chunks_by_document: dict[str, list[KnowledgeChunk]] = {}
    for chunk in chunks:
        chunks_by_document.setdefault(chunk.document_id, []).append(chunk)

    try:
        repository = MongoKnowledgeDocumentRepository()
        documents_to_import = _preflight(repository, documents, chunks)
        index = MongoAtlasKnowledgeIndex([])
        imported_count = 0
        for document in documents_to_import:
            document_chunks = chunks_by_document[document.document_id]
            repository.add_document(document, document_chunks)
            try:
                index.add_chunks(document_chunks)
            except Exception:
                repository.delete_document(document.document_id)
                index.delete_document(document.document_id)
                raise
            imported_count += 1
        print(
            f"Migration complete: imported {imported_count} document(s). "
            "The local JSON source was left unchanged."
        )
    finally:
        close_mongodb_client()


if __name__ == "__main__":
    main()
