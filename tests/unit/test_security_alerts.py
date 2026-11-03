import json
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.integrations.n8n import N8nAlertNotifier, N8nJiraNotifier
from backend.app.main import app
from backend.app.threat_detection.alerts import create_security_alert
from backend.app.threat_detection.monitor import reset_monitor_state


def _login(client: TestClient, user_id: str) -> None:
    response = client.post("/api/v1/auth/demo-login", json={"user_id": user_id})
    assert response.status_code == 200


def test_suspicious_scan_creates_redacted_alert_and_supports_review_lifecycle(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_MODE", "demo")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.setenv("SECURITY_ALERTS_PATH", str(tmp_path / "alerts.json"))
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    client = TestClient(app)
    _login(client, "demo-security")

    scan = client.post(
        "/api/v1/threat-scans/urls",
        json={"url": "http://192.0.2.10/account/verify?token=fictional-secret"},
    )
    assert scan.status_code == 200
    alert_id = scan.json()["security_alert_id"]
    assert alert_id

    alerts = client.get("/api/v1/security/alerts")
    assert alerts.status_code == 200
    alert = alerts.json()[0]
    assert alert["alert_id"] == alert_id
    assert alert["status"] == "open"
    assert alert["notification_status"] == "not_configured"
    assert all(item["evidence_redacted"] for item in alert["indicators"])
    serialized_alerts = (tmp_path / "alerts.json").read_text(encoding="utf-8")
    assert "fictional-secret" not in serialized_alerts
    assert "192.0.2.10" not in serialized_alerts

    acknowledged = client.patch(
        f"/api/v1/security/alerts/{alert_id}",
        json={"status": "acknowledged"},
    )
    assert acknowledged.status_code == 200
    assert acknowledged.json()["reviewed_by"] == "demo-security"
    resolved = client.patch(
        f"/api/v1/security/alerts/{alert_id}",
        json={"status": "resolved"},
    )
    assert resolved.status_code == 200
    repeated = client.patch(
        f"/api/v1/security/alerts/{alert_id}",
        json={"status": "false_positive"},
    )
    assert repeated.status_code == 409


def test_alert_queue_rejects_users_without_security_permissions(
    monkeypatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_MODE", "demo")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    client = TestClient(app)
    _login(client, "demo-employee")

    assert client.get("/api/v1/security/alerts").status_code == 403
    assert client.patch(
        "/api/v1/security/alerts/00000000-0000-0000-0000-000000000001",
        json={"status": "resolved"},
    ).status_code == 403


def test_repeated_auth_denials_generate_anomaly_alert(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_MODE", "demo")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.setenv("SECURITY_ALERTS_PATH", str(tmp_path / "alerts.json"))
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("SECURITY_DENIAL_THRESHOLD", "3")
    monkeypatch.setenv("SECURITY_DENIAL_WINDOW_SECONDS", "300")
    monkeypatch.setenv("SECURITY_DENIAL_ALERT_COOLDOWN_SECONDS", "600")
    reset_monitor_state()
    client = TestClient(app)

    responses = [client.get("/api/v1/me") for _ in range(3)]

    assert all(response.status_code == 401 for response in responses)
    alert_file = tmp_path / "alerts.json"
    alerts = json.loads(alert_file.read_text(encoding="utf-8"))
    alert = next(iter(alerts.values()))
    assert alert["alert_type"] == "authentication_anomaly"
    assert alert["severity"] == "medium"
    assert "testclient" not in alert_file.read_text(encoding="utf-8")


def test_n8n_notifier_sends_only_minimal_alert_metadata(monkeypatch, caplog) -> None:
    monkeypatch.setenv(
        "N8N_ALERT_WEBHOOK_URL",
        "https://automation.example.test/webhook/security-alerts",
    )
    monkeypatch.setenv("N8N_ALERT_WEBHOOK_TOKEN", "test-webhook-token")
    captured: dict[str, object] = {}

    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return httpx.Response(202)

    monkeypatch.setattr(httpx, "post", fake_post)
    notifier = N8nAlertNotifier()
    assert notifier.configured
    result = notifier.notify_security_alert(
        alert_id="alert-id",
        alert_type="document_security",
        severity="high",
        detector_version="test-v1",
        rule_ids=["document-secret-assignment"],
        occurred_at=datetime.now(UTC),
    )

    assert result == "sent"
    payload = captured["json"]
    assert payload["alert_id"] == "alert-id"
    assert payload["rule_ids"] == ["document-secret-assignment"]
    assert "evidence" not in payload
    assert "document_text" not in payload
    assert "test-webhook-token" not in caplog.text
    assert captured["headers"]["Authorization"] == "Bearer test-webhook-token"


def test_n8n_notifier_rejects_insecure_remote_webhook(monkeypatch) -> None:
    monkeypatch.setenv("N8N_ALERT_WEBHOOK_URL", "http://automation.example.test/hook")
    monkeypatch.setenv("N8N_ALERT_WEBHOOK_TOKEN", "test-webhook-token")
    assert not N8nAlertNotifier().configured


def test_n8n_alert_notifier_requires_authentication(monkeypatch, caplog) -> None:
    monkeypatch.setenv(
        "N8N_ALERT_WEBHOOK_URL",
        "https://automation.example.test/webhook/security-alerts",
    )
    monkeypatch.delenv("N8N_ALERT_WEBHOOK_TOKEN", raising=False)

    def unexpected_post(*args, **kwargs):
        raise AssertionError("An unauthenticated security webhook must not be called.")

    monkeypatch.setattr(httpx, "post", unexpected_post)
    notifier = N8nAlertNotifier()
    result = notifier.notify_security_alert(
        alert_id="alert-id",
        alert_type="document_security",
        severity="high",
        detector_version="test-v1",
        rule_ids=["synthetic-test-rule"],
        occurred_at=datetime.now(UTC),
    )

    assert not notifier.configured
    assert result == "failed"
    assert "test-webhook-token" not in caplog.text


def test_n8n_alert_notifier_reports_invalid_authentication(monkeypatch, caplog) -> None:
    monkeypatch.setenv(
        "N8N_ALERT_WEBHOOK_URL",
        "https://automation.example.test/webhook/security-alerts",
    )
    monkeypatch.setenv("N8N_ALERT_WEBHOOK_TOKEN", "test-webhook-token")
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: httpx.Response(401),
    )

    result = N8nAlertNotifier().notify_security_alert(
        alert_id="alert-id",
        alert_type="document_security",
        severity="high",
        detector_version="test-v1",
        rule_ids=["synthetic-test-rule"],
        occurred_at=datetime.now(UTC),
    )

    assert result == "failed"
    assert "test-webhook-token" not in caplog.text


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout])
def test_n8n_alert_notifier_handles_unavailable_webhook(
    monkeypatch,
    error_type: type[httpx.RequestError],
) -> None:
    monkeypatch.setenv(
        "N8N_ALERT_WEBHOOK_URL",
        "https://automation.example.test/webhook/security-alerts",
    )
    monkeypatch.setenv("N8N_ALERT_WEBHOOK_TOKEN", "test-webhook-token")

    def unavailable(*args, **kwargs):
        raise error_type("synthetic webhook unavailable")

    monkeypatch.setattr(httpx, "post", unavailable)
    result = N8nAlertNotifier().notify_security_alert(
        alert_id="alert-id",
        alert_type="document_security",
        severity="high",
        detector_version="test-v1",
        rule_ids=["synthetic-test-rule"],
        occurred_at=datetime.now(UTC),
    )

    assert result == "failed"


