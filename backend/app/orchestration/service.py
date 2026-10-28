import os
import re
from decimal import Decimal, InvalidOperation
from typing import Literal

from fastapi import HTTPException, Request, status
from pydantic import BaseModel, Field

from backend.app.api.v1.chat_models import SourceCitation
from backend.app.connectors.jira import JiraDemoConnector
from backend.app.connectors.recruitment_demo import RecruitmentDemoConnector
from backend.app.core.demo_auth import DemoUser
from backend.app.core.permissions import require_capability, user_scopes
from backend.app.knowledge.generation import generate_grounded_answer
from backend.app.knowledge.ingestion import KnowledgeChunk
from backend.app.knowledge.retrieval import KnowledgeIndex, RetrievalMode, RetrievedChunk
from backend.app.orchestration.routing import RouteDecision

SALARY_PATTERN = re.compile(
    r"\b(?:salary|base salary|for)\s+(?:of\s+)?(?:credits\s*)?"
    r"([0-9][0-9,]*(?:\.\d{1,2})?)\b",
    re.IGNORECASE,
)


class OrchestrationResult(BaseModel):
    answer: str
    workflow_status: Literal["available", "planned"]
    sources: list[SourceCitation]
    needs_clarification: bool
    audit_outcome: Literal["success", "denied"] = "success"
    audit_action: str | None = None
    audit_metadata: dict[str, str | int | bool] = Field(default_factory=dict)


def _citation_from_chunk(chunk: KnowledgeChunk) -> SourceCitation:
    return SourceCitation(
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


def _retrieval_citations(results: list[RetrievedChunk]) -> list[SourceCitation]:
    return [_citation_from_chunk(result.chunk) for result in results]


def _recruitment_citation(
    index: KnowledgeIndex,
    document_id: str,
) -> list[SourceCitation]:
    chunk = next(
        (chunk for chunk in index.chunks if chunk.document_id == document_id),
        None,
    )
    return [_citation_from_chunk(chunk)] if chunk is not None else []


def _recruitment_answer(
    question: str,
    user: DemoUser,
    index: KnowledgeIndex,
) -> tuple[str, list[SourceCitation]] | None:
    if "recruitment" not in user_scopes(user):
        return None

    connector = RecruitmentDemoConnector()
    lowered = question.lower()
    if any(term in lowered for term in ("success fee", "fee", "commission")):
        salary: Decimal | None = None
        salary_match = SALARY_PATTERN.search(question)
        if salary_match:
            try:
                salary = Decimal(salary_match.group(1).replace(",", ""))
            except InvalidOperation as error:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Salary must be a valid amount.",
                ) from error
        result = connector.calculate_success_fee(salary)
        answer = (
            f"SIMULATED recruitment agreement: the success fee is "
            f"{result.rate_percent}% of the candidate's first-year base salary. "
            f"Formula: {result.formula}."
        )
        if result.salary is not None and result.fee is not None:
            answer += (
                f" For {result.salary:,.2f} {result.currency}, the illustrative "
                f"fee is {result.fee:,.2f} {result.currency}."
            )
        else:
            answer += " Provide a salary amount to calculate an example fee."
        return answer, _recruitment_citation(index, result.agreement_document_id)

    if any(term in lowered for term in ("cv", "cvs", "candidate", "candidates", "match")):
        result = connector.match_campaign("backend-engineer")
        if result is None:
            return None
        answer = (
            f"SIMULATED recruitment screening for {result.campaign_title}: "
            f"{result.matched_count} of {result.total_candidates} fictional CVs "
            f"meet the listed criteria ({'; '.join(result.criteria)}). "
            "This is a criteria-based count, not a hiring recommendation; "
            "a human recruiter must review the evidence."
        )
        if result.matches:
            evidence = " ".join(
                f"{match.profile_id}: {match.evidence}"
                for match in result.matches
                if match.matched
            )
            if evidence:
                answer += f" Matching evidence: {evidence}"
        citations: list[SourceCitation] = []
        for match in result.matches:
            citations.extend(_recruitment_citation(index, match.document_id))
        return answer, citations
    return None


