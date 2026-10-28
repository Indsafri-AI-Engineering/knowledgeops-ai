import os
import hashlib
import time
from functools import lru_cache
from typing import Any
from typing import Annotated

import jwt
from fastapi import Cookie, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.app.core.demo_auth import DemoUser, get_session_user
from backend.app.storage.audit import AuditLog

SESSION_COOKIE = "knowledgeops_demo_session"
_bearer_scheme = HTTPBearer(auto_error=False)
_ALLOWED_CAPABILITIES = frozenset(
    {
        "chat:ask",
        "knowledge:read:general",
        "knowledge:read:hr",
        "knowledge:read:it",
        "recruitment:read",
        "jira:read",
        "jira:propose",
        "jira:approve",
        "threat_scans:scan",
        "security_alerts:read",
        "security_alerts:manage",
        "audit:read",
        "system:admin",
        "knowledge:manage",
    }
)


class OIDCConfigurationError(ValueError):
    pass


def demo_auth_enabled() -> bool:
    return (
        os.getenv("APP_ENV", "").lower() == "development"
        and os.getenv("DEMO_AUTH_ENABLED", "").lower() == "true"
    )


def auth_mode() -> str:
    configured_mode = os.getenv("AUTH_MODE")
    if configured_mode:
        return configured_mode.lower()
    return "demo" if demo_auth_enabled() else "oidc"


def require_demo_auth_enabled() -> None:
    if auth_mode() != "demo" or not demo_auth_enabled():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Demo authentication requires APP_ENV=development and "
                "DEMO_AUTH_ENABLED=true."
            ),
        )


def get_current_user(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(_bearer_scheme),
    ] = None,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> DemoUser:
    mode = auth_mode()
    if mode == "oidc":
        if credentials is None or credentials.scheme.lower() != "bearer":
            _record_auth_denial(request, "auth.missing_bearer_token")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Bearer token required.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            return authenticate_oidc_token(credentials.credentials)
        except OIDCConfigurationError as error:
            _record_auth_denial(request, "auth.oidc_misconfigured")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OIDC authentication is not configured correctly.",
            ) from error
        except (jwt.PyJWTError, ValueError):
            _record_auth_denial(request, "auth.invalid_bearer_token")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Bearer token is invalid or expired.",
                headers={"WWW-Authenticate": "Bearer"},
            ) from None

    if mode != "demo" or not demo_auth_enabled():
        _record_auth_denial(request, "auth.unavailable")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication is not configured.",
        )
    if session_token is None:
        _record_auth_denial(request, "auth.missing_session")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    user = get_session_user(session_token, time.time())
    if user is None:
        _record_auth_denial(request, "auth.invalid_session")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session is invalid or expired.",
        )
    return user


@lru_cache(maxsize=4)
def _jwks_client(jwks_url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(jwks_url, cache_jwk_set=True, lifespan=300)


def authenticate_oidc_token(token: str) -> DemoUser:
    issuer = os.getenv("OIDC_ISSUER_URL", "").rstrip("/")
    audience = os.getenv("OIDC_AUDIENCE", "")
    groups_claim = os.getenv("OIDC_GROUPS_CLAIM", "groups")
    if not issuer or not audience or not groups_claim:
        raise OIDCConfigurationError(
            "OIDC_ISSUER_URL, OIDC_AUDIENCE, and OIDC_GROUPS_CLAIM are required."
        )

    jwks_url = os.getenv("OIDC_JWKS_URL", f"{issuer}/protocol/openid-connect/certs")
    group_capabilities = _group_capability_mapping()
    signing_key = _jwks_client(jwks_url).get_signing_key_from_jwt(token)
    claims: dict[str, Any] = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=audience,
        issuer=issuer,
        options={"require": ["exp", "iat", "sub", "iss", "aud"]},
    )

    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise jwt.InvalidTokenError("Missing OIDC subject.")
    raw_groups = claims.get(groups_claim, [])
    if not isinstance(raw_groups, list) or any(
        not isinstance(group, str) for group in raw_groups
    ):
        raise jwt.InvalidTokenError("Malformed OIDC groups claim.")

    capabilities = sorted(
        {
            capability
            for group in raw_groups
            for capability in group_capabilities.get(group, [])
        }
    )
    matched_group = next(
        (group for group in raw_groups if group in group_capabilities),
        None,
    )
    role = matched_group.rsplit("/", 1)[-1].replace("-", "_") if matched_group else "authenticated"
    display_name = claims.get("name") or claims.get("preferred_username") or subject
    if not isinstance(display_name, str):
        display_name = subject
    return DemoUser(
        user_id=subject,
        display_name=display_name,
        role=role,
        capabilities=capabilities,
    )


def _group_capability_mapping() -> dict[str, list[str]]:
    import json

    raw_mapping = os.getenv("OIDC_GROUP_CAPABILITIES", "{}")
    try:
        mapping = json.loads(raw_mapping)
    except json.JSONDecodeError as error:
        raise OIDCConfigurationError("OIDC_GROUP_CAPABILITIES must be valid JSON.") from error
    if not isinstance(mapping, dict):
        raise OIDCConfigurationError("OIDC_GROUP_CAPABILITIES must be a JSON object.")

    validated: dict[str, list[str]] = {}
    for group, capabilities in mapping.items():
        if (
            not isinstance(group, str)
            or not group
            or not isinstance(capabilities, list)
            or any(
                not isinstance(capability, str)
                or capability not in _ALLOWED_CAPABILITIES
                for capability in capabilities
            )
        ):
            raise OIDCConfigurationError(
                "OIDC_GROUP_CAPABILITIES contains an unsupported group or capability."
            )
        validated[group] = list(set(capabilities))
    return validated


def _record_auth_denial(request: Request, action: str) -> None:
    source_fingerprint = None
    if request.client is not None:
        source_fingerprint = hashlib.sha256(
            request.client.host.encode("utf-8")
        ).hexdigest()[:16]
    AuditLog().record(
        request_id=request.state.request_id,
        actor_id="anonymous",
        action=action,
        resource_type="session",
        outcome="denied",
        metadata=(
            {"source_fingerprint": source_fingerprint}
            if source_fingerprint is not None
            else {}
        ),
    )
