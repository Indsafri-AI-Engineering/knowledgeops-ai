import os
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from backend.app.core.auth import get_current_user
from backend.app.core.demo_auth import DemoUser
from backend.app.core.permissions import require_capability, user_scopes
from backend.app.moderation.guardrails import (
    AMBIGUOUS_MESSAGE,
    BLOCKED_INPUT_MESSAGE,
    ModerationDecision,
    OUT_OF_SCOPE_MESSAGE,
    UNSAFE_ANSWER_MESSAGE,
    moderate_input,
    moderate_output,
    record_moderation_event,
)
from backend.app.knowledge.faqs import suggest_faqs
from backend.app.knowledge.index import get_knowledge_index
from backend.app.knowledge.retrieval import KnowledgeIndex, RetrievalMode
from backend.app.orchestration.routing import (
    Intent,
    RouteCategory,
    RouteComponent,
    route_question,
)
from backend.app.storage.audit import AuditLog
from backend.app.api.v1.chat_models import SourceCitation
from backend.app.orchestration.service import orchestrate_request


router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000)
    retrieval_mode: RetrievalMode = "hybrid"


class ChatResponse(BaseModel):
    question: str
    answer: str
    intent: Intent
    route_category: RouteCategory
    route_component: RouteComponent
    workflow_status: Literal["available", "planned"]
    retrieval_mode: RetrievalMode
    sources: list[SourceCitation]
    needs_clarification: bool
    action_proposal: None = None


class FAQSuggestion(BaseModel):
    faq_id: str
    question: str


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    request: Request,
    user: Annotated[DemoUser, Depends(get_current_user)],
    index: Annotated[KnowledgeIndex, Depends(get_knowledge_index)],
) -> ChatResponse:
    require_capability(user, "chat:ask", request)
    input_decision = moderate_input(payload.question)
    record_moderation_event(
        input_decision,
        request=request,
        actor_id=user.user_id,
        metadata={"input_length": len(payload.question)},
    )
    if input_decision.outcome != "allowed":
        answer = (
            BLOCKED_INPUT_MESSAGE
            if input_decision.outcome == "blocked"
            else (
                AMBIGUOUS_MESSAGE
                if input_decision.category == "ambiguous"
                else OUT_OF_SCOPE_MESSAGE
            )
        )
        return ChatResponse(
            question=payload.question,
            answer=answer,
            intent="knowledge.question",
            route_category="unsupported",
            route_component="unsupported",
            workflow_status="planned",
            retrieval_mode=payload.retrieval_mode,
            sources=[],
            needs_clarification=input_decision.outcome
            == "clarification_required",
        )

    route = route_question(payload.question)
    if route.category == "workflow" and route.component in {
        "jira",
        "threat_analysis",
    } and route.needs_clarification:
        record_moderation_event(
            ModerationDecision(
                stage="action",
                outcome="flagged",
                category="unapproved_action",
                severity="low",
                rule_id="chat-action-not-executed",
                reason_code="approved_workflow_required",
            ),
            request=request,
            actor_id=user.user_id,
            metadata={"target": route.component},
        )
    orchestration = orchestrate_request(
        payload.question,
        route,
        user,
        request,
        index,
        payload.retrieval_mode,
    )
    answer = orchestration.answer
    workflow_status = orchestration.workflow_status
    sources = orchestration.sources
    needs_clarification = orchestration.needs_clarification

    output_decision = moderate_output(
        answer,
        source_count=len(sources),
    )
    if output_decision.outcome != "allowed":
        record_moderation_event(
            output_decision,
            request=request,
            actor_id=user.user_id,
            metadata={"source_count": len(sources)},
        )
        answer = UNSAFE_ANSWER_MESSAGE
        sources = []
        needs_clarification = True

    if orchestration.audit_action is not None:
        AuditLog().record(
            request_id=request.state.request_id,
            actor_id=user.user_id,
            action=orchestration.audit_action,
            resource_type="mock_connector",
            outcome="success",
            metadata=orchestration.audit_metadata,
        )

    AuditLog().record(
        request_id=request.state.request_id,
        actor_id=user.user_id,
        action="chat.ask",
        resource_type="chat_request",
        outcome=orchestration.audit_outcome,
        metadata={
            "intent": route.intent,
            "route_category": route.category,
            "route_component": route.component,
            "source_count": len(sources),
            "workflow_status": workflow_status,
            "moderation_outcome": output_decision.outcome,
        },
    )
    return ChatResponse(
        question=payload.question,
        answer=answer,
        intent=route.intent,
        route_category=route.category,
        route_component=route.component,
        workflow_status=workflow_status,
        retrieval_mode=payload.retrieval_mode,
        sources=sources,
        needs_clarification=needs_clarification,
    )


@router.get("/faqs/suggestions", response_model=list[FAQSuggestion])
def get_faq_suggestions(
    request: Request,
    user: Annotated[DemoUser, Depends(get_current_user)],
    query: Annotated[str, Query(max_length=2000)] = "",
) -> list[FAQSuggestion]:
    require_capability(user, "chat:ask", request)
    if os.getenv("ENABLE_TEST_FIXTURES", "").lower() != "true":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    suggestions = [
        FAQSuggestion(faq_id=item.faq_id, question=item.question)
        for item in suggest_faqs(query, set(user_scopes(user)))
    ]
    AuditLog().record(
        request_id=request.state.request_id,
        actor_id=user.user_id,
        action="faq.suggest",
        resource_type="faq_catalogue",
        outcome="success",
        metadata={"result_count": len(suggestions)},
    )
    return suggestions
