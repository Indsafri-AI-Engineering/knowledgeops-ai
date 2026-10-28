import os
from hashlib import sha256
import threading
from collections import OrderedDict
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient, models

from backend.app.knowledge.ai_providers import create_embeddings
from backend.app.knowledge.ingestion import KnowledgeChunk
from backend.app.knowledge.retrieval import (
    LocalKnowledgeIndex,
    RetrievalMode,
    RetrievedChunk,
    reciprocal_rank_fusion,
)

DEFAULT_QDRANT_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "runtime" / "qdrant"
)


class QdrantKnowledgeIndex:
    """Persistent local dense retrieval with permission-filtered Qdrant queries."""

    def __init__(
        self,
        chunks: list[KnowledgeChunk],
        *,
        client: QdrantClient | None = None,
        embeddings: Embeddings | None = None,
        collection_name: str | None = None,
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
        base_collection_name = collection_name or os.getenv(
            "QDRANT_COLLECTION",
            "knowledgeops",
        )
        try:
            self._minimum_score = float(os.getenv("QDRANT_MIN_SCORE", "0.5"))
        except ValueError as error:
            raise ValueError("QDRANT_MIN_SCORE must be a number between 0 and 1.") from error
        if not 0 <= self._minimum_score <= 1:
            raise ValueError("QDRANT_MIN_SCORE must be a number between 0 and 1.")

        if client is None:
            path = Path(os.getenv("QDRANT_LOCAL_PATH", str(DEFAULT_QDRANT_PATH)))
            path.parent.mkdir(parents=True, exist_ok=True)
            client = QdrantClient(path=str(path))
        self._client = client
        self._embeddings = embeddings or create_embeddings()
        if collection_name is None:
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
            embedding_identity = f"{embedding_provider}:{embedding_model}"
            suffix = sha256(embedding_identity.encode("utf-8")).hexdigest()[:10]
            self._collection_name = f"{base_collection_name}_{suffix}"
        else:
            self._collection_name = base_collection_name
        if not self._client.collection_exists(self._collection_name):
            vector_size = len(self._embeddings.embed_query("knowledge index dimension"))
            self._client.create_collection(
                collection_name=self._collection_name,
                vectors_config=models.VectorParams(
                    size=vector_size,
                    distance=models.Distance.COSINE,
                ),
            )

        self._vector_store = QdrantVectorStore(
            client=self._client,
            collection_name=self._collection_name,
            embedding=self._embeddings,
            distance=models.Distance.COSINE,
        )
        self._sync_chunks()

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

    def _sync_chunks(self) -> None:
        if not self._chunks:
            return
        documents = [_chunk_to_document(chunk) for chunk in self._chunks]
        ids = [
            str(uuid5(NAMESPACE_URL, chunk.chunk_id))
            for chunk in self._chunks
        ]
        self._vector_store.add_documents(documents=documents, ids=ids)

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
        normalized_tokens = tuple(question.lower().split())
        cache_key = (
            normalized_tokens,
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

        scope_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="metadata.access_scope",
                    match=models.MatchAny(any=sorted(allowed_scopes)),
                )
            ]
        )
        chunk_by_id = {chunk.chunk_id: chunk for chunk in self._chunks}
        dense_ranking: list[tuple[KnowledgeChunk, float]] = []
        if mode != "keyword":
            dense_matches = self._vector_store.similarity_search_with_score(
                question,
                k=max(limit * 5, limit),
                filter=scope_filter,
            )
            dense_ranking = [
                (chunk_by_id[document.metadata["chunk_id"]], score)
                for document, score in dense_matches
                if document.metadata.get("chunk_id") in chunk_by_id
                and score >= self._minimum_score
            ]
        if mode == "vector":
            results = [
                RetrievedChunk(chunk, score)
                for chunk, score in dense_ranking[:limit]
            ]
        else:
            lexical = self._lexical_index.search(
                question,
                allowed_scopes,
                limit=max(limit * 5, limit),
                mode="keyword",
            )
            if mode == "keyword":
                results = lexical[:limit]
            else:
                ranks = reciprocal_rank_fusion(
                    [
                        [chunk.chunk_id for chunk, _ in dense_ranking],
                        [item.chunk.chunk_id for item in lexical],
                    ]
                )
                ordered = sorted(
                    (
                        (chunk_id, fused_score)
                        for chunk_id, fused_score in ranks.items()
                    ),
                    key=lambda item: (-item[1], item[0]),
                )
                results = [
                    RetrievedChunk(chunk_by_id[chunk_id], fused_score)
                    for chunk_id, fused_score in ordered[:limit]
                ]

        if self._cache_size:
            with self._cache_lock:
                self._cache[cache_key] = list(results)
                self._cache.move_to_end(cache_key)
                while len(self._cache) > self._cache_size:
                    self._cache.popitem(last=False)
        return results

    def delete_document(self, document_id: str) -> None:
        ids = [
            str(uuid5(NAMESPACE_URL, chunk.chunk_id))
            for chunk in self._chunks
            if chunk.document_id == document_id
        ]
        if ids:
            self._vector_store.delete(ids=ids)
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
        previous_ids = {chunk.chunk_id for chunk in self._chunks}
        new_chunks = [
            chunk for chunk in chunks if chunk.chunk_id not in previous_ids
        ]
        if not new_chunks:
            return
        documents = [_chunk_to_document(chunk) for chunk in new_chunks]
        self._vector_store.add_documents(
            documents=documents,
            ids=[
                str(uuid5(NAMESPACE_URL, chunk.chunk_id))
                for chunk in new_chunks
            ],
        )
        self._chunks = (*self._chunks, *new_chunks)
        self._lexical_index = LocalKnowledgeIndex(
            list(self._chunks),
            cache_size=0,
        )
        with self._cache_lock:
            self._cache.clear()


def _chunk_to_document(chunk: KnowledgeChunk) -> Document:
    metadata = {
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "title": chunk.title,
        "source": chunk.source,
        "access_scope": chunk.access_scope,
        "source_path": chunk.source_path,
        "section": chunk.section,
        "owner": chunk.owner,
        "version": chunk.version,
        "effective_date": chunk.effective_date,
        "next_review": chunk.next_review,
        "environment": chunk.environment,
    }
    return Document(
        page_content=chunk.text,
        metadata={key: value for key, value in metadata.items() if value is not None},
    )
