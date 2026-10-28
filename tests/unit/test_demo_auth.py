import json

from fastapi.testclient import TestClient

from backend.app.main import app


def test_demo_admin_has_audit_read_capability() -> None:
    from backend.app.core.demo_auth import DEMO_USERS

    assert "audit:read" in DEMO_USERS["demo-admin"].capabilities
    assert "knowledge:manage" in DEMO_USERS["demo-admin"].capabilities


def test_audit_log_records_auth_and_admin_can_read(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))

    anonymous_client = TestClient(app)
    denied_response = anonymous_client.get("/api/v1/me")
    assert denied_response.status_code == 401
    assert denied_response.headers["x-request-id"]

    administrator_client = TestClient(app)
    administrator_client.post("/api/v1/auth/demo-login", json={"user_id": "demo-admin"})
    forbidden_response = administrator_client.post(
        "/api/v1/chat",
        json={"question": "personal leave balance is private"},
    )
    assert forbidden_response.status_code == 403

    employee_client = TestClient(app)
    employee_client.post("/api/v1/auth/demo-login", json={"user_id": "demo-employee"})
    employee_audit_response = employee_client.get("/api/v1/audit-events")
    assert employee_audit_response.status_code == 403

    audit_response = administrator_client.get("/api/v1/audit-events")
    assert audit_response.status_code == 200
    events = audit_response.json()

    assert any(event["action"] == "auth.missing_session" for event in events)
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


def test_demo_authentication_lifecycle(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    client = TestClient(app)

    assert client.get("/api/v1/health").json() == {"status": "ok"}
    assert client.get("/api/v1/me").status_code == 401

    available_users = client.get("/api/v1/auth/demo-users")
    assert available_users.status_code == 200
    assert {user["user_id"] for user in available_users.json()} >= {
        "demo-employee",
        "demo-hr",
    }

    login_response = client.post(
        "/api/v1/auth/demo-login",
        json={"user_id": "demo-employee"},
    )
    assert login_response.status_code == 200
    assert login_response.json()["role"] == "employee"
    assert login_response.cookies.get("knowledgeops_demo_session")
    assert "httponly" in login_response.headers["set-cookie"].lower()

    current_user = client.get("/api/v1/me")
    assert current_user.status_code == 200
    assert current_user.json()["user_id"] == "demo-employee"
    assert "knowledge:read:hr" not in current_user.json()["capabilities"]
    assert "knowledge:read:it" not in current_user.json()["capabilities"]

    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/me").status_code == 401


def test_system_status_requires_demo_auth_and_reports_local_boundaries(
    monkeypatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.setenv("RAG_BACKEND", "qdrant")
    monkeypatch.setenv("RAG_GENERATION_BACKEND", "ollama")
    client = TestClient(app)

    assert client.get("/api/v1/system/status").status_code == 401
    client.post(
        "/api/v1/auth/demo-login",
        json={"user_id": "demo-employee"},
    )
    response = client.get("/api/v1/system/status")

    assert response.status_code == 200
    body = response.json()
    components = {component["name"]: component for component in body["components"]}
    assert body["environment"] == "development"
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
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.setenv("RAG_BACKEND", "qdrant")
    monkeypatch.setenv("RAG_EMBEDDING_PROVIDER", "mistral")
    monkeypatch.setenv("RAG_GENERATION_BACKEND", "groq")
    client = TestClient(app)
    client.post("/api/v1/auth/demo-login", json={"user_id": "demo-employee"})

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


def test_demo_authentication_is_disabled_outside_development(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    client = TestClient(app)

    assert client.get("/api/v1/auth/demo-users").status_code == 404
    assert (
        client.post(
            "/api/v1/auth/demo-login",
            json={"user_id": "demo-employee"},
        ).status_code
        == 404
    )


def test_demo_login_rejects_unknown_identity(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    client = TestClient(app)

    assert (
        client.post(
            "/api/v1/auth/demo-login",
            json={"user_id": "not-a-demo-user"},
        ).status_code
        == 422
    )