def _jira_search(
    question: str,
    user: DemoUser,
    request: Request,
) -> OrchestrationResult:
    require_capability(user, "jira:read", request)
    search_query = (
        "AI Team"
        if "ai team" in question.lower()
        else "Salesforce"
        if "salesforce" in question.lower()
        else question
    )
    issues = JiraDemoConnector().search(search_query)
    answer = (
        "SIMULATED Jira search results. No live Jira system was queried. "
        if issues
        else "No matching issues were found in the fictional Jira dataset."
    )
    if issues:
        answer += " " + " ".join(
            f"{issue.key} ({issue.status}, {issue.priority}, "
            f"{issue.assignee_team}): {issue.summary}"
            for issue in issues
        )
    return OrchestrationResult(
        answer=answer,
        workflow_status="available",
        sources=[
            SourceCitation(
                title=f"{issue.key}: {issue.summary}",
                source="fictional_jira_demo",
                source_path="jira_issues/issues.json",
                section=issue.status,
                document_id=issue.key,
            )
            for issue in issues
        ],
        needs_clarification=not issues,
        audit_action="connector.jira.search",
        audit_metadata={"result_count": len(issues)},
    )


def _planned_workflow(route: RouteDecision) -> OrchestrationResult:
    if route.clarification_prompt:
        answer = route.clarification_prompt
    elif route.component == "threat_analysis":
        answer = (
            "Threat analysis is not available through chat. Use the authorized "
            "threat-scan interface; no artifact was scanned."
        )
    elif route.component == "jira":
        answer = (
            "Jira search is not available in this environment. No external "
            "system was queried."
            if not route.needs_clarification
            else "Jira actions are not available through chat. No external "
            "system was queried or changed."
        )
    else:
        answer = (
            "That request is not supported. No external system was queried or changed."
        )
    return OrchestrationResult(
        answer=answer,
        workflow_status="planned",
        sources=[],
        needs_clarification=route.needs_clarification,
    )


def orchestrate_request(
    question: str,
    route: RouteDecision,
    user: DemoUser,
    request: Request,
    index: KnowledgeIndex,
    retrieval_mode: RetrievalMode,
) -> OrchestrationResult:
    test_fixture_mode = os.getenv("ENABLE_TEST_FIXTURES", "").lower() == "true"

    if route.required_scope and route.required_scope not in user_scopes(user):
        department = {
            "hr": "HR",
            "it": "IT",
            "recruitment": "Recruitment",
        }[route.required_scope]
        return OrchestrationResult(
            answer=(
                f"You are not authorized to access this {department} information. "
                f"Contact your {department} administrator if you believe you "
                "should have access."
            ),
            workflow_status="available",
            sources=[],
            needs_clarification=True,
            audit_outcome="denied",
        )

    if route.category == "unsupported":
        return _planned_workflow(route)

    if route.component == "jira":
        is_read_request = not route.needs_clarification
        if test_fixture_mode and is_read_request:
            return _jira_search(question, user, request)
        return _planned_workflow(route)

    if route.component == "threat_analysis":
        return _planned_workflow(route)

    if route.component == "recruitment" and test_fixture_mode:
        recruitment_result = _recruitment_answer(question, user, index)
        if recruitment_result is not None:
            answer, sources = recruitment_result
            fee_request = any(
                term in question.lower()
                for term in ("fee", "commission")
            )
            return OrchestrationResult(
                answer=answer,
                workflow_status="available",
                sources=sources,
                needs_clarification=not sources,
                audit_action=(
                    "connector.recruitment.success_fee"
                    if fee_request
                    else "connector.recruitment.cv_match"
                ),
                audit_metadata={"source_count": len(sources)},
            )

    results = index.search(
        question,
        set(user_scopes(user)),
        mode=retrieval_mode,
    )
    return OrchestrationResult(
        answer=generate_grounded_answer(
            results,
            question,
            analytical=route.category == "analytical",
        ),
        workflow_status="available",
        sources=_retrieval_citations(results),
        needs_clarification=not results,
    )
