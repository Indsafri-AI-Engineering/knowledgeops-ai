from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from backend.app.api.v1.chat_models import SourceCitation
from backend.app.connectors.hr_demo import HRDemoConnector
from backend.app.connectors.it_knowledge import ITKnowledgeConnector
from backend.app.connectors.jira import DemoIssue, JiraDemoConnector, JiraProposalInput
from backend.app.connectors.recruitment_demo import (
    CVMatchResult,
    RecruitmentDemoConnector,
    SuccessFeeResult,
)
from backend.app.core.auth import get_current_user
from backend.app.core.demo_auth import DemoUser
from backend.app.core.permissions import (
    require_capability,
    require_source_scope,
    user_scopes,
)
from backend.app.knowledge.generation import generate_grounded_answer
from backend.app.knowledge.index import get_knowledge_index
from backend.app.knowledge.salesforce_support import (
    SalesforceLoginSymptom,
    troubleshoot_salesforce_login as run_salesforce_login_guide,
)
from backend.app.storage.audit import AuditLog
from backend.app.integrations.n8n import N8nDemoConnector, NotificationResult
from backend.app.storage.jira_actions import JiraAction, JiraActionStore

router = APIRouter(prefix="/connectors", tags=["mock connectors"])


class ConnectorKnowledgeResponse(BaseModel):
    connector: str
    status: str
    answer: str
    sources: list[SourceCitation]


class ITTroubleshootRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class SalesforceLoginRequest(BaseModel):
    symptom: SalesforceLoginSymptom


class SalesforceLoginGuideResponse(BaseModel):
    connector: str = "fictional_it_knowledge"
    status: str = "mock"
    execution: str = "local_langchain"
    symptom: SalesforceLoginSymptom
    steps: list[str]
    escalation: str
    sources: list[SourceCitation]


class SuccessFeeRequest(BaseModel):
    salary: Decimal | None = Field(default=None, gt=0, le=1_000_000_000)


class JiraIssueSearchResponse(BaseModel):
    connector: str = "fictional_jira_demo"
    status: str = "mock"
    issues: list[DemoIssue]


class JiraProposalResponse(BaseModel):
    proposal: JiraAction
    connector: str = "fictional_jira_demo"


class JiraApprovalResponse(BaseModel):
    action: JiraAction
    issue: DemoIssue
    notification: NotificationResult


def _sources(results) -> list[SourceCitation]:
    return [
        SourceCitation(
            title=result.chunk.title,
            source=result.chunk.source,
            source_path=result.chunk.source_path,
            section=result.chunk.section,
            document_id=result.chunk.document_id,
            owner=result.chunk.owner,
            version=result.chunk.version,
            effective_date=result.chunk.effective_date,
            next_review=result.chunk.next_review,
            environment=result.chunk.environment,
        )
        for result in results
    ]


def _audit(
    request: Request,
    user: DemoUser,
    action: str,
    metadata: dict[str, str | int | bool] | None = None,
) -> None:
    AuditLog().record(
        request_id=request.state.request_id,
        actor_id=user.user_id,
        action=action,
        resource_type="mock_connector",
        outcome="success",
        metadata=metadata,
    )


@router.get("/hr/leave-policy", response_model=ConnectorKnowledgeResponse)
def get_leave_policy(
    request: Request,
    user: Annotated[DemoUser, Depends(get_current_user)],
) -> ConnectorKnowledgeResponse:
    require_capability(user, "chat:ask", request)
    scopes = set(user_scopes(user))
    require_source_scope(user, "general", request)
    connector = HRDemoConnector()
    results = connector.leave_guidance(scopes)
    response = ConnectorKnowledgeResponse(
        connector=connector.metadata.connector,
        status=connector.metadata.status,
        answer=generate_grounded_answer(
            results,
            "What is the annual leave policy?",
        ),
        sources=_sources(results),
    )
    _audit(request, user, "connector.hr.leave_policy")
    return response


@router.post("/it/troubleshooting", response_model=ConnectorKnowledgeResponse)
def troubleshoot_it(
    payload: ITTroubleshootRequest,
    request: Request,
    user: Annotated[DemoUser, Depends(get_current_user)],
) -> ConnectorKnowledgeResponse:
    require_capability(user, "chat:ask", request)
    require_source_scope(user, "it", request)
    connector = ITKnowledgeConnector()
    results = connector.troubleshoot(payload.question, set(user_scopes(user)))
    result = ConnectorKnowledgeResponse(
        connector=connector.metadata.connector,
        status=connector.metadata.status,
        answer=generate_grounded_answer(results, payload.question),
        sources=_sources(results),
    )
    _audit(
        request,
        user,
        "connector.it.troubleshoot",
        {"source_count": len(results)},
    )
    return result


