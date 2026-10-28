from collections import namedtuple
from datetime import UTC, datetime, timedelta

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from backend.app.core import auth
from backend.app.main import app

SigningKey = namedtuple("SigningKey", ["key"])


def _signed_token(
    private_key,
    *,
    issuer: str = "http://localhost:8080/realms/knowledgeops",
    audience: str = "knowledgeops-api",
    groups: list[str] | None = None,
) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": issuer,
            "aud": audience,
            "sub": "user-subject-42",
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "name": "Synthetic User",
            "preferred_username": "synthetic-user",
            "groups": groups or [],
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )


def _configure_oidc(monkeypatch, private_key) -> None:
    monkeypatch.setenv("AUTH_MODE", "oidc")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")
    monkeypatch.setenv(
        "OIDC_ISSUER_URL",
        "http://localhost:8080/realms/knowledgeops",
    )
    monkeypatch.setenv("OIDC_AUDIENCE", "knowledgeops-api")
    monkeypatch.setenv("OIDC_GROUPS_CLAIM", "groups")
    monkeypatch.setenv(
        "OIDC_GROUP_CAPABILITIES",
        '{"/knowledge/employee":["chat:ask","knowledge:read:general"],'
        '"/knowledge/manager":["chat:ask","knowledge:read:general","knowledge:manage"],'
        '"/knowledge/administrator":["system:admin","audit:read","knowledge:manage"]}',
    )

    class FakeJwksClient:
        def get_signing_key_from_jwt(self, token: str):
            assert token
            return SigningKey(private_key.public_key())

    def fake_jwks_client(jwks_url: str) -> FakeJwksClient:
        assert jwks_url.endswith("/protocol/openid-connect/certs")
        return FakeJwksClient()

    monkeypatch.setattr(auth, "_jwks_client", fake_jwks_client)


def test_oidc_bearer_auth_maps_verified_group_to_scopes(
    monkeypatch,
    tmp_path,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _configure_oidc(monkeypatch, private_key)
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    token = _signed_token(private_key, groups=["/knowledge/employee"])

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/me",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json()["user_id"] == "user-subject-42"
    assert response.json()["display_name"] == "Synthetic User"
    assert response.json()["capabilities"] == [
        "chat:ask",
        "knowledge:read:general",
    ]

    with TestClient(app) as client:
        status_response = client.get(
            "/api/v1/system/status",
            headers={"Authorization": f"Bearer {token}"},
        )
    components = {
        item["name"]: item for item in status_response.json()["components"]
    }
    assert status_response.status_code == 200
    assert components["Authentication"]["mode"] == "local"


def test_oidc_manager_group_can_manage_knowledge_without_system_admin(
    monkeypatch,
    tmp_path,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _configure_oidc(monkeypatch, private_key)
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    token = _signed_token(private_key, groups=["/knowledge/manager"])

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/me",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    capabilities = response.json()["capabilities"]
    assert "knowledge:manage" in capabilities
    assert "system:admin" not in capabilities


def test_oidc_rejects_missing_or_invalid_bearer_token(
    monkeypatch,
    tmp_path,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _configure_oidc(monkeypatch, private_key)
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    wrong_audience = _signed_token(private_key, audience="other-api")

    with TestClient(app) as client:
        missing = client.get("/api/v1/me")
        invalid = client.get(
            "/api/v1/me",
            headers={"Authorization": f"Bearer {wrong_audience}"},
        )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"


def test_oidc_group_mapping_fails_closed_on_unknown_capability(
    monkeypatch,
    tmp_path,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _configure_oidc(monkeypatch, private_key)
    monkeypatch.setenv("OIDC_GROUP_CAPABILITIES", '{"/knowledge/employee":["admin:*"]}')
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    token = _signed_token(private_key, groups=["/knowledge/employee"])

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/me",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 503


def test_oidc_group_mapping_rejects_non_string_capabilities(
    monkeypatch,
    tmp_path,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    _configure_oidc(monkeypatch, private_key)
    monkeypatch.setenv(
        "OIDC_GROUP_CAPABILITIES",
        '{"/knowledge/employee":[{"unexpected":"object"}]}',
    )
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    token = _signed_token(private_key, groups=["/knowledge/employee"])

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/me",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "OIDC authentication is not configured correctly."


def test_demo_auth_endpoints_are_disabled_when_oidc_is_selected(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "oidc")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_AUTH_ENABLED", "true")

    with TestClient(app) as client:
        response = client.get("/api/v1/auth/demo-users")

    assert response.status_code == 404
