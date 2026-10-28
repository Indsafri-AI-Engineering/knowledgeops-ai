from uuid import uuid4

import pytest

from backend.app.core.demo_auth import DEMO_USERS
from backend.app.orchestration.routing import route_question
from backend.app.orchestration.service import orchestrate_request
from backend.app.storage.conversations import (
    ConversationStore,
    ConversationTurn,
    MAX_CONVERSATION_TURNS,
)


@pytest.mark.parametrize(
    ("question", "expected_intent", "expected_workflow"),
    [
        ("Who approves my annual leave request?", "hr.policy", "knowledge"),
        ("Help troubleshoot a Salesforce login error", "it.troubleshooting", "knowledge"),
        ("What success fee applies to the recruitment agreement?", "recruitment.knowledge", "knowledge"),
        ("Which Jira issues are assigned to the AI team?", "jira.search", "planned"),
        ("Scan this email for phishing", "threat.scan", "planned"),
        ("Where can I find the data policy?", "knowledge.question", "knowledge"),
    ],
)
def test_langchain_router_assigns_workflow(
    question: str,
    expected_intent: str,
    expected_workflow: str,
) -> None:
    decision = route_question(question)
    assert decision.intent == expected_intent
    assert decision.workflow == expected_workflow


@pytest.mark.parametrize(
    ("question", "category", "component"),
    [
        ("Who approves my annual leave request?", "knowledge", "hr_knowledge"),
        ("Help troubleshoot a Salesforce login error", "knowledge", "it_knowledge"),
        ("What success fee applies?", "knowledge", "recruitment"),
        ("Which Jira issues are open?", "workflow", "jira"),
        ("Scan this email for phishing", "workflow", "threat_analysis"),
        ("Compare the two policy options", "analytical", "knowledge_analytics"),
        ("Where can I find the data policy?", "knowledge", "knowledge_base"),
        ("Send an email to the payroll team", "unsupported", "unsupported"),
    ],
)
def test_router_emits_structured_category_and_component(
    question: str,
    category: str,
    component: str,
) -> None:
    decision = route_question(question)

    assert decision.category == category
    assert decision.component == component


def test_unsupported_action_does_not_fall_through_to_retrieval(
    monkeypatch,
) -> None:
    class RetrievalMustNotRun:
        @property
        def chunks(self):
            return []

        def search(self, *args, **kwargs):
            raise AssertionError("Unsupported action must not invoke retrieval.")

    monkeypatch.setenv("ENABLE_TEST_FIXTURES", "false")
    decision = route_question("Send an email to the payroll team")
    result = orchestrate_request(
        "Send an email to the payroll team",
        decision,
        DEMO_USERS["demo-employee"],
        None,
        RetrievalMustNotRun(),
        "hybrid",
    )

    assert result.workflow_status == "planned"
    assert result.needs_clarification is True
    assert result.sources == []
    assert "cannot perform that action" in result.answer.lower()


def test_json_conversation_store_limits_history_and_enforces_owner(tmp_path) -> None:
    store = ConversationStore(tmp_path / "conversations.json")
    conversation_id = uuid4()
    store.create(conversation_id, "demo-employee")
    for number in range(MAX_CONVERSATION_TURNS + 2):
        saved = store.append(
            conversation_id,
            "demo-employee",
            ConversationTurn(
                question=f"question {number}",
                answer=f"answer {number}",
                intent="knowledge.question",
            ),
        )
        assert saved is not None

    loaded = ConversationStore(tmp_path / "conversations.json").get(
        conversation_id,
        "demo-employee",
    )
    assert loaded is not None
    assert len(loaded.turns) == MAX_CONVERSATION_TURNS
    assert loaded.turns[0].question == "question 2"
    assert store.get(conversation_id, "demo-recruiter") is None
