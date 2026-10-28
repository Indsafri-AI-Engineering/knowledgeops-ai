import re
import os
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from backend.app.core.auth import get_current_user
from backend.app.core.demo_auth import DemoUser
from backend.app.core.permissions import require_capability, user_scopes
from backend.app.knowledge.faqs import suggest_faqs
from backend.app.knowledge.index import get_knowledge_index
from backend.app.knowledge.retrieval import KnowledgeIndex, RetrievalMode
from backend.app.orchestration.routing import (
    Intent,
    RouteCategory,
    RouteComponent,
    route_question,
)
from backend.app.storage.conversations import (
    Conversation,
    ConversationRepository,
    ConversationTurn,
    get_conversation_repository,
)
from backend.app.storage.audit import AuditLog
from backend.app.api.v1.chat_models import SourceCitation
from backend.app.orchestration.service import orchestrate_request


router = APIRouter(tags=["chat"])
FOLLOW_UP_PATTERN = re.compile(
    r"^\s*(and\b|who\b|what about\b|how about\b|where\b|when\b|why\b|"
    r"does it\b|is it\b|can i\b)",
    re.IGNORECASE,
)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    retrieval_mode: RetrievalMode = "hybrid"
    conversation_id: UUID | None = None


class ChatResponse(BaseModel):
    answer: str
    intent: Intent
    route_category: RouteCategory
    route_component: RouteComponent
    workflow_status: Literal["available", "planned"]
    retrieval_mode: RetrievalMode
    sources: list[SourceCitation]
    needs_clarification: bool
    action_proposal: None = None
    conversation_id: UUID
    history: list[ConversationTurn]


class FAQSuggestion(BaseModel):
    faq_id: str
    question: str


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    request: Request,
    user: Annotated[DemoUser, Depends(get_current_user)],
    index: Annotated[KnowledgeIndex, Depends(get_knowledge_index)],
    store: Annotated[
        ConversationRepository,
        Depends(get_conversation_repository),
    ],
) -> ChatResponse:
    require_capability(user, "chat:ask", request)
    conversation_id = payload.conversation_id or uuid4()
    if payload.conversation_id is None:
        conversation = store.create(conversation_id, user.user_id)
    else:
        conversation = store.get(conversation_id, user.user_id)
        if conversation is None:
            AuditLog().record(
                request_id=request.state.request_id,
                actor_id=user.user_id,
                action="conversation.access",
                resource_type="conversation",
                outcome="denied",
            )
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")

    context_question = payload.question
    if conversation.turns and FOLLOW_UP_PATTERN.search(payload.question):
        context_question = f"{conversation.turns[-1].question} {payload.question}"

    route = route_question(context_question)
    orchestration = orchestrate_request(
        context_question,
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

    if orchestration.audit_action is not None:
        AuditLog().record(
            request_id=request.state.request_id,
            actor_id=user.user_id,
            action=orchestration.audit_action,
            resource_type="mock_connector",
            outcome="success",
            metadata=orchestration.audit_metadata,
        )

    saved_conversation = store.append(
        conversation_id,
        user.user_id,
        ConversationTurn(
            question=payload.question,
            answer=answer,
            intent=route.intent,
            sources=sources,
        ),
    )
    if saved_conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")

    AuditLog().record(
        request_id=request.state.request_id,
        actor_id=user.user_id,
        action="chat.ask",
        resource_type="conversation",
        outcome="success",
        metadata={
            "conversation_id": str(conversation_id),
            "intent": route.intent,
            "route_category": route.category,
            "route_component": route.component,
            "source_count": len(sources),
            "workflow_status": workflow_status,
        },
    )
    return ChatResponse(
        answer=answer,
        intent=route.intent,
        route_category=route.category,
        route_component=route.component,
        workflow_status=workflow_status,
        retrieval_mode=payload.retrieval_mode,
        sources=sources,
        needs_clarification=needs_clarification,
        conversation_id=conversation_id,
        history=saved_conversation.turns,
    )


@router.get("/conversations/{conversation_id}", response_model=Conversation)
def get_conversation(
    conversation_id: UUID,
    request: Request,
    user: Annotated[DemoUser, Depends(get_current_user)],
    store: Annotated[
        ConversationRepository,
        Depends(get_conversation_repository),
    ],
) -> Conversation:
    conversation = store.get(conversation_id, user.user_id)
    if conversation is None:
        AuditLog().record(
            request_id=request.state.request_id,
            actor_id=user.user_id,
            action="conversation.access",
            resource_type="conversation",
            outcome="denied",
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")
    AuditLog().record(
        request_id=request.state.request_id,
        actor_id=user.user_id,
        action="conversation.read",
        resource_type="conversation",
        outcome="success",
        metadata={"turn_count": len(conversation.turns)},
    )
    return conversation


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
