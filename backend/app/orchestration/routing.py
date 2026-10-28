import re
from typing import Literal

from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel

Intent = Literal[
    "hr.policy",
    "it.troubleshooting",
    "recruitment.knowledge",
    "jira.search",
    "threat.scan",
    "knowledge.analysis",
    "knowledge.question",
    "unsupported.action",
]
RouteCategory = Literal["knowledge", "workflow", "analytical", "unsupported"]
RouteComponent = Literal[
    "knowledge_base",
    "hr_knowledge",
    "it_knowledge",
    "recruitment",
    "jira",
    "threat_analysis",
    "knowledge_analytics",
    "unsupported",
]
RouteWorkflow = Literal["knowledge", "planned"]

_ROUTES: tuple[
    tuple[Intent, RouteCategory, RouteComponent, re.Pattern[str]], ...
] = (
    (
        "threat.scan",
        "workflow",
        "threat_analysis",
        re.compile(r"\b(scan|phishing|malware|suspicious|threat)\b", re.IGNORECASE),
    ),
    (
        "jira.search",
        "workflow",
        "jira",
        re.compile(r"\b(jira|ticket|bug|issue key|open issues)\b", re.IGNORECASE),
    ),
    (
        "recruitment.knowledge",
        "knowledge",
        "recruitment",
        re.compile(
            r"\b(recruitment|recruiter|candidate|candidates|cv|cvs|success fee|campaign)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "hr.policy",
        "knowledge",
        "hr_knowledge",
        re.compile(r"\b(annual leave|leave days|leave request|people portal)\b", re.IGNORECASE),
    ),
    (
        "it.troubleshooting",
        "knowledge",
        "it_knowledge",
        re.compile(
            r"\b(salesforce|troubleshoot|troubleshooting|login|log in|password|"
            r"multi.factor|mfa|sign.in error|incident|runbook|it support)\b",
            re.IGNORECASE,
        ),
    ),
)
_ANALYTICAL_PATTERN = re.compile(
    r"\b(compare|comparison|summari[sz]e|summary|trend|trends|"
    r"analy[sz]e|analysis|average|distribution|aggregate|"
    r"calculate|calculation|count|total|breakdown)\b",
    re.IGNORECASE,
)
_RECRUITMENT_PATTERN = re.compile(
    r"\b(recruitment|recruiter|candidate|candidates|cv|cvs|success fee|campaign)\b",
    re.IGNORECASE,
)
_RECRUITMENT_FEE_PATTERN = re.compile(
    r"\b(success fee|fee|commission)\b",
    re.IGNORECASE,
)
_ACTION_PATTERN = re.compile(
    r"\b(create|update|delete|submit|send|approve|execute|book|pay)\b",
    re.IGNORECASE,
)


class RouteDecision(BaseModel):
    intent: Intent
    category: RouteCategory
    component: RouteComponent
    workflow: RouteWorkflow
    required_scope: Literal["hr", "it", "recruitment"] | None = None
    needs_clarification: bool = False
    clarification_prompt: str | None = None


_HR_RESTRICTED_PATTERN = re.compile(
    r"\b(onboarding|induction|orientation|new starter|new hire|new employee checklist)\b",
    re.IGNORECASE,
)


def _classify_intent(question: str) -> RouteDecision:
    if _HR_RESTRICTED_PATTERN.search(question):
        return RouteDecision(
            intent="hr.policy",
            category="knowledge",
            component="hr_knowledge",
            workflow="knowledge",
            required_scope="hr",
        )

    has_recruitment_context = bool(_RECRUITMENT_PATTERN.search(question))
    if _ANALYTICAL_PATTERN.search(question) and not (
        has_recruitment_context and _RECRUITMENT_FEE_PATTERN.search(question)
    ):
        return RouteDecision(
            intent="knowledge.analysis",
            category="analytical",
            component="knowledge_analytics",
            workflow="knowledge",
        )

    for intent, category, component, pattern in _ROUTES:
        if pattern.search(question):
            is_unavailable_action = (
                category == "workflow" and bool(_ACTION_PATTERN.search(question))
            )
            return RouteDecision(
                intent=intent,
                category=category,
                component=component,
                workflow=(
                    "planned"
                    if category in ("workflow", "unsupported")
                    else "knowledge"
                ),
                required_scope={
                    "hr_knowledge": "hr",
                    "it_knowledge": "it",
                    "recruitment": "recruitment",
                }.get(component),
                needs_clarification=(
                    is_unavailable_action or component == "threat_analysis"
                ),
                clarification_prompt=(
                    "This action is not available through chat. No external "
                    "system was changed."
                    if is_unavailable_action
                    else None
                ),
            )
    if _ACTION_PATTERN.search(question):
        return RouteDecision(
            intent="unsupported.action",
            category="unsupported",
            component="unsupported",
            workflow="planned",
            needs_clarification=True,
            clarification_prompt=(
                "I cannot perform that action. Please ask a knowledge question "
                "or use an approved workflow."
            ),
        )
    return RouteDecision(
        intent="knowledge.question",
        category="knowledge",
        component="knowledge_base",
        workflow="knowledge",
    )


intent_router = RunnableLambda(_classify_intent)


def route_question(question: str) -> RouteDecision:
    return intent_router.invoke(question)
