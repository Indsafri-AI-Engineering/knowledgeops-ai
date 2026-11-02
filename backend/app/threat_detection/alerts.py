import os

from backend.app.integrations.n8n import N8nAlertNotifier
from backend.app.storage.security_alerts import (
    AlertIndicator,
    AlertSeverity,
    AlertType,
    SecurityAlert,
    SecurityAlertRepository,
    VirusTotalAlertFinding,
)
from backend.app.threat_detection.rules import DETECTOR_VERSION, ThreatIndicator

_SEVERITY_ORDER: dict[str, int] = {
    "info": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
}


def highest_severity(indicators: list[ThreatIndicator]) -> AlertSeverity:
    if not indicators:
        return "info"
    return max(
        (indicator.severity for indicator in indicators),
        key=_SEVERITY_ORDER.__getitem__,
    )


def should_block_ingestion(indicators: list[ThreatIndicator]) -> bool:
    configured_threshold = os.getenv(
        "THREAT_INGESTION_BLOCK_SEVERITY",
        "high",
    ).strip().lower()
    if configured_threshold not in _SEVERITY_ORDER:
        raise RuntimeError(
            "THREAT_INGESTION_BLOCK_SEVERITY must be info, low, medium, or high."
        )
    threshold = _SEVERITY_ORDER[configured_threshold]
    return any(
        _SEVERITY_ORDER[indicator.severity] >= threshold
        for indicator in indicators
    )


def create_security_alert(
    *,
    alert_type: AlertType,
    severity: AlertSeverity,
    title: str,
    summary: str,
    actor_id: str | None,
    detector_version: str,
    indicators: list[ThreatIndicator],
    artifact_sha256: str | None = None,
    virustotal_findings: list[VirusTotalAlertFinding] | None = None,
) -> SecurityAlert:
    alert = SecurityAlert(
        alert_type=alert_type,
        severity=severity,
        title=title,
        summary=summary,
        actor_id=actor_id,
        artifact_sha256=artifact_sha256,
        detector_version=detector_version,
        virustotal_findings=virustotal_findings or [],
        indicators=[
            AlertIndicator(
                rule_id=indicator.rule_id,
                severity=indicator.severity,
                description=indicator.description,
                evidence_redacted=True,
            )
            for indicator in indicators
        ],
    )
    repository = SecurityAlertRepository()
    repository.create(alert)
    notification_status = N8nAlertNotifier().notify_security_alert(
        alert_id=str(alert.alert_id),
        alert_type=alert.alert_type,
        severity=alert.severity,
        detector_version=alert.detector_version,
        rule_ids=[indicator.rule_id for indicator in alert.indicators],
        occurred_at=alert.created_at,
    )
    alert.notification_status = notification_status
    return repository.save(alert)


def document_detector_version() -> str:
    return f"{DETECTOR_VERSION}+document-security-v1"
