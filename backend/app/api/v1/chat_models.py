from pydantic import BaseModel


class SourceCitation(BaseModel):
    title: str
    source: str
    source_path: str
    section: str
    document_id: str
    owner: str | None = None
    version: str | None = None
    effective_date: str | None = None
    next_review: str | None = None
    environment: str | None = None
