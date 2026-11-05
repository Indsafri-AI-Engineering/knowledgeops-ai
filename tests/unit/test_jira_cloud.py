from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.integrations.jira_cloud import (
    JiraCloudClient,
    JiraConfigurationError,
    JiraRequestError,
)
from backend.app.main import app
from conftest import authenticate_as


def _response(payload: dict, status_code: int = 200) -> SimpleNamespace:
    return SimpleNamespace(
        status_code=status_code,
        content=b"{}" if status_code != 204 else b"",
        is_success=200 <= status_code < 300,
        json=lambda: payload,
    )


def test_jira_client_requires_secure_configured_cloud_credentials(monkeypatch) -> None:
    monkeypatch.delenv("JIRA_BASE_URL", raising=False)
    monkeypatch.delenv("JIRA_EMAIL", raising=False)
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)

    client = JiraCloudClient()
    assert not client.configured
    with pytest.raises(JiraConfigurationError, match="JIRA_BASE_URL"):
        client.projects()

    monkeypatch.setenv("JIRA_BASE_URL", "http://jira.example.test")
    monkeypatch.setenv("JIRA_EMAIL", "service@example.test")
    monkeypatch.setenv("JIRA_API_TOKEN", "test-token")
    with pytest.raises(JiraConfigurationError, match="HTTPS"):
        JiraCloudClient().projects()


def test_jira_cloud_search_escapes_text_and_maps_issue_fields(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_request(method, url, **kwargs):
        captured.update(method=method, url=url, **kwargs)
        return _response(
            {
                "issues": [
                    {
                        "id": "10001",
                        "key": "OPS-15",
                        "fields": {
                            "summary": "Investigate sign-in",
                            "description": {
                                "type": "doc",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [{"type": "text", "text": "Steps"}],
                                    }
                                ],
                            },
                            "status": {"name": "In Progress"},
                            "priority": {"name": "High"},
                            "project": {"key": "OPS"},
                            "assignee": {"displayName": "A. Employee"},
                            "issuetype": {"name": "Bug"},
                            "updated": "2026-10-27T06:00:00.000+0000",
                        },
                    }
                ]
            }
        )

    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net/")
    monkeypatch.setenv("JIRA_EMAIL", "service@example.test")
    monkeypatch.setenv("JIRA_API_TOKEN", "test-token")
    monkeypatch.setattr(httpx, "request", fake_request)

    issues = JiraCloudClient().search_issues('login "problem"', "OPS", 10)

    assert issues == [
        {
            "id": "10001",
            "key": "OPS-15",
            "summary": "Investigate sign-in",
            "description": "Steps",
            "status": "In Progress",
            "priority": "High",
            "project_key": "OPS",
            "assignee": "A. Employee",
            "issue_type": "Bug",
            "updated": "2026-10-27T06:00:00.000+0000",
        }
    ]
    assert captured["method"] == "POST"
    assert captured["url"] == "https://example.atlassian.net/rest/api/3/search/jql"
    request_payload = captured["json"]
    assert request_payload["jql"] == 'text ~ "login \\"problem\\"" AND project = OPS'
    assert captured["auth"] == ("service@example.test", "test-token")
    assert captured["follow_redirects"] is False


def test_jira_client_builds_cloud_issue_and_comment_payloads(monkeypatch) -> None:
    calls: list[tuple[str, str, dict]] = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if url.endswith("/rest/api/3/issue"):
            return _response(
                {
                    "id": "10002",
                    "key": "OPS-16",
                    "self": "https://example.atlassian.net/rest/api/3/issue/10002",
                }
            )
        if url.endswith("/comment"):
            return _response({"id": "30001"})
        return _response({}, status_code=204)

    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "service@example.test")
    monkeypatch.setenv("JIRA_API_TOKEN", "test-token")
    monkeypatch.setattr(httpx, "request", fake_request)
    client = JiraCloudClient()

    created = client.create_issue(
        project_key="OPS",
        issue_type_id="10001",
        summary="Investigate sign-in error",
        description="The login page returns an error.",
        priority_name="High",
    )
    comment = client.add_comment("OPS-16", "Confirmed by the support team.")
    client.update_issue(
        "OPS-16",
        summary="Updated sign-in investigation",
        description=None,
        priority_name=None,
    )
    client.transition_issue("OPS-16", "31")

    assert created["key"] == "OPS-16"
    assert comment == {"id": "30001"}
    create_payload = calls[0][2]["json"]["fields"]
    assert create_payload["project"] == {"key": "OPS"}
    assert create_payload["issuetype"] == {"id": "10001"}
    assert create_payload["description"]["content"][0]["content"][0]["text"] == (
        "The login page returns an error."
    )
    assert calls[1][2]["json"]["body"]["content"][0]["content"][0]["text"] == (
        "Confirmed by the support team."
    )
    assert calls[-1][2]["json"] == {"transition": {"id": "31"}}


def test_jira_client_rejects_malformed_issue_keys_and_upstream_errors(monkeypatch) -> None:
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "service@example.test")
    monkeypatch.setenv("JIRA_API_TOKEN", "test-token")
    with pytest.raises(ValueError, match="Issue key"):
        JiraCloudClient().transitions("OPS/16")

    def unavailable(*args, **kwargs):
        return _response({}, status_code=403)

    monkeypatch.setattr(httpx, "request", unavailable)
    with pytest.raises(JiraRequestError) as error:
        JiraCloudClient().projects()
    assert error.value.status_code == 403


