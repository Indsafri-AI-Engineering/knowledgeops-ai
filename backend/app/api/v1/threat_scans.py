from typing import Annotated, Callable

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from backend.app.core.auth import get_current_user
from backend.app.core.demo_auth import DemoUser
from backend.app.core.permissions import require_capability
from backend.app.storage.audit import AuditLog
from backend.app.threat_detection.alerts import create_security_alert
from backend.app.threat_detection.scanner import (
    ThreatScanResult,
    scan_document,
    scan_email,
    scan_url,
)

router = APIRouter(prefix="/threat-scans", tags=["threat detection"])


class URLScanRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class EmailScanRequest(BaseModel):
    email_text: str = Field(min_length=1, max_length=50_000)


class DocumentScanRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1, max_length=100_000)


def _scan_artifact(
    request: Request,
    user: DemoUser,
    scan_type: str,
    scan_callable: Callable[[], ThreatScanResult],
) -> ThreatScanResult:
    require_capability(user, "threat_scans:scan", request)
    try:
        result = scan_callable()
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error

    if result.indicators:
        alert = create_security_alert(
            alert_type="threat_indicator",
            severity=result.severity,
            title=f"Suspicious {scan_type} indicator detected",
            summary=(
                f"The local scanner found {len(result.indicators)} indicator(s). "
                "The submitted artifact content is not retained in the alert."
            ),
            actor_id=user.user_id,
            detector_version=result.detector_version,
            indicators=result.indicators,
            artifact_sha256=result.artifact_sha256,
        )
        result.security_alert_id = alert.alert_id

    AuditLog().record(
        request_id=request.state.request_id,
        actor_id=user.user_id,
        action=f"threat_scan.{scan_type}",
        resource_type="threat_scan",
        outcome="success",
        metadata={
            "scan_id": str(result.scan_id),
            "verdict": result.verdict,
            "indicator_count": len(result.indicators),
            "security_alert_id": (
                str(result.security_alert_id) if result.security_alert_id else ""
            ),
        },
    )
    return result


@router.post("/urls", response_model=ThreatScanResult)
def create_url_scan(
    payload: URLScanRequest,
    request: Request,
    user: Annotated[DemoUser, Depends(get_current_user)],
) -> ThreatScanResult:
    return _scan_artifact(
        request,
        user,
        "url",
        lambda: scan_url(payload.url),
    )


@router.post("/emails", response_model=ThreatScanResult)
def create_email_scan(
    payload: EmailScanRequest,
    request: Request,
    user: Annotated[DemoUser, Depends(get_current_user)],
) -> ThreatScanResult:
    return _scan_artifact(
        request,
        user,
        "email",
        lambda: scan_email(payload.email_text),
    )


@router.post("/documents", response_model=ThreatScanResult)
def create_document_scan(
    payload: DocumentScanRequest,
    request: Request,
    user: Annotated[DemoUser, Depends(get_current_user)],
) -> ThreatScanResult:
    return _scan_artifact(
        request,
        user,
        "document",
        lambda: scan_document(payload.filename, payload.text),
    )
