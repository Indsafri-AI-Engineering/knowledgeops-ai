from dataclasses import dataclass


MAX_EXTRACTED_CHARACTERS = 500_000


class DocumentIngestionError(ValueError):
    pass


@dataclass(frozen=True)
class KnowledgeDocumentMetadata:
    document_id: str
    title: str
    filename: str
    source: str
    access_scope: str
    owner: str | None = None
    version: str | None = None
    effective_date: str | None = None
    next_review: str | None = None
    environment: str | None = None
    document_type: str = "application/pdf"