def test_jira_api_uses_capabilities_and_requires_explicit_write_confirmation(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_MODE", "demo")
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "service@example.test")
    monkeypatch.setenv("JIRA_API_TOKEN", "test-token")
    monkeypatch.setenv("N8N_JIRA_WEBHOOK_URL", "https://n8n.example.test/webhook/jira")

    def unexpected_notification(*args, **kwargs):
        raise AssertionError("Unauthorized or unconfirmed writes must not notify n8n.")

    monkeypatch.setattr(httpx, "post", unexpected_notification)
    monkeypatch.setattr(
        httpx,
        "request",
        lambda *args, **kwargs: _response({"values": []}),
    )

    requester = TestClient(app)
    authenticate_as("demo-it")
    assert requester.get("/api/v1/jira/projects").status_code == 200
    forbidden_write = requester.post(
        "/api/v1/jira/issues",
        json={
            "project_key": "OPS",
            "issue_type_id": "10001",
            "summary": "Investigate sign-in error",
            "description": "The login page returns an error.",
            "confirmed": True,
        },
    )
    assert forbidden_write.status_code == 403

    manager = TestClient(app)
    authenticate_as("demo-manager")
    missing_confirmation = manager.post(
        "/api/v1/jira/issues",
        json={
            "project_key": "OPS",
            "issue_type_id": "10001",
            "summary": "Investigate sign-in error",
            "description": "The login page returns an error.",
        },
    )
    assert missing_confirmation.status_code == 422


def test_jira_api_returns_created_issue_with_cors_headers(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_MODE", "demo")
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setattr(
        "backend.app.api.v1.jira._client",
        lambda: SimpleNamespace(
            create_issue=lambda **kwargs: {
                "id": "10002",
                "key": "OPS-16",
                "url": "https://example.atlassian.net/rest/api/3/issue/10002",
            }
        ),
    )

    client = TestClient(app)
    authenticate_as("demo-manager")
    response = client.post(
        "/api/v1/jira/issues",
        headers={"Origin": "http://localhost:5173"},
        json={
            "project_key": "OPS",
            "issue_type_id": "10001",
            "summary": "Investigate sign-in error",
            "description": "The login page returns an error.",
            "confirmed": True,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": "10002",
        "key": "OPS-16",
        "url": "https://example.atlassian.net/browse/OPS-16",
        "notification_status": "not_configured",
    }
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


@pytest.mark.parametrize(
    ("webhook_status", "expected_status"),
    [(200, "sent"), (503, "failed")],
)
def test_jira_issue_notification_reports_delivery_without_sending_issue_content(
    monkeypatch,
    tmp_path,
    webhook_status: int,
    expected_status: str,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_MODE", "demo")
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("N8N_JIRA_WEBHOOK_URL", "https://n8n.example.test/webhook/jira")
    monkeypatch.setenv("N8N_JIRA_WEBHOOK_TOKEN", "test-n8n-token")
    monkeypatch.setattr(
        "backend.app.api.v1.jira._client",
        lambda: SimpleNamespace(
            create_issue=lambda **kwargs: {
                "id": "10002",
                "key": "OPS-16",
                "url": "https://example.atlassian.net/rest/api/3/issue/10002",
            }
        ),
    )
    captured: dict[str, object] = {}

    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return _response({}, status_code=webhook_status)

    monkeypatch.setattr(httpx, "post", fake_post)
    client = TestClient(app)
    authenticate_as("demo-manager")
    response = client.post(
        "/api/v1/jira/issues",
        json={
            "project_key": "OPS",
            "issue_type_id": "10001",
            "summary": "Investigate sign-in error",
            "description": "Detailed potentially sensitive issue description.",
            "confirmed": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["key"] == "OPS-16"
    assert response.json()["notification_status"] == expected_status
    assert captured["url"] == "https://n8n.example.test/webhook/jira"
    assert captured["headers"]["Authorization"] == "Bearer test-n8n-token"
    assert captured["json"] == {
        "event": "knowledgeops.jira.issue_created",
        "issue_key": "OPS-16",
        "project_key": "OPS",
        "issue_url": "https://example.atlassian.net/browse/OPS-16",
    }


def test_jira_issue_creation_failure_does_not_notify_n8n(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_MODE", "demo")
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("N8N_JIRA_WEBHOOK_URL", "https://n8n.example.test/webhook/jira")
    monkeypatch.setattr(
        "backend.app.api.v1.jira._client",
        lambda: SimpleNamespace(
            create_issue=lambda **kwargs: (_ for _ in ()).throw(JiraRequestError(403))
        ),
    )

    def unexpected_notification(*args, **kwargs):
        raise AssertionError("n8n must not be notified when Jira creation fails.")

    monkeypatch.setattr(httpx, "post", unexpected_notification)
    client = TestClient(app)
    authenticate_as("demo-manager")
    response = client.post(
        "/api/v1/jira/issues",
        json={
            "project_key": "OPS",
            "issue_type_id": "10001",
            "summary": "Investigate sign-in error",
            "description": "The login page returns an error.",
            "confirmed": True,
        },
    )

    assert response.status_code == 502


def test_jira_api_reports_missing_credentials_without_leaking_secrets(
    monkeypatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.setenv("AUTH_MODE", "demo")
    monkeypatch.delenv("JIRA_EMAIL", raising=False)
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")

    client = TestClient(app)
    authenticate_as("demo-it")
    response = client.get("/api/v1/jira/projects")

    assert response.status_code == 503
    assert "JIRA_EMAIL" in response.json()["detail"]
    assert "test-token" not in response.text
