import pytest

from backend.app.core.demo_auth import DEMO_USERS
from backend.app.orchestration.routing import route_question
from backend.app.orchestration.service import orchestrate_request


@pytest.mark.parametrize(
    ("question", "expected_intent", "expected_workflow"),
    [
        ("Who approves my annual leave request?", "hr.policy", "knowledge"),
        ("What steps are included in the employee onboarding checklist?", "hr.policy", "knowledge"),
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
        ("What steps are included in the employee onboarding checklist?", "knowledge", "hr_knowledge"),
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


@pytest.mark.parametrize(
    ("question", "expected_scope", "denied_department"),
    [
        (
            "What steps are included in the employee onboarding checklist?",
            "hr",
            "hr",
        ),
        (
            "What success fee applies under the recruitment agreement?",
            "recruitment",
            "recruitment",
        ),
        (
            "What are the incident-triage steps in the IT support runbook?",
            "it",
            "it",
        ),
    ],
)
def test_employee_restricted_questions_are_denied_before_retrieval(
    monkeypatch,
    question: str,
    expected_scope: str,
    denied_department: str,
) -> None:
    class RetrievalMustNotRun:
        @property
        def chunks(self):
            return []

        def search(self, *args, **kwargs):
            raise AssertionError("Restricted HR retrieval must not run.")

    monkeypatch.setenv("ENABLE_TEST_FIXTURES", "false")
    decision = route_question(question)
    result = orchestrate_request(
        question,
        decision,
        DEMO_USERS["demo-employee"],
        None,
        RetrievalMustNotRun(),
        "hybrid",
    )

    assert decision.required_scope == expected_scope
    assert result.audit_outcome == "denied"
    assert result.sources == []
    assert result.needs_clarification is True
    assert "not authorized" in result.answer.lower()
    assert denied_department in result.answer.lower()
    assert question.split()[0].lower() not in result.answer.lower()
