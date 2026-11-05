from datetime import UTC, datetime
from typing import Any

from pymongo.errors import DuplicateKeyError

import pytest

from backend.app.knowledge.ingestion import KnowledgeChunk
from backend.app.knowledge.mongodb_index import MongoAtlasKnowledgeIndex
from backend.app.storage.knowledge import (
    DuplicateKnowledgeDocumentError,
    KnowledgeDocumentStore,
    StoredKnowledgeDocument,
)
from backend.app.storage.mongodb_knowledge import MongoKnowledgeDocumentRepository
from backend.app.storage import migrate_knowledge_to_mongodb


class FakeCursor(list):
    def sort(self, fields):
        for field, direction in reversed(fields):
            super().sort(
                key=lambda record: record.get(field),
                reverse=direction < 0,
            )
        return self


class FakeCollection:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self.indexes: list[tuple[Any, ...]] = []
        self.search_indexes: list[dict[str, str]] = []
        self.pipeline: list[dict[str, Any]] | None = None
        self.vector_results: list[dict[str, Any]] = []
        self.bulk_write_count = 0

    def create_index(self, keys, **kwargs):
        self.indexes.append((keys, kwargs))

    def find_one(self, query, projection=None):
        return next(
            (record for record in self.records.values() if _matches(record, query)),
            None,
        )

    def insert_one(self, record):
        if record["_id"] in self.records:
            raise DuplicateKeyError("duplicate key")
        self.records[record["_id"]] = dict(record)

    def insert_many(self, records, ordered=True):
        for record in records:
            self.insert_one(record)

    def find(self, query=None, projection=None):
        records = [
            dict(record)
            for record in self.records.values()
            if _matches(record, query or {})
        ]
        if projection:
            excluded = {key for key, include in projection.items() if not include}
            if excluded:
                for record in records:
                    for key in excluded:
                        record.pop(key, None)
            else:
                included = {key for key, include in projection.items() if include}
                records = [
                    {key: record[key] for key in included if key in record}
                    for record in records
                ]
        return FakeCursor(records)

    def delete_many(self, query):
        keys = [
            key for key, record in self.records.items()
            if _matches(record, query)
        ]
        for key in keys:
            del self.records[key]

    def delete_one(self, query):
        record = self.find_one(query)
        if record:
            del self.records[record["_id"]]
            return type("DeleteResult", (), {"deleted_count": 1})()
        return type("DeleteResult", (), {"deleted_count": 0})()

    def list_search_indexes(self):
        return iter(self.search_indexes)

    def bulk_write(self, operations, ordered=True):
        self.bulk_write_count += len(operations)

    def aggregate(self, pipeline):
        self.pipeline = pipeline
        return iter(dict(record) for record in self.vector_results)


class FakeDatabase:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self.collections:
            self.collections[name] = FakeCollection()
        return self.collections[name]


class FixedEmbeddings:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0]


def _matches(record: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, expected in query.items():
        actual = record.get(key)
        if isinstance(expected, dict) and "$in" in expected:
            if actual not in expected["$in"]:
                return False
        elif isinstance(expected, dict) and "$exists" in expected:
            if (key in record) != expected["$exists"]:
                return False
        elif actual != expected:
            return False
    return True


def _chunk(
    chunk_id: str = "doc:0",
    document_id: str = "doc",
    access_scope: str = "it",
    text: str = "synthetic procedure",
) -> KnowledgeChunk:
    return KnowledgeChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        title="Synthetic guide",
        source="uploaded",
        access_scope=access_scope,
        source_path="guide.txt",
        section="Overview",
        text=text,
    )


def _document(document_id: str = "doc", sha256: str = "a" * 64):
    return StoredKnowledgeDocument(
        document_id=document_id,
        title="Synthetic guide",
        filename="guide.txt",
        source="uploaded",
        document_type="text/plain",
        access_scope="it",
        sha256=sha256,
        uploaded_at=datetime.now(UTC),
        chunk_count=1,
    )


def test_mongodb_repository_persists_document_and_chunks() -> None:
    database = FakeDatabase()
    repository = MongoKnowledgeDocumentRepository(database=database)

    repository.add_document(_document(), [_chunk()])

    assert repository.list_documents()[0].document_id == "doc"
    assert repository.list_chunks()[0].text == "synthetic procedure"
    assert repository.delete_document("doc") is True
    assert repository.list_documents() == []
    assert repository.list_chunks() == []


