import hashlib
import logging
import os
from datetime import UTC, date, datetime
from pathlib import PurePosixPath
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from backend.app.core.auth import get_current_user
from backend.app.core.config import get_virustotal_settings
from backend.app.core.demo_auth import DemoUser
from backend.app.core.permissions import require_capability
from backend.app.knowledge.index import get_knowledge_index
from backend.app.knowledge.document_models import (
    DocumentIngestionError,
    KnowledgeDocumentMetadata,
)
from backend.app.knowledge.office_ingestion import (
    OfficeIngestionError,
    extract_docx_sections,
    extract_office_link_targets,
    extract_pptx_sections,
    extract_xlsx_sections,
)
from backend.app.knowledge.pdf_ingestion import (
    chunks_from_pdf_sections,
    extract_pdf_link_targets,
    extract_pdf_sections,
)
from backend.app.knowledge.text_ingestion import (
    chunks_from_sections,
    extract_html_link_targets,
    extract_text_sections,
    prepare_sections,
)
from backend.app.storage.audit import AuditLog
from backend.app.storage.knowledge import (
    DuplicateKnowledgeDocumentError,
    KnowledgeDocumentRepository,
    StoredKnowledgeDocument,
    get_knowledge_document_repository,
)
from backend.app.storage.security_alerts import VirusTotalAlertFinding
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
from backend.app.threat_detection.urls import inspect_url
from backend.app.threat_detection.virustotal import (
    VirusTotalDocumentSummary,
    VirusTotalService,
    extract_document_urls,
)

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
    status: Literal["stored"] = "stored"
    security_status: Literal["clear", "alert_created"] = "clear"
    security_alert_id: str | None = None
    url_scan: VirusTotalDocumentSummary
    ingestion_blocked: bool = False


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
    user: DemoUser,
    *,
    indicators: list[ThreatIndicator],
    artifact_sha256: str,
    virustotal_findings: list[VirusTotalAlertFinding] | None = None,
) -> str | None:
    if not indicators and not virustotal_findings:
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
        detector_version=f"{document_detector_version()}+virustotal-v1",
        indicators=indicators,
        artifact_sha256=artifact_sha256,
        virustotal_findings=virustotal_findings,
    )
    return str(alert.alert_id)


