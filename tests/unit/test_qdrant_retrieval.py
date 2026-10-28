import hashlib

from langchain_core.embeddings import Embeddings
from qdrant_client import QdrantClient

from backend.app.knowledge.ingestion import KnowledgeChunk
from backend.app.knowledge.qdrant_index import QdrantKnowledgeIndex
from backend.app.knowledge.retrieval import reciprocal_rank_fusion


class HashEmbeddings(Embeddings):
    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * 64
        for token in text.lower().split():
            position = int.from_bytes(
                hashlib.sha256(token.encode("utf-8")).digest()[:2],
                byteorder="big",
            ) % len(vector)
            vector[position] += 1.0
        return vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class OrthogonalEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.0, 1.0] if "unrelated" in text else [1.0, 0.0]


class SplitSignalEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [
            [1.0, 0.0] if "semantic-only" in text else [0.0, 1.0]
            for text in texts
        ]

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0]


def _chunk(
    chunk_id: str,
    document_id: str,
    access_scope: str,
    text: str,
) -> KnowledgeChunk:
    return KnowledgeChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        title=document_id,
        source="synthetic_test",
        access_scope=access_scope,
        source_path=f"{document_id}.pdf",
        section="Page 1",
        text=text,
    )


def test_reciprocal_rank_fusion_rewards_shared_results_and_deduplicates() -> None:
    scores = reciprocal_rank_fusion(
        [
            ["shared", "semantic-only", "semantic-only"],
            ["shared", "keyword-only"],
        ]
    )

    assert scores == {
        "shared": (1 / 61) + (1 / 61),
        "semantic-only": 1 / 62,
        "keyword-only": 1 / 62,
    }


def test_hybrid_search_fuses_semantic_and_bm25_only_candidates(tmp_path) -> None:
    chunks = [
        _chunk(
            "semantic:0",
            "semantic",
            "it",
            "semantic-only conceptually related passage",
        ),
        _chunk(
            "keyword:0",
            "keyword",
            "it",
            "exact zebra protocol keyword match",
        ),
    ]
    client = QdrantClient(path=str(tmp_path / "qdrant"))
    index = QdrantKnowledgeIndex(
        chunks,
        client=client,
        embeddings=SplitSignalEmbeddings(),
        collection_name="hybrid-fusion-test",
    )

    dense_results = index.search(
        "exact zebra protocol",
        {"it"},
        limit=4,
        mode="vector",
    )
    keyword_results = index.search(
        "exact zebra protocol",
        {"it"},
        limit=4,
        mode="keyword",
    )
    hybrid_results = index.search(
        "exact zebra protocol",
        {"it"},
        limit=4,
        mode="hybrid",
    )

    assert [item.chunk.document_id for item in dense_results] == ["semantic"]
    assert [item.chunk.document_id for item in keyword_results] == ["keyword"]
    assert {item.chunk.document_id for item in hybrid_results} == {
        "semantic",
        "keyword",
    }
    assert all(item.score > 0 for item in hybrid_results)
    client.close()


def test_qdrant_search_modes_apply_scope_filters_before_results(
    tmp_path,
) -> None:
    chunks = [
        _chunk(
            "hr-guide:0",
            "hr-guide",
            "hr",
            "violet arc lamp configuration and calibration procedures",
        ),
        _chunk(
            "it-guide:0",
            "it-guide",
            "it",
            "violet arc lamp configuration and calibration procedures",
        ),
    ]
    client = QdrantClient(path=str(tmp_path / "qdrant"))
    index = QdrantKnowledgeIndex(
        chunks,
        client=client,
        embeddings=HashEmbeddings(),
        collection_name="scoped-test",
    )

    for mode in ("vector", "keyword", "hybrid"):
        results = index.search(
            "violet arc lamp configuration",
            {"hr"},
            limit=2,
            mode=mode,
        )
        assert results
        assert {result.chunk.document_id for result in results} == {"hr-guide"}

    assert index.cache_info()["hits"] == 0
    index.search(
        "violet arc lamp configuration",
        {"hr"},
        limit=2,
        mode="vector",
    )
    assert index.cache_info()["hits"] == 1
    client.close()


def test_qdrant_index_deletes_vectors_for_document(tmp_path) -> None:
    client = QdrantClient(path=str(tmp_path / "qdrant"))
    index = QdrantKnowledgeIndex(
        [_chunk("remove-me:0", "remove-me", "it", "synthetic violet calibration")],
        client=client,
        embeddings=HashEmbeddings(),
        collection_name="delete-test",
    )

    index.delete_document("remove-me")

    assert index.chunks == []
    assert index.search("violet calibration", {"it"}) == []
    client.close()


def test_qdrant_index_adds_chunks_to_dense_and_hybrid_search(tmp_path) -> None:
    client = QdrantClient(path=str(tmp_path / "qdrant"))
    index = QdrantKnowledgeIndex(
        [],
        client=client,
        embeddings=HashEmbeddings(),
        collection_name="add-test",
    )

    index.add_chunks(
        [_chunk("new-guide:0", "new-guide", "it", "amber zephyr router setup")]
    )

    for mode in ("vector", "hybrid"):
        results = index.search("amber zephyr router", {"it"}, mode=mode)
        assert results
        assert results[0].chunk.document_id == "new-guide"
    client.close()


def test_qdrant_dense_search_abstains_below_relevance_threshold(tmp_path) -> None:
    client = QdrantClient(path=str(tmp_path / "qdrant"))
    index = QdrantKnowledgeIndex(
        [_chunk("known:0", "known", "it", "known equipment procedure")],
        client=client,
        embeddings=OrthogonalEmbeddings(),
        collection_name="threshold-test",
    )

    assert index.search("unrelated topic", {"it"}, mode="vector") == []
    assert index.search("unrelated topic", {"it"}, mode="hybrid") == []
    client.close()


def test_qdrant_rejects_invalid_minimum_score(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("QDRANT_MIN_SCORE", "1.5")

    try:
        QdrantKnowledgeIndex(
            [],
            client=QdrantClient(path=str(tmp_path / "qdrant")),
            embeddings=HashEmbeddings(),
            collection_name="invalid-threshold-test",
        )
    except ValueError as error:
        assert "QDRANT_MIN_SCORE" in str(error)
    else:
        raise AssertionError("An out-of-range QDRANT_MIN_SCORE must fail.")


def test_default_qdrant_collection_is_namespaced_by_embedding_model(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("QDRANT_COLLECTION", "model-namespace-test")
    monkeypatch.setenv("RAG_EMBEDDING_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_EMBEDDING_MODEL", "local-model-a")
    client = QdrantClient(path=str(tmp_path / "qdrant"))
    first = QdrantKnowledgeIndex(
        [],
        client=client,
        embeddings=HashEmbeddings(),
    )

    monkeypatch.setenv("OLLAMA_EMBEDDING_MODEL", "local-model-b")
    second = QdrantKnowledgeIndex(
        [],
        client=client,
        embeddings=HashEmbeddings(),
    )

    assert first._collection_name != second._collection_name
    client.close()
