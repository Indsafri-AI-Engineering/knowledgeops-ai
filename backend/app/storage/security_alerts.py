import json
import os
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

AlertStatus = Literal["open", "acknowledged", "resolved", "false_positive"]
AlertSeverity = Literal["info", "low", "medium", "high", "critical"]
AlertType = Literal[
    "document_security",
    "threat_indicator",
    "authentication_anomaly",
    "authorization_anomaly",
]
NotificationStatus = Literal["not_configured", "sent", "failed"]
ResponseWorkflowStatus = Literal[
    "not_requested",
    "not_configured",
    "sent",
    "failed",
]
DEFAULT_ALERTS_PATH = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "runtime"
    / "security_alerts.json"
)
_ALERT_LOCK = threading.RLock()


class AlertIndicator(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    severity: AlertSeverity
    description: str
    evidence_redacted: bool = True


class VirusTotalAlertFinding(BaseModel):
    provider: Literal["VirusTotal"] = "VirusTotal"
    threat_category: Literal["Malicious URL", "Suspicious URL", "Unknown URL reputation"]
    severity: AlertSeverity
    detection_ratio: str | None = None
    scan_status: str
    redacted_url: str
    document_event_reference: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SecurityAlert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alert_id: UUID = Field(default_factory=uuid4)
    alert_type: AlertType
    severity: AlertSeverity
    title: str
    summary: str
    status: AlertStatus = "open"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    actor_id: str | None = None
    artifact_sha256: str | None = None
    indicators: list[AlertIndicator] = Field(default_factory=list)
    virustotal_findings: list[VirusTotalAlertFinding] = Field(default_factory=list)
    detector_version: str
    notification_status: NotificationStatus = "not_configured"
    response_workflow_status: ResponseWorkflowStatus = "not_requested"
    resolution_note: str | None = Field(default=None, max_length=1000)
    reviewed_by: str | None = None


class CorruptSecurityAlertStoreError(ValueError):
    """Raised when persisted security alerts cannot be safely loaded."""


class SecurityAlertRepository:
    def __init__(self, path: Path | None = None) -> None:
        configured_path = os.getenv("SECURITY_ALERTS_PATH")
        self.path = path or (
            Path(configured_path) if configured_path else DEFAULT_ALERTS_PATH
        )

    def _read(self) -> dict[str, SecurityAlert]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Alert store must be a JSON object.")
            alerts = {
                key: SecurityAlert.model_validate(value)
                for key, value in payload.items()
            }
            if any(key != str(alert.alert_id) for key, alert in alerts.items()):
                raise ValueError("Alert store keys must match alert IDs.")
            return alerts
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
            raise CorruptSecurityAlertStoreError(
                f"Security alert store contains invalid records: {self.path}"
            ) from error

    def _write(self, alerts: dict[str, SecurityAlert]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                json.dump(
                    {
                        key: alert.model_dump(mode="json")
                        for key, alert in alerts.items()
                    },
                    temporary_file,
                    ensure_ascii=False,
                    indent=2,
                )
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    def create(self, alert: SecurityAlert) -> SecurityAlert:
        key = str(alert.alert_id)
        with _ALERT_LOCK:
            alerts = self._read()
            if key in alerts:
                raise ValueError("Security alert already exists.")
            alerts[key] = alert
            self._write(alerts)
        return alert

    def get(self, alert_id: UUID) -> SecurityAlert | None:
        with _ALERT_LOCK:
            return self._read().get(str(alert_id))

    def list_alerts(
        self,
        *,
        status: AlertStatus | None = None,
        limit: int = 100,
    ) -> list[SecurityAlert]:
        with _ALERT_LOCK:
            alerts = list(self._read().values())
        if status is not None:
            alerts = [alert for alert in alerts if alert.status == status]
        alerts.sort(key=lambda alert: (alert.created_at, str(alert.alert_id)), reverse=True)
        return alerts[:limit]

    def save(self, alert: SecurityAlert) -> SecurityAlert:
        key = str(alert.alert_id)
        with _ALERT_LOCK:
            alerts = self._read()
            if key not in alerts:
                raise KeyError("Security alert does not exist.")
            alert.updated_at = datetime.now(UTC)
            alerts[key] = alert
            self._write(alerts)
        return alert


def get_security_alert_repository() -> SecurityAlertRepository:
    return SecurityAlertRepository()
