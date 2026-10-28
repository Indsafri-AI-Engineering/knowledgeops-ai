import hashlib
import logging
from datetime import UTC, date, datetime
from pathlib import PurePosixPath
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from backend.app.core.auth import get_current_user
from backend.app.core.demo_auth import DemoUser
from backend.app.core.permissions import require_capability
from backend.app.knowledge.index import get_knowledge_index
from backend.app.knowledge.document_models import (
    DocumentIngestionError,
    KnowledgeDocumentMetadata,
)
from backend.app.knowledge.office_ingestion import (
    OfficeIngestionError,
    extract_docx_chunks,
    extract_pptx_chunks,
    extract_xlsx_chunks,
)
from backend.app.knowledge.pdf_ingestion import extract_pdf_chunks
from backend.app.knowledge.text_ingestion import extract_text_chunks
from backend.app.storage.audit import AuditLog
from backend.app.storage.knowledge import (
    DuplicateKnowledgeDocumentError,
    KnowledgeDocumentRepository,
    StoredKnowledgeDocument,
    get_knowledge_document_repository,
)
from backend.app.threat_detection.alerts import (
    create_security_alert,
    document_detector_version,
    highest_severity,
    should_block_ingestion,
)
from backend.app.threat_detection.document_security import (
    inspect_document_content,
    inspect_document_preflight,
)
from backend.app.threat_detection.rules import ThreatIndicator

router = APIRouter(prefix="/knowledge", tags=["knowledge documents"])
logger = logging.getLogger(__name__)
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
DOCUMENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".html": "text/html",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
KnowledgeScope = Literal["general", "hr", "it", "recruitment"]


class KnowledgeDocumentSummary(BaseModel):
    document_id: str
    title: str
    filename: str
    source: str
    document_type: str
    sha256: str
    access_scope: str
    uploaded_at: date
    owner: str | None = None
    version: str | None = None
    chunk_count: int


class KnowledgeDocumentIngestResponse(BaseModel):
    document: KnowledgeDocumentSummary
    status: Literal["stored_locally"] = "stored_locally"
    security_status: Literal["clear", "alert_created"] = "clear"
    security_alert_id: str | None = None


def _summary(document: StoredKnowledgeDocument) -> KnowledgeDocumentSummary:
    return KnowledgeDocumentSummary(
        document_id=document.document_id,
        title=document.title,
        filename=document.filename,
        source=document.source,
        document_type=document.document_type,
        sha256=document.sha256,
        access_scope=document.access_scope,
        uploaded_at=document.uploaded_at.date(),
        owner=document.owner,
        version=document.version,
        chunk_count=document.chunk_count,
    )


def _audit(
    request: Request,
    user: DemoUser,
    *,
    action: str,
    metadata: dict[str, str | int | bool],
) -> None:
    AuditLog().record(
        request_id=request.state.request_id,
        actor_id=user.user_id,
        action=action,
        resource_type="local_knowledge_document",
        outcome="success",
        metadata=metadata,
    )


def _record_document_security_result(
    request: Request,
    user: DemoUser,
    *,
    indicators: list[ThreatIndicator],
    artifact_sha256: str,
) -> str | None:
    if not indicators:
        return None
    alert = create_security_alert(
        alert_type="document_security",
        severity=highest_severity(indicators),
        title="Pre-ingestion document security indicators",
        summary=(
            f"Document security inspection found {len(indicators)} indicator(s). "
            "Source content and matched values are not stored in this alert."
        ),
        actor_id=user.user_id,
        detector_version=document_detector_version(),
        indicators=indicators,
        artifact_sha256=artifact_sha256,
    )
    return str(alert.alert_id)


@router.get("/documents", response_model=list[KnowledgeDocumentSummary])
def list_knowledge_documents(
    request: Request,
    user: Annotated[DemoUser, Depends(get_current_user)],
    store: Annotated[
        KnowledgeDocumentRepository,
        Depends(get_knowledge_document_repository),
    ],
) -> list[KnowledgeDocumentSummary]:
    require_capability(user, "knowledge:manage", request)
    documents = store.list_documents()
    _audit(
        request,
        user,
        action="knowledge.document.list",
        metadata={"result_count": len(documents)},
    )
    return [_summary(document) for document in documents]


