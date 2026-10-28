import logging
import os
from collections.abc import Callable
from typing import Annotated, Literal
from typing import TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from backend.app.core.auth import get_current_user
from backend.app.core.demo_auth import DemoUser
from backend.app.core.permissions import require_capability
from backend.app.integrations.jira_cloud import (
    JiraCloudClient,
    JiraConfigurationError,
    JiraRequestError,
)
from backend.app.storage.audit import AuditLog

router = APIRouter(prefix="/jira", tags=["Jira Cloud"])
logger = logging.getLogger(__name__)
Result = TypeVar("Result")


class JiraStatusResponse(BaseModel):
    configured: bool
    base_url: str | None


class JiraProject(BaseModel):
    id: str
    key: str
    name: str


class JiraIssueType(BaseModel):
    id: str
    name: str


class JiraIssue(BaseModel):
    id: str
    key: str
    summary: str
    description: str
    status: str | None
    priority: str | None
    project_key: str | None
    assignee: str | None
    issue_type: str | None
    updated: str


class JiraIssueSearchResponse(BaseModel):
    issues: list[JiraIssue]


class JiraCreateIssueRequest(BaseModel):
    project_key: str = Field(min_length=1, max_length=10)
    issue_type_id: str = Field(pattern=r"^[0-9]+$")
    summary: str = Field(min_length=5, max_length=255)
    description: str = Field(min_length=1, max_length=5000)
    priority_name: str | None = Field(default=None, max_length=50)
    confirmed: Literal[True]


class JiraCreatedIssue(BaseModel):
    id: str
    key: str
    url: str


class JiraUpdateIssueRequest(BaseModel):
    summary: str | None = Field(default=None, min_length=5, max_length=255)
    description: str | None = Field(default=None, min_length=1, max_length=5000)
    priority_name: str | None = Field(default=None, max_length=50)
    confirmed: Literal[True]


class JiraCommentRequest(BaseModel):
    body: str = Field(min_length=1, max_length=5000)
    confirmed: Literal[True]


class JiraTransitionRequest(BaseModel):
    transition_id: str = Field(pattern=r"^[0-9]+$")
    confirmed: Literal[True]


class JiraCommentResponse(BaseModel):
    id: str


class JiraTransition(BaseModel):
    id: str
    name: str


def _record(
    request: Request,
    user: DemoUser,
    *,
    action: str,
    outcome: str,
    metadata: dict[str, str | int | bool] | None = None,
) -> None:
    AuditLog().record(
        request_id=request.state.request_id,
        actor_id=user.user_id,
        action=action,
        resource_type="jira",
        outcome=outcome,
        metadata=metadata or {},
    )