def test_mongodb_repository_ignores_vector_only_chunks_without_ordinals() -> None:
    database = FakeDatabase()
    repository = MongoKnowledgeDocumentRepository(database=database)
    repository.add_document(_document(), [_chunk()])
    database["knowledge_chunks"].insert_one(
        {
            "_id": "seed:0",
            "chunk_id": "seed:0",
            "document_id": "seed",
            "title": "Seed guide",
            "source": "fictional_demo",
            "access_scope": "general",
            "source_path": "seed.md",
            "section": "Overview",
            "text": "synthetic seed content",
        }
    )

    chunks = repository.list_chunks()

    assert [chunk.document_id for chunk in chunks] == ["doc"]
    assert chunks[0].text == "synthetic procedure"


def test_mongodb_repository_rejects_duplicate_document_hash() -> None:
    repository = MongoKnowledgeDocumentRepository(database=FakeDatabase())
    repository.add_document(_document(), [_chunk()])

    with pytest.raises(DuplicateKnowledgeDocumentError):
        repository.add_document(
            _document(document_id="other"),
            [_chunk(chunk_id="other:0", document_id="other")],
        )


def test_atlas_vector_search_filters_scopes_before_results(monkeypatch) -> None:
    monkeypatch.setenv("MONGODB_VECTOR_DIMENSIONS", "2")
    collection = FakeCollection()
    collection.search_indexes = [
        {
            "name": "knowledge_vector_index",
            "status": "READY",
            "queryable": True,
        }
    ]
    collection.vector_results = [
        {
            "chunk_id": "hr:0",
            "document_id": "hr",
            "title": "HR guide",
            "source": "uploaded",
            "access_scope": "hr",
            "source_path": "hr.txt",
            "section": "Overview",
            "text": "restricted HR guidance",
            "score": 0.9,
        },
        {
            "chunk_id": "it:0",
            "document_id": "it",
            "title": "IT guide",
            "source": "uploaded",
            "access_scope": "it",
            "source_path": "it.txt",
            "section": "Overview",
            "text": "permitted IT guidance",
            "score": 0.9,
        },
    ]
    index = MongoAtlasKnowledgeIndex(
        [],
        collection=collection,
        embeddings=FixedEmbeddings(),
    )

    results = index.search("guidance", {"it"}, mode="vector")

    assert [result.chunk.document_id for result in results] == ["it"]
    assert collection.pipeline is not None
    assert collection.pipeline[0]["$vectorSearch"]["filter"] == {
        "access_scope": {"$in": ["it"]}
    }


def test_missing_vector_index_fails_before_seed_chunks_are_written(
    monkeypatch,
) -> None:
    monkeypatch.setenv("MONGODB_VECTOR_DIMENSIONS", "2")
    collection = FakeCollection()

    with pytest.raises(RuntimeError, match="Vector Search index"):
        MongoAtlasKnowledgeIndex(
            [_chunk()],
            collection=collection,
            embeddings=FixedEmbeddings(),
        )

    assert collection.bulk_write_count == 0


def test_unready_vector_index_fails_before_seed_chunks_are_written(
    monkeypatch,
) -> None:
    monkeypatch.setenv("MONGODB_VECTOR_DIMENSIONS", "2")
    collection = FakeCollection()
    collection.search_indexes = [
        {"name": "knowledge_vector_index", "status": "BUILDING"}
    ]

    with pytest.raises(RuntimeError, match="not ready"):
        MongoAtlasKnowledgeIndex(
            [_chunk()],
            collection=collection,
            embeddings=FixedEmbeddings(),
        )

    assert collection.bulk_write_count == 0


def test_migration_defaults_to_read_only_dry_run(
    monkeypatch,
    tmp_path,
    capsys,
) -> None:
    source_path = tmp_path / "knowledge.json"
    monkeypatch.setenv("KNOWLEDGE_STORE_PATH", str(source_path))
    source = KnowledgeDocumentStore(source_path)
    source.add_document(_document(), [_chunk()])
    monkeypatch.setattr(
        migrate_knowledge_to_mongodb,
        "MongoKnowledgeDocumentRepository",
        lambda: pytest.fail("dry run must not connect to MongoDB"),
    )

    migrate_knowledge_to_mongodb.main([])

    output = capsys.readouterr().out
    assert "1 document(s), 1 chunk(s)" in output
    assert "Dry run only" in output