@pytest.mark.parametrize("severity", ["critical", "high", "medium", "low"])
def test_n8n_alert_notifier_forwards_severity_for_workflow_routing(
    monkeypatch,
    severity: str,
) -> None:
    monkeypatch.setenv(
        "N8N_ALERT_WEBHOOK_URL",
        "https://automation.example.test/webhook/security-alerts",
    )
    monkeypatch.setenv("N8N_ALERT_WEBHOOK_TOKEN", "test-webhook-token")
    captured: dict[str, object] = {}

    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return httpx.Response(202)

    monkeypatch.setattr(httpx, "post", fake_post)
    result = N8nAlertNotifier().notify_security_alert(
        alert_id="alert-id",
        alert_type="document_security",
        severity=severity,
        detector_version="test-v1",
        rule_ids=["synthetic-test-rule"],
        occurred_at=datetime.now(UTC),
    )

    assert result == "sent"
    assert captured["json"]["severity"] == severity


def test_critical_alert_is_stored_and_notified(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SECURITY_ALERTS_PATH", str(tmp_path / "alerts.json"))
    monkeypatch.setenv(
        "N8N_ALERT_WEBHOOK_URL",
        "https://automation.example.test/webhook/security-alerts",
    )
    monkeypatch.setenv("N8N_ALERT_WEBHOOK_TOKEN", "test-webhook-token")
    captured: dict[str, object] = {}

    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return httpx.Response(202)

    monkeypatch.setattr(httpx, "post", fake_post)
    alert = create_security_alert(
        alert_type="threat_indicator",
        severity="critical",
        title="Synthetic critical alert",
        summary="Synthetic notification test.",
        actor_id=None,
        detector_version="test-v1",
        indicators=[],
    )
    persisted = json.loads((tmp_path / "alerts.json").read_text(encoding="utf-8"))

    assert alert.severity == "critical"
    assert alert.notification_status == "sent"
    assert persisted[str(alert.alert_id)]["severity"] == "critical"
    assert captured["url"] == "https://automation.example.test/webhook/security-alerts"
    assert captured["json"]["severity"] == "critical"


def test_security_and_jira_notifications_use_independent_webhooks(monkeypatch) -> None:
    monkeypatch.setenv(
        "N8N_ALERT_WEBHOOK_URL",
        "https://automation.example.test/webhook/security-alerts",
    )
    monkeypatch.setenv("N8N_ALERT_WEBHOOK_TOKEN", "security-test-token")
    monkeypatch.setenv(
        "N8N_JIRA_WEBHOOK_URL",
        "https://automation.example.test/webhook/jira",
    )
    monkeypatch.setenv("N8N_JIRA_WEBHOOK_TOKEN", "jira-test-token")
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(202)

    monkeypatch.setattr(httpx, "post", fake_post)
    occurred_at = datetime.now(UTC)

    security_status = N8nAlertNotifier().notify_security_alert(
        alert_id="alert-id",
        alert_type="document_security",
        severity="high",
        detector_version="test-v1",
        rule_ids=["synthetic-test-rule"],
        occurred_at=occurred_at,
    )
    jira_status = N8nJiraNotifier().notify_issue_created(
        issue_key="OPS-16",
        project_key="OPS",
        issue_url="https://example.atlassian.net/browse/OPS-16",
    )

    assert security_status == jira_status == "sent"
    assert [url for url, _ in calls] == [
        "https://automation.example.test/webhook/security-alerts",
        "https://automation.example.test/webhook/jira",
    ]
    assert calls[0][1]["json"]["event"] == "knowledgeops.security.alert"
    assert calls[1][1]["json"]["event"] == "knowledgeops.jira.issue_created"


def test_failed_n8n_delivery_is_recorded_on_the_alert(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_MODE", "demo")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.setenv("SECURITY_ALERTS_PATH", str(tmp_path / "alerts.json"))
    monkeypatch.setenv(
        "N8N_ALERT_WEBHOOK_URL",
        "https://automation.example.test/webhook/security-alerts",
    )
    monkeypatch.setenv("N8N_ALERT_WEBHOOK_TOKEN", "test-webhook-token")
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: httpx.Response(503),
    )
    client = TestClient(app)
    _login(client, "demo-security")

    scan = client.post(
        "/api/v1/threat-scans/urls",
        json={"url": "http://192.0.2.10/account/verify"},
    )

    assert scan.status_code == 200
    alerts = client.get("/api/v1/security/alerts")
    assert alerts.status_code == 200
    assert alerts.json()[0]["notification_status"] == "failed"


def test_approved_response_dispatch_requires_acknowledgement_and_confirmation(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_MODE", "demo")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.setenv("SECURITY_ALERTS_PATH", str(tmp_path / "alerts.json"))
    monkeypatch.setenv(
        "N8N_ALERT_WEBHOOK_URL",
        "https://automation.example.test/webhook/security-alerts",
    )
    monkeypatch.setenv("N8N_ALERT_WEBHOOK_TOKEN", "test-webhook-token")
    posted_payloads: list[dict[str, object]] = []

    def fake_post(url, **kwargs):
        posted_payloads.append(kwargs["json"])
        return httpx.Response(202)

    monkeypatch.setattr(httpx, "post", fake_post)
    client = TestClient(app)
    _login(client, "demo-security")
    scan = client.post(
        "/api/v1/threat-scans/urls",
        json={"url": "http://192.0.2.10/account/verify"},
    )
    alert_id = scan.json()["security_alert_id"]

    not_acknowledged = client.post(
        f"/api/v1/security/alerts/{alert_id}/response-workflow",
        json={"confirmed": True},
    )
    missing_confirmation = client.post(
        f"/api/v1/security/alerts/{alert_id}/response-workflow",
        json={},
    )
    assert not_acknowledged.status_code == 409
    assert missing_confirmation.status_code == 422

    acknowledged = client.patch(
        f"/api/v1/security/alerts/{alert_id}",
        json={"status": "acknowledged"},
    )
    assert acknowledged.status_code == 200
    requested = client.post(
        f"/api/v1/security/alerts/{alert_id}/response-workflow",
        json={"confirmed": True},
    )

    assert requested.status_code == 200
    assert requested.json()["response_workflow_status"] == "sent"
    assert posted_payloads[-1]["event"] == "knowledgeops.security.response_requested"
    assert set(posted_payloads[-1]) == {
        "event",
        "alert_id",
        "alert_type",
        "severity",
        "detector_version",
        "rule_ids",
        "occurred_at",
    }
    duplicate_dispatch = client.post(
        f"/api/v1/security/alerts/{alert_id}/response-workflow",
        json={"confirmed": True},
    )
    assert duplicate_dispatch.status_code == 409