def _call(
    operation: Callable[[], Result],
    request: Request,
    user: DemoUser,
    *,
    action: str,
    metadata: dict[str, str | int | bool] | None = None,
):
    try:
        result = operation()
    except JiraConfigurationError as error:
        _record(request, user, action=action, outcome="failure")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except JiraRequestError as error:
        _record(
            request,
            user,
            action=action,
            outcome="failure",
            metadata=metadata,
        )
        logger.warning(
            "Jira request failed with status %s for action %s.",
            error.status_code,
            action,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Jira rejected the request or is unavailable. Check the "
                "Jira account permissions and backend logs."
            ),
        ) from error
    except ValueError as error:
        _record(
            request,
            user,
            action=action,
            outcome="failure",
            metadata=metadata,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    _record(
        request,
        user,
        action=action,
        outcome="success",
        metadata=metadata,
    )
    return result


def _client() -> JiraCloudClient:
    return JiraCloudClient()


@router.get("/status", response_model=JiraStatusResponse)
def jira_status(
    user: Annotated[DemoUser, Depends(get_current_user)],
) -> JiraStatusResponse:
    client = _client()
    base_url = os.getenv("JIRA_BASE_URL", "").strip().rstrip("/")
    return JiraStatusResponse(
        configured=client.configured,
        base_url=base_url or None,
    )


@router.get("/projects", response_model=list[JiraProject])
def list_projects(
    request: Request,
    user: Annotated[DemoUser, Depends(get_current_user)],
) -> list[JiraProject]:
    require_capability(user, "jira:read", request)
    projects = _call(
        _client().projects,
        request,
        user,
        action="jira.projects.read",
    )
    return [JiraProject.model_validate(project) for project in projects]


@router.get(
    "/projects/{project_key}/issue-types",
    response_model=list[JiraIssueType],
)
def list_issue_types(
    project_key: str,
    request: Request,
    user: Annotated[DemoUser, Depends(get_current_user)],
) -> list[JiraIssueType]:
    require_capability(user, "jira:read", request)
    issue_types = _call(
        lambda: _client().issue_types(project_key),
        request,
        user,
        action="jira.issue_types.read",
        metadata={"project_key": project_key},
    )
    return [JiraIssueType.model_validate(item) for item in issue_types]


@router.get("/issues", response_model=JiraIssueSearchResponse)
def search_issues(
    request: Request,
    user: Annotated[DemoUser, Depends(get_current_user)],
    query: Annotated[str, Query(max_length=200)] = "",
    project_key: Annotated[str | None, Query(max_length=10)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> JiraIssueSearchResponse:
    require_capability(user, "jira:read", request)
    issues = _call(
        lambda: _client().search_issues(query, project_key, limit),
        request,
        user,
        action="jira.issues.search",
        metadata={
            "project_key": project_key or "",
            "result_limit": limit,
        },
    )
    return JiraIssueSearchResponse(
        issues=[JiraIssue.model_validate(issue) for issue in issues]
    )


@router.post("/issues", response_model=JiraCreatedIssue)
def create_issue(
    payload: JiraCreateIssueRequest,
    request: Request,
    user: Annotated[DemoUser, Depends(get_current_user)],
) -> JiraCreatedIssue:
    require_capability(user, "jira:approve", request)
    result = _call(
        lambda: _client().create_issue(
            project_key=payload.project_key,
            issue_type_id=payload.issue_type_id,
            summary=payload.summary,
            description=payload.description,
            priority_name=payload.priority_name,
        ),
        request,
        user,
        action="jira.issue.create",
        metadata={"project_key": payload.project_key},
    )
    base_url = os.getenv("JIRA_BASE_URL", "").strip().rstrip("/")
    return JiraCreatedIssue(
        id=result["id"],
        key=result["key"],
        url=f"{base_url}/browse/{result['key']}",
    )


@router.patch("/issues/{issue_key}", status_code=status.HTTP_204_NO_CONTENT)
def update_issue(
    issue_key: str,
    payload: JiraUpdateIssueRequest,
    request: Request,
    user: Annotated[DemoUser, Depends(get_current_user)],
) -> None:
    require_capability(user, "jira:approve", request)
    _call(
        lambda: _client().update_issue(
            issue_key,
            summary=payload.summary,
            description=payload.description,
            priority_name=payload.priority_name,
        ),
        request,
        user,
        action="jira.issue.update",
        metadata={"issue_key": issue_key},
    )


@router.post(
    "/issues/{issue_key}/comments",
    response_model=JiraCommentResponse,
)
def add_comment(
    issue_key: str,
    payload: JiraCommentRequest,
    request: Request,
    user: Annotated[DemoUser, Depends(get_current_user)],
) -> JiraCommentResponse:
    require_capability(user, "jira:approve", request)
    result = _call(
        lambda: _client().add_comment(issue_key, payload.body),
        request,
        user,
        action="jira.issue.comment",
        metadata={"issue_key": issue_key},
    )
    return JiraCommentResponse.model_validate(result)


@router.get(
    "/issues/{issue_key}/transitions",
    response_model=list[JiraTransition],
)
def list_transitions(
    issue_key: str,
    request: Request,
    user: Annotated[DemoUser, Depends(get_current_user)],
) -> list[JiraTransition]:
    require_capability(user, "jira:read", request)
    transitions = _call(
        lambda: _client().transitions(issue_key),
        request,
        user,
        action="jira.issue.transitions.read",
        metadata={"issue_key": issue_key},
    )
    return [JiraTransition.model_validate(item) for item in transitions]


@router.post(
    "/issues/{issue_key}/transitions",
    status_code=status.HTTP_204_NO_CONTENT,
)
def transition_issue(
    issue_key: str,
    payload: JiraTransitionRequest,
    request: Request,
    user: Annotated[DemoUser, Depends(get_current_user)],
) -> None:
    require_capability(user, "jira:approve", request)
    _call(
        lambda: _client().transition_issue(issue_key, payload.transition_id),
        request,
        user,
        action="jira.issue.transition",
        metadata={"issue_key": issue_key},
    )
