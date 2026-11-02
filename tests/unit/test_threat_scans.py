import json
import urllib.request

from fastapi.testclient import TestClient

from backend.app.main import app


def _login(client: TestClient, user_id: str) -> None:
    response = client.post("/api/v1/auth/demo-login", json={"user_id": user_id})
    assert response.status_code == 200


def test_threat_scan_api_requires_security_capability(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))

    employee = TestClient(app)
    _login(employee, "demo-employee")
    denied = employee.post(
        "/api/v1/threat-scans/urls",
        json={"url": "https://example.com"},
    )
    assert denied.status_code == 403

    security = TestClient(app)
    _login(security, "demo-security")
    allowed = security.post(
        "/api/v1/threat-scans/urls",
        json={"url": "https://example.com"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["verdict"] == "no-known-indicator"

    status_response = security.get("/api/v1/system/status")
    assert status_response.status_code == 200
    threat_component = next(
        component
        for component in status_response.json()["components"]
        if component["name"] == "Threat detection"
    )
    assert threat_component["mode"] == "local"
    assert threat_component["external_connection"] is False


def test_system_status_reports_virustotal_without_exposing_missing_key(
    monkeypatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.setenv("VIRUSTOTAL_ENABLED", "true")
    monkeypatch.delenv("VIRUSTOTAL_API_KEY", raising=False)

    client = TestClient(app)
    _login(client, "demo-security")
    response = client.get("/api/v1/system/status")

    assert response.status_code == 200
    status = response.json()["virustotal"]
    assert status["enabled"] is True
    assert status["api_key_configured"] is False
    assert status["connection_status"] == "missing_api_key"
    assert status["failure_policy"] == "fail_open"
    assert "fictional-test-key" not in response.text


def test_url_scan_returns_traceable_local_indicators_without_fetch_or_storage(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("AUDIT_LOG_PATH", str(audit_path))

    def unexpected_fetch(*args, **kwargs):
        raise AssertionError("Threat scans must never fetch a URL.")

    monkeypatch.setattr(urllib.request, "urlopen", unexpected_fetch)
    client = TestClient(app)
    _login(client, "demo-security")
    submitted_url = "https://example.com/verify?token=private-demo"

    response = client.post(
        "/api/v1/threat-scans/urls",
        json={"url": submitted_url},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["artifact_type"] == "url"
    assert result["verdict"] == "suspicious"
    assert result["artifact_sha256"]
    assert result["scan_id"]
    assert result["detector_version"] == "fictional-rules-v1"
    assert any(item["rule_id"] == "url-sensitive-path" for item in result["indicators"])
    assert "not proof that the artifact is safe" in " ".join(result["limitations"])
    assert submitted_url not in audit_path.read_text(encoding="utf-8")
    assert not (tmp_path / "threat_scans.json").exists()


def test_email_and_document_scans_extract_findings_and_never_persist_input(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("AUDIT_LOG_PATH", str(audit_path))
    client = TestClient(app)
    _login(client, "demo-security")
    email = (
        "From: Payroll <payroll@example.org>\n"
        "Reply-To: attacker@example.net\n"
        "Subject: Urgent\n\n"
        "Send your verification code immediately: https://example.com/login"
    )

    email_response = client.post(
        "/api/v1/threat-scans/emails",
        json={"email_text": email},
    )
    assert email_response.status_code == 200
    email_result = email_response.json()
    rule_ids = {item["rule_id"] for item in email_result["indicators"]}
    assert {"email-reply-to-mismatch", "credential-request"} <= rule_ids
    assert email_result["extracted_urls"] == ["https://example.com/login"]

    document_text = "This fictional note asks for a password."
    document_response = client.post(
        "/api/v1/threat-scans/documents",
        json={"filename": "sample.txt", "text": document_text},
    )
    assert document_response.status_code == 200
    assert document_response.json()["verdict"] == "suspicious"

    audit = audit_path.read_text(encoding="utf-8")
    assert email not in audit
    assert document_text not in audit
    assert "attacker@example.net" not in audit
    events = [json.loads(line) for line in audit.splitlines()]
    assert all("email_text" not in json.dumps(event) for event in events)


def test_threat_scan_rejects_invalid_url_and_unsupported_document(
    monkeypatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    client = TestClient(app)
    _login(client, "demo-security")

    malformed_url = client.post(
        "/api/v1/threat-scans/urls",
        json={"url": "https://example.com:invalid"},
    )
    assert malformed_url.status_code == 422

    unsupported_document = client.post(
        "/api/v1/threat-scans/documents",
        json={"filename": "sample.pdf", "text": "Not parsed as a binary document."},
    )
    assert unsupported_document.status_code == 422

    oversized_url = client.post(
        "/api/v1/threat-scans/urls",
        json={"url": f"https://example.com/{'a' * 2048}"},
    )
    assert oversized_url.status_code == 422