@router.post(
    "/documents",
    response_model=KnowledgeDocumentIngestResponse,
    status_code=201,
)
async def ingest_knowledge_document(
    request: Request,
    user: Annotated[DemoUser, Depends(get_current_user)],
    store: Annotated[
        KnowledgeDocumentRepository,
        Depends(get_knowledge_document_repository),
    ],
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form(min_length=1, max_length=200)],
    access_scope: Annotated[KnowledgeScope, Form()],
    owner: Annotated[str | None, Form(max_length=120)] = None,
    version: Annotated[str | None, Form(max_length=80)] = None,
    effective_date: Annotated[date | None, Form()] = None,
    next_review: Annotated[date | None, Form()] = None,
    environment: Annotated[str | None, Form(max_length=160)] = None,
) -> KnowledgeDocumentIngestResponse:
    require_capability(user, "knowledge:manage", request)
    filename = PurePosixPath((file.filename or "").replace("\\", "/")).name
    suffix = PurePosixPath(filename).suffix.lower()
    document_type = DOCUMENT_TYPES.get(suffix)
    if not filename or document_type is None:
        raise HTTPException(
            status_code=415,
            detail="Upload a PDF, DOCX, TXT, MD, HTML, XLSX, or PPTX document.",
        )

    file_bytes = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Document size is limited to 10 MiB.",
        )
    if not title.strip():
        raise HTTPException(status_code=422, detail="Document title cannot be blank.")

    artifact_sha256 = hashlib.sha256(file_bytes).hexdigest()
    preflight_indicators = inspect_document_preflight(filename, file_bytes)
    if should_block_ingestion(preflight_indicators):
        alert_id = _record_document_security_result(
            request,
            user,
            indicators=preflight_indicators,
            artifact_sha256=artifact_sha256,
        )
        AuditLog().record(
            request_id=request.state.request_id,
            actor_id=user.user_id,
            action="knowledge.document.security_blocked",
            resource_type="document_upload",
            outcome="failure",
            metadata={
                "alert_id": alert_id or "",
                "severity": highest_severity(preflight_indicators),
            },
        )
        raise HTTPException(
            status_code=422,
            detail=(
                "Document security inspection found high-risk indicators. "
                "The document was blocked before extraction or indexing; "
                f"security alert {alert_id} was created."
            ),
        )

    document_id = str(uuid4())
    metadata = KnowledgeDocumentMetadata(
        document_id=document_id,
        title=title.strip(),
        filename=filename,
        source="uploaded",
        access_scope=access_scope,
        owner=owner.strip() if owner and owner.strip() else None,
        version=version.strip() if version and version.strip() else None,
        effective_date=effective_date.isoformat() if effective_date else None,
        next_review=next_review.isoformat() if next_review else None,
        environment=environment.strip() if environment and environment.strip() else None,
        document_type=document_type,
    )
    try:
        if suffix == ".pdf":
            if not file_bytes.startswith(b"%PDF-"):
                raise HTTPException(
                    status_code=415,
                    detail="The uploaded content is not a PDF.",
                )
            chunks = extract_pdf_chunks(file_bytes, metadata)
        elif suffix in {".docx", ".xlsx", ".pptx"}:
            if not file_bytes.startswith(b"PK"):
                raise OfficeIngestionError(
                    "The uploaded content is not a valid Office document."
                )
            if suffix == ".docx":
                chunks = extract_docx_chunks(file_bytes, metadata)
            elif suffix == ".xlsx":
                chunks = extract_xlsx_chunks(file_bytes, metadata)
            else:
                chunks = extract_pptx_chunks(file_bytes, metadata)
        else:
            chunks = extract_text_chunks(
                file_bytes,
                metadata,
                html=suffix == ".html",
            )
    except DocumentIngestionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    extracted_text = "\n".join(chunk.text for chunk in chunks)
    extracted_indicators = inspect_document_content(extracted_text)
    all_indicators = {
        indicator.rule_id: indicator
        for indicator in (*preflight_indicators, *extracted_indicators)
    }
    security_indicators = list(all_indicators.values())
    alert_id = _record_document_security_result(
        request,
        user,
        indicators=security_indicators,
        artifact_sha256=artifact_sha256,
    )
    if should_block_ingestion(security_indicators):
        AuditLog().record(
            request_id=request.state.request_id,
            actor_id=user.user_id,
            action="knowledge.document.security_blocked",
            resource_type="document_upload",
            outcome="failure",
            metadata={
                "alert_id": alert_id or "",
                "severity": highest_severity(security_indicators),
            },
        )
        raise HTTPException(
            status_code=422,
            detail=(
                "Document security inspection found high-risk indicators. "
                "The document was blocked before indexing; "
                f"security alert {alert_id} was created."
            ),
        )

    document = StoredKnowledgeDocument(
        **metadata.__dict__,
        sha256=artifact_sha256,
        uploaded_at=datetime.now(UTC),
        chunk_count=len(chunks),
    )
    index = get_knowledge_index()
    try:
        index.add_chunks(chunks)
        store.add_document(document, chunks)
    except DuplicateKnowledgeDocumentError as error:
        index.delete_document(document_id)
        raise HTTPException(status_code=409, detail=str(error)) from error
    except Exception as error:
        index.delete_document(document_id)
        logger.exception("Failed to index uploaded document %s", document_id)
        raise HTTPException(
            status_code=503,
            detail="The document was not stored because indexing failed.",
        ) from error
    _audit(
        request,
        user,
        action="knowledge.document.ingest",
        metadata={
            "document_id": document_id,
            "access_scope": access_scope,
            "chunk_count": len(chunks),
            "security_alert_id": alert_id or "",
        },
    )
    return KnowledgeDocumentIngestResponse(
        document=_summary(document),
        security_status="alert_created" if alert_id else "clear",
        security_alert_id=alert_id,
    )


@router.delete("/documents/{document_id}", status_code=204)
def delete_knowledge_document(
    document_id: str,
    request: Request,
    user: Annotated[DemoUser, Depends(get_current_user)],
    store: Annotated[
        KnowledgeDocumentRepository,
        Depends(get_knowledge_document_repository),
    ],
) -> None:
    require_capability(user, "knowledge:manage", request)
    index = get_knowledge_index()
    deleted = store.delete_document(document_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Knowledge document not found.")
    index.delete_document(document_id)
    _audit(
        request,
        user,
        action="knowledge.document.delete",
        metadata={"document_id": document_id},
    )
