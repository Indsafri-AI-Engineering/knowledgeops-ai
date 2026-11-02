import math
import os
import threading
from collections import OrderedDict
from typing import Any

from langchain_core.embeddings import Embeddings
from pymongo.collection import Collection
from pymongo.errors import PyMongoError
from pymongo.operations import UpdateOne

from backend.app.knowledge.ai_providers import create_embeddings
from backend.app.knowledge.ingestion import KnowledgeChunk
from backend.app.knowledge.retrieval import (
    LocalKnowledgeIndex,
    RetrievalMode,
    RetrievedChunk,
    reciprocal_rank_fusion,
)
from backend.app.storage.mongodb import get_mongodb_database


class MongoAtlasKnowledgeIndex:
    """Atlas Vector Search with a server-side access-scope prefilter."""

    def __init__(
        self,
        chunks: list[KnowledgeChunk],
        *,
        collection: Collection[dict[str, Any]] | None = None,
        embeddings: Embeddings | None = None,
        cache_size: int = 128,
    ) -> None:
        self._chunks = tuple(chunks)
        self._cache_size = max(0, cache_size)
        self._cache: OrderedDict[
            tuple[tuple[str, ...], frozenset[str], int, RetrievalMode],
            list[RetrievedChunk],
        ] = OrderedDict()
        self._cache_lock = threading.RLock()
        self._cache_hits = 0
        self._cache_misses = 0
        self._lexical_index = LocalKnowledgeIndex(chunks, cache_size=0)
        self._collection = (
            collection
            if collection is not None
            else get_mongodb_database()[
                os.getenv("MONGODB_CHUNKS_COLLECTION", "knowledge_chunks").strip()
            ]
        )
        self._embeddings = embeddings or create_embeddings()
        embedding_provider = os.getenv(
            "RAG_EMBEDDING_PROVIDER",
            "ollama",
        ).strip().lower()
        if embedding_provider == "mistral":
            embedding_model = os.getenv(
                "MISTRAL_EMBEDDING_MODEL",
                "mistral-embed",
            )
        else:
            embedding_model = os.getenv(
                "OLLAMA_EMBEDDING_MODEL",
                "nomic-embed-text:latest",
            )
        self._embedding_identity = f"{embedding_provider}:{embedding_model}"
        self._vector_index = os.getenv(
            "MONGODB_VECTOR_INDEX",
            "knowledge_vector_index",
        ).strip()
        if not self._vector_index:
            raise ValueError("MONGODB_VECTOR_INDEX must not be empty.")
        try:
            self._vector_dimensions = int(
                os.getenv("MONGODB_VECTOR_DIMENSIONS", "768")
            )
        except ValueError as error:
            raise ValueError(
                "MONGODB_VECTOR_DIMENSIONS must be a positive integer."
            ) from error
        if self._vector_dimensions < 1:
            raise ValueError(
                "MONGODB_VECTOR_DIMENSIONS must be a positive integer."
            )
        try:
            self._minimum_score = float(
                os.getenv("ATLAS_VECTOR_MIN_SCORE", "0.0")
            )
        except ValueError as error:
            raise ValueError(
                "ATLAS_VECTOR_MIN_SCORE must be a number between 0 and 1."
            ) from error
        if not 0 <= self._minimum_score <= 1:
            raise ValueError(
                "ATLAS_VECTOR_MIN_SCORE must be a number between 0 and 1."
            )
        self._require_vector_index()
        self._index_missing_vectors(chunks)

    @property
    def chunks(self) -> list[KnowledgeChunk]:
        return list(self._chunks)

    def cache_info(self) -> dict[str, int]:
        with self._cache_lock:
            return {
                "hits": self._cache_hits,
                "misses": self._cache_misses,
                "entries": len(self._cache),
                "max_entries": self._cache_size,
            }

    def _require_vector_index(self) -> None:
        try:
            indexes = self._collection.list_search_indexes()
            for index in indexes:
                if index.get("name") != self._vector_index:
                    continue
                if index.get("queryable") is True or index.get("status") == "READY":
                    return
                raise RuntimeError(
                    f"Atlas Vector Search index '{self._vector_index}' is not "
                    "ready yet. Wait for its status to become READY."
                )
        except PyMongoError as error:
            raise RuntimeError(
                "Could not verify the Atlas Vector Search index. Check the "
                "database user's index-read permissions and the configured "
                "MONGODB_VECTOR_INDEX."
            ) from error
        raise RuntimeError(
            f"Atlas Vector Search index '{self._vector_index}' is missing from "
            "the configured chunks collection. Create it in Atlas before "
            "starting retrieval."
        )

    def _index_missing_vectors(self, chunks: list[KnowledgeChunk]) -> None:
        if not chunks:
            return
        chunk_ids = [chunk.chunk_id for chunk in chunks]
        existing_ids = {
            record["_id"]
            for record in self._collection.find(
                {
                    "_id": {"$in": chunk_ids},
                    "embedding": {"$exists": True},
                    "embedding_model": self._embedding_identity,
                },
                {"_id": 1},
            )
        }
        missing_chunks = [
            chunk for chunk in chunks if chunk.chunk_id not in existing_ids
        ]
        if missing_chunks:
            self._upsert_vectors(missing_chunks)

    def _upsert_vectors(self, chunks: list[KnowledgeChunk]) -> None:
        vectors = self._embeddings.embed_documents([chunk.text for chunk in chunks])
        if len(vectors) != len(chunks):
            raise RuntimeError("Embedding provider returned an unexpected vector count.")
        dimension = len(vectors[0]) if vectors else 0
        if dimension != self._vector_dimensions:
            raise RuntimeError(
                "Embedding dimension does not match MONGODB_VECTOR_DIMENSIONS "
                f"({dimension} != {self._vector_dimensions})."
            )
        if any(
            len(vector) != dimension
            or any(not math.isfinite(value) for value in vector)
            for vector in vectors
        ):
            raise RuntimeError(
                "Embedding provider returned invalid or inconsistent vectors."
            )

        operations = []
        for chunk, vector in zip(chunks, vectors):
            record = _chunk_record(chunk)
            record["embedding"] = vector
            record["embedding_model"] = self._embedding_identity
            operations.append(
                UpdateOne(
                    {"_id": chunk.chunk_id},
                    {
                        "$set": {
                            key: value
                            for key, value in record.items()
                            if key != "_id"
                        },
                        "$setOnInsert": {"_id": chunk.chunk_id},
                    },
                    upsert=True,
                )
            )
        for offset in range(0, len(operations), 500):
            self._collection.bulk_write(
                operations[offset : offset + 500],
                ordered=True,
            )

    def _vector_search(
        self,
        question: str,
        allowed_scopes: set[str],
        limit: int,
    ) -> list[RetrievedChunk]:
        query_vector = self._embeddings.embed_query(question)
        if (
            len(query_vector) != self._vector_dimensions
            or any(not math.isfinite(value) for value in query_vector)
        ):
            raise RuntimeError("Embedding provider returned an invalid query vector.")
        candidate_limit = max(limit * 5, limit)
        pipeline = [
            {
                "$vectorSearch": {
                    "index": self._vector_index,
                    "path": "embedding",
                    "queryVector": query_vector,
                    "numCandidates": max(candidate_limit * 4, candidate_limit + 1),
                    "limit": candidate_limit,
                    "filter": {
                        "access_scope": {"$in": sorted(allowed_scopes)}
                    },
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "chunk_id": 1,
                    "document_id": 1,
                    "title": 1,
                    "source": 1,
                    "access_scope": 1,
                    "source_path": 1,
                    "section": 1,
                    "text": 1,
                    "owner": 1,
                    "version": 1,
                    "effective_date": 1,
                    "next_review": 1,
                    "environment": 1,
                    "score": {"$meta": "vectorSearchScore"},
                }
            },
        ]
        results: list[RetrievedChunk] = []
        for record in self._collection.aggregate(pipeline):
            score = float(record.pop("score", 0.0))
            if (
                record.get("access_scope") not in allowed_scopes
                or score < self._minimum_score
            ):
                continue
            record["chunk_id"] = record.get("chunk_id") or record.get("_id")
            chunk = KnowledgeChunk(**record)
            results.append(RetrievedChunk(chunk, score))
        return results

    def search(
        self,
        question: str,
        allowed_scopes: set[str],
        limit: int = 4,
        mode: RetrievalMode = "hybrid",
    ) -> list[RetrievedChunk]:
        if (
            limit <= 0
            or mode not in ("vector", "keyword", "hybrid")
            or not allowed_scopes
        ):
            return []

        cache_key = (
            tuple(question.lower().split()),
            frozenset(allowed_scopes),
            limit,
            mode,
        )
        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached is not None:
                self._cache_hits += 1
                self._cache.move_to_end(cache_key)
                return list(cached)
            if self._cache_size:
                self._cache_misses += 1

        if mode == "keyword":
            results = self._lexical_index.search(
                question,
                allowed_scopes,
                limit=limit,
                mode="keyword",
            )
        else:
            dense_results = self._vector_search(
                question,
                allowed_scopes,
                max(limit * 5, limit),
            )
            if mode == "vector":
                results = dense_results[:limit]
            else:
                lexical_results = self._lexical_index.search(
                    question,
                    allowed_scopes,
                    limit=max(limit * 5, limit),
                    mode="keyword",
                )
                dense_by_id = {
                    item.chunk.chunk_id: item for item in dense_results
                }
                lexical_by_id = {
                    item.chunk.chunk_id: item for item in lexical_results
                }
                ranks = reciprocal_rank_fusion(
                    [
                        list(dense_by_id),
                        list(lexical_by_id),
                    ]
                )
                ordered = sorted(
                    ranks.items(),
                    key=lambda item: (-item[1], item[0]),
                )
                results = []
                for chunk_id, score in ordered[:limit]:
                    result = dense_by_id.get(chunk_id)
                    if result is None:
                        result = lexical_by_id[chunk_id]
                    results.append(RetrievedChunk(result.chunk, score))

        if self._cache_size:
            with self._cache_lock:
                self._cache[cache_key] = list(results)
                self._cache.move_to_end(cache_key)
                while len(self._cache) > self._cache_size:
                    self._cache.popitem(last=False)
        return results

    def delete_document(self, document_id: str) -> None:
        self._collection.delete_many({"document_id": document_id})
        self._chunks = tuple(
            chunk for chunk in self._chunks if chunk.document_id != document_id
        )
        self._lexical_index = LocalKnowledgeIndex(
            list(self._chunks),
            cache_size=0,
        )
        with self._cache_lock:
            self._cache.clear()

    def add_chunks(self, chunks: list[KnowledgeChunk]) -> None:
        existing_ids = {chunk.chunk_id for chunk in self._chunks}
        new_chunks = [chunk for chunk in chunks if chunk.chunk_id not in existing_ids]
        if not new_chunks:
            return
        self._upsert_vectors(new_chunks)
        self._chunks = (*self._chunks, *new_chunks)
        self._lexical_index = LocalKnowledgeIndex(
            list(self._chunks),
            cache_size=0,
        )
        with self._cache_lock:
            self._cache.clear()


def _chunk_record(chunk: KnowledgeChunk) -> dict[str, Any]:
    return {
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "title": chunk.title,
        "source": chunk.source,
        "access_scope": chunk.access_scope,
        "source_path": chunk.source_path,
        "section": chunk.section,
        "text": chunk.text,
        "owner": chunk.owner,
        "version": chunk.version,
        "effective_date": chunk.effective_date,
        "next_review": chunk.next_review,
        "environment": chunk.environment,
    }
