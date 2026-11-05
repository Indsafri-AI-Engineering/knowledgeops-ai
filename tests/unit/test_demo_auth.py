import json

from fastapi.testclient import TestClient

from backend.app.main import app
from conftest import authenticate_as


def test_audit_log_records_auth_and_admin_can_read(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))

    anonymous_client = TestClient(app)
    denied_response = anonymous_client.get("/api/v1/me")
    assert denied_response.status_code == 401
    assert denied_response.headers["x-request-id"]

    administrator_client = TestClient(app)
    authenticate_as("demo-admin")
    forbidden_response = administrator_client.post(
        "/api/v1/chat",
        json={"question": "personal leave balance is private"},
    )
    assert forbidden_response.status_code == 403

    employee_client = TestClient(app)
    authenticate_as("demo-employee")
    employee_audit_response = employee_client.get("/api/v1/audit-events")
    assert employee_audit_response.status_code == 403

    authenticate_as("demo-admin")
    audit_response = administrator_client.get("/api/v1/audit-events")
    assert audit_response.status_code == 200
    events = audit_response.json()

    assert any(event["action"] == "auth.missing_bearer_token" for event in events)
    assert any(
        event["action"] == "authorization.chat:ask"
        and event["outcome"] == "denied"
        for event in events
    )
    assert any(
        event["action"] == "authorization.audit:read"
        and event["outcome"] == "denied"
        for event in events
    )
    assert all(
        "personal leave balance" not in json.dumps(event).lower()
        for event in events
    )


def test_demo_cookie_and_login_endpoints_are_rejected(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "demo")
    client = TestClient(app)

    assert client.get("/api/v1/health").json() == {"status": "ok"}
    assert (
        client.get(
            "/api/v1/me",
            cookies={"knowledgeops_demo_session": "fictional-session"},
        ).status_code
        == 401
    )
    assert client.get("/api/v1/auth/demo-users").status_code == 404
    assert (
        client.post(
            "/api/v1/auth/demo-login",
            json={"user_id": "demo-employee"},
        ).status_code
        == 404
    )
    assert client.post("/api/v1/auth/logout").status_code == 404


def test_system_status_requires_bearer_auth_and_reports_local_boundaries(
    monkeypatch,
) -> None:
    monkeypatch.setenv("VIRUSTOTAL_ENABLED", "false")
    monkeypatch.delenv("VIRUSTOTAL_API_KEY", raising=False)
    monkeypatch.setenv("RAG_BACKEND", "qdrant")
    monkeypatch.setenv("RAG_GENERATION_BACKEND", "ollama")
    client = TestClient(app)

    assert client.get("/api/v1/system/status").status_code == 401
    authenticate_as("demo-employee")
    response = client.get("/api/v1/system/status")

    assert response.status_code == 200
    body = response.json()
    components = {component["name"]: component for component in body["components"]}
    assert body["environment"] == "test"
    assert components["Authentication"]["mode"] == "local"
    assert components["MCP"]["mode"] == "disabled"
    assert components["n8n notifications"]["mode"] == "disabled"
    assert components["Groq"]["mode"] == "disabled"
    assert components["Mistral"]["mode"] == "disabled"
    assert "Ollama embeddings" in components["Retrieval"]["description"]
    assert "Ollama chat generation" in components["Answer generation"]["description"]
    assert all(
        component["external_connection"] is False
        for component in body["components"]
    ), [
        component["name"]
        for component in body["components"]
        if component["external_connection"]
    ]


def test_system_status_discloses_selected_hosted_providers(monkeypatch) -> None:
    monkeypatch.setenv("RAG_BACKEND", "qdrant")
    monkeypatch.setenv("RAG_EMBEDDING_PROVIDER", "mistral")
    monkeypatch.setenv("RAG_GENERATION_BACKEND", "groq")
    client = TestClient(app)
    authenticate_as("demo-employee")

    response = client.get("/api/v1/system/status")

    assert response.status_code == 200
    components = {
        component["name"]: component
        for component in response.json()["components"]
    }
    assert components["Embeddings"]["mode"] == "external"
    assert components["Embeddings"]["external_connection"] is True
    assert components["Answer generation"]["mode"] == "external"
    assert components["Groq"]["external_connection"] is True
    assert components["Mistral"]["external_connection"] is True


def test_system_status_reports_atlas_document_and_vector_storage(
    monkeypatch,
) -> None:
    monkeypatch.setenv("KNOWLEDGE_STORE_BACKEND", "mongodb")
    monkeypatch.setenv("MONGODB_URI", "mongodb+srv://configured.example")
    monkeypatch.setenv("RAG_BACKEND", "atlas")
    client = TestClient(app)
    authenticate_as("demo-admin")

    response = client.get("/api/v1/system/status")

    assert response.status_code == 200
    components = {
        component["name"]: component
        for component in response.json()["components"]
    }
    assert components["Knowledge sources"]["mode"] == "external"
    assert components["Storage"]["mode"] == "external"
    assert components["Retrieval"]["mode"] == "external"
    assert "access-scope prefilter" in components["Retrieval"]["description"]
