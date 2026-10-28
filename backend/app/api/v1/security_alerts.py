from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from backend.app.core.auth import get_current_user
from backend.app.core.demo_auth import DemoUser
from backend.app.core.permissions import require_capability
from backend.app.integrations.n8n import N8nAlertNotifier
from backend.app.storage.audit import AuditLog
from backend.app.storage.security_alerts import (
    AlertStatus,
    SecurityAlert,
    SecurityAlertRepository,
    get_security_alert_repository,
)

router = APIRouter(prefix="/security/alerts", tags=["security alerts"])
ReviewStatus = Literal["acknowledged", "resolved", "false_positive"]


class AlertReviewRequest(BaseModel):
    status: ReviewStatus


class AlertResponseWorkflowRequest(BaseModel):
    confirmed: Literal[True]


def _require_alert_access(
    user: DemoUser,
    request: Request,
    *,
    review: bool = False,
) -> None:
    allowed = (
        {"security_alerts:manage", "threat_scans:scan", "system:admin"}
        if review
        else {
            "security_alerts:read",
            "security_alerts:manage",
            "threat_scans:scan",
            "system:admin",
        }
    )
    if not any(capability in user.capabilities for capability in allowed):
        require_capability(user, "security_alerts:manage" if review else "security_alerts:read", request)


@router.get("", response_model=list[SecurityAlert])
def list_security_alerts(
    request: Request,
    user: Annotated[DemoUser, Depends(get_current_user)],
    repository: Annotated[
        SecurityAlertRepository,
        Depends(get_security_alert_repository),
    ],
    alert_status: Annotated[AlertStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[SecurityAlert]:
    _require_alert_access(user, request)
    return repository.list_alerts(status=alert_status, limit=limit)


@router.patch("/{alert_id}", response_model=SecurityAlert)
def review_security_alert(
    alert_id: UUID,
    payload: AlertReviewRequest,
    request: Request,
    user: Annotated[DemoUser, Depends(get_current_user)],
    repository: Annotated[
        SecurityAlertRepository,
        Depends(get_security_alert_repository),
    ],
) -> SecurityAlert:
    _require_alert_access(user, request, review=True)
    alert = repository.get(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Security alert not found.")
    if alert.status not in {"open", "acknowledged"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This security alert has already been resolved.",
        )
    if payload.status == "acknowledged" and alert.status != "open":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only open alerts can be acknowledged.",
        )
    alert.status = payload.status
    alert.reviewed_by = user.user_id
    saved = repository.save(alert)
    AuditLog().record(
        request_id=request.state.request_id,
        actor_id=user.user_id,
        action="security.alert.review",
        resource_type="security_alert",
        outcome="success",
        metadata={
            "alert_id": str(alert.alert_id),
            "status": alert.status,
        },
    )
    return saved


@router.post("/{alert_id}/response-workflow", response_model=SecurityAlert)
def request_alert_response_workflow(
    alert_id: UUID,
    payload: AlertResponseWorkflowRequest,
    request: Request,
    user: Annotated[DemoUser, Depends(get_current_user)],
    repository: Annotated[
        SecurityAlertRepository,
        Depends(get_security_alert_repository),
    ],
) -> SecurityAlert:
    _require_alert_access(user, request, review=True)
    alert = repository.get(alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Security alert not found.")
    if alert.status != "acknowledged":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A security analyst must acknowledge the alert first.",
        )
    if alert.response_workflow_status == "sent":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The approved response workflow was already dispatched.",
        )

    alert.response_workflow_status = N8nAlertNotifier().request_approved_response(
        alert_id=str(alert.alert_id),
        alert_type=alert.alert_type,
        severity=alert.severity,
        detector_version=alert.detector_version,
        rule_ids=[indicator.rule_id for indicator in alert.indicators],
        occurred_at=alert.created_at,
    )
    saved = repository.save(alert)
    AuditLog().record(
        request_id=request.state.request_id,
        actor_id=user.user_id,
        action="security.alert.response_workflow",
        resource_type="security_alert",
        outcome="success" if alert.response_workflow_status == "sent" else "failure",
        metadata={
            "alert_id": str(alert.alert_id),
            "notification_status": alert.response_workflow_status,
            "confirmed": payload.confirmed,
        },
    )
    return saved
