from datetime import UTC, datetime
import logging
import os
from uuid import UUID, NAMESPACE_URL, uuid5
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class NotificationResult(BaseModel):
    notification_id: str
    status: str = "simulated"
    destination: str = "fictional IT Support queue"
    sent_at: datetime


class N8nDemoConnector:
    """Simulates a minimal notification and never calls a webhook."""

    def notify_issue_created(
        self,
        action_id: UUID,
        issue_key: str,
        assignee_team: str,
    ) -> NotificationResult:
        return NotificationResult(
            notification_id=str(uuid5(NAMESPACE_URL, f"jira-action:{action_id}")),
            sent_at=datetime.now(UTC),
            destination=f"fictional {assignee_team} queue",
        )


class N8nJiraNotifier:
    """Sends minimal metadata after a Jira issue has been created."""

    def __init__(self) -> None:
        self._webhook_url = os.getenv("N8N_JIRA_WEBHOOK_URL", "").strip()
        self._webhook_token = os.getenv("N8N_JIRA_WEBHOOK_TOKEN", "").strip()

    @property
    def configured(self) -> bool:
        if not self._webhook_url:
            return False
        try:
            parsed = urlsplit(self._webhook_url)
            port = parsed.port
        except ValueError:
            return False
        local_http = parsed.scheme == "http" and parsed.hostname in {
            "localhost",
            "127.0.0.1",
            "::1",
        }
        return bool(
            (parsed.scheme == "https" or local_http)
            and parsed.hostname
            and parsed.path
            and (port is None or 1 <= port <= 65535)
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
        )

    def notify_issue_created(
        self,
        *,
        issue_key: str,
        project_key: str,
        issue_url: str,
    ) -> str:
        if not self._webhook_url:
            return "not_configured"
        if not self.configured:
            logger.error("n8n Jira webhook configuration is invalid.")
            return "failed"

        headers = {"Accept": "application/json"}
        if self._webhook_token:
            headers["Authorization"] = f"Bearer {self._webhook_token}"
        payload = {
            "event": "knowledgeops.jira.issue_created",
            "issue_key": issue_key,
            "project_key": project_key,
            "issue_url": issue_url,
        }
        try:
            response = httpx.post(
                self._webhook_url,
                json=payload,
                headers=headers,
                timeout=3.0,
                follow_redirects=False,
            )
        except httpx.RequestError:
            logger.warning("n8n Jira notification delivery failed due to a network error.")
            return "failed"
        if not response.is_success:
            logger.warning(
                "n8n Jira notification delivery returned HTTP %s.",
                response.status_code,
            )
            return "failed"
        return "sent"


class N8nAlertNotifier:
    """Delivers minimal security-alert metadata to an explicitly configured webhook."""

    def __init__(self) -> None:
        self._webhook_url = os.getenv("N8N_ALERT_WEBHOOK_URL", "").strip()
        self._webhook_token = os.getenv("N8N_ALERT_WEBHOOK_TOKEN", "").strip()

    @property
    def configured(self) -> bool:
        if not self._webhook_url:
            return False
        try:
            parsed = urlsplit(self._webhook_url)
            port = parsed.port
        except ValueError:
            return False
        local_http = parsed.scheme == "http" and parsed.hostname in {
            "localhost",
            "127.0.0.1",
            "::1",
        }
        return bool(
            (parsed.scheme == "https" or local_http)
            and parsed.hostname
            and parsed.path
            and (port is None or 1 <= port <= 65535)
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
        )

    def notify_security_alert(
        self,
        *,
        alert_id: str,
        alert_type: str,
        severity: str,
        detector_version: str,
        rule_ids: list[str],
        occurred_at: datetime,
    ) -> str:
        return self._send_alert_event(
            event="knowledgeops.security.alert",
            alert_id=alert_id,
            alert_type=alert_type,
            severity=severity,
            detector_version=detector_version,
            rule_ids=rule_ids,
            occurred_at=occurred_at,
        )

    def request_approved_response(
        self,
        *,
        alert_id: str,
        alert_type: str,
        severity: str,
        detector_version: str,
        rule_ids: list[str],
        occurred_at: datetime,
    ) -> str:
        return self._send_alert_event(
            event="knowledgeops.security.response_requested",
            alert_id=alert_id,
            alert_type=alert_type,
            severity=severity,
            detector_version=detector_version,
            rule_ids=rule_ids,
            occurred_at=occurred_at,
        )

    def _send_alert_event(
        self,
        *,
        event: str,
        alert_id: str,
        alert_type: str,
        severity: str,
        detector_version: str,
        rule_ids: list[str],
        occurred_at: datetime,
    ) -> str:
        if not self.configured:
            return "not_configured"
        headers = {"Accept": "application/json"}
        if self._webhook_token:
            headers["Authorization"] = f"Bearer {self._webhook_token}"
        payload = {
            "event": event,
            "alert_id": alert_id,
            "alert_type": alert_type,
            "severity": severity,
            "detector_version": detector_version,
            "rule_ids": rule_ids,
            "occurred_at": occurred_at.isoformat(),
        }
        try:
            response = httpx.post(
                self._webhook_url,
                json=payload,
                headers=headers,
                timeout=3.0,
                follow_redirects=False,
            )
        except httpx.RequestError:
            logger.warning("n8n security alert delivery failed due to a network error.")
            return "failed"
        if not response.is_success:
            logger.warning(
                "n8n security alert delivery returned HTTP %s.",
                response.status_code,
            )
            return "failed"
        return "sent"
