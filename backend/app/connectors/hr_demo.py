from backend.app.connectors.base import ConnectorMetadata
from backend.app.knowledge.index import get_knowledge_index
from backend.app.knowledge.retrieval import KnowledgeIndex, RetrievedChunk

LEAVE_POLICY_ID = "demo-hr-annual-leave"


class HRDemoConnector:
    metadata = ConnectorMetadata(connector="fictional_hr_demo")

    def __init__(self, index: KnowledgeIndex | None = None) -> None:
        self._index = index or get_knowledge_index()

    def leave_guidance(self, allowed_scopes: set[str]) -> list[RetrievedChunk]:
        if "general" not in allowed_scopes:
            return []
        return [
            result
            for result in self._index.search(
                "annual leave entitlement request approval People Portal",
                allowed_scopes,
                mode="hybrid",
            )
            if result.chunk.document_id == LEAVE_POLICY_ID
        ]
