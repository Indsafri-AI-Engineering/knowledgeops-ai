from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from backend.app.core.auth import get_current_user
from backend.app.core.demo_auth import DemoUser
from backend.app.core.permissions import require_capability
from backend.app.storage.audit import AuditEvent, AuditLog

router = APIRouter(tags=["audit"])


@router.get("/audit-events", response_model=list[AuditEvent])
def list_audit_events(
    request: Request,
    user: Annotated[DemoUser, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AuditEvent]:
    require_capability(user, "audit:read", request)
    audit_log = AuditLog()
    audit_log.record(
        request_id=request.state.request_id,
        actor_id=user.user_id,
        action="audit.read",
        resource_type="audit_log",
        outcome="success",
        metadata={"limit": limit},
    )
    return audit_log.list_events(limit)
