import hashlib
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from backend.app.threat_detection.documents import inspect_document
from backend.app.threat_detection.emails import inspect_email
from backend.app.threat_detection.rules import (
    DETECTOR_VERSION,
    Severity,
    ThreatIndicator,
)
from backend.app.threat_detection.urls import inspect_url

ArtifactType = Literal["url", "email", "document"]
Verdict = Literal["suspicious", "no-known-indicator"]


class ThreatScanResult(BaseModel):
    scan_id: UUID
    security_alert_id: UUID | None = None
    artifact_type: ArtifactType
    artifact_sha256: str
    submitted_reference: str | None = None
    verdict: Verdict
    severity: Severity
    indicators: list[ThreatIndicator] = Field(default_factory=list)
    extracted_urls: list[str] = Field(default_factory=list)
    detector_version: str = DETECTOR_VERSION
    scanned_at: datetime
    limitations: list[str]


def _severity(indicators: list[ThreatIndicator]) -> Severity:
    severities = [indicator.severity for indicator in indicators]
    for severity in ("high", "medium", "low", "info"):
        if severity in severities:
            return severity
    return "info"


def _result(
    artifact_type: ArtifactType,
    content: str,
    indicators: list[ThreatIndicator],
    extracted_urls: list[str] | None = None,
    submitted_reference: str | None = None,
) -> ThreatScanResult:
    return ThreatScanResult(
        scan_id=uuid4(),
        artifact_type=artifact_type,
        artifact_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        submitted_reference=submitted_reference,
        verdict="suspicious" if indicators else "no-known-indicator",
        severity=_severity(indicators),
        indicators=indicators,
        extracted_urls=extracted_urls or [],
        scanned_at=datetime.now(UTC),
        limitations=[
            "Local deterministic rules only; no reputation service or malware engine was queried.",
            "No submitted URL was fetched and no file or attachment was executed.",
            "No-known-indicator is not proof that the artifact is safe.",
            "Results are indicators for human review, not a final fraud determination.",
        ],
    )


def scan_url(url: str) -> ThreatScanResult:
    normalized, indicators = inspect_url(url)
    return _result(
        "url",
        normalized,
        indicators,
    )


def scan_email(text: str) -> ThreatScanResult:
    indicators, urls = inspect_email(text)
    return _result("email", text, indicators, extracted_urls=urls)


def scan_document(filename: str, text: str) -> ThreatScanResult:
    indicators, urls = inspect_document(filename, text)
    return _result(
        "document",
        text,
        indicators,
        extracted_urls=urls,
        submitted_reference=filename,
    )
