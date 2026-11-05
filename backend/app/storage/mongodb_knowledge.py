import os
from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from backend.app.knowledge.ingestion import KnowledgeChunk
from backend.app.storage.knowledge import (
    DuplicateKnowledgeDocumentError,
    StoredKnowledgeChunk,
    StoredKnowledgeDocument,
)
from backend.app.storage.mongodb import get_mongodb_database


class MongoKnowledgeDocumentRepository:
    def __init__(self, database: Database | None = None) -> None:
        db = database if database is not None else get_mongodb_database()
        documents_name = os.getenv(
            "MONGODB_DOCUMENTS_COLLECTION",
            "knowledge_documents",
        ).strip()
        chunks_name = os.getenv(
            "MONGODB_CHUNKS_COLLECTION",
            "knowledge_chunks",
        ).strip()
        if not documents_name or not chunks_name:
            raise RuntimeError("MongoDB collection names must not be empty.")
        if documents_name == chunks_name:
            raise RuntimeError("MongoDB documents and chunks need separate collections.")

        self._documents: Collection[dict[str, Any]] = db[documents_name]
        self._chunks: Collection[dict[str, Any]] = db[chunks_name]
        self._documents.create_index(
            [("sha256", ASCENDING)],
            unique=True,
            name="unique_document_sha256",
        )
        self._documents.create_index(
            [("uploaded_at", DESCENDING), ("document_id", DESCENDING)],
            name="documents_by_upload_date",
        )
        self._chunks.create_index(
            [("document_id", ASCENDING), ("ordinal", ASCENDING)],
            name="chunks_by_document",
        )

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
        if self._documents.find_one(
            {"sha256": document.sha256},
            {"_id": 1},
        ):
            raise DuplicateKnowledgeDocumentError(
                "This document has already been ingested."
            )

        document_record = document.model_dump(mode="python")
        document_record["_id"] = document.document_id
        try:
            self._documents.insert_one(document_record)
        except DuplicateKeyError as error:
            if self._documents.find_one({"sha256": document.sha256}, {"_id": 1}):
                raise DuplicateKnowledgeDocumentError(
                    "This document has already been ingested."
                ) from error
            raise ValueError("Document ID already exists.") from error

        chunk_records = [
            {
                **StoredKnowledgeChunk.from_chunk(chunk, ordinal).model_dump(
                    mode="python"
                ),
                "_id": chunk.chunk_id,
            }
            for ordinal, chunk in enumerate(chunks)
        ]
        try:
            self._chunks.insert_many(chunk_records, ordered=True)
        except Exception:
            self._chunks.delete_many({"document_id": document.document_id})
            self._documents.delete_one({"_id": document.document_id})
            raise

    def list_documents(self) -> list[StoredKnowledgeDocument]:
        documents = self._documents.find(
            {},
            {"_id": 0},
        ).sort(
            [("uploaded_at", DESCENDING), ("document_id", DESCENDING)]
        )
        return [
            StoredKnowledgeDocument.model_validate(document)
            for document in documents
        ]

    def list_chunks(self) -> list[KnowledgeChunk]:
        document_ids = [
            document["document_id"]
            for document in self._documents.find({}, {"document_id": 1})
        ]
        if not document_ids:
            return []
        chunks = self._chunks.find(
            {"document_id": {"$in": document_ids}},
            {"_id": 0, "embedding": 0, "embedding_model": 0},
        ).sort(
            [("document_id", ASCENDING), ("ordinal", ASCENDING)]
        )
        return [
            StoredKnowledgeChunk.model_validate(chunk).to_chunk()
            for chunk in chunks
        ]

    def delete_document(self, document_id: str) -> bool:
        if not self._documents.find_one({"_id": document_id}, {"_id": 1}):
            return False
        self._chunks.delete_many({"document_id": document_id})
        return self._documents.delete_one({"_id": document_id}).deleted_count == 1
