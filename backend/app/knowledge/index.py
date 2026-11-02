from functools import lru_cache
import os
from pathlib import Path

from backend.app.knowledge.ingestion import load_knowledge_chunks
from backend.app.knowledge.retrieval import KnowledgeIndex, LocalKnowledgeIndex
from backend.app.storage.knowledge import get_knowledge_document_repository

DEFAULT_SEED_DIRECTORY = (
    Path(__file__).resolve().parents[3] / "data" / "fictional_demo"
)


@lru_cache(maxsize=1)
def get_knowledge_index() -> KnowledgeIndex:
    seed_directory = os.getenv(
        "KNOWLEDGE_SEED_DIRECTORY",
        str(DEFAULT_SEED_DIRECTORY),
    )
    chunks = (
        load_knowledge_chunks(Path(seed_directory))
        if seed_directory
        else []
    )
    chunks.extend(get_knowledge_document_repository().list_chunks())
    rag_backend = os.getenv("RAG_BACKEND", "atlas").strip().lower()
    if rag_backend == "atlas":
        from backend.app.knowledge.mongodb_index import MongoAtlasKnowledgeIndex

        return MongoAtlasKnowledgeIndex(chunks)
    if rag_backend == "qdrant":
        from backend.app.knowledge.qdrant_index import QdrantKnowledgeIndex

        return QdrantKnowledgeIndex(chunks)
    if rag_backend != "local":
        raise ValueError(f"Unsupported RAG_BACKEND: {rag_backend}")
    return LocalKnowledgeIndex(chunks)