@router.post(
    "/it/salesforce/login-guide",
    response_model=SalesforceLoginGuideResponse,
)
def troubleshoot_salesforce_login(
    payload: SalesforceLoginRequest,
    request: Request,
    user: Annotated[DemoUser, Depends(get_current_user)],
) -> SalesforceLoginGuideResponse:
    require_capability(user, "chat:ask", request)
    require_source_scope(user, "it", request)
    guide = run_salesforce_login_guide(
        payload.symptom,
        set(user_scopes(user)),
    )
    source_ids = set(guide.source_document_ids)
    sources: list[SourceCitation] = []
    for chunk in get_knowledge_index().chunks:
        if chunk.document_id in source_ids:
            sources.append(
                SourceCitation(
                    title=chunk.title,
                    source=chunk.source,
                    source_path=chunk.source_path,
                    section=chunk.section,
                    document_id=chunk.document_id,
                    owner=chunk.owner,
                    version=chunk.version,
                    effective_date=chunk.effective_date,
                    next_review=chunk.next_review,
                    environment=chunk.environment,
                )
            )
            source_ids.remove(chunk.document_id)
    _audit(
        request,
        user,
        "connector.it.salesforce_login_guide",
        {"symptom": payload.symptom, "source_count": len(sources)},
    )
    return SalesforceLoginGuideResponse(
        symptom=guide.symptom,
        steps=guide.steps,
        escalation=guide.escalation,
        sources=sources,
    )


@router.post(
    "/recruitment/campaigns/{campaign_id}/matches",
    response_model=CVMatchResult,
)
def match_recruitment_campaign(
    campaign_id: str,
    request: Request,
    user: Annotated[DemoUser, Depends(get_current_user)],
) -> CVMatchResult:
    require_capability(user, "recruitment:read", request)
    result = RecruitmentDemoConnector().match_campaign(campaign_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found.")
    _audit(
        request,
        user,
        "connector.recruitment.cv_match",
        {
            "campaign_id": campaign_id,
            "candidate_count": result.total_candidates,
            "matched_count": result.matched_count,
        },
    )
    return result


@router.post(
    "/recruitment/success-fee",
    response_model=SuccessFeeResult,
)
def calculate_recruitment_success_fee(
    payload: SuccessFeeRequest,
    request: Request,
    user: Annotated[DemoUser, Depends(get_current_user)],
) -> SuccessFeeResult:
    require_capability(user, "recruitment:read", request)
    try:
        result = RecruitmentDemoConnector().calculate_success_fee(payload.salary)
    except (InvalidOperation, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    _audit(
        request,
        user,
        "connector.recruitment.success_fee",
        {"calculated": result.fee is not None},
    )
    return result


@router.get("/jira/issues", response_model=JiraIssueSearchResponse)
def search_jira_issues(
    request: Request,
    user: Annotated[DemoUser, Depends(get_current_user)],
    query: str = "",
    limit: int = 20,
) -> JiraIssueSearchResponse:
    require_capability(user, "jira:read", request)
    if len(query) > 200:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Query must be 200 characters or fewer.",
        )
    if not 1 <= limit <= 50:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Limit must be between 1 and 50.",
        )
    issues = JiraDemoConnector().search(query, limit)
    _audit(
        request,
        user,
        "connector.jira.search",
        {"result_count": len(issues)},
    )
    return JiraIssueSearchResponse(issues=issues)


@router.post("/jira/proposals", response_model=JiraProposalResponse)
def create_jira_proposal(
    payload: JiraProposalInput,
    request: Request,
    user: Annotated[DemoUser, Depends(get_current_user)],
) -> JiraProposalResponse:
    require_capability(user, "jira:propose", request)
    proposal = JiraActionStore().create(user.user_id, payload)
    _audit(
        request,
        user,
        "connector.jira.propose",
        {
            "action_id": str(proposal.action_id),
            "project": payload.project,
            "priority": payload.priority,
        },
    )
    return JiraProposalResponse(proposal=proposal)


@router.get("/jira/proposals", response_model=list[JiraAction])
def list_jira_proposals(
    request: Request,
    user: Annotated[DemoUser, Depends(get_current_user)],
) -> list[JiraAction]:
    require_capability(user, "jira:approve", request)
    proposals = JiraActionStore().list_pending()
    _audit(
        request,
        user,
        "connector.jira.proposals.read",
        {"result_count": len(proposals)},
    )
    return proposals


@router.post("/jira/proposals/{action_id}/approve", response_model=JiraApprovalResponse)
def approve_jira_proposal(
    action_id: str,
    request: Request,
    user: Annotated[DemoUser, Depends(get_current_user)],
) -> JiraApprovalResponse:
    require_capability(user, "jira:approve", request)
    try:
        action_uuid = UUID(action_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail="Proposal not found.") from error

    action_store = JiraActionStore()
    action = action_store.get(action_uuid)
    if action is None:
        raise HTTPException(status_code=404, detail="Proposal not found.")
    if action.requester_id == user.user_id:
        _audit(
            request,
            user,
            "connector.jira.approval",
            {"action_id": action_id, "reason": "self_approval_denied"},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot approve your own proposal.",
        )
    if action.status == "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Proposal has already been processed.",
        )
    if action.status == "proposed":
        action.status = "approved"
        action.approver_id = user.user_id
        action.approved_at = datetime.now(UTC)
        action_store.save(action)
    elif action.approver_id != user.user_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Proposal is being processed by another approver.",
        )

    issue = JiraDemoConnector().create_issue(action.action_id, action.proposal)
    notification = N8nDemoConnector().notify_issue_created(
        action.action_id,
        issue.key,
        issue.assignee_team,
    )
    action.status = "completed"
    action.issue_key = issue.key
    action.notification_status = "simulated"
    action_store.save(action)
    _audit(
        request,
        user,
        "connector.jira.approve_and_create",
        {
            "action_id": action_id,
            "issue_key": issue.key,
            "notification_status": notification.status,
        },
    )
    return JiraApprovalResponse(
        action=action,
        issue=issue,
        notification=notification,
    )
