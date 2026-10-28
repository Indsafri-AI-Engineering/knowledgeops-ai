from backend.app.connectors.base import ConnectorMetadata
from backend.app.knowledge.index import get_knowledge_index
from backend.app.knowledge.retrieval import KnowledgeIndex, RetrievedChunk


class ITKnowledgeConnector:
    metadata = ConnectorMetadata(connector="fictional_it_knowledge")

    def __init__(self, index: KnowledgeIndex | None = None) -> None:
        self._index = index or get_knowledge_index()

    def troubleshoot(
        self,
        question: str,
        allowed_scopes: set[str],
    ) -> list[RetrievedChunk]:
        return self._index.search(question, allowed_scopes, mode="hybrid")
