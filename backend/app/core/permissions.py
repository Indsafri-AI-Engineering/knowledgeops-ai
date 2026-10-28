from fastapi import HTTPException, Request, status

from backend.app.core.demo_auth import DemoUser
from backend.app.storage.audit import AuditLog


def user_scopes(user: DemoUser) -> frozenset[str]:
    scopes = {
        capability.removeprefix("knowledge:read:")
        for capability in user.capabilities
        if capability.startswith("knowledge:read:")
    }
    if "recruitment:read" in user.capabilities:
        scopes.add("recruitment")
    return frozenset(scopes)


def has_capability(user: DemoUser, capability: str) -> bool:
    return capability in user.capabilities


def require_capability(
    user: DemoUser,
    capability: str,
    request: Request | None = None,
) -> None:
    if not has_capability(user, capability):
        if request is not None:
            AuditLog().record(
                request_id=request.state.request_id,
                actor_id=user.user_id,
                action=f"authorization.{capability}",
                resource_type="capability",
                outcome="denied",
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action.",
        )


def require_source_scope(
    user: DemoUser,
    scope: str,
    request: Request | None = None,
) -> None:
    if scope not in user_scopes(user):
        if request is not None:
            AuditLog().record(
                request_id=request.state.request_id,
                actor_id=user.user_id,
                action="source.read",
                resource_type="source_scope",
                outcome="denied",
                metadata={"scope": scope},
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this source.",
        )