def _blocked_ingestion_response(
    detail: str,
    *,
    alert_id: str | None,
    url_scan: VirusTotalDocumentSummary | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "detail": detail,
            "security_alert_id": alert_id,
            "url_scan": url_scan.model_dump(mode="json") if url_scan else None,
            "ingestion_blocked": True,
        },
    )


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
    access_scope: Annotated[KnowledgeScope, Form()],
    title: Annotated[str | None, Form(max_length=200)] = None,
    owner: Annotated[str | None, Form(max_length=120)] = None,
    version: Annotated[str | None, Form(max_length=80)] = None,
    effective_date: Annotated[date | None, Form()] = None,
    next_review: Annotated[date | None, Form()] = None,
    environment: Annotated[str | None, Form(max_length=160)] = None,
) -> KnowledgeDocumentIngestResponse | JSONResponse:
    require_capability(user, "knowledge:manage", request)
    if os.getenv("KNOWLEDGE_INGESTION_ENABLED", "false").strip().lower() != "true":
        raise HTTPException(
            status_code=503,
            detail=(
                "Document ingestion is disabled until MongoDB storage and "
                "Atlas Vector Search have been verified."
            ),
        )
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
    document_title = (
        title.strip()
        if title is not None
        else PurePosixPath(filename).stem.strip()
    )
    if not document_title:
        raise HTTPException(status_code=422, detail="Document title cannot be blank.")

    artifact_sha256 = hashlib.sha256(file_bytes).hexdigest()
    preflight_indicators = inspect_document_preflight(filename, file_bytes)
    if should_block_ingestion(preflight_indicators):
        alert_id = _record_document_security_result(
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
        return _blocked_ingestion_response(
            (
                "Document security inspection found high-risk indicators. "
                "The document was blocked before extraction or indexing; "
                f"security alert {alert_id} was created."
            ),
            alert_id=alert_id,
        )

    document_id = str(uuid4())
    metadata = KnowledgeDocumentMetadata(
        document_id=document_id,
        title=document_title,
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
            extracted_sections = extract_pdf_sections(file_bytes)
        elif suffix in {".docx", ".xlsx", ".pptx"}:
            if not file_bytes.startswith(b"PK"):
                raise OfficeIngestionError(
                    "The uploaded content is not a valid Office document."
                )
            if suffix == ".docx":
                extracted_sections = extract_docx_sections(file_bytes)
            elif suffix == ".xlsx":
                extracted_sections = extract_xlsx_sections(file_bytes)
            else:
                extracted_sections = extract_pptx_sections(file_bytes)
        else:
            extracted_sections = extract_text_sections(
                file_bytes,
                html=suffix == ".html",
            )
        link_targets = (
            extract_pdf_link_targets(file_bytes)
            if suffix == ".pdf"
            else (
                extract_office_link_targets(file_bytes)
                if suffix in {".docx", ".xlsx", ".pptx"}
                else (
                    extract_html_link_targets(file_bytes)
                    if suffix == ".html"
                    else []
                )
            )
        )
    except DocumentIngestionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    try:
        normalized_sections = prepare_sections(extracted_sections)
    except DocumentIngestionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    extracted_text = "\n".join(
        paragraph
        for _, paragraphs in normalized_sections
        for paragraph in paragraphs
    )
    extracted_indicators = inspect_document_content(extracted_text)
    extracted_urls = extract_document_urls(extracted_text)
    for link_target in link_targets:
        for link_url in extract_document_urls(link_target):
            if link_url not in extracted_urls:
                extracted_urls.append(link_url)
    local_url_indicators = []
    for extracted_url in extracted_urls:
        _, url_indicators = inspect_url(extracted_url)
        local_url_indicators.extend(url_indicators)

    privacy_sensitive_rules = {
        "document-secret-assignment",
        "document-private-key",
        "document-cloud-access-key",
        "document-bearer-token",
        "document-national-id",
        "document-payment-card",
        "document-personal-email",
        "document-confidential-label",
    }
    suppress_external_lookup = any(
        indicator.rule_id in privacy_sensitive_rules
        for indicator in (*preflight_indicators, *extracted_indicators)
    )
    virustotal_settings = get_virustotal_settings()
    url_scan = await run_in_threadpool(
        VirusTotalService(virustotal_settings).scan_document_urls,
        extracted_urls,
        suppress_external_lookup=suppress_external_lookup,
    )

    virustotal_indicators: list[ThreatIndicator] = []
    virustotal_findings: list[VirusTotalAlertFinding] = []
    failure_statuses = {
        "unknown",
        "provider_unavailable",
        "rate_limited",
        "authentication_failure",
        "not_configured",
    }
    for result in url_scan.results:
        if result.status == "malicious":
            category = "Malicious URL"
            severity = "high"
        elif result.status == "suspicious":
            category = "Suspicious URL"
            severity = "medium"
        elif (
            virustotal_settings.enabled
            and virustotal_settings.failure_policy == "fail_closed"
            and result.status in failure_statuses
        ):
            category = "Unknown URL reputation"
            severity = "high"
        else:
            continue

        virustotal_indicators.append(
            ThreatIndicator(
                rule_id=f"virustotal-url-{result.status.replace('_', '-')}",
                severity=severity,
                description=(
                    f"VirusTotal reported {result.status.replace('_', ' ')} URL "
                    f"reputation"
                    + (
                        f" ({result.detection_ratio} detections)."
                        if result.detection_ratio
                        else "."
                    )
                ),
                evidence=result.redacted_url,
            )
        )
        virustotal_findings.append(
            VirusTotalAlertFinding(
                threat_category=category,
                severity=severity,
                detection_ratio=result.detection_ratio,
                scan_status=result.status,
                redacted_url=result.redacted_url,
                document_event_reference=str(request.state.request_id),
                timestamp=result.checked_at,
            )
        )

    all_indicators = {
        indicator.rule_id: indicator
        for indicator in (
            *preflight_indicators,
            *extracted_indicators,
            *local_url_indicators,
            *virustotal_indicators,
        )
    }
    security_indicators = list(all_indicators.values())
    alert_id = _record_document_security_result(
        user,
        indicators=security_indicators,
        artifact_sha256=artifact_sha256,
        virustotal_findings=virustotal_findings,
    )
    if should_block_ingestion(security_indicators):
        url_scan = url_scan.model_copy(update={"ingestion_blocked": True})
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
        return _blocked_ingestion_response(
            (
                "Document security inspection found high-risk indicators. "
                "The document was blocked before indexing; "
                f"security alert {alert_id} was created."
            ),
            alert_id=alert_id,
            url_scan=url_scan,
        )

    try:
        chunks = (
            chunks_from_pdf_sections(normalized_sections, metadata)
            if suffix == ".pdf"
            else chunks_from_sections(normalized_sections, metadata)
        )
    except DocumentIngestionError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    document = StoredKnowledgeDocument(
        **metadata.__dict__,
        sha256=artifact_sha256,
        uploaded_at=datetime.now(UTC),
        chunk_count=len(chunks),
    )
    index = get_knowledge_index()
    try:
        store.add_document(document, chunks)
        index.add_chunks(chunks)
    except DuplicateKnowledgeDocumentError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except Exception as error:
        store.delete_document(document_id)
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
        url_scan=url_scan,
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
