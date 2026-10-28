import json
from datetime import UTC, datetime

import httpx
from fastapi.testclient import TestClient

from backend.app.integrations.n8n import N8nAlertNotifier
from backend.app.main import app
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


def test_n8n_notifier_sends_only_minimal_alert_metadata(monkeypatch) -> None:
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
    assert captured["headers"]["Authorization"] == "Bearer test-webhook-token"


def test_n8n_notifier_rejects_insecure_remote_webhook(monkeypatch) -> None:
    monkeypatch.setenv("N8N_ALERT_WEBHOOK_URL", "http://automation.example.test/hook")
    assert not N8nAlertNotifier().configured


def test_failed_n8n_delivery_is_recorded_on_the_alert(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_MODE", "demo")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.setenv("SECURITY_ALERTS_PATH", str(tmp_path / "alerts.json"))
    monkeypatch.setenv(
        "N8N_ALERT_WEBHOOK_URL",
        "https://automation.example.test/webhook/security-alerts",
    )
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
